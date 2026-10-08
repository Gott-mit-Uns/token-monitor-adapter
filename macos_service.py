"""macOS loopback cache service and reversible user LaunchAgent installer."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import venv
from urllib.parse import urlsplit

from adapter import Adapter, Handler, Server, StorageError, UpstreamError, atomic_json

VERSION = '0.1.21'
LABEL = 'io.github.gott-mit-uns.token-monitor-adapter'
CLIENT_KEYS = ('hubMode', 'hubUrl', 'syncUploadIntervalMs')


def defaults(home=None):
    home = Path(home or Path.home())
    support = home / 'Library' / 'Application Support'
    return support / 'TokenMonitorAdapter', support / 'Token Monitor', home / 'Library' / 'LaunchAgents' / (LABEL + '.plist')


def read_credentials(path):
    try:
        document = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        secret = document.get('credentials', {}).get('hub', {}).get('clientSecret')
        if not isinstance(secret, str) or not secret.strip():
            raise ValueError()
        return secret
    except (OSError, ValueError, TypeError, AttributeError):
        raise UpstreamError(503, {'error': 'credential_unavailable'}) from None


def make_config(client_root, upstream=None):
    settings = json.loads((Path(client_root) / 'settings.json').read_text(encoding='utf-8-sig'))
    upstream = (upstream or settings.get('hubUrl', '')).rstrip('/')
    parsed = urlsplit(upstream)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('HTTPS Hub address required')
    if not isinstance(settings.get('deviceId'), str) or not settings['deviceId']:
        raise ValueError('Client device ID required')
    path = Path(client_root) / 'credentials.json'
    read_credentials(path)
    return {'upstream': upstream, 'port': 17322, 'device_id': settings['deviceId'],
            'credentials_file': str(path.resolve()), 'interval_seconds': 300, 'upload_interval_ms': 300000}


def make_adapter(config, root):
    return Adapter(config, root, secret_provider=lambda: read_credentials(config['credentials_file']),
                   local_secret_provider=lambda: read_credentials(config['credentials_file']), version=VERSION)


def check_port(port):
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', port))


def save_private(path, document):
    # State can include cached usage; protect even the atomic temporary file.
    previous = os.umask(0o077)
    try:
        atomic_json(path, document)
        os.chmod(path, 0o600)
    finally:
        os.umask(previous)


def attach_client(client_root, state_root, port=17322):
    settings_path = Path(client_root) / 'settings.json'
    settings = json.loads(settings_path.read_text(encoding='utf-8-sig'))
    backup_dir = Path(state_root) / 'backups'
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    record = Path(state_root) / 'client-restore.json'
    if not record.exists():
        backup = backup_dir / ('settings.pre-adapter-' + time.strftime('%Y%m%d-%H%M%S') + '.json')
        save_private(backup, settings)
        save_private(record, {'settings_path': str(settings_path.resolve()), 'backup': str(backup.resolve()),
                              'original': {k: settings[k] for k in CLIENT_KEYS if k in settings}})
    settings.update(hubMode='client', hubUrl=f'http://127.0.0.1:{port}', syncUploadIntervalMs=0)
    save_private(settings_path, settings)


def restore_client(state_root):
    record_path = Path(state_root) / 'client-restore.json'
    if not record_path.exists():
        return False
    record = json.loads(record_path.read_text())
    path = Path(record['settings_path'])
    settings = json.loads(path.read_text(encoding='utf-8-sig'))
    # Preserve subsequent edits unrelated to the connection. Refuse to undo
    # a connection the user deliberately switched after installation.
    if settings.get('hubUrl', '').rstrip('/') != 'http://127.0.0.1:17322':
        raise ValueError('Client connection changed; restore it manually from the backup')
    for key in CLIENT_KEYS:
        if key in record['original']:
            settings[key] = record['original'][key]
        else:
            settings.pop(key, None)
    save_private(path, settings)
    record_path.unlink()
    return True


def launch_document(python, service, root):
    return {'Label': LABEL, 'ProgramArguments': [str(python), str(service), 'run', '--root', str(root)],
            'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 10, 'Umask': 0o077,
            'WorkingDirectory': str(service.parent), 'StandardOutPath': '/dev/null', 'StandardErrorPath': '/dev/null'}


def launchctl(*args, check=True):
    result = subprocess.run(['/bin/launchctl', *args], capture_output=True)
    if check and result.returncode:
        raise RuntimeError('LaunchAgent operation failed')
    return result


def quit_client():
    # Quit before changing settings: Electron may persist settings on shutdown.
    result = subprocess.run(['/usr/bin/osascript', '-e', 'tell application "Token Monitor" to quit'], capture_output=True)
    if result.returncode:
        raise RuntimeError('Unable to quit Token Monitor safely')
    for _ in range(50):
        if subprocess.run(['/usr/bin/pgrep', '-x', 'Token Monitor'], capture_output=True).returncode:
            return
        time.sleep(0.2)
    raise RuntimeError('Token Monitor did not exit; connection unchanged')


def open_client():
    subprocess.run(['/usr/bin/open', '-a', 'Token Monitor'], check=True, capture_output=True)


def install(root, client_root, plist_path, upstream=None):
    if sys.platform != 'darwin':
        raise RuntimeError('Installation requires macOS')
    check_port(17322)
    config = make_config(client_root, upstream)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    service = root / 'service'
    service.mkdir(mode=0o700, exist_ok=True)
    source = Path(__file__).resolve().parent
    for name in ('adapter.py', 'hub_protocol.py', 'state_store.py', 'sync_schedule.py', 'macos_service.py'):
        if (source / name).resolve() != (service / name).resolve():
            shutil.copy2(source / name, service / name)
    runtime = root / 'runtime'
    if not (runtime / 'bin' / 'python3').exists():
        venv.EnvBuilder(with_pip=False).create(runtime)
    python = runtime / 'bin' / 'python3'
    subprocess.run([str(python), '-c', 'import gzip, ssl, sqlite3; import sys; assert sys.version_info >= (3,9)'], check=True, capture_output=True)
    save_private(root / 'config.json', config)
    # Validate authenticated remote stats before changing the client's address.
    probe = make_adapter(config, root)
    probe.refresh()
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_bytes(plistlib.dumps(launch_document(python, service / 'macos_service.py', root)))
    os.chmod(plist_path, 0o600)
    domain = f'gui/{os.getuid()}'
    launchctl('bootstrap', domain, str(plist_path))
    attached = False
    try:
        ready = False
        for _ in range(50):
            try:
                with urllib.request.urlopen('http://127.0.0.1:17322/adapter/status', timeout=1) as response:
                    state = json.load(response)
                if state.get('version') == VERSION and state.get('state') == 'cached':
                    ready = True
                    break
            except (OSError, ValueError):
                pass
            time.sleep(0.2)
        if not ready:
            raise RuntimeError('Local adapter did not become ready')
        quit_client()
        attach_client(client_root, root)
        attached = True
        open_client()
    except Exception:
        launchctl('bootout', domain, str(plist_path), check=False)
        plist_path.unlink(missing_ok=True)
        if attached:
            quit_client()
            restore_client(root)
        open_client()
        raise
    print('Installed: download 300s, upload 300s; http://127.0.0.1:17322/adapter')


def uninstall(root, plist_path):
    if sys.platform != 'darwin':
        raise RuntimeError('Uninstallation requires macOS')
    if (root / 'client-restore.json').exists():
        quit_client()
        try:
            restore_client(root)
        except Exception:
            open_client()
            raise
    launchctl('bootout', f'gui/{os.getuid()}', str(plist_path), check=False)
    plist_path.unlink(missing_ok=True)
    open_client()
    print('Original client connection restored; local state and backups retained')


def run(root):
    os.umask(0o077)
    config = json.loads((root / 'config.json').read_text())
    adapter = make_adapter(config, root)
    server = Server(('127.0.0.1', config['port']), Handler)
    server.adapter = adapter
    def stop(*_):
        adapter.stop.set()
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    def supervise():
        while not adapter.stop.wait(2):
            adapter.ensure_scheduler()
            with adapter.lock:
                request_age = max((time.monotonic() - r['monotonic'] for r in adapter.active_requests.values()), default=0)
            if max(time.monotonic() - adapter.heartbeat_monotonic, request_age) > 120:
                os._exit(1)  # LaunchAgent restarts; pending/cache already durable.
    adapter.ensure_scheduler()
    threading.Thread(target=supervise, daemon=True).start()
    try:
        server.serve_forever(poll_interval=0.3)
    finally:
        adapter.stop.set()
        if adapter.scheduler_thread:
            adapter.scheduler_thread.join(timeout=15)
        try:
            adapter.save()
        except StorageError:
            pass
        server.server_close()


def main():
    root, client, plist = defaults()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('install', 'run', 'uninstall'))
    parser.add_argument('--root', type=Path, default=root)
    parser.add_argument('--client-root', type=Path, default=client)
    parser.add_argument('--upstream', help='HTTPS Hub address; credentials stay in Token Monitor')
    args = parser.parse_args()
    try:
        if args.action == 'install':
            install(args.root, args.client_root, plist, args.upstream)
        elif args.action == 'uninstall':
            uninstall(args.root, plist)
        else:
            run(args.root)
    except (OSError, ValueError, RuntimeError, UpstreamError, StorageError):
        # Do not print exception text: OS/network errors can contain user data.
        print('Operation failed: check port, Python runtime, client settings, credentials and Hub availability', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
