import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from state_store import JsonStateStore, StorageError, atomic_json
from adapter import Adapter


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = JsonStateStore(self.root)

    def test_atomic_replace_failure_preserves_previous_snapshot(self):
        self.store.write('pending.json', {'sequence': 1})
        with patch('state_store.os.replace', side_effect=OSError('private path')):
            with self.assertRaisesRegex(StorageError, '^local_save_failed$'):
                self.store.write('pending.json', {'sequence': 2})
        self.assertEqual(self.store.read('pending.json'), {'sequence': 1})
        self.assertEqual(self.store.failures, {'pending.json'})
        self.store.write('pending.json', {'sequence': 2})
        self.assertEqual(JsonStateStore(self.root).read('pending.json'), {'sequence': 2})
        self.assertFalse(self.store.failures)

    def test_independent_failure_flags(self):
        with patch.object(self.store, 'writer', side_effect=OSError()):
            for name in ('pending.json', 'metrics.json'):
                with self.assertRaises(StorageError):
                    self.store.write(name, {})
        self.store.write('metrics.json', {})
        self.assertEqual(self.store.failures, {'pending.json'})

    def test_missing_corrupt_and_non_object_files(self):
        self.assertIsNone(self.store.read('absent.json'))
        for raw in (b'bad JSON', b'[]', b'42', b'null', b'"text"', b'\xff'):
            (self.root / 'cache.json').write_bytes(raw)
            self.assertIsNone(self.store.read('cache.json'))

    def test_core_restarts_with_non_object_documents(self):
        for name in ('metrics.json', 'cache.json', 'pending.json'):
            atomic_json(self.root / name, [])
        a = Adapter({'upstream': 'https://example.invalid', 'device_id': 'Synthetic'}, self.root,
                    transport=lambda *args: {}, secret_provider=lambda: 'synthetic')
        self.assertEqual(a.cache, {})
        self.assertIsNone(a.pending)
        self.assertTrue(a.status()['storage']['ok'])

    def test_injected_store_loads_pending_without_reading_disk(self):
        class MemoryStore:
            def __init__(self):
                self.failures = set()
                self.documents = {'pending.json': {'deviceId': 'Synthetic', 'sequence': 3}}
            def read(self, name):
                return self.documents.get(name)
            def write(self, name, value):
                self.documents[name] = value
        store = MemoryStore()
        a = Adapter({'upstream': 'https://example.invalid', 'device_id': 'Synthetic'}, self.root,
                    store=store, secret_provider=lambda: 'synthetic')
        self.assertEqual(a.pending['sequence'], 3)
        a.ingest({'deviceId': 'Synthetic', 'sequence': 4})
        self.assertEqual(store.documents['pending.json']['sequence'], 4)
        self.assertFalse((self.root / 'pending.json').exists())
