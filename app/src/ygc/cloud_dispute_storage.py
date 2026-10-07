"""Private immutable dispute originals, never projected into HTTP responses.

CloudStorage owns fixed-generation creation and transport integrity. This layer
adds the dispute's smaller byte limit and a SHA-256 digest bound to each stored
reference. Originals have no automatic deletion, expiry, or bucket sweep. In
particular, neither an upload timeout nor a failed/unknown database commit is
evidence that it is safe to delete the object.
"""
import hashlib
import hmac
import re

from ygc.cloud_storage import ObjectReference
from ygc.db.repository import utcnow
from ygc.disputes import MAX_BYTES

ORIGINAL_COLUMNS = ('evidence_id', 'object_scope', 'object_name',
                    'object_generation', 'byte_size', 'content_type', 'sha256', 'created_at')
CONTENT_TYPES = ('application/pdf', 'image/jpeg')


class OriginalUnavailable(RuntimeError):
    """A private original is unavailable or inconsistent; never expose its ref."""


def original_reference(row):
    """Validate persisted metadata before any private storage access."""
    try:
        if (type(row['evidence_id']) is not int or not 0 < row['evidence_id'] < 2**63
                or row['object_scope'] != 'content'
                or type(row['byte_size']) is not int or not 0 < row['byte_size'] <= MAX_BYTES
                or type(row['object_generation']) is not int or not 0 < row['object_generation'] < 2**63
                or row['content_type'] not in CONTENT_TYPES
                or not isinstance(row['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', row['sha256'])
                or not isinstance(row['created_at'], str) or not row['created_at']):
            raise ValueError()
        return ObjectReference(row['object_scope'], row['object_name'], row['object_generation'],
                               row['byte_size'], row['content_type'])
    except (KeyError, IndexError, TypeError, ValueError):
        raise OriginalUnavailable('Invalid private original metadata.') from None


def read_original(storage, row):
    """Read only the recorded generation, then verify its size and SHA-256."""
    reference = original_reference(row)
    if storage is None:
        raise OriginalUnavailable('Private original storage is unavailable.')
    try:
        data = storage.get(reference)
        if (not isinstance(data, bytes) or len(data) != reference.size
                or not hmac.compare_digest(hashlib.sha256(data).hexdigest(), row['sha256'])):
            raise ValueError()
    except Exception:
        raise OriginalUnavailable('Private original could not be verified.') from None
    return data


def verify_original(storage, row):
    """Backup/restore integrity check; callers own their authorization fences."""
    read_original(storage, row)


class CloudDisputeStorage:
    """Explicit optional shared-state-machine adapter; never stores BYTEA."""
    def __init__(self, storage):
        self.storage = storage

    def additional_bytes(self, connection, case_id):
        return connection.execute('''SELECT CAST(COALESCE(SUM(o.byte_size),0) AS BIGINT)
            FROM ownership_dispute_originals o JOIN ownership_dispute_evidence e
            ON e.id=o.evidence_id WHERE e.dispute_id=?''', (case_id,)).fetchone()[0]

    def store(self, connection, evidence_id, content, mime):
        if self.storage is None:
            raise OriginalUnavailable('Private original storage is unavailable.')
        if not isinstance(content, bytes) or not 0 < len(content) <= MAX_BYTES or mime not in CONTENT_TYPES:
            raise OriginalUnavailable('Invalid private original.')
        # This is called only after final authority, revision, party and quota
        # checks, while the caller's canonical transaction fences are held.
        try:
            reference = self.storage.put('content', content, content_type=mime)
            if (not isinstance(reference, ObjectReference) or reference.scope != 'content'
                    or reference.size != len(content) or reference.content_type != mime):
                raise ValueError()
        except Exception:
            raise OriginalUnavailable('Private original upload result is unavailable.') from None
        row = dict(evidence_id=evidence_id, object_scope=reference.scope,
                   object_name=reference.name, object_generation=reference.generation,
                   byte_size=reference.size, content_type=reference.content_type,
                   sha256=hashlib.sha256(content).hexdigest(), created_at=utcnow())
        original_reference(row)
        connection.execute('''INSERT INTO ownership_dispute_originals
            (evidence_id,object_scope,object_name,object_generation,byte_size,content_type,sha256,created_at)
            VALUES (?,?,?,?,?,?,?,?)''', tuple(row[key] for key in ORIGINAL_COLUMNS))
