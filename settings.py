"""User-local configuration and Windows DPAPI; never returns stored secrets to UI."""
import base64
import ctypes as C
from ctypes import wintypes as W
import json
import http.client
from hub_protocol import decode_json, valid_response
import os
from pathlib import Path
import shutil
import time
from urllib.parse import urlsplit
from adapter import atomic_json, UpstreamError

class Blob(C.Structure):
    _fields_=[('length',W.DWORD),('data',C.POINTER(C.c_ubyte))]

def protect(data, decrypt=False):
    if os.name != 'nt': raise RuntimeError('Windows required')
    buf=(C.c_ubyte*len(data)).from_buffer_copy(data)
    source=Blob(len(data),buf); result=Blob()
    crypt=C.WinDLL('crypt32',use_last_error=True)
    name='CryptUnprotectData' if decrypt else 'CryptProtectData'
    fn=getattr(crypt,name)
    fn.argtypes=[C.POINTER(Blob),C.c_void_p,C.c_void_p,C.c_void_p,C.c_void_p,W.DWORD,C.POINTER(Blob)]
    fn.restype=W.BOOL
    if not fn(C.byref(source),None,None,None,None,1,C.byref(result)): raise RuntimeError('Windows credential encryption failed')
    try: return C.string_at(result.data,result.length)
    finally:
        kernel=C.WinDLL('kernel32'); kernel.LocalFree.argtypes=[C.c_void_p]; kernel.LocalFree(C.cast(result.data,C.c_void_p))

def client_root(): return Path(os.environ['APPDATA'])/'Token Monitor'
def data_root(): return Path(os.environ['LOCALAPPDATA'])/'TokenMonitorHotspotAdapter'
def load(root):
    try: value=json.loads((Path(root)/'config.json').read_text(encoding='utf-8-sig'))
    except (OSError,ValueError): value={}
    original={}
    try: original=json.loads((client_root()/'settings.json').read_text(encoding='utf-8-sig'))
    except (OSError,ValueError): pass
    return {'upstream':'','port':17322,'device_id':original.get('deviceId','Desktop'),
            'credentials_file':str(client_root()/'credentials.json'),'interval_seconds':600,
            'upload_interval_ms':1800000,'theme':'system','ui_style':'glass',**value}

def local_secret(config):
    try:
        d=json.loads(Path(config['credentials_file']).read_text(encoding='utf-8-sig'))
        v=d['credentials']['hub']['clientSecret']
        if not isinstance(v,str) or not v: raise ValueError()
        return v
    except (OSError,KeyError,ValueError): raise UpstreamError(503,{'error':'local_credential_unavailable'}) from None

def remote_secret(root,config):
    p=Path(root)/'remote-secret.bin'
    if p.exists():
        try: return protect(p.read_bytes(),True).decode('utf-8')
        except Exception: raise UpstreamError(503,{'error':'remote_credential_unavailable'}) from None
    # Existing installations remain compatible until the user supplies a new key.
    return local_secret(config)

def validate(value):
    u=urlsplit(value.get('upstream','').strip())
    if u.scheme!='https' or not u.hostname or u.username or u.password or u.query or u.fragment:
        raise ValueError('请输入 HTTPS 服务器地址，不要在地址中包含密钥、查询参数或账号。')
    try: u.port
    except ValueError: raise ValueError('服务器端口无效。') from None
    download=int(value.get('interval_seconds',600)); upload=int(value.get('upload_interval_ms',1800000))
    if download not in (60,300,600,900,1800,3600) or upload not in (60000,300000,600000,900000,1800000,3600000):
        raise ValueError('请选择提供的同步周期。')
    theme=value.get('theme','system')
    if theme not in ('system','light','dark'): raise ValueError('主题无效。')
    style=value.get('ui_style','glass')
    if style not in ('glass','clean','instrument','paper','midnight'): raise ValueError('界面风格无效。')
    return {'upstream':value['upstream'].strip().rstrip('/'),'interval_seconds':download,'upload_interval_ms':upload,'theme':theme,'ui_style':style}

class PendingMigrationRequired(ValueError):
    pass

def verify_remote(url,key):
    """Validate the destination without transmitting pending snapshots or echoing errors."""
    u=urlsplit(url);conn=http.client.HTTPSConnection(u.hostname,u.port or 443,timeout=12)
    try:
        for path in ('/api/health','/api/stats'):
            conn.request('GET',u.path.rstrip('/')+path,headers={'Authorization':'Bearer '+key,'Accept-Encoding':'gzip'})
            response=conn.getresponse();raw=response.read(16*1024*1024+1)
            if response.status in (401,403): raise ValueError('新 Hub 认证失败，地址和密钥均未保存。')
            if response.status!=200: raise ValueError(f'新 Hub 返回 HTTP {response.status}，地址和密钥均未保存。')
            if len(raw)>16*1024*1024: raise ValueError('新 Hub 响应过大，设置未保存。')
            data=decode_json(raw,response.getheader('Content-Encoding'))
            valid=valid_response(path,data)
            if not valid: raise ValueError('新地址未提供兼容的 Hub 接口，设置未保存。')
    except ValueError as e:
        if str(e).startswith(('新 Hub','新地址')): raise
        raise ValueError('新 Hub 响应无效，设置未保存。') from None
    except Exception:
        raise ValueError('无法连接新 Hub，设置未保存。请检查地址与网络。') from None
    finally: conn.close()

def save(root,value,key='',confirm_migration=False):
    root=Path(root); root.mkdir(parents=True,exist_ok=True); old=load(root)
    new={**old,**validate({**value,'ui_style':value.get('ui_style',old.get('ui_style','glass'))})}
    for name, legacy in [('interval_seconds', 3600), ('upload_interval_ms', 3600000)]:
        if new[name] == legacy and old.get(name) != legacy:
            raise ValueError('60 分钟仅用于保留原配置，请选择新的同步周期。')
    changed=new['upstream']!=old['upstream']
    if changed:
        try: pending=json.loads((root/'pending.json').read_text(encoding='utf-8'))
        except FileNotFoundError: pending=None
        if pending and not confirm_migration:
            raise PendingMigrationRequired('地址尚未保存：有待上报数据。是否保留这些数据并迁移到新 Hub？确认后会验证新 Hub 并备份；后续快照将发送到新 Hub。')
    if key and (not isinstance(key,str) or len(key)>8192): raise ValueError('密钥长度无效。')
    effective=key or remote_secret(root,old)
    if changed: verify_remote(new['upstream'],effective)
    names=('config.json','remote-secret.bin','metrics.json')
    previous={n:(root/n).read_bytes() if (root/n).exists() else None for n in names}
    if changed:
        import uuid
        backup=root/'backups'/('hub-switch-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
        backup.mkdir(parents=True)
        for n in (*names,'pending.json','cache.json'):
            if (root/n).exists(): shutil.copy2(root/n,backup/n)
    try:
        if key or not (root/'remote-secret.bin').exists():
            temp=root/'remote-secret.bin.tmp';temp.write_bytes(protect(effective.encode()));os.replace(temp,root/'remote-secret.bin')
        if changed and (root/'metrics.json').exists():
            metrics=json.loads((root/'metrics.json').read_text(encoding='utf-8'))
            schedule=metrics.get('upload_schedule')
            if isinstance(schedule,dict): schedule.update(retry_at=0,failures=0)
            metrics['last_upload_error']=None;metrics['last_manual_at']=0
            atomic_json(root/'metrics.json',metrics)
        atomic_json(root/'config.json',new)
    except Exception:
        for n,data in previous.items():
            if data is None: (root/n).unlink(missing_ok=True)
            else:
                temp=root/(n+'.restore');temp.write_bytes(data);os.replace(temp,root/n)
        raise
    return new

def connect_client(root,config):
    path=client_root()/'settings.json'
    if not path.exists(): raise ValueError('请先运行并配置 Token Monitor 客户端。')
    local_secret(config)
    d=json.loads(path.read_text(encoding='utf-8-sig'))
    backup=Path(root)/'backups'; backup.mkdir(parents=True,exist_ok=True)
    shutil.copy2(path,backup/('settings-before-exe-'+str(time.time_ns())+'.json'))
    d['hubUrl']='http://127.0.0.1:'+str(config['port']); d['syncUploadIntervalMs']=0
    atomic_json(path,d)
    return '已备份并接入 Token Monitor；请重启 Token Monitor 客户端使设置生效。'

def autostart(enabled,executable):
    import winreg
    target=Path(os.environ['LOCALAPPDATA'])/'Programs'/'TokenMonitorAdapter'/'TokenMonitorAdapter.exe'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
        if enabled:
            try:
                existing=winreg.QueryValueEx(key,'TokenMonitorHotspotAdapter')[0]
                if existing.startswith('"'+str(Path(executable))+'" '): target=Path(executable)
            except FileNotFoundError: pass
            target.parent.mkdir(parents=True,exist_ok=True)
            if Path(executable).resolve()!=target.resolve(): shutil.copy2(executable,target)
            winreg.SetValueEx(key,'TokenMonitorHotspotAdapter',0,winreg.REG_SZ,'"'+str(target)+'" --background')
        else:
            try: winreg.DeleteValue(key,'TokenMonitorHotspotAdapter')
            except FileNotFoundError: pass
    return target

def startup_enabled():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run') as k:
            return 'TokenMonitorAdapter.exe' in winreg.QueryValueEx(k,'TokenMonitorHotspotAdapter')[0]
    except FileNotFoundError: return False
