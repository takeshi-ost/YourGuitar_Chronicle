"""Synthetic private storage and additive schema for portable service tests."""
from ygc.cloud_storage import ObjectReference


def add_originals_table(connection):
    # The local SQLite baseline is deliberately unchanged. This fixture models
    # only the additive PostgreSQL table used by the CloudDisputes adapter.
    connection.execute('''CREATE TABLE ownership_dispute_originals (
        evidence_id INTEGER PRIMARY KEY REFERENCES ownership_dispute_evidence(id),
        object_scope TEXT NOT NULL CHECK(object_scope='content'),
        object_name TEXT NOT NULL, object_generation INTEGER NOT NULL CHECK(object_generation>0),
        byte_size INTEGER NOT NULL CHECK(byte_size>0 AND byte_size<=12582912),
        content_type TEXT NOT NULL CHECK(content_type IN ('application/pdf','image/jpeg')),
        sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
        UNIQUE(object_scope,object_name,object_generation))''')


class MemoryOriginalStorage:
    def __init__(self):
        self.objects = {}
        self.uploads = []
        self.reads = []
        self.deletions = []

    def put(self, scope, data, *, content_type):
        number = len(self.uploads) + 1
        reference = ObjectReference(scope, 'media/' + f'{number:032x}', 2**53 + number, len(data), content_type)
        self.objects[reference] = data
        self.uploads.append(reference)
        return reference

    def get(self, reference):
        self.reads.append(reference)
        return self.objects[reference]

    def delete(self, reference):
        self.deletions.append(reference)
        raise AssertionError('Dispute originals must never be deleted automatically.')
