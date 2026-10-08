"""Settings orchestration independent of Win32, UI and process construction."""
import time


def overview_window_bounds(work_area, scale=1.0, preferred_height=1040):
    """Fit the preferred overview window within a monitor's physical work area."""
    x, y, available_width, available_height = work_area
    margin = round(8 * scale)
    width = min(round(440 * scale), max(1, available_width - 2 * margin))
    height = min(round(preferred_height * scale), max(1, available_height - 2 * margin))
    return (x + (available_width - width) // 2,
            y + (available_height - height) // 2, width, height)


class SettingsController:
    def __init__(self, host, settings, version, executable, frozen, stop, probe, clock=None):
        self.host, self.settings = host, settings
        self.version, self.executable, self.frozen = version, executable, frozen
        self.stop, self.probe = stop, probe
        self.clock = clock if clock is not None else time

    def get_settings(self):
        config = self.settings.load(self.host.root)
        return {key: config[key] for key in ('upstream', 'interval_seconds', 'upload_interval_ms', 'theme')} | {'ui_style': config.get('ui_style', 'glass'),
            'key_saved': (self.host.root / 'remote-secret.bin').exists(),
            'autostart': self.settings.startup_enabled(), 'version': self.version}

    def save_settings(self, value):
        host = self.host
        try:
            if not isinstance(value, dict):
                raise ValueError('设置格式无效，未保存。')
            # Reject unsupported startup mode before changing files or stopping work.
            if value.get('autostart') and not self.frozen:
                raise ValueError('开机启动请使用 EXE 版本。')
            with host.lock:
                self.stop()
                if host.child: host.child.wait(timeout=18)
                host.restart_at = 0
                config = self.settings.save(host.root, value, value.get('secret', ''),
                                            confirm_migration=value.get('confirm_migration') is True)
                self.settings.autostart(bool(value.get('autostart')), self.executable)
                note = self.settings.connect_client(host.root, config) if value.get('connect_client') else '设置已保存，后台已使用当前地址。'
                host.spawn()
                deadline = self.clock.monotonic() + 10
                while self.clock.monotonic() < deadline:
                    try:
                        if self.probe(host.root).get('upstream') == config['upstream']: break
                    except Exception: pass
                    if host.child.poll() is not None: raise RuntimeError('worker_start_failed')
                    self.clock.sleep(.2)
                else: raise RuntimeError('worker_configuration_not_confirmed')
            return {'ok': True, 'message': note, 'settings': self.get_settings()}
        except Exception as error:
            try:
                with host.lock:
                    if host.child is None or host.child.poll() is not None: host.spawn()
            except Exception:
                # Recovery failure must still yield a fixed, credential-free response.
                pass
            return {'ok': False, 'requires_migration': isinstance(error, self.settings.PendingMigrationRequired),
                    'message': str(error) if isinstance(error, ValueError) else '设置操作未完成，未确认后台已加载新地址；请重新打开设置核对保存值及诊断状态。'}
