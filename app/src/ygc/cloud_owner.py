"""Current Owner responses through canonical identity and shared Claim rules."""
from contextlib import contextmanager
import re
import hashlib
import json
from ygc.claim_revision import revision, ClaimConflict
from ygc.cloud_guitars import positive_id
from ygc.db.postgres import connect
from ygc.db.postgres_ownership import PostgresOwnership
from ygc.platform_boundaries import ActorContext
from ygc.cloud_claim_media import media_rows, media_projection


def specification_items(connection, row):
    """Expose complete review content within the existing Claim input limits."""
    if row['claim_type'] != 'specification':
        return []
    items = [dict(item) for item in connection.execute(
        'SELECT field_name,value_text FROM claim_spec_items WHERE claim_id=? ORDER BY id LIMIT 51',
        (row['id'],)).fetchall()]
    if not items and row['field_name']:
        items = [dict(field_name=row['field_name'], value_text=row['value_text'])]
    # Never invite approval of silently truncated or missing Claim content.
    if not items or len(items) > 50 or any(
        not isinstance(item[key], str) or not item[key] or len(item[key]) > limit
        for item in items for key, limit in (('field_name', 120), ('value_text', 500))
    ):
        raise ValueError('Claim specification content cannot be fully reviewed.')
    return items


def content_revision(connection, row):
    """Bind confirmation to complete typed content, not just its timestamp."""
    content = {key: row[key] for key in ('claim_type', 'specification_kind', 'field_name',
        'value_text', 'body', 'occurred_at', 'author_user_id')}
    content['revision'] = revision(row)
    content['spec_items'] = specification_items(connection, row)
    if row['claim_type'] == 'media':
        content['media_items'] = media_rows(connection, row)
    return hashlib.sha256(json.dumps(content, ensure_ascii=True, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


class CloudOwner:
    def __init__(self, settings, operations):
        self.settings, self.operations = settings, operations

    @contextmanager
    def transaction(self, actor, individual, *, write=False):
        positive_id(str(individual))
        with connect(self.settings, 'operations') as guard:
            if write and not guard.execute('SELECT pg_try_advisory_xact_lock(79432190) AS locked').fetchone()['locked']:
                raise ClaimConflict('Maintenance or Crawl is running.')
            with self.operations.access('user_write' if write else 'user_read', actor) as (_, mode, account):
                principal = ActorContext(account['id'], 'identity-platform', None, True, account['app_user_id'])
                with PostgresOwnership(self.settings)._transaction(principal, individual) as (repo, canonical):
                    repo.can_write = mode['mode'] != 'read_only'
                    yield repo, canonical['id']

    def pending(self, actor, individual):
        from ygc import disputes
        with self.transaction(actor, individual) as (repo, user):
            ids = repo.owner_verifiable_claim_ids(individual, user)
            return {'can_write': getattr(repo, 'can_write', False), 'items': [dict(id=str(row['id']), individual_id=str(individual),
                author_name=row['author_name'], claim_type=row['claim_type'],
                ownership_kind=row['ownership_kind'], occurred_at=row['occurred_at'], body=row['body'],
                field_name=row['field_name'], value_text=row['value_text'],
                specification_kind=row['specification_kind'], spec_items=specification_items(repo.connection, row),
                decline_reason_required=disputes.eligible(repo.connection, disputes.candidate(repo.connection, row['id'])),
                verification_status=row['verification_status'], created_at=row['created_at'],
                updated_at=row['updated_at'], revision=content_revision(repo.connection, row))
                | media_projection(repo.connection, row)
                for claim in sorted(ids,reverse=True)
                if (row := repo.connection.execute('''SELECT c.*,u.display_name AS author_name
                    FROM claims c JOIN users u ON u.id=c.author_user_id WHERE c.id=?
                    AND (c.claim_type<>'media' OR u.ban_status='normal')''', (claim,)).fetchone())]}

    def respond(self, actor, individual, claim, data):
        positive_id(str(claim))
        if not isinstance(data, dict) or not {'stance', 'revision'} <= set(data) or set(data) - {'stance', 'revision', 'reason'} or data['stance'] not in ('positive', 'negative', 'unverified') or not isinstance(data['revision'], str) or not re.fullmatch('[0-9a-f]{64}', data['revision']):
            raise ValueError('Invalid Owner response.')
        reason = data.get('reason')
        if 'reason' in data:
            if data['stance'] != 'negative' or not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 4000:
                raise ValueError('Invalid decline reason.')
            reason = reason.strip()
        with self.transaction(actor, individual, write=True) as (repo, user):
            row = repo.connection.execute('SELECT * FROM claims WHERE id=? FOR UPDATE', (claim,)).fetchone()
            if not row or row['individual_id'] != individual:
                raise ClaimConflict('Claim changed; reload before responding.')
            if row['claim_type'] == 'media':
                if (claim not in repo.owner_verifiable_claim_ids(individual, user)
                        or not repo.connection.execute("SELECT 1 FROM users WHERE id=? AND ban_status='normal'",
                                                       (row['author_user_id'],)).fetchone()):
                    # A handoff/BAN revokes the photo review even if the Claim
                    # itself did not change. Signal the UI to discard old blobs.
                    raise ClaimConflict('Media Claim is no longer available for review.')
            if content_revision(repo.connection, row) != data['revision']:
                raise ClaimConflict('Claim changed; reload before responding.')
            if not repo.set_claim_response_in_connection(repo.connection, claim, user, data['stance'], reason):
                raise ClaimConflict('Claim is no longer active.')
            return {'claim_id': str(claim), 'verification_status': data['stance']}
