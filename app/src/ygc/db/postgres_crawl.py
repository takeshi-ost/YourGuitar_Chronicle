"""Explicit PostgreSQL adapter for the shared Reverb pipeline, no SQLite fallback."""
from contextlib import contextmanager
from pathlib import Path
import re
import uuid
from ygc.db.postgres import connect
from ygc.db.postgres_accounts import PostgresAccounts,now
from ygc.db.postgres_queries import ObservationConnection,SharedCursor,qmark_parameters
from ygc.db.repository import Repository

# The only shared inserts whose callers require an auto-generated identifier.
INSERT_IDS=frozenset(('claims','individuals','crawl_runs','crawl_unregistered_records'))
SOURCE_SQL="""
 SELECT e.source_site,e.source_listing_id,e.source_url,e.captured_at AS observed_at,
 c.individual_id,c.id AS claim_id,e.legacy_observation_id,COALESCE(e.legacy_observation_id,e.id) AS sort_id
 FROM claim_source_evidence e JOIN claims c ON c.id=e.claim_id
 WHERE e.evidence_type='marketplace_listing' AND e.source_site IS NOT NULL AND e.source_site<>'user' AND e.source_listing_id IS NOT NULL
 UNION ALL
 SELECT o.source_site,o.source_listing_id,o.source_url,o.observed_at,o.individual_id,NULL,o.id,o.id
 FROM observations o WHERE o.source_site IS NOT NULL AND o.source_site<>'user' AND o.source_listing_id IS NOT NULL
 AND NOT EXISTS(SELECT 1 FROM claim_source_evidence e WHERE e.evidence_type='marketplace_listing' AND e.source_site=o.source_site AND e.source_listing_id=o.source_listing_id)
 UNION ALL
 SELECT a.payload_json::jsonb->>'source_site',a.payload_json::jsonb->>'source_listing_id',a.payload_json::jsonb->>'source_url',
 a.payload_json::jsonb->>'observed_at',NULL,NULL,a.legacy_observation_id,a.legacy_observation_id
 FROM legacy_crawl_archive a WHERE a.payload_json::jsonb->>'source_site'<>'user' AND a.payload_json::jsonb->>'source_listing_id' IS NOT NULL
 AND NOT EXISTS(SELECT 1 FROM observations o WHERE o.id=a.legacy_observation_id OR(o.source_site=a.payload_json::jsonb->>'source_site' AND o.source_listing_id=a.payload_json::jsonb->>'source_listing_id'))
 AND NOT EXISTS(SELECT 1 FROM claim_source_evidence e WHERE e.evidence_type='marketplace_listing' AND e.source_site=a.payload_json::jsonb->>'source_site' AND e.source_listing_id=a.payload_json::jsonb->>'source_listing_id')
 UNION ALL
 SELECT r.source_site,r.source_listing_id,r.source_url,r.observed_at,NULL,NULL,NULL,r.id
 FROM crawl_unregistered_records r WHERE r.source_site<>'user'
 AND NOT EXISTS(SELECT 1 FROM claim_source_evidence e WHERE e.evidence_type='marketplace_listing' AND e.source_site=r.source_site AND e.source_listing_id=r.source_listing_id)
 AND NOT EXISTS(SELECT 1 FROM observations o WHERE o.source_site=r.source_site AND o.source_listing_id=r.source_listing_id)
 AND NOT EXISTS(SELECT 1 FROM legacy_crawl_archive a WHERE a.payload_json::jsonb->>'source_site'=r.source_site AND a.payload_json::jsonb->>'source_listing_id'=r.source_listing_id)
"""


def reserve_automation(settings):
    """Reserve an ordinary positive ID in the canonical registry; never a login identity."""
    with connect(settings,'accounts') as con:
        con.execute('SELECT pg_advisory_xact_lock(79432191)')
        record=con.execute("SELECT a.* FROM account_metadata m JOIN account_records a ON a.app_user_id=m.value WHERE m.key='system_actor:automation'").fetchone()
        if record:
            if record['account_type']!='source' or not record['disabled'] or record['role']!='member':raise ValueError('Invalid Automation reservation.')
            return record['id']
        stamp=now()
        record=con.execute("""INSERT INTO account_records(app_user_id,display_name,account_type,identity_provider,ban_status,disabled,created_at,updated_at)
          VALUES(%s,'Automation','source','system','normal',1,%s,%s) RETURNING id,app_user_id""",(str(uuid.uuid4()),stamp,stamp)).fetchone()
        con.execute("INSERT INTO account_metadata(key,value) VALUES('system_actor:automation',%s)",(record['app_user_id'],))
        return record['id']


class CrawlConnection(ObservationConnection):
    marketplace_sources_sql=SOURCE_SQL
    def executemany(self,query,parameters):
        with self.connection.cursor() as cursor:cursor.executemany(qmark_parameters(query),parameters)
    def execute(self,query,parameters=None):
        match=re.match(r'\s*INSERT\s+INTO\s+([a-z_]+)\s*\(',query,re.I)
        if match and match[1].lower() in INSERT_IDS:
            cursor=self.connection.execute(qmark_parameters(query)+' RETURNING id',parameters or ())
            result=SharedCursor(cursor);result.lastrowid=cursor.fetchone()['id'];return result
        return super().execute(query,parameters)


class PostgresCrawlRepository(Repository):
    def __init__(self,settings,automation_id,actor=None):
        super().__init__(Path(':memory:'));self.settings=settings;self.automation_id=automation_id;self.actor=actor
    def init_db(self):raise ValueError('Runtime does not initialize schema.')
    @contextmanager
    def connect(self):
        # The short transaction fence is never held during a Reverb network request.
        with connect(self.settings,'accounts') as source:
            source.execute("SET LOCAL lock_timeout='5s'")
            source.execute('LOCK TABLE account_records IN SHARE MODE')
            current=list(source.execute('SELECT * FROM account_records ORDER BY id'))
            if self.actor is not None:
                actor=next((a for a in current if a['app_user_id']==self.actor),None)
                PostgresAccounts._active(actor)
                if actor['role']!='admin':raise PermissionError('Admin revoked.')
            with connect(self.settings,'chronicle') as dest:
                dest.execute("SET LOCAL lock_timeout='5s'")
                dest.execute('SELECT pg_advisory_xact_lock(79432002)')
                store=PostgresAccounts(self.settings)
                receipts={r['account_id']:r for r in dest.execute('SELECT r.account_id,r.app_user_id,r.revision,u.app_user_id AS user_uuid FROM account_projection_receipts r JOIN users u ON u.id=r.account_id')}
                for account in current:
                    receipt=receipts.get(account['id'])
                    if receipt and (receipt['app_user_id']!=account['app_user_id'] or receipt['user_uuid']!=account['app_user_id']):raise ValueError('Participant registry conflict.')
                    if not receipt or receipt['revision']!=account['projection_version']:store._apply_projection(dest,account)
                yield CrawlConnection(dest)
    def _source_user_id(self,con,source_name):
        if source_name!='Automation':raise ValueError('Unknown source participant.')
        row=con.execute("SELECT id FROM users WHERE id=? AND account_type='source' AND display_name='Automation'",(self.automation_id,)).fetchone()
        if not row:raise ValueError('Automation projection missing.')
        return row['id']
    def finish_run(self,run_id,**stats):
        # Provider exceptions may include bearer headers or response bodies; never persist them.
        if stats.get('error_message'):stats['error_message']='Crawl failed; inspect the recorded phase.'
        return super().finish_run(run_id,**stats)
