"""Canonical-account fenced adapter for the established private dispute rules.

The shared local state machine owns eligibility, rounds, chronology and atomic
resolution. These methods add bounded inputs, revision/round CAS and private
allowlisted models. Attachments are fetched separately, only after permission.
"""
from contextlib import contextmanager
from datetime import timedelta, timezone
import re
import threading

from ygc import disputes
from ygc.claim_revision import ClaimConflict
from ygc.cloud_claims import ClaimConnection
from ygc.cloud_dispute_dto import (acknowledgment_payload, submission_payload, publication_payload,
    decision_payload, text, result_projection, request_projection,
    bounded, MAX_ROUNDS, MAX_EVENTS, MAX_CLAIMS, MAX_EVIDENCE, MAX_PARTIES)
from ygc.cloud_dispute_storage import CloudDisputeStorage, OriginalUnavailable, read_original
from ygc.cloud_backup_preflight import preflight_legacy_evidence
from ygc.cloud_guitars import GuitarMissing
from ygc.cloud_ownership import identifier, page, digest, guitar, person, ownership_revision
from ygc.db.postgres import connect, status as database_status
from ygc.db.postgres_accounts import PostgresAccounts
from ygc.db.postgres_ownership import BoundRepository, PostgresOwnership
from ygc.db.postgres_queries import ObservationConnection, SharedCursor, qmark_parameters

UPLOADS = threading.BoundedSemaphore(1)


class DisputeConnection(ClaimConnection):
    """Generated dispute IDs without changing shared SQL or fetching BYTEA."""
    def execute(self, query, parameters=None):
        if re.match(r'\s*INSERT\s+INTO\s+ownership_dispute(?:s|_rounds|_evidence|_events)\s*\(', query, re.I):
            cursor = self.connection.execute(qmark_parameters(query) + ' RETURNING id', parameters or ())
            result = SharedCursor(cursor)
            result.lastrowid = cursor.fetchone()['id']
            return result
        return super().execute(query, parameters)


def candidate(connection, claim_id, user):
    row = disputes.candidate(connection, claim_id)
    if row is None or row['author_user_id'] != user:
        raise GuitarMissing()
    return row


def case_row(connection, case_id, user, admin=False):
    row = connection.execute('SELECT * FROM ownership_disputes WHERE id=?', (case_id,)).fetchone()
    if row is None or (not admin and user not in disputes.participants(connection, row)):
        raise GuitarMissing()
    return row


def evidence_row(connection, evidence_id, user, admin=False):
    row = connection.execute('''SELECT id,dispute_id,claim_id,author_id,content_type,filename,
        published_at FROM ownership_dispute_evidence WHERE id=?''', (evidence_id,)).fetchone()
    if row is None:
        raise GuitarMissing()
    case_row(connection, row['dispute_id'], user, admin)
    if not admin and row['author_id'] != user:
        raise GuitarMissing()
    return row


def candidate_revision(connection, row):
    decline = connection.execute('SELECT * FROM ownership_declines WHERE claim_id=?', (row['id'],)).fetchone()
    applications = [dict(r) for r in connection.execute('''SELECT revision,claim_id,applicant_id,status,request_kind
        FROM acquire_applications WHERE claim_id=? ORDER BY revision''', (row['id'],))]
    return digest({'claim': dict(row), 'decline': dict(decline) if decline else None,
                   'applications': applications, 'ownership': ownership_revision(connection, row['individual_id']),
                   'decline_notice': connection.execute("SELECT MAX(id) FROM notifications WHERE claim_id=? AND notification_type='ownership_decline'", (row['id'],)).fetchone()[0]})


def check_case(connection, case, version, round_number):
    rnd = disputes.current_round(connection, case['id'])
    if case['version'] != version or rnd is None or rnd['number'] != round_number:
        raise ClaimConflict('Dispute or evidence round changed; reload before retrying.')
    return rnd


class CloudDisputes:
    def __init__(self, settings, operations, storage=None):
        self.settings, self.operations, self.storage = settings, operations, storage

    def check_schema(self):
        """Read-only gate; runtime never initializes or migrates a database."""
        result = database_status(self.settings, 'chronicle')
        if result['version'] < 3:
            raise RuntimeError('Private dispute storage migration is required.')
        return result

    @staticmethod
    def _rows(connection, user, kind, after, limit, status, admin):
        if kind == 'options':
            return connection.execute('''SELECT c.id,c.individual_id FROM claims c
                WHERE c.author_user_id=? AND c.status='active' AND c.claim_type='ownership'
                AND c.ownership_kind='acquire' AND COALESCE(c.ownership_source,'') NOT IN
                    ('former_owner','automation','merged_listing')
                AND EXISTS (SELECT 1 FROM acquire_applications a WHERE a.claim_id=c.id AND a.status='accepted' AND a.request_kind='acquire')
                AND NOT EXISTS (SELECT 1 FROM ownership_dispute_claims dc WHERE dc.claim_id=c.id)
                AND NOT EXISTS (SELECT 1 FROM ownership_declines d WHERE d.claim_id=c.id AND d.acknowledged_at IS NOT NULL)
                AND (?=0 OR c.id<?) ORDER BY c.id DESC LIMIT ?''', (user, after, after, limit + 1)).fetchall()
        return connection.execute('''SELECT d.id,d.individual_id FROM ownership_disputes d
            WHERE (?='all' OR d.status=?) AND (?=1 OR d.owner_id=? OR EXISTS (
                SELECT 1 FROM ownership_dispute_claims dc WHERE dc.dispute_id=d.id AND dc.applicant_id=?))
            AND (?=0 OR d.id<?) ORDER BY d.id DESC LIMIT ?''',
            (status, status, int(admin), user, user, after, after, limit + 1)).fetchall()

    @staticmethod
    def _target(connection, user, *, claim=None, case=None, evidence=None, admin=False):
        if evidence is not None:
            record = evidence_row(connection, evidence, user, admin)
            case = record['dispute_id']
        if case is not None:
            return case_row(connection, case, user, admin)['individual_id']
        return candidate(connection, claim, user)['individual_id']

    @contextmanager
    def transaction(self, actor, *, claim=None, case=None, evidence=None, admin=False, write=False, listing=None):
        for value in (claim, case, evidence):
            if value is not None:
                identifier(value)
        if type(admin) is not bool:
            raise ValueError('Invalid dispute access category.')
        self.check_schema()
        with connect(self.settings, 'operations') as guard:
            if write and not guard.execute('SELECT pg_try_advisory_xact_lock(79432190) AS locked').fetchone()['locked']:
                raise ClaimConflict('Maintenance or Crawl is running.')
            kind = ('admin_' if admin else 'user_') + ('write' if write else 'read')
            with self.operations.access(kind, actor) as (_, mode, account):
                if account['ban_status'] != 'normal':
                    raise PermissionError('An active dispute participant is required.')
                with connect(self.settings, 'chronicle') as raw:
                    raw.execute("SET LOCAL statement_timeout='5s'")
                    raw.execute("SET LOCAL lock_timeout='2s'")
                    before = ObservationConnection(raw)
                    if listing is not None:
                        rows = self._rows(before, account['id'], *listing, admin)
                        targets = {r['individual_id'] for r in rows}
                    else:
                        targets = {self._target(before, account['id'], claim=claim, case=case, evidence=evidence, admin=admin)}
                    scope = {account['id']}
                    for individual in targets:
                        scope.update(PostgresOwnership._participants(raw, individual))
                        # Resolved cases retain the original parties, including
                        # owners no longer present in the latest Snapshot.
                        scope.update(r[0] for r in before.execute('''SELECT owner_id FROM ownership_disputes WHERE individual_id=?
                            UNION SELECT dc.applicant_id FROM ownership_dispute_claims dc JOIN ownership_disputes d
                            ON d.id=dc.dispute_id WHERE d.individual_id=?''', (individual, individual)))
                with PostgresAccounts(self.settings).content_transaction(actor, scope, require_admin=admin) as (raw, canonical):
                    if canonical['id'] != account['id'] or canonical['ban_status'] != 'normal':
                        raise PermissionError('Account participant mapping changed.')
                    raw.execute("SET LOCAL statement_timeout='5s'")
                    raw.execute("SET LOCAL lock_timeout='2s'")
                    connection = DisputeConnection(raw)
                    if listing is not None:
                        current = self._rows(connection, canonical['id'], *listing, admin)
                        if [dict(r) for r in current] != [dict(r) for r in rows]:
                            raise ClaimConflict('Dispute inbox changed; reload.')
                    elif {self._target(connection, canonical['id'], claim=claim, case=case, evidence=evidence, admin=admin)} != targets:
                        raise ClaimConflict('Dispute target changed; reload.')
                    for individual in targets:
                        current_scope = PostgresOwnership._participants(raw, individual)
                        current_scope.update(r[0] for r in connection.execute('''SELECT owner_id FROM ownership_disputes WHERE individual_id=?
                            UNION SELECT dc.applicant_id FROM ownership_dispute_claims dc JOIN ownership_disputes d
                            ON d.id=dc.dispute_id WHERE d.individual_id=?''', (individual, individual)))
                        if not current_scope.issubset(scope):
                            raise ClaimConflict('Dispute participants changed; reload.')
                    yield BoundRepository(connection), canonical['id'], admin or mode['mode'] != 'read_only'

    @staticmethod
    def _option(connection, row, user, can_write):
        decline = connection.execute('SELECT * FROM ownership_declines WHERE claim_id=?', (row['id'],)).fetchone()
        owner = connection.execute('SELECT current_owner_user_id FROM individuals WHERE id=?', (row['individual_id'],)).fetchone()[0]
        linked = connection.execute('SELECT dispute_id FROM ownership_dispute_claims WHERE claim_id=?', (row['id'],)).fetchone()
        opened = disputes.active(connection, row['individual_id'])
        rnd = disputes.current_round(connection, opened['id']) if opened else None
        eligible = disputes.eligible(connection, row)
        since = disputes.datetime.fromisoformat(row['requested_at'].replace('Z', '+00:00'))
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        deadline = since + timedelta(days=disputes.WAIT_DAYS)
        valid_decline = bool(decline and decline['owner_id'] == owner and not decline['acknowledged_at'])
        decline_ok = (not decline or valid_decline)
        ready = ((row['verification_status'] == 'negative' and valid_decline) or
                 (row['verification_status'] == 'unverified' and disputes.datetime.now(timezone.utc) >= deadline))
        return {'claim_id': str(row['id']), 'individual': guitar(connection, row['individual_id']),
                'applicant': person(connection, user), 'owner': person(connection, owner) if owner is not None else None,
                'requested_at': row['requested_at'], 'verification_status': row['verification_status'],
                'decline': {k: decline[k] for k in ('reason', 'created_at', 'acknowledged_at')} if decline else None,
                'eligible': bool(eligible), 'can_write': can_write,
                'can_acknowledge': bool(can_write and eligible and valid_decline and row['verification_status'] == 'negative' and not opened),
                'can_appeal': bool(can_write and eligible and decline_ok and ready and (not rnd or rnd['phase'] == 'collecting')),
                'wait_until': deadline.isoformat(), 'wait_days': disputes.WAIT_DAYS,
                'revision': candidate_revision(connection, row), 'case_id': str(linked[0]) if linked else None}

    def options(self, actor, *, after=0, limit=25):
        page(after, limit)
        listing = ('options', after, limit, 'open')
        with self.transaction(actor, listing=listing) as (repo, user, can_write):
            rows = self._rows(repo.connection, user, *listing, False)
            items = [self._option(repo.connection, candidate(repo.connection, r['id'], user), user, can_write) for r in rows[:limit]]
            return result_projection('options', {'items': [r for r in items if r['eligible']],
                'next_after': str(rows[limit - 1]['id']) if len(rows) > limit else None,
                'can_write': can_write, 'viewer_user_id': str(user)})

    def option(self, actor, claim):
        identifier(claim)
        with self.transaction(actor, claim=claim) as (repo, user, can_write):
            return result_projection('option', self._option(repo.connection, candidate(repo.connection, claim, user), user, can_write))

    @staticmethod
    def _case(connection, case, user, admin):
        rnd = disputes.current_round(connection, case['id'])
        if rnd is None:
            raise RuntimeError('Dispute round is unavailable.')
        current_owner = connection.execute('SELECT current_owner_user_id FROM individuals WHERE id=?', (case['individual_id'],)).fetchone()[0]
        applicants = connection.execute('''SELECT DISTINCT applicant_id FROM ownership_dispute_claims
            WHERE dispute_id=? AND (?=1 OR ?=? OR applicant_id=?) ORDER BY applicant_id LIMIT ?''',
            (case['id'], int(admin), user, case['owner_id'], user, MAX_CLAIMS + 1)).fetchall()
        bounded(applicants, MAX_CLAIMS)
        return {key: case[key] for key in ('id', 'individual_id', 'owner_id', 'locked_owner_id', 'winner_id',
                'status', 'version', 'created_at', 'updated_at', 'decision', 'reason')} | {
                'individual': guitar(connection, case['individual_id']), 'owner': person(connection, case['owner_id']),
                'current_owner': person(connection, current_owner) if current_owner is not None else None,
                'applicants': [person(connection, r['applicant_id']) for r in applicants],
                'round_number': rnd['number'], 'round_phase': rnd['phase']}

    def list(self, actor, *, after=0, limit=25, status='open', admin=False):
        page(after, limit)
        if status not in ('open', 'resolved', 'all') or type(admin) is not bool:
            raise ValueError('Invalid dispute filter.')
        listing = ('list', after, limit, status)
        with self.transaction(actor, listing=listing, admin=admin) as (repo, user, can_write):
            rows = self._rows(repo.connection, user, *listing, admin)
            return result_projection('list', {'items': [self._case(repo.connection,
                case_row(repo.connection, r['id'], user, admin), user, admin) for r in rows[:limit]],
                'next_after': str(rows[limit - 1]['id']) if len(rows) > limit else None,
                'can_write': can_write, 'viewer_user_id': str(user)})

    @classmethod
    def _detail(cls, connection, case, user, can_write, admin=False):
        result = cls._case(connection, case, user, admin)
        result.update(viewer_user_id=str(user), can_write=can_write, is_admin=admin,
            can_reopen=bool(admin and can_write and case['status'] == 'resolved' and result['current_owner']
                and str(case['winner_id']) == result['current_owner']['id'] and not disputes.active(connection, case['individual_id'])))
        claims = connection.execute('''SELECT dc.claim_id,dc.applicant_id,u.display_name AS applicant_name,
            d.reason AS decline_reason,COALESCE(a.submitted_at,a.created_at,c.created_at) AS requested_at FROM ownership_dispute_claims dc
            JOIN claims c ON c.id=dc.claim_id JOIN users u ON u.id=dc.applicant_id
            LEFT JOIN acquire_applications a ON a.claim_id=c.id
            LEFT JOIN ownership_declines d ON d.claim_id=dc.claim_id WHERE dc.dispute_id=?
            AND (?=1 OR ?=? OR dc.applicant_id=?) ORDER BY dc.claim_id LIMIT ?''',
            (case['id'], int(admin), user, case['owner_id'], user, MAX_CLAIMS + 1)).fetchall()
        bounded(claims, MAX_CLAIMS)
        result['claims'] = [dict(r) for r in claims]
        allowed = {r['claim_id'] for r in claims}
        rounds = []
        latest = disputes.current_round(connection, case['id'])
        for rnd in bounded(connection.execute('SELECT id,number,phase,request_reason,created_at FROM ownership_dispute_rounds WHERE dispute_id=? ORDER BY number LIMIT ?', (case['id'], MAX_ROUNDS + 1)).fetchall(), MAX_ROUNDS):
            parties = []
            for p in bounded(connection.execute('''SELECT p.claim_id,p.user_id,p.submitted_at,u.display_name
                FROM ownership_dispute_round_parties p JOIN users u ON u.id=p.user_id
                WHERE p.round_id=? ORDER BY p.claim_id,p.user_id LIMIT ?''', (rnd['id'], MAX_PARTIES + 1)).fetchall(), MAX_PARTIES):
                if p['claim_id'] in allowed:
                    parties.append(dict(p) | {'can_submit': bool(not admin and can_write and case['status'] == 'open'
                        and rnd['id'] == latest['id'] and rnd['phase'] == 'collecting' and p['user_id'] == user and not p['submitted_at'])})
            rounds.append(dict(rnd) | {'parties': parties})
        result['rounds'], result['round'] = rounds, rounds[-1]
        # Deliberately select metadata, never e.* or content: a case can hold
        # 256 MiB, and an unauthorized reader must not load any original bytes.
        evidence = connection.execute('''SELECT e.id,e.claim_id,e.author_id,e.created_at,e.published_summary,e.published_at,
            CASE WHEN ?=1 OR e.author_id=? THEN e.explanation ELSE NULL END AS explanation,
            CASE WHEN ?=1 OR e.author_id=? THEN e.summary ELSE NULL END AS summary,
            CASE WHEN ?=1 OR e.author_id=? THEN e.filename ELSE NULL END AS filename,
            CASE WHEN ?=1 OR e.author_id=? THEN e.content_type ELSE NULL END AS content_type,
            CASE WHEN (?=1 OR e.author_id=?) AND (length(e.content)>0 OR EXISTS
                (SELECT 1 FROM ownership_dispute_originals o WHERE o.evidence_id=e.id)) THEN 1 ELSE 0 END AS has_attachment,
            u.display_name AS author_name,r.number AS round_number FROM ownership_dispute_evidence e
            JOIN users u ON u.id=e.author_id JOIN ownership_dispute_round_evidence re ON re.evidence_id=e.id
            JOIN ownership_dispute_rounds r ON r.id=re.round_id
            JOIN ownership_dispute_claims dc ON dc.dispute_id=e.dispute_id AND dc.claim_id=e.claim_id
            WHERE e.dispute_id=? AND (?=1 OR ?=? OR dc.applicant_id=?)
            AND (?=1 OR e.author_id=? OR e.published_at IS NOT NULL) ORDER BY e.id LIMIT ?''',
            (int(admin), user) * 5 + (case['id'], int(admin), user, case['owner_id'], user,
                                      int(admin), user, MAX_EVIDENCE + 1)).fetchall()
        bounded(evidence, MAX_EVIDENCE)
        result['evidence'] = []
        for row in evidence:
            if row['claim_id'] not in allowed or (not admin and row['author_id'] != user and not row['published_at']):
                continue
            item = {key: row[key] for key in ('id', 'claim_id', 'author_id', 'author_name', 'created_at',
                                               'published_summary', 'published_at', 'round_number')}
            item['can_publish'] = bool(admin and can_write and case['status'] == 'open' and not row['published_at'])
            if admin or row['author_id'] == user:
                item.update({key: row[key] for key in ('explanation', 'summary', 'filename', 'content_type')})
                item['has_attachment'] = bool(row['has_attachment'])
            result['evidence'].append(item)
        events = [dict(r) for r in bounded(connection.execute('SELECT id,kind,note,created_at FROM ownership_dispute_events WHERE dispute_id=? ORDER BY id LIMIT ?', (case['id'], MAX_EVENTS + 1)).fetchall(), MAX_EVENTS)]
        count = max(0, len(rounds) - 1)
        starts = [e['id'] for e in events if e['kind'] in ('request_evidence', 'reopened')]
        boundaries = set(starts[-count:]) if count else set()
        number = 1
        for e in events:
            if e['id'] in boundaries:
                number += 1
            e['round_number'] = number
        result['events'] = events
        return result_projection('detail', result)

    def detail(self, actor, case, *, admin=False):
        identifier(case)
        if type(admin) is not bool:
            raise ValueError('Invalid dispute access category.')
        with self.transaction(actor, case=case, admin=admin) as (repo, user, can_write):
            return self._detail(repo.connection, case_row(repo.connection, case, user, admin), user, can_write, admin)

    def acknowledge(self, actor, claim, data):
        identifier(claim)
        data = acknowledgment_payload(data)
        with self.transaction(actor, claim=claim, write=True) as (repo, user, can_write):
            row = candidate(repo.connection, claim, user)
            option = self._option(repo.connection, row, user, can_write)
            if option['revision'] != data['revision']:
                raise ClaimConflict('Acquire or decline changed; reload before accepting.')
            if not option['can_acknowledge']:
                raise ClaimConflict('This decline cannot be accepted now.')
            repo.connection.execute('UPDATE ownership_declines SET acknowledged_at=? WHERE claim_id=?', (disputes.utcnow(), claim))
            return {'option': result_projection('option', self._option(repo.connection, row, user, can_write))}

    def preflight(self, actor, *, claim=None, case=None):
        """Reject unavailable actors/modes/targets before expensive image work.

        This short read owns no locks while decoding. It grants no authority to
        commit: the final transaction repeats the canonical access, projection,
        complete participant scope and revision/round checks after decoding.
        """
        self.check_schema()
        with self.operations.access('user_write', actor) as (_, _, account):
            if account['ban_status'] != 'normal':
                raise PermissionError('An active dispute participant is required.')
            with connect(self.settings, 'chronicle') as raw:
                raw.execute("SET LOCAL statement_timeout='5s'")
                raw.execute("SET LOCAL lock_timeout='2s'")
                self._target(ObservationConnection(raw), account['id'], claim=claim, case=case)

    def submit(self, actor, claim, data, content=b'', filename=''):
        identifier(claim)
        data = submission_payload(data)
        if not isinstance(content, bytes) or len(content) > disputes.MAX_BYTES:
            raise ValueError('The attachment must be at most 12 MiB.')
        text(filename, 255)
        if data['case_id'] is None and not content:
            raise ValueError('Additional evidence attachment is required to open a dispute.')
        target = {'case': data['case_id']} if data['case_id'] is not None else {'claim': claim}
        if content:
            self.preflight(actor, **target)
            if self.storage is None:
                raise OriginalUnavailable('Private original storage is unavailable.')
        with UPLOADS:
            content, mime, name = disputes.validate_submission(data['explanation'], data['summary'], content, filename)
        if len(content) > disputes.MAX_BYTES:
            raise ValueError('The sanitized attachment must be at most 12 MiB.')
        with self.transaction(actor, **target, write=True) as (repo, user, can_write):
            connection = repo.connection
            preflight_legacy_evidence(connection)
            evidence_storage = CloudDisputeStorage(self.storage)
            if data['case_id'] is None:
                row = candidate(connection, claim, user)
                if candidate_revision(connection, row) != data['revision']:
                    raise ClaimConflict('Acquire or decline changed; reload before appealing.')
                option = self._option(connection, row, user, can_write)
                if not option['can_appeal']:
                    raise ClaimConflict('This Acquire cannot be appealed now.')
                case_id = disputes.open_case(connection, claim, user, data['explanation'], data['summary'], content, mime, name,
                                             evidence_storage=evidence_storage)
            else:
                case_id = data['case_id']
                case = case_row(connection, case_id, user)
                check_case(connection, case, data['version'], data['round_number'])
                disputes.add_evidence(connection, case, claim, user, data['explanation'], data['summary'], content, mime, name,
                                      expected_round=data['round_number'], evidence_storage=evidence_storage)
            return {'detail': self._detail(connection, case_row(connection, case_id, user), user, can_write)}

    def attachment(self, actor, evidence, *, admin=False):
        identifier(evidence)
        if type(admin) is not bool:
            raise ValueError('Invalid dispute access category.')
        with self.transaction(actor, evidence=evidence, admin=admin) as (repo, user, _):
            row = evidence_row(repo.connection, evidence, user, admin)
            if row['content_type'] not in ('application/pdf', 'image/jpeg'):
                raise GuitarMissing()
            size = repo.connection.execute('SELECT length(content) FROM ownership_dispute_evidence WHERE id=?', (evidence,)).fetchone()[0]
            original = repo.connection.execute('SELECT * FROM ownership_dispute_originals WHERE evidence_id=?', (evidence,)).fetchone()
            if original is not None:
                if size is not None or original['content_type'] != row['content_type']:
                    raise OriginalUnavailable('Private original metadata is inconsistent.')
                # Keep the canonical role/BAN/projection/mode fences held across
                # the fixed-generation download and integrity verification.
                content = read_original(self.storage, original)
            else:
                if not size or size > disputes.MAX_BYTES:
                    raise OriginalUnavailable('Private original is unavailable.')
                content = repo.connection.execute('SELECT content FROM ownership_dispute_evidence WHERE id=?', (evidence,)).fetchone()[0]
            return {'content': bytes(content), 'content_type': row['content_type'],
                    'filename': 'document.pdf' if row['content_type'] == 'application/pdf' else 'photo.jpg'}

    def publish(self, actor, evidence, data):
        identifier(evidence)
        data = publication_payload(data)
        with self.transaction(actor, evidence=evidence, admin=True, write=True) as (repo, user, can_write):
            row = evidence_row(repo.connection, evidence, user, True)
            case = case_row(repo.connection, row['dispute_id'], user, True)
            check_case(repo.connection, case, data['version'], data['round_number'])
            if case['status'] != 'open' or row['published_at']:
                raise ClaimConflict('Published summaries cannot be overwritten; reload this open dispute.')
            repo.connection.execute('UPDATE ownership_dispute_evidence SET published_summary=?,published_at=? WHERE id=?',
                                    (data['summary'], disputes.utcnow(), evidence))
            disputes.event(repo.connection, case, 'summary_published', 'A reviewed summary is available', user)
            return {'detail': self._detail(repo.connection, case_row(repo.connection, case['id'], user, True), user, can_write, True)}

    def decide(self, actor, case, data):
        identifier(case)
        data = decision_payload(data)
        with self.transaction(actor, case=case, admin=True, write=True) as (repo, user, can_write):
            row = case_row(repo.connection, case, user, True)
            check_case(repo.connection, row, data['version'], data['round_number'])
            disputes.decide(repo, repo.connection, case, data['version'], data['action'], data['reason'],
                            data['winner_claim_id'], actor=user, audit_actor='identity-platform:' + str(actor))
            return {'detail': self._detail(repo.connection, case_row(repo.connection, case, user, True), user, can_write, True)}
