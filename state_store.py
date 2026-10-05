"""JSON file persistence, independent of Hub transport and synchronization policy.

Callers serialize access. Each replacement is atomic; multiple files are not a
transaction. Failed writes leave the previous destination and a retryable flag.
"""
import json
import os
from pathlib import Path


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_bytes(encode(value))
    os.replace(temporary, path)


class StorageError(Exception):
    pass


class JsonStateStore:
    def __init__(self, root, writer=None):
        self.root = Path(root)
        self.writer = writer or atomic_json
        self.failures = set()

    def read(self, name):
        """Return a document object; absent, unreadable or malformed files are ignored.

        Shape and identity validation remain the synchronization core's job.
        """
        try:
            value = json.loads((self.root / name).read_text(encoding='utf-8'))
            return value if isinstance(value, dict) else None
        except (OSError, ValueError, TypeError):
            return None

    def write(self, name, value):
        try:
            self.writer(self.root / name, value)
        except OSError:
            self.failures.add(name)
            raise StorageError('local_save_failed') from None
        self.failures.discard(name)
