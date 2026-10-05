import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock
from desktop_settings import SettingsController


class PendingMigrationRequired(ValueError): pass


class Clock:
    def __init__(self): self.now = 0
    def monotonic(self): return self.now
    def sleep(self, seconds): self.now += seconds


class ControllerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.host = Mock(root=Path(temp.name), lock=threading.RLock())
        self.host.child.poll.return_value = None
        self.settings = Mock(PendingMigrationRequired=PendingMigrationRequired)
        self.config = {'upstream': 'https://example.invalid', 'interval_seconds': 600,
                       'upload_interval_ms': 1800000, 'theme': 'system'}
        self.settings.save.return_value = self.config
        self.settings.load.return_value = self.config
        self.stop = Mock()
        self.probe = Mock(return_value={'upstream': self.config['upstream']})
        self.controller = SettingsController(self.host, self.settings, 'test', 'synthetic.exe', True,
                                             self.stop, self.probe, Clock())

    def test_success_drains_before_save_and_confirms_worker(self):
        operations = []
        self.stop.side_effect = lambda: operations.append('stop')
        self.host.child.wait.side_effect = lambda **kwargs: operations.append('drain')
        self.settings.save.side_effect = lambda *args, **kwargs: operations.append('save') or self.config
        self.host.spawn.side_effect = lambda: operations.append('spawn')
        self.assertTrue(self.controller.save_settings({})['ok'])
        self.assertEqual(operations, ['stop', 'drain', 'save', 'spawn'])
        self.probe.assert_called_once()

    def test_pending_confirmation_returns_explicit_failure(self):
        self.settings.save.side_effect = PendingMigrationRequired('确认迁移')
        self.host.child.poll.return_value = 0
        result = self.controller.save_settings({})
        self.assertFalse(result['ok']); self.assertTrue(result['requires_migration'])
        self.settings.autostart.assert_not_called()
        self.host.spawn.assert_called_once()

    def test_confirmation_is_explicit_boolean(self):
        self.controller.save_settings({'confirm_migration': 'true'})
        self.assertFalse(self.settings.save.call_args.kwargs['confirm_migration'])
        self.controller.save_settings({'confirm_migration': True})
        self.assertTrue(self.settings.save.call_args.kwargs['confirm_migration'])

    def test_unsupported_startup_rejected_before_changes(self):
        self.controller.frozen = False
        self.assertFalse(self.controller.save_settings({'autostart': True})['ok'])
        self.stop.assert_not_called(); self.settings.save.assert_not_called()

    def test_wrong_running_address_never_reports_success(self):
        self.probe.return_value = {'upstream': 'https://old.example.invalid'}
        result = self.controller.save_settings({})
        self.assertFalse(result['ok'])
        self.assertGreaterEqual(self.controller.clock.now, 10)

    def test_recovery_failure_has_safe_response(self):
        self.host.child.wait.side_effect = RuntimeError('private detail')
        self.host.child.poll.return_value = 0
        self.host.spawn.side_effect = RuntimeError('private recovery detail')
        result = self.controller.save_settings({})
        self.assertFalse(result['ok']); self.assertNotIn('private', result['message'])
        self.settings.save.assert_not_called()

    def test_invalid_input(self):
        self.assertFalse(self.controller.save_settings([])['ok'])
        self.stop.assert_not_called()
