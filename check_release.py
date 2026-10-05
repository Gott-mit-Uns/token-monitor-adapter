"""Inspect the source release allowlist without printing any matched data."""
from pathlib import Path
import re
import sys
import os
import ast

ALLOWED={'sync_schedule.py','test_sync_schedule.py','state_store.py','test_state_store.py','hub_protocol.py','test_hub_protocol.py','adapter.py','desktop.py','settings.py','tray_host.py','local_ipc.py','dashboard.html',
         'macos_service.py','test_macos.py','README.macos.md','scripts/install-macos.sh','scripts/uninstall-macos.sh',
         'test_adapter.py','test_settings.py','test_runtime.py','test_ipc.py','requirements-build.txt','TokenMonitorAdapter.spec',
         '.gitignore','config.example.json','README.md','RELEASE.md','check_release.py'}
PATTERN=re.compile(rb'github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|-----BEGIN [A-Z ]{0,16}PRIVATE KEY-----')
def check(root):
    findings=[]
    for name in ALLOWED:
        p=root/name
        if not p.is_file(): findings.append(name+': missing release source');continue
        if PATTERN.search(p.read_bytes()): findings.append(name+': credential-like content')
    assets=list((root/'assets').glob('*'))
    if sorted(p.name for p in assets)!=['icon-amber.ico','icon-green.ico','icon-red.ico']: findings.append('Unexpected asset files')
    ref=os.environ.get('GITHUB_REF_NAME','')
    if ref.startswith('adapter-v'):
        tree=ast.parse((root/'desktop.py').read_text(encoding='utf-8'))
        versions=[ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='VERSION' for t in n.targets)]
        if len(versions)!=1 or ref!='adapter-v'+versions[0]: findings.append('Release tag does not match desktop.py VERSION')
        mac_tree=ast.parse((root/'macos_service.py').read_text(encoding='utf-8'))
        mac_versions=[ast.literal_eval(n.value) for n in mac_tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='VERSION' for t in n.targets)]
        if mac_versions != versions: findings.append('macOS and Windows versions differ')
    for line in findings: print(line)
    return bool(findings)
if __name__=='__main__':sys.exit(check(Path(__file__).parent))
