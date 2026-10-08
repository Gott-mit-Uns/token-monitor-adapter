import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock
from desktop_settings import SettingsController, overview_window_bounds


class PendingMigrationRequired(ValueError): pass


class Clock:
    def __init__(self): self.now = 0
    def monotonic(self): return self.now
    def sleep(self, seconds): self.now += seconds


class WindowBoundsTests(unittest.TestCase):
    def test_full_overview_on_tall_monitor(self):
        self.assertEqual(overview_window_bounds((0,0,1920,1400)),(740,180,440,1040))

    def test_1080_work_area_excludes_taskbar(self):
        x,y,width,height=overview_window_bounds((0,0,1920,1040))
        self.assertEqual((width,height),(440,1024))
        self.assertGreaterEqual(y,0)
        self.assertLessEqual(y+height,1040)

    def test_high_dpi_and_short_screen_stay_inside_work_area(self):
        for scale in (1,1.25,1.5,2):
            for area in ((0,0,1366,728),(-1920,32,1920,1008),(0,0,320,480)):
                x,y,w,h=overview_window_bounds(area,scale)
                self.assertGreater(w,0);self.assertGreater(h,0)
                self.assertGreaterEqual(x,area[0]);self.assertGreaterEqual(y,area[1])
                self.assertLessEqual(x+w,area[0]+area[2]);self.assertLessEqual(y+h,area[1]+area[3])

    def test_populated_overview_height_is_fitted_but_bounded(self):
        self.assertEqual(overview_window_bounds((0,0,1920,1400),1,1160)[3],1160)
        self.assertEqual(overview_window_bounds((0,0,1920,1040),1,1160)[3],1024)


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

    def test_legacy_settings_bridge_returns_default_style(self):
        self.assertEqual(self.controller.get_settings()['ui_style'],'glass')

    def test_settings_bridge_returns_selected_style_without_secret(self):
        self.config['ui_style']='instrument'
        self.config['secret']='synthetic-private-value'
        result=self.controller.get_settings()
        self.assertEqual(result['ui_style'],'instrument')
        self.assertNotIn('secret',result)

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
