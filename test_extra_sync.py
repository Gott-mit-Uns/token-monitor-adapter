import copy
import json
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from adapter import Adapter, StorageError, UpstreamError


class ExtraSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.calls = []
        self.doc = {'ok': True, 'version': 1, 'revision': 0, 'updatedAt': '', 'value': None}
        self.policy = {'ok': True, 'enabled': False, 'generation': 0}
        self.cfg = {'upstream': 'https://example.invalid', 'device_id': 'Synthetic Desktop', 'interval_seconds': 600}
        self.a = Adapter(self.cfg, self.temp.name, transport=self.remote, secret_provider=lambda: 'synthetic')
    def remote(self, method, path, body=None):
        self.calls.append((method, path, copy.deepcopy(body)))
        if path == '/api/sync/content':
            return {'ok': True, 'version': 1, 'sharedSettings': True, 'sessionTitles': {'enabled': True}}
        if path.startswith('/api/sync/titles/'):
            self.policy = {'ok': True, 'enabled': body['enabled'], 'generation': self.policy['generation'] + 1}
            return copy.deepcopy(self.policy)
        if path.startswith('/api/sync/settings/'):
            if method == 'PUT':
                if body['baseRevision'] != self.doc['revision']:
                    raise UpstreamError(409, {**self.doc, 'error': 'stale_write'})
                self.doc = {'ok': True, 'version': 1, 'revision': self.doc['revision'] + 1, 'updatedAt': 'synthetic', 'value': body['value']}
            return copy.deepcopy(self.doc)
        if path == '/api/ingest': return {'ok': True}
        if path == '/api/stats': return {'devices': [], 'periods': {}}
        raise UpstreamError(404)
    def test_capability_reads_coalesce(self):
        threads = [threading.Thread(target=self.a.refresh, args=('/api/sync/content',)) for _ in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(len(self.calls), 1)
    def test_settings_write_primes_cache_and_conflicts_do_not_overwrite(self):
        path = '/api/sync/settings/modelAliases'
        self.a.write_extra(path, {'baseRevision': 0, 'value': {'modelAliases': {'sample': 'canonical'}, 'modelAliasGrouping': 'off'}})
        self.assertEqual(self.a.refresh(path)['revision'], 1)
        self.assertEqual(len(self.calls), 1)
        with self.assertRaises(UpstreamError) as conflict:
            self.a.write_extra(path, {'baseRevision': 0, 'value': None})
        self.assertEqual(conflict.exception.status, 409)
        self.assertEqual(self.a.cache[path]['data']['revision'], 1)
    def test_title_policy_coalesces_and_restores(self):
        path = self.a.title_policy_path
        first = self.a.write_extra(path, {'enabled': True})
        for _ in range(10): self.assertEqual(self.a.write_extra(path, {'enabled': True}), first)
        restored = Adapter(self.cfg, self.temp.name, transport=self.remote)
        self.assertEqual(restored.write_extra(path, {'enabled': True}), first)
        self.assertEqual(len(self.calls), 1)
    def test_external_conflict_refreshes_local_review_base(self):
        path = '/api/sync/settings/modelAliases'
        self.a.refresh(path)
        self.doc = {'version': 1, 'revision': 2, 'updatedAt': 'synthetic', 'value': {'modelAliases': {}, 'modelAliasGrouping': 'off'}}
        with self.assertRaises(UpstreamError):
            self.a.write_extra(path, {'baseRevision': 0, 'value': {}})
        count = len(self.calls)
        self.assertEqual(self.a.refresh(path)['revision'], 2)
        self.assertEqual(len(self.calls), count)
    def test_title_revocation_scrubs_pending_and_new_snapshots(self):
        payload = {'deviceId': self.cfg['device_id'], 'sessionTitleSyncGeneration': 1,
                   'periods': {'today': {'sessions': {'s': {'title': 'synthetic title', 'firstUserMessage': 'synthetic text', 'totalTokens': 12}}}}}
        self.a.ingest(payload)
        self.a.write_extra(self.a.title_policy_path, {'enabled': False})
        self.assertNotIn('sessionTitleSyncGeneration', self.a.pending)
        self.assertEqual(self.a.pending['periods']['today']['sessions']['s'], {'totalTokens': 12})
        self.a.ingest(payload)
        self.assertNotIn('title', self.a.pending['periods']['today']['sessions']['s'])
    def test_other_device_policy_rejected_locally(self):
        with self.assertRaises(UpstreamError) as error:
            self.a.write_extra('/api/sync/titles/Other', {'enabled': True})
        self.assertEqual(error.exception.status, 403); self.assertEqual(self.calls, [])
    def test_policy_failure_backoff_preserves_pending(self):
        self.a.transport = Mock(side_effect=UpstreamError(403))
        self.a.ingest({'deviceId': self.cfg['device_id'], 'sequence': 5})
        for _ in range(5):
            with self.assertRaises(UpstreamError): self.a.write_extra(self.a.title_policy_path, {'enabled': True})
        self.assertEqual(self.a.transport.call_count, 1)
        self.assertEqual(self.a.pending['sequence'], 5)
    def test_old_hub_probe_backoff(self):
        self.a.transport = Mock(side_effect=UpstreamError(404))
        for _ in range(5):
            with self.assertRaises(UpstreamError): self.a.refresh('/api/sync/content')
        self.assertEqual(self.a.transport.call_count, 1)
        self.assertGreater(self.a.next_retry['/api/sync/content'], time.time() + 590)
    def test_storage_error_does_not_acknowledge_policy(self):
        with patch('adapter.atomic_json', side_effect=OSError('synthetic failure')):
            with self.assertRaises(StorageError): self.a.write_extra(self.a.title_policy_path, {'enabled': False})
    def test_invalid_success_reply_not_cached(self):
        self.a.transport = lambda *args: {'ok': True}
        with self.assertRaises(UpstreamError): self.a.refresh('/api/sync/content')
        with self.assertRaises(UpstreamError): self.a.write_extra(self.a.title_policy_path, {'enabled': True})
        self.assertNotIn(self.a.title_policy_path, self.a.cache)
    def test_remote_sse_is_not_allowed(self):
        with self.assertRaises(UpstreamError) as error:
            self.a.http_request('GET', '/api/stats/stream')
        self.assertEqual(error.exception.status, 405)
    def test_shared_conflict_body_strips_diagnostics(self):
        response = Mock(status=409)
        response.getheader.return_value = None
        response.read.return_value = json.dumps({**self.doc, 'message': 'private diagnostic', 'debug': 'private'}).encode()
        connection = Mock(); connection.getresponse.return_value = response
        with patch('adapter.http.client.HTTPSConnection', return_value=connection):
            with self.assertRaises(UpstreamError) as error:
                self.a.http_request('PUT', '/api/sync/settings/customPricing', {'baseRevision': 0, 'value': []})
        self.assertEqual(error.exception.status, 409)
        self.assertNotIn('message', error.exception.body)
        self.assertNotIn('debug', error.exception.body)
