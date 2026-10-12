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
from ygc.cloud_claim_media import PHOTO_CLAIM_TYPES, media_rows, media_projection, image_reference


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
    # A successful same-stance response consumes its confirmation even when
    # timestamps coincide. Inbox read state is deliberately not part of this
    # token. Shared former-owner pairs must invalidate each other's decisions.
    content['verification_notice_id'] = connection.execute("""SELECT MAX(n.id)
        FROM notifications n JOIN claims c ON c.id=n.claim_id
        WHERE n.notification_type='claim_verified' AND n.recipient_user_id=? AND
          (c.id=? OR (c.individual_id=? AND c.ownership_source='former_owner'
            AND c.ownership_pair_id IS NOT NULL AND c.ownership_pair_id=
              (SELECT ownership_pair_id FROM claims WHERE id=? AND ownership_source='former_owner')))""",
        (row['author_user_id'], row['id'], row['individual_id'], row['id'])).fetchone()[0]
    content['spec_items'] = specification_items(connection, row)
    if row['claim_type'] in PHOTO_CLAIM_TYPES:
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

    def inbox_candidates(self, actor, after, limit):
        with self.operations.access('user_read', actor) as (_, _, account):
            with connect(self.settings, 'chronicle') as con:
                con.execute("SET LOCAL statement_timeout='5s'")
                return [dict(row) for row in con.execute("""SELECT c.id,c.individual_id,
                    i.manufacturer,i.model FROM claims c
                    JOIN individuals i ON i.id=c.individual_id
                    JOIN acquire_applications a ON a.claim_id=c.id
                    JOIN users u ON u.id=c.author_user_id
                    WHERE i.current_owner_user_id=%s AND c.author_user_id<>%s
                    AND c.id>%s AND c.status='active' AND c.verification_status='unverified'
                    AND c.claim_type='ownership' AND c.ownership_kind='acquire'
                    AND COALESCE(c.ownership_source,'') NOT IN ('former_owner','automation','merged_listing')
                    AND a.status='accepted' AND a.request_kind='acquire' AND u.ban_status='normal'
                    ORDER BY c.id LIMIT %s""", (account['id'],account['id'],after,limit)).fetchall()]

    def inbox(self, actor, after=0):
        if type(after) is not int or not 0 <= after < 2**63:
            raise ValueError('Invalid cursor.')
        candidates = self.inbox_candidates(actor, after, 51)
        items, checked = [], {}
        for candidate in candidates[:50]:
            individual = candidate['individual_id']
            if individual not in checked:
                # Reuse canonical participant/BAN/dispute/ownership rules. This
                # list is advisory; opening and answering revalidate once more.
                checked[individual] = self.pending(actor, individual)
            for row in checked[individual]['items']:
                if (row['id'] == str(candidate['id']) and row['verification_status'] == 'unverified'
                        and row['decline_reason_required']):
                    items.append(dict(id=row['id'], individual_id=str(individual),
                        author_name=row['author_name'], product_name=' '.join(filter(None,
                            [candidate['manufacturer'], candidate['model']])),
                        can_write=checked[individual]['can_write']))
        return dict(items=items, next_after=str(candidates[49]['id']) if len(candidates)>50 else None)

    def pending(self, actor, individual):
        from ygc import disputes
        with self.transaction(actor, individual) as (repo, user):
            ids = repo.owner_verifiable_claim_ids(individual, user)
            return {'can_write': getattr(repo, 'can_write', False), 'items': [dict(id=str(row['id']), individual_id=str(individual),
                author_name=row['author_name'], claim_type=row['claim_type'],
                ownership_kind=row['ownership_kind'], occurred_at=row['occurred_at'], body=row['body'],
                field_name=row['field_name'], value_text=row['value_text'],
                event_kind=row['value_text'] if row['claim_type'] == 'event' else None,
                specification_kind=row['specification_kind'], spec_items=specification_items(repo.connection, row),
                decline_reason_required=disputes.eligible(repo.connection, disputes.candidate(repo.connection, row['id'])),
                verification_status=row['verification_status'], created_at=row['created_at'],
                updated_at=row['updated_at'], revision=content_revision(repo.connection, row))
                | media_projection(repo.connection, row)
                for claim in sorted(ids,reverse=True)
                if (row := repo.connection.execute('''SELECT c.*,u.display_name AS author_name
                    FROM claims c JOIN users u ON u.id=c.author_user_id WHERE c.id=?
                    AND (c.claim_type NOT IN ('media','event') OR u.ban_status='normal')''', (claim,)).fetchone())]}

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
            if row['claim_type'] in PHOTO_CLAIM_TYPES:
                if (claim not in repo.owner_verifiable_claim_ids(individual, user)
                        or not repo.connection.execute("SELECT 1 FROM users WHERE id=? AND ban_status='normal'",
                                                       (row['author_user_id'],)).fetchone()):
                    # A handoff/BAN revokes the photo review even if the Claim
                    # itself did not change. Signal the UI to discard old blobs.
                    raise ClaimConflict('Photo Claim is no longer available for review.')
                # Legacy local paths remain manageable by their author, but
                # cannot support a cloud review of the attached photos.
                for attachment in media_rows(repo.connection, row):
                    image_reference(attachment)
            if content_revision(repo.connection, row) != data['revision']:
                raise ClaimConflict('Claim changed; reload before responding.')
            if not repo.set_claim_response_in_connection(repo.connection, claim, user, data['stance'], reason):
                raise ClaimConflict('Claim is no longer active.')
            repo.create_verification_notification_in_connection(
                repo.connection, claim, user, data['stance'])
            return {'claim_id': str(claim), 'verification_status': data['stance']}
