"""OIDC worker operations over fenced PostgreSQL transactions and private Storage.

No credentials or inference client live here. The gateway authenticates the
worker; YGC alone evaluates observations and creates Claims.
"""
import base64
from contextlib import contextmanager
import hashlib
from io import BytesIO
import json
import re
import secrets
import time

from PIL import Image, UnidentifiedImageError
from ygc import acquire_review as common, listing_review
from ygc.cloud_applications import references
from ygc.cloud_content_media import decode_reference, MediaConflict
from ygc.db.postgres import connect
from ygc.db.postgres_accounts import PROJECTION_FIELDS
from ygc.db.postgres_ownership import BoundRepository
from ygc.db.postgres_queries import ObservationConnection, SharedCursor, qmark_parameters
from ygc.db.repository import utcnow


class PrivatePhotoUnavailable(ValueError):
    """One application's immutable evidence cannot be read or decoded."""


def storage_photo_failure(error):
    # Classify only exact-object failures, never authorization, transient service
    # errors, or database/integrity errors. The SDK is an optional dependency.
    if isinstance(error, (FileNotFoundError, KeyError, ValueError)):
        return True
    try:
        from google.api_core.exceptions import NotFound, PreconditionFailed
        from google.cloud.storage.exceptions import DataCorruption
    except ImportError:
        return False
    return isinstance(error, (NotFound, PreconditionFailed, DataCorruption))


class ReviewConnection(ObservationConnection):
    """Only initial Listing's three legacy inserts require lastrowid."""
    def execute(self, query, parameters=None):
        match = re.match(r'\s*INSERT\s+INTO\s+(individuals|claims|media_assets)\s*\(', query, re.I)
        if match and not re.search(r'\bRETURNING\b', query, re.I):
            cursor = self.connection.execute(qmark_parameters(query) + ' RETURNING id', parameters or ())
            result = SharedCursor(cursor)
            result.lastrowid = cursor.fetchone()['id']
            return result
        return super().execute(query, parameters)


class ReviewRepository(BoundRepository):
    def create_initial_listing_claim(self, user_id, **kwargs):
        # Keep submitted evidence private: no public representative Media is
        # introduced until the separate publication/consent flow is connected.
        result = super().create_initial_listing_claim(user_id, **kwargs)
        con = kwargs['connection']
        con.execute('DELETE FROM claim_evidence WHERE media_asset_id=?', (result[3],))
        con.execute('DELETE FROM media_assets WHERE id=?', (result[3],))
        return result


class CloudReview:
    def __init__(self, settings, storage):
        self.settings, self.storage = settings, storage

    @staticmethod
    def tools():
        return common.tools() + listing_review.tools()

    @contextmanager
    def transaction(self):
        # Same maintenance/Crawl mutex and canonical->projection lock order as
        # existing content writers. Review OFF is independent of user modes.
        with connect(self.settings, 'operations') as control:
            if not control.execute('SELECT pg_try_advisory_xact_lock(79432190) AS locked').fetchone()['locked']:
                raise MediaConflict('Maintenance or Crawl is running.')
            enabled = bool(control.execute('SELECT enabled FROM review_settings WHERE id=1 FOR SHARE').fetchone()['enabled'])
            with connect(self.settings, 'accounts') as source:
                source.execute("SET LOCAL lock_timeout='5s'")
                source.execute('LOCK TABLE account_records IN SHARE MODE')
                accounts = {r['id']: r for r in source.execute('SELECT * FROM account_records')}
                with connect(self.settings, 'chronicle') as dest:
                    dest.execute("SET LOCAL lock_timeout='5s'")
                    dest.execute("SET LOCAL statement_timeout='10s'")
                    dest.execute('SELECT pg_advisory_xact_lock(79432002)')
                    projected = {r['id']: r for r in dest.execute('''SELECT u.*, r.revision AS projection_revision
                        FROM users u LEFT JOIN account_projection_receipts r ON r.account_id=u.id''')}
                    for user, account in accounts.items():
                        row = projected.get(user)
                        if not row or row['projection_revision'] != account['projection_version'] or any(
                            row[key] != account[key] for key in PROJECTION_FIELDS if key not in ('identity_provider', 'identity_subject')):
                            raise ValueError('Canonical account projection is pending.')
                    if set(projected) - set(accounts):
                        raise ValueError('Unknown projected account.')
                    yield ReviewConnection(dest), control, enabled, accounts

    def invalidated(self, con, row, accounts):
        account = accounts.get(row['applicant_id'])
        if not account or account['disabled'] or account['ban_status'] != 'normal':
            return 'Applicant account is unavailable.'
        reason = common.invalidated(con, row)
        if reason:
            return reason
        if row['request_kind'] == 'acquire':
            from ygc.disputes import active
            if active(con, row['individual_id']):
                return 'Ownership dispute is active; submit again after resolution.'
            source = json.loads(row['reference_source'])
            if source.get('claim_revision'):
                from ygc.claim_revision import revision
                claim = con.execute('SELECT * FROM claims WHERE id=?', (source['claim_id'],)).fetchone()
                if not claim or revision(claim) != source['claim_revision']:
                    return 'Reference Claim changed; submit again.'
        return None

    @staticmethod
    def lease(con, key, kind, *, enabled=True):
        row = common.find(con, key.revision)
        if row['request_kind'] != kind or not row['lease_token'] or not secrets.compare_digest(row['lease_token'], key.lease_token):
            raise ValueError('Review lease is invalid.')
        if row['status'] not in common.TERMINAL and (row['status'] != 'processing' or (enabled and row['lease_until'] <= time.time())):
            raise ValueError('Review lease expired.')
        return row

    @staticmethod
    def photos(row):
        try:
            images = references(row)
        except (ValueError, TypeError) as error:
            raise PrivatePhotoUnavailable('Private photo references are invalid.') from error
        required = {'closeup', 'overview'}
        if json.loads(row['reference_source'])['kind'] != 'absent':
            required.add('reference')
        if not required <= images.keys():
            raise PrivatePhotoUnavailable('Required private photos are missing.')
        return images

    def photo(self, row, role):
        path = self.photos(row).get(role)
        if not path:
            raise PrivatePhotoUnavailable('Private photo unavailable.')
        if self.storage is None:
            raise RuntimeError('Private photo storage is unavailable.')
        try:
            data = self.storage.get(decode_reference(path))
        except Exception as error:
            if not storage_photo_failure(error):
                raise
            raise PrivatePhotoUnavailable('Private photo unavailable.') from error
        try:
            with Image.open(BytesIO(data)) as photo:
                photo.verify()
            # JPEG verify() checks headers only; force decoding as well so a
            # truncated pixel stream cannot be leased or accepted as evidence.
            with Image.open(BytesIO(data)) as photo:
                photo.load()
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
            raise PrivatePhotoUnavailable('Private photo cannot be decoded.') from error
        return data

    @staticmethod
    def photo_error(con, row):
        # This runs before Claim/notification writes. Keep the application for an
        # explicit applicant retry, but revoke its worker's execution authority.
        reason = 'Private review photos are unavailable. Retry after the photos are restored.'
        con.execute("UPDATE acquire_applications SET status='error',error=?,lease_token=NULL,lease_until=NULL WHERE revision=?",
                    (reason, row['revision']))
        common.event(con, row['revision'], 'error', reason)

    def close(self, con, row, reason):
        con.execute("UPDATE acquire_applications SET status='closed',error=?,completed_at=?,lease_token=NULL,lease_until=NULL WHERE revision=?",
                    (reason, utcnow(), row['revision']))
        common.event(con, row['revision'], 'closed', reason)

    def apply(self, con, row, review, accounts):
        received = review.model_dump(exclude={'lease_token'})
        if row['status'] in common.TERMINAL:
            if not row['received'] or json.loads(row['received']) != received:
                raise ValueError('Different result already received.')
            return
        if row['status'] != 'processing':
            raise ValueError('Application is not processing.')
        reason = self.invalidated(con, row, accounts)
        if reason:
            self.close(con, row, reason)
            return
        for role in self.photos(row):
            self.photo(row, role)
        common.apply_review(ReviewRepository(con), con, row, review)

    @staticmethod
    def model(name):
        return common.ProductRequest if name.endswith('_product_details') else common.Failure if name.startswith('ygc_fail_') else listing_review.ListingReview if 'listing' in name else common.Review

    def answer(self, con, row, name, request, accounts):
        if name.endswith('_product_details'):
            if row['status'] != 'processing':
                raise ValueError('Application is not processing.')
            observed = request.observations.model_dump()
            if row['product_observations'] and json.loads(row['product_observations']) != observed:
                raise ValueError('Independent observations are immutable.')
            con.execute('UPDATE acquire_applications SET product_observations=? WHERE revision=?', (json.dumps(observed), row['revision']))
            return {'product_details': json.loads(row['product_details']), 'observations': observed}
        if name.startswith('ygc_fail_'):
            if row['status'] != 'processing':
                raise ValueError('Application is not processing.')
            con.execute("UPDATE acquire_applications SET status='error',error=?,lease_token=NULL,lease_until=NULL WHERE revision=?", (request.reason, row['revision']))
            common.event(con, row['revision'], 'error', request.reason)
        else:
            self.apply(con, row, request, accounts)
        done = common.find(con, row['revision'])
        return {'status': done['status'], 'revision': done['revision'], 'claim_id': done['claim_id']}

    def retain(self, control, con, row, name, request):
        payload = request.model_dump()
        if name.startswith('ygc_submit_'):
            observed = row['product_observations'] or control.execute('SELECT payload FROM paused_review_answers WHERE revision=%s AND kind=%s', (row['revision'], 'ygc_' + row['request_kind'] + '_product_details')).fetchone()
            if not observed or request.product_consistency is None:
                raise ValueError('Independent observations and product assessment required.')
            if (json.loads(row['reference_source'])['kind'] == 'absent') != (request.identity is None):
                raise ValueError('Identity assessment does not match reference availability.')
        if name.startswith(('ygc_submit_', 'ygc_fail_')):
            other = ('ygc_fail_' + row['request_kind']) if name.startswith('ygc_submit_') else ('ygc_submit_' + row['request_kind'] + '_review')
            if control.execute('SELECT 1 FROM paused_review_answers WHERE revision=%s AND kind=%s', (row['revision'], other)).fetchone():
                raise ValueError('Conflicting paused outcome already recorded.')
        previous = control.execute('SELECT payload FROM paused_review_answers WHERE revision=%s AND kind=%s', (row['revision'], name)).fetchone()
        if previous and json.loads(previous['payload']) != payload:
            raise ValueError('Different paused answer already recorded.')
        if name.endswith('_product_details') and row['product_observations'] and json.loads(row['product_observations']) != payload['observations']:
            raise ValueError('Independent observations are immutable.')
        control.execute('''INSERT INTO paused_review_answers(revision,kind,received_at,payload) VALUES(%s,%s,%s,%s)
            ON CONFLICT(revision,kind) DO NOTHING''', (row['revision'], name, utcnow(), json.dumps(payload)))
        if name.endswith('_product_details'):
            return {'product_details': json.loads(row['product_details']), 'observations': payload['observations'], 'paused': True}
        return {'status': 'processing', 'revision': row['revision'], 'paused': True, 'answer_received': True, 'applied': False}

    def replay(self, con, control, accounts):
        # Content commits before deletion of retained answers. A crash between
        # those commits is safe because replay checks lease and identical result.
        rows = control.execute('''SELECT * FROM paused_review_answers WHERE kind=ANY(%s)
            ORDER BY CASE WHEN kind LIKE %s THEN 0 ELSE 1 END,received_at''',
            ([t['name'] for t in self.tools()], '%product_details')).fetchall()
        for saved in rows:
            request = self.model(saved['kind']).model_validate(json.loads(saved['payload']))
            kind = 'listing' if 'listing' in saved['kind'] else 'acquire'
            row = con.execute('SELECT * FROM acquire_applications WHERE revision=?', (saved['revision'],)).fetchone()
            if row and row['lease_token'] and secrets.compare_digest(row['lease_token'], request.lease_token) and row['request_kind'] == kind:
                if row['status'] == 'processing':
                    # OFF time does not turn an already received answer into a
                    # timeout, but cancellation/restore/rotation still invalidate it.
                    try:
                        self.answer(con, row, saved['kind'], request, accounts)
                    except PrivatePhotoUnavailable:
                        self.photo_error(con, row)
                elif row['status'] in common.TERMINAL and saved['kind'].startswith('ygc_submit_'):
                    self.apply(con, row, request, accounts)
            control.execute('DELETE FROM paused_review_answers WHERE revision=%s AND kind=%s', (saved['revision'], saved['kind']))

    def call_tool(self, name, args):
        if name not in {t['name'] for t in self.tools()} or not isinstance(args, dict):
            raise ValueError('Unsupported review tool.')
        kind = 'listing' if 'listing' in name else 'acquire'
        with self.transaction() as (con, control, enabled, accounts):
            if name.startswith('ygc_pending_'):
                request = common.Pending.model_validate(args)
                if not enabled:
                    return {'jobs': [], 'remaining_revisions': [], 'instructions': 'Review is paused.'}
                self.replay(con, control, accounts)
                for row in con.execute("SELECT * FROM acquire_applications WHERE status='processing' AND lease_until<=?", (time.time(),)).fetchall():
                    state = 'error' if row['attempts'] >= 3 else 'pending'
                    con.execute('UPDATE acquire_applications SET status=?,lease_token=NULL,lease_until=NULL,error=? WHERE revision=?', (state, 'Review lease timed out.', row['revision']))
                    common.event(con, row['revision'], 'timeout')
                revisions = request.remaining_revisions
                if revisions is not None and (len(revisions) > 500 or any(not isinstance(r, str) or not re.fullmatch('[0-9a-f]{32}', r) for r in revisions)):
                    raise ValueError('Invalid queue cursor.')
                rows = con.execute("SELECT * FROM acquire_applications WHERE status='pending' AND request_kind=? ORDER BY submitted_at,revision", (kind,)).fetchall()
                rows = [r for r in rows if revisions is None or r['revision'] in revisions][:500]
                jobs = []
                while rows and not jobs:
                    row = rows.pop(0)
                    reason = self.invalidated(con, row, accounts)
                    if reason:
                        self.close(con, row, reason)
                        continue
                    meta = {}
                    try:
                        for role in self.photos(row):
                            data = self.photo(row, role)
                            with Image.open(BytesIO(data)) as photo:
                                meta[role] = {'sha256': hashlib.sha256(data).hexdigest(), 'width': photo.width, 'height': photo.height}
                    except PrivatePhotoUnavailable:
                        self.photo_error(con, row)
                        continue
                    lease = secrets.token_urlsafe(32)
                    version = listing_review.PROMPT_VERSION if kind == 'listing' else common.PROMPT_VERSION
                    con.execute("UPDATE acquire_applications SET status='processing',started_at=?,lease_token=?,lease_until=?,attempts=attempts+1,error=NULL,product_observations=NULL,prompt_version=? WHERE revision=?",
                                (utcnow(), lease, time.time() + common.LEASE_SECONDS, version, row['revision']))
                    common.event(con, row['revision'], 'claimed', json.dumps(meta))
                    jobs = [{'revision': row['revision'], 'lease_token': lease, 'request_kind': kind, 'images': meta, 'reference_available': 'reference' in meta}]
                return {'jobs': jobs, 'remaining_revisions': [r['revision'] for r in rows], 'instructions': listing_review.PROMPT if kind == 'listing' else common.PROMPT}
            key = common.Key.model_validate({k: args.get(k) for k in ('revision', 'lease_token')})
            request = (common.ImageKey if name.endswith('_image') else self.model(name)).model_validate(args)
            # Retained failure/result can revoke a lease or complete the job.
            # Recheck execution authority after replay, including image reads.
            if enabled:
                self.replay(con, control, accounts)
            try:
                row = self.lease(con, key, kind, enabled=enabled)
                if name.endswith('_image') and (not enabled or row['status'] != 'processing'):
                    raise ValueError('Review image access is paused or completed.')
                if row['status'] != 'processing' and (not enabled or not name.startswith('ygc_submit_')):
                    raise ValueError('Application is not processing.')
            except ValueError as error:
                # Commit independently received answers even when this caller's
                # now-stale key is rejected. Do not catch errors from mutations.
                rejected = error
            else:
                if name.endswith('_image'):
                    return {'content': [{'type': 'image', 'mimeType': 'image/jpeg', 'data': base64.b64encode(self.photo(row, request.role)).decode()}]}
                if not enabled:
                    return self.retain(control, con, row, name, request)
                return self.answer(con, row, name, request, accounts)
        raise rejected
