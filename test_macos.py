import copy
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from adapter import Adapter, UpstreamError
import macos_service as mac


class MacTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.client = self.root / 'client'
        self.client.mkdir()
        self.state = self.root / 'state'
        self.state.mkdir()
        self.settings = {'hubMode': 'client', 'hubUrl': 'https://example.invalid',
                         'deviceId': 'Synthetic Mac', 'syncUploadIntervalMs': 600000, 'theme': 'dark'}
        mac.save_private(self.client / 'settings.json', self.settings)
        self.credentials('synthetic-secret-one')

    def credentials(self, secret):
        mac.save_private(self.client / 'credentials.json', {'credentials': {'hub': {'clientSecret': secret}}})

    def test_config_uses_five_minutes_and_never_copies_secret(self):
        config = mac.make_config(self.client)
        self.assertEqual(config['interval_seconds'], 300)
        self.assertEqual(config['upload_interval_ms'], 300000)
        self.assertNotIn('synthetic-secret-one', json.dumps(config))
        adapter = mac.make_adapter(config, self.state)
        self.assertEqual(adapter.secret_provider(), 'synthetic-secret-one')
        self.credentials('synthetic-secret-two')
        self.assertEqual(adapter.secret_provider(), 'synthetic-secret-two')
        self.assertEqual(adapter.local_secret_provider(), 'synthetic-secret-two')

    def test_invalid_credentials_are_safe(self):
        (self.client / 'credentials.json').write_text('invalid synthetic data')
        with self.assertRaises(UpstreamError) as caught:
            mac.read_credentials(self.client / 'credentials.json')
        self.assertEqual(caught.exception.body, {'error': 'credential_unavailable'})

    def test_attach_restore_preserves_other_changes_and_first_backup(self):
        mac.attach_client(self.client, self.state)
        record = (self.state / 'client-restore.json').read_bytes()
        mac.attach_client(self.client, self.state)
        self.assertEqual((self.state / 'client-restore.json').read_bytes(), record)
        settings = json.loads((self.client / 'settings.json').read_text())
        self.assertEqual(settings['hubUrl'], 'http://127.0.0.1:17322')
        self.assertEqual(settings['syncUploadIntervalMs'], 0)
        settings['theme'] = 'light'
        mac.save_private(self.client / 'settings.json', settings)
        self.assertTrue(mac.restore_client(self.state))
        restored = json.loads((self.client / 'settings.json').read_text())
        self.assertEqual(restored, {**self.settings, 'theme': 'light'})
        if os.name == 'posix':
            self.assertEqual((self.client / 'settings.json').stat().st_mode & 0o777, 0o600)

    def test_restore_refuses_to_overwrite_user_connection_change(self):
        mac.attach_client(self.client, self.state)
        settings = json.loads((self.client / 'settings.json').read_text())
        settings['hubUrl'] = 'https://different.invalid'
        mac.save_private(self.client / 'settings.json', settings)
        with self.assertRaises(ValueError):
            mac.restore_client(self.state)
        self.assertEqual(json.loads((self.client / 'settings.json').read_text()), settings)

    def test_port_conflict_leaves_client_untouched(self):
        before = (self.client / 'settings.json').read_bytes()
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1', 0))
            occupied.listen()
            with self.assertRaises(OSError):
                mac.check_port(occupied.getsockname()[1])
        self.assertEqual((self.client / 'settings.json').read_bytes(), before)

    def test_launchagent_uses_absolute_private_runtime(self):
        doc = mac.launch_document(self.root / 'runtime/bin/python3', self.root / 'service/macos_service.py', self.state)
        self.assertEqual(doc['Umask'], 0o077)
        self.assertTrue(doc['KeepAlive'])
        self.assertTrue(Path(doc['ProgramArguments'][0]).is_absolute())
        self.assertNotIn('synthetic-secret-one', json.dumps(doc))

    def test_five_minute_cache_upload_and_restart(self):
        config = mac.make_config(self.client)
        calls = []
        stats = {'devices': [{'deviceId': 'Synthetic Mac'}], 'periods': {}}
        def remote(method, path, body=None):
            calls.append((method, path))
            return copy.deepcopy(stats) if method == 'GET' else {'ok': True}
        a = Adapter(config, self.state, transport=remote)
        a.refresh()
        for _ in range(25):
            a.refresh()
        self.assertEqual(calls, [('GET', '/api/stats')])
        a.cache['/api/stats']['at'] -= 301
        a.refresh()
        self.assertEqual(len(calls), 2)
        self.assertEqual(a.upload_pending(), 'no_data')
        a.ingest({'deviceId': 'Synthetic Mac', 'today': {'totalTokens': 42}})
        self.assertEqual(a.upload_pending(), 'waiting')
        a.metrics['upload_schedule']['next_at'] -= 301
        self.assertEqual(a.upload_pending(), 'success')
        self.assertEqual(a.upload_pending(), 'no_data')
        a.ingest({'deviceId': 'Synthetic Mac', 'today': {'totalTokens': 43}})
        restarted = Adapter(config, self.state, transport=remote)
        self.assertEqual(restarted.pending['today']['totalTokens'], 43)
        before = len(calls)
        restarted.refresh()
        self.assertEqual(len(calls), before)

    def test_install_port_conflict_has_no_side_effect(self):
        with patch.object(mac.sys, 'platform', 'darwin'), patch.object(mac, 'check_port', side_effect=OSError()), patch.object(mac, 'quit_client') as quit_client:
            with self.assertRaises(OSError):
                mac.install(self.root / 'not-created', self.client, self.root / 'launch.plist')
            quit_client.assert_not_called()
            self.assertFalse((self.root / 'not-created').exists())

    def test_install_copies_core_protocol_dependency(self):
        target = self.root / 'dependency-check'
        with patch.object(mac.sys, 'platform', 'darwin'), patch.object(mac, 'check_port'), patch.object(mac.venv.EnvBuilder, 'create', side_effect=RuntimeError('stop after source copy')):
            with self.assertRaisesRegex(RuntimeError, 'stop after source copy'):
                mac.install(target, self.client, self.root / 'launch.plist')
        source = Path(mac.__file__).parent
        self.assertEqual((target / 'service' / 'hub_protocol.py').read_bytes(), (source / 'hub_protocol.py').read_bytes())


if __name__ == '__main__':
    unittest.main()
