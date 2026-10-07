"""Reasoned Admin application decisions, separate from Claim verification.

The existing review/Ownership algorithms own decisions and Snapshot rebuilding.
This adapter supplies canonical authority, fencing, private evidence, and bounded
read models. It never starts a reviewer or replaces an Owner's required consent.
"""
from contextlib import contextmanager
import hashlib
import json
import re
import time

from ygc import acquire_review as common
from ygc.cloud_applications import references, revision_id
from ygc.cloud_content_media import decode_reference
from ygc.cloud_guitars import GuitarMissing
from ygc.cloud_review import CloudReview, ReviewRepository
from ygc.db.postgres_accounts import PostgresAccounts

STATES = ('draft', 'pending', 'processing', 'error', 'accepted', 'rejected', 'closed', 'expired', 'cancelled')
ACTIONS = ('accept', 'reject', 'retry', 'cancel')
MANUAL_REVIEW = {
    'mode': 'external_mcp', 'automatic_start': False,
    'instructions': (
        'Use the existing authorized ygc_staging_review MCP in a separate reviewer session. '
        'First run ygc_review_connection_check. Review ON only permits work; it does not start a model. '
        'With explicit approval to review the intended applications, call ygc_pending_listing and '
        'ygc_pending_acquire once each, then carry forward only each returned remaining_revisions '
        'until that batch is empty. Follow the returned instructions: retrieve actual photos; record '
        'independent observations before product details; submit observations, never a chosen verdict. '
        'If photos cannot be seen, use the matching ygc_fail tool. Do not fabricate observations. '
        'Refresh this Console to see processing, retained answers, errors and final results. '
        'Review OFF stops new work and holds worker answers; an explicit Admin decision still applies '
        'immediately. Re-review only queues work and does not launch a process or a model.'
    ),
}


class ApplicationConflict(ValueError):
    """The displayed application version is no longer actionable."""


def parameters(query):
    if set(query) - {'q', 'status', 'kind', 'after', 'limit'}:
        raise ValueError('Invalid application search.')
    if any(len(query.getlist(key)) != 1 for key in query):
        raise ValueError('Duplicate search parameter.')
    q, status, kind = query.get('q', '').strip(), query.get('status', ''), query.get('kind', '')
    after, limit = query.get('after') or None, query.get('limit', '25')
    if len(q) > 200 or status not in ('', *STATES) or kind not in ('', 'listing', 'acquire'):
        raise ValueError('Invalid application search.')
    if after is not None:
        revision_id(after)
    if not isinstance(limit, str) or not re.fullmatch(r'[0-9]{1,2}', limit) or not 1 <= int(limit) <= 50:
        raise ValueError('Invalid page size.')
    return dict(q=q, status=status, kind=kind, after=after, limit=int(limit))


def safe_diagnostic(value, locators=()):
    """Never expose Storage locators or worker authority in nested history."""
    if isinstance(value, dict):
        return {key: safe_diagnostic(item, locators) for key, item in value.items()
                if key not in ('lease_token', 'path', 'url', 'storage_path', 'bucket', 'generation')}
    if isinstance(value, list):
        return [safe_diagnostic(item, locators) for item in value]
    if isinstance(value, str):
        for locator in locators:
            if locator:
                value = value.replace(locator, '[private reference]')
                value = value.replace(json.dumps(locator)[1:-1], '[private reference]')
    return value


class CloudAdminApplications(CloudReview):
    def __init__(self, settings, operations, storage):
        super().__init__(settings, storage)
        self.operations = operations

    @contextmanager
    def transaction(self, actor, write=False):
        # Same lock order as the worker: maintenance/Crawl -> canonical Accounts
        # -> projection -> Chronicle. All participants are held through commit.
        # Admin reads are deliberately fenced too, giving one consistent view
        # of the Chronicle state and independently retained worker answers.
        with super().transaction() as (con, control, enabled, accounts):
            account = next((row for row in accounts.values() if row['app_user_id'] == actor), None)
            PostgresAccounts._active(account)
            if account['role'] != 'admin':
                raise PermissionError('An active administrator is required.')
            yield con, control, enabled, accounts

    @staticmethod
    def find(con, revision):
        revision_id(revision)
        row = con.execute('SELECT * FROM acquire_applications WHERE revision=?', (revision,)).fetchone()
        if row is None:
            raise GuitarMissing()
        return row

    @staticmethod
    def paused(control, revision):
        return [dict(row) for row in control.execute(
            'SELECT kind,received_at FROM paused_review_answers WHERE revision=%s ORDER BY received_at,kind',
            (revision,)).fetchall()]

    @staticmethod
    def version(con, row, paused):
        # Observations may arrive without an event; holding an older detail must
        # not authorize a decision over newer diagnostic material.
        data = [common.management_version(con, row),
                {key: row[key] for key in row.keys() if key != 'seen_event_id'}, paused]
        return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()

    def view(self, con, control, enabled, row, *, detail=False):
        applicant = con.execute('SELECT display_name FROM users WHERE id=?', (row['applicant_id'],)).fetchone()
        individual = con.execute('SELECT * FROM individuals WHERE id=?', (row['individual_id'],)).fetchone()
        claim = con.execute('SELECT * FROM claims WHERE id=?', (row['claim_id'],)).fetchone()
        payload = json.loads(row['listing_payload']) if row['listing_payload'] else None
        product = ' '.join(filter(None, [individual['manufacturer'], individual['model']])) if individual else (
            ' '.join(filter(None, [payload['manufacturer'], payload['model']])) if payload else '(deleted)')
        status = 'expired' if row['status'] == 'draft' and row['expires_at'] <= time.time() else row['status']
        paused = self.paused(control, row['revision'])
        actions = [action for action in common.management_actions(row) if action in ACTIONS]
        if status == 'expired':
            actions = []
        result = {key: row[key] for key in ('revision', 'request_kind', 'serial', 'created_at', 'submitted_at',
                   'completed_at', 'error', 'attempts', 'lease_until')}
        result.update(status=status, applicant_id=str(row['applicant_id']), applicant_name=applicant[0] if applicant else '(deleted)',
            product_name=product, individual_id=str(row['individual_id']) if row['individual_id'] else None,
            claim_id=str(row['claim_id']) if row['claim_id'] else None,
            current_owner_user_id=str(individual['current_owner_user_id']) if individual and individual['current_owner_user_id'] else None,
            verification_status=claim['verification_status'] if claim else None, admin_actions=actions,
            management_version=self.version(con, row, paused), paused_answers=paused, review_enabled=enabled)
        if not detail:
            return result
        result.update({key: row[key] for key in ('body', 'acquisition_date', 'challenge', 'expires_at', 'report', 'prompt_version')})
        try:
            private_photos = references(row)
        except (ValueError, TypeError, KeyError):
            private_photos = {}
            result['photos_unavailable'] = True
        result['photos'] = list(private_photos)
        # Historical text reports embed their original JSON, including private
        # source locators. Redact only those locators; observations stay intact.
        locators = list(private_photos.values())
        source = json.loads(row['reference_source']) if row['reference_source'] else {}
        locators.extend(source.get(key) for key in ('path', 'url'))
        for locator in locators:
            if locator and result['report']:
                result['report'] = result['report'].replace(locator, '[private reference]')
                result['report'] = result['report'].replace(json.dumps(locator)[1:-1], '[private reference]')
        for key in ('result', 'received', 'product_details', 'product_observations'):
            result[key] = safe_diagnostic(json.loads(row[key]), locators) if row[key] else None
        result['listing_payload'] = payload
        result['events'] = []
        result['admin_review'] = None
        for event in con.execute('SELECT id,at,kind,note FROM acquire_application_events WHERE revision=? ORDER BY id', (row['revision'],)):
            event = dict(event)
            event['id'] = str(event['id'])
            try:
                note = safe_diagnostic(json.loads(event['note']), locators)
                event['note'] = json.dumps(note, ensure_ascii=False)
            except (ValueError, TypeError):
                note = None
            if event['kind'] in ('admin_accept', 'admin_reject') and isinstance(note, dict):
                result['admin_review'] = {'at': event['at'], **note}
            elif event['kind'] == 'admin_retry':
                result['admin_review'] = None
            result['events'].append(event)
        result['manual_review'] = MANUAL_REVIEW.copy()
        return result

    def list(self, actor, *, q='', status='', kind='', after=None, limit=25):
        if (not isinstance(q, str) or len(q) > 200 or status not in ('', *STATES)
                or kind not in ('', 'acquire', 'listing') or type(limit) is not int or not 1 <= limit <= 50):
            raise ValueError('Invalid application search.')
        if after is not None:
            revision_id(after)
        with self.transaction(actor) as (con, control, enabled, _):
            filters, args = [], []
            if status:
                filters.append("(CASE WHEN a.status='draft' AND a.expires_at<=? THEN 'expired' ELSE a.status END)=?")
                args.extend((time.time(), status))
            if kind:
                filters.append('a.request_kind=?')
                args.append(kind)
            if q.strip():
                # Escape wildcard input so search is literal, not a query language.
                token = '%' + q.strip().lower().replace('!', '!!').replace('%', '!%').replace('_', '!_') + '%'
                filters.append("(" + ' OR '.join(f"LOWER(COALESCE({field},'')) LIKE ? ESCAPE '!'" for field in
                    ('a.revision', 'a.serial', 'u.display_name', 'i.manufacturer', 'i.model', 'a.listing_payload')) + ")")
                args.extend([token] * 6)
            joins = ' FROM acquire_applications a LEFT JOIN users u ON u.id=a.applicant_id LEFT JOIN individuals i ON i.id=a.individual_id'
            where = (' WHERE ' + ' AND '.join(filters)) if filters else ''
            total = con.execute('SELECT COUNT(*)' + joins + where, args).fetchone()[0]
            if after is not None:
                # Revision is an opaque keyset cursor; resolve timestamp on the server.
                cursor = self.find(con, after)
                filters.append('(a.created_at<? OR (a.created_at=? AND a.revision<?))')
                args.extend((cursor['created_at'], cursor['created_at'], after))
                where = ' WHERE ' + ' AND '.join(filters)
            rows = con.execute('SELECT a.*' + joins + where + ' ORDER BY a.created_at DESC,a.revision DESC LIMIT ?', (*args, limit + 1)).fetchall()
            return dict(items=[self.view(con, control, enabled, row) for row in rows[:limit]], total=str(total),
                next_after=rows[limit - 1]['revision'] if len(rows) > limit else None,
                review_enabled=enabled, manual_review=MANUAL_REVIEW.copy())

    def detail(self, actor, revision):
        with self.transaction(actor) as (con, control, enabled, _):
            return self.view(con, control, enabled, self.find(con, revision), detail=True)

    def image(self, actor, revision, role):
        if role not in ('closeup', 'overview', 'reference'):
            raise ValueError('Invalid photo role.')
        with self.transaction(actor) as (con, _, _, _):
            row = self.find(con, revision)
            path = references(row).get(role)
            if path is None:
                raise GuitarMissing()
            # Drafts may only have one uploaded image; complete-photo validation
            # is required on acceptance, not on inspecting an individual image.
            return self.storage.get(decode_reference(path))

    def decide(self, actor, revision, operation, reason, expected_version):
        if operation not in ACTIONS or not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 2000:
            raise ValueError('Invalid reasoned application decision.')
        if not isinstance(expected_version, str) or not re.fullmatch('[0-9a-f]{64}', expected_version):
            raise ValueError('Invalid displayed version.')
        with self.transaction(actor, True) as (con, control, enabled, accounts):
            row = self.find(con, revision)
            paused = self.paused(control, revision)
            if expected_version != self.version(con, row, paused):
                raise ApplicationConflict('Application changed. Refresh before deciding.')
            if row['status'] == 'draft' and row['expires_at'] <= time.time():
                raise ApplicationConflict('Application draft expired.')
            if operation in ('accept', 'retry'):
                for role in self.photos(row):
                    self.photo(row, role)
            if operation in ('accept', 'reject') and row['individual_id']:
                from ygc.disputes import guard
                guard(con, row['individual_id'], row['claim_id'])
                if row['claim_id']:
                    claim = con.execute('SELECT * FROM claims WHERE id=?', (row['claim_id'],)).fetchone()
                    if not claim or claim['status'] != 'active' or claim['individual_id'] != row['individual_id']:
                        raise ApplicationConflict('Claim moved, was removed, or is inactive.')
            retained = []
            for saved in control.execute('SELECT kind,received_at,payload FROM paused_review_answers WHERE revision=%s ORDER BY received_at,kind', (revision,)).fetchall():
                retained.append({'kind': saved['kind'], 'received_at': saved['received_at'],
                                 'payload': safe_diagnostic(json.loads(saved['payload']))})
            common.administer_in_connection(ReviewRepository(con), con, revision, operation, reason,
                common.management_version(con, row), actor='identity-platform:' + actor, return_detail=False,
                invalidation_check=lambda connection, saved: self.invalidated(connection, saved, accounts),
                review_context={'retained_answers': retained} if retained else None)
            # Commit content first. If deletion in Operations fails, stale saved
            # answers still cannot apply because the old lease was revoked.
            control.execute('DELETE FROM paused_review_answers WHERE revision=%s', (revision,))
            return self.view(con, control, enabled, self.find(con, revision), detail=True)
