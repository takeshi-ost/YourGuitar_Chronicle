"""Private, immutable Cloud Storage objects; resource authorization belongs to callers."""
from dataclasses import dataclass
import os
import re
import uuid

MAX_BYTES = 25 * 1024 * 1024
MARKER = '_ygc/storage-read-check-v1'
MARKER_DATA = b'YGC private storage read check v1\n'


@dataclass(frozen=True)
class StorageSettings:
    project: str
    content_bucket: str
    accounts_bucket: str

    def __post_init__(self):
        if not isinstance(self.project, str) or not re.fullmatch(r'[a-z][a-z0-9-]{4,61}[a-z0-9]', self.project):
            raise ValueError('Explicit storage project required.')
        buckets = (self.content_bucket, self.accounts_bucket)
        if any(not isinstance(b, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]', b) for b in buckets) or buckets[0] == buckets[1]:
            raise ValueError('Two distinct explicit storage buckets required.')

    @classmethod
    def from_environment(cls, project):
        if os.environ.get('YGC_PLATFORM_TARGET') != 'gcp' or os.environ.get('YGC_MEDIA_BACKEND') != 'gcs':
            raise ValueError('Explicit GCP/Cloud Storage configuration required.')
        if 'STORAGE_EMULATOR_HOST' in os.environ:
            raise ValueError('Storage Emulator is not allowed.')
        return cls(project, os.environ.get('YGC_CONTENT_BUCKET', ''), os.environ.get('YGC_ACCOUNTS_BUCKET', ''))


@dataclass(frozen=True)
class ObjectReference:
    scope: str
    name: str
    generation: int
    size: int
    content_type: str

    def __post_init__(self):
        if self.scope not in ('content', 'accounts') or not isinstance(self.name, str) or not re.fullmatch(r'media/[0-9a-f]{32}', self.name):
            raise ValueError('Invalid object reference.')
        if type(self.generation) is not int or self.generation <= 0 or type(self.size) is not int or not 0 < self.size <= MAX_BYTES:
            raise ValueError('Invalid generation or size.')
        if not isinstance(self.content_type, str) or not re.fullmatch(r'[a-z0-9.+-]+/[a-z0-9.+-]+', self.content_type):
            raise ValueError('Invalid content type.')


class CloudStorage:
    def __init__(self, settings, *, client=None):
        if 'STORAGE_EMULATOR_HOST' in os.environ:
            raise ValueError('Storage Emulator is not allowed.')
        self.settings = settings
        if client is None:
            from google.cloud import storage
            client = storage.Client(project=settings.project)
        self.client = client
        self.buckets = {'content': settings.content_bucket, 'accounts': settings.accounts_bucket}

    def _blob(self, scope, name, generation=None):
        if scope not in self.buckets:
            raise ValueError('Unknown storage scope.')
        return self.client.bucket(self.buckets[scope]).blob(name, generation=generation)

    def put(self, scope, data, *, content_type):
        if not isinstance(data, bytes) or not 0 < len(data) <= MAX_BYTES:
            raise ValueError('Invalid object size.')
        name = 'media/' + uuid.uuid4().hex
        ObjectReference(scope, name, 1, len(data), content_type)
        blob = self._blob(scope, name)
        blob.cache_control = 'private, no-store'
        blob.upload_from_string(data, content_type=content_type, if_generation_match=0,
                                checksum='crc32c', timeout=10, retry=None)
        # The SDK populates generation from the successful upload response.
        return ObjectReference(scope, name, int(blob.generation), len(data), content_type)

    def get(self, reference):
        if not isinstance(reference, ObjectReference):
            raise ValueError('An explicit object reference is required.')
        blob = self._blob(reference.scope, reference.name, reference.generation)
        blob.reload(if_generation_match=reference.generation, timeout=10, retry=None)
        if blob.size != reference.size or blob.content_type != reference.content_type or blob.content_encoding:
            raise ValueError('Object metadata does not match the reference.')
        data = blob.download_as_bytes(if_generation_match=reference.generation, raw_download=True,
                                      checksum='crc32c', timeout=10, retry=None)
        if len(data) != reference.size:
            raise ValueError('Object size does not match the reference.')
        return data

    def delete(self, reference):
        if not isinstance(reference, ObjectReference):
            raise ValueError('An explicit object reference is required.')
        self._blob(reference.scope, reference.name, reference.generation).delete(
            if_generation_match=reference.generation, timeout=10, retry=None)

    def _marker_read(self, scope):
        blob = self._blob(scope, MARKER)
        blob.reload(timeout=5, retry=None)
        if blob.size != len(MARKER_DATA) or blob.content_encoding:
            raise ValueError('Invalid storage marker.')
        data = blob.download_as_bytes(if_generation_match=int(blob.generation), raw_download=True,
                                      checksum='crc32c', timeout=5, retry=None)
        if data != MARKER_DATA:
            raise ValueError('Invalid storage marker.')

    def status(self):
        results = {}
        for scope in self.buckets:
            try:
                self._marker_read(scope)
                results[scope] = 'available'
            except Exception:
                results[scope] = 'unavailable'
        return {'backend': 'gcs', **results, 'check': 'read_only'}

    def probe(self):
        """IAM-only setup/check: unique temporary objects, then persistent read markers."""
        from google.api_core.exceptions import NotFound, PreconditionFailed
        for scope in self.buckets:
            reference = self.put(scope, b'YGC disposable storage probe\n', content_type='application/octet-stream')
            try:
                if self.get(reference) != b'YGC disposable storage probe\n':
                    raise ValueError('Storage read mismatch.')
                try:
                    self._blob(scope, reference.name).upload_from_string(b'overwrite',
                        if_generation_match=0, timeout=10, retry=None)
                except PreconditionFailed:
                    pass
                else:
                    raise ValueError('Storage overwrite guard failed.')
            finally:
                self.delete(reference)
            try:
                self.get(reference)
            except NotFound:
                pass
            else:
                raise ValueError('Probe deletion failed.')
            marker = self._blob(scope, MARKER)
            marker.cache_control = 'private, no-store'
            try:
                marker.upload_from_string(MARKER_DATA, content_type='text/plain', if_generation_match=0,
                                          checksum='crc32c', timeout=10, retry=None)
            except PreconditionFailed:
                pass
            self._marker_read(scope)
        return {'status': 'ok', 'scopes': 2, 'write_read_delete': True, 'overwrite_rejected': True}

    def close(self):
        self.client.close()
