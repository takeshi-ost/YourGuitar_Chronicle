"""Synthetic private storage and additive schema for portable service tests."""
from ygc.cloud_storage import ObjectReference


def legacy_archive_fixture(connection, stamp, content):
    """Seed historical proof with identity Claims that survive restore rebuilds."""
    user = dict(connection.execute('''INSERT INTO users(display_name,app_user_id,created_at,updated_at)
        VALUES('Synthetic archive member','synthetic-archive-member',?,?)
        RETURNING *''', (stamp, stamp)).fetchone())
    guitar = connection.execute('''INSERT INTO individuals(manufacturer,model,serial_number,
        normalized_manufacturer,created_at,updated_at) VALUES('Synthetic','Archive',
        'LEGACY-PROOF','synthetic',?,?) RETURNING id''', (stamp, stamp)).fetchone()['id']
    # Restore reapplies Account projections and rebuilds every participant's
    # Individual from active Claims. The snapshot alone cannot supply identity.
    # Deliberately omit owner fields: private proof must not confer ownership.
    listing = connection.execute('''INSERT INTO claims(individual_id,author_user_id,
        claim_type,verification_status,occurred_at,created_at,updated_at)
        VALUES(?,?,'listing','positive',?,?,?) RETURNING id''',
        (guitar, user['id'], stamp, stamp, stamp)).fetchone()['id']
    for field, value in (('manufacturer', 'Synthetic'), ('model', 'Archive'),
                         ('serial_number', 'LEGACY-PROOF')):
        connection.execute('''INSERT INTO claim_listing_items(claim_id,field_name,value_text,created_at)
            VALUES(?,?,?,?)''', (listing, field, value, stamp))
    claim = connection.execute('''INSERT INTO claims(individual_id,author_user_id,claim_type,
        created_at,updated_at) VALUES(?,?,'event',?,?) RETURNING id''',
        (guitar, user['id'], stamp, stamp)).fetchone()['id']
    case = connection.execute('''INSERT INTO ownership_disputes(individual_id,owner_id,
        locked_owner_id,status,created_at,updated_at) VALUES(?,?,?,'resolved',?,?)
        RETURNING id''', (guitar, user['id'], user['id'], stamp, stamp)).fetchone()['id']
    evidence = connection.execute('''INSERT INTO ownership_dispute_evidence(dispute_id,
        claim_id,author_id,explanation,summary,filename,content_type,content,created_at)
        VALUES(?,?,?,'Synthetic legacy proof','Private summary','document.pdf',
        'application/pdf',?,?) RETURNING id''',
        (case, claim, user['id'], content, stamp)).fetchone()['id']
    return user, guitar, claim, case, evidence


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
