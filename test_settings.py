import sys
import unittest
if sys.platform != "win32":
    raise unittest.SkipTest("Windows platform integration tests run in Windows CI")
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import settings
VERIFY_REMOTE=settings.verify_remote
from adapter import atomic_json

class SettingsTests(unittest.TestCase):
    def test_duplicate_instance_uses_ctypes_last_error(self):
        import desktop
        with tempfile.TemporaryDirectory() as name:
            first,existing=desktop.instance_mutex(name)
            second=None
            try:
                self.assertFalse(existing)
                second,existing=desktop.instance_mutex(name)
                self.assertTrue(existing)
            finally:
                if second: desktop.K.CloseHandle(second)
                desktop.K.CloseHandle(first)
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.remote_check=patch('settings.verify_remote');self.remote_check.start();self.addCleanup(self.remote_check.stop)
        self.value={'upstream':'https://example.invalid','interval_seconds':600,'upload_interval_ms':1800000,'theme':'dark'}
    def tearDown(self): self.temp.cleanup()
    def test_old_config_defaults_to_glass(self):
        self.assertEqual(settings.load(self.root)['ui_style'],'glass')
    def test_all_styles_persist_and_legacy_save_preserves_style(self):
        for style in ('glass','clean','instrument'):
            settings.save(self.root,{**self.value,'ui_style':style},'synthetic-secret')
            self.assertEqual(settings.load(self.root)['ui_style'],style)
        settings.save(self.root,self.value,'synthetic-secret')
        self.assertEqual(settings.load(self.root)['ui_style'],'instrument')
    def test_invalid_style_rejected_before_save(self):
        with self.assertRaises(ValueError):
            settings.save(self.root,{**self.value,'ui_style':'unknown'},'synthetic-secret')
        self.assertFalse((self.root/'config.json').exists())
    def test_dpapi_roundtrip_and_no_plaintext(self):
        key=b'synthetic-secret-for-tests'; blob=settings.protect(key)
        self.assertNotIn(key,blob);self.assertEqual(settings.protect(blob,True),key)
    def test_save_config_contains_no_key(self):
        c=settings.save(self.root,self.value,'synthetic-secret')
        self.assertNotIn('secret',(self.root/'config.json').read_text())
        self.assertEqual(settings.remote_secret(self.root,c),'synthetic-secret')
    def test_save_preserves_registered_executable_location(self):
        exe=self.root/'chosen-location'/'TokenMonitorAdapter.exe'
        exe.parent.mkdir();exe.write_bytes(b'synthetic executable')
        with patch('winreg.CreateKey'),patch('winreg.QueryValueEx',return_value=('"'+str(exe)+'" --background',1)),patch('winreg.SetValueEx') as save,patch('settings.shutil.copy2') as copy:
            self.assertEqual(settings.autostart(True,exe),exe)
            copy.assert_not_called()
            self.assertEqual(save.call_args.args[-1],'"'+str(exe)+'" --background')
    def test_pending_blocks_server_change_without_touching_key(self):
        settings.save(self.root,self.value,'old-synthetic-key')
        old=(self.root/'remote-secret.bin').read_bytes()
        atomic_json(self.root/'pending.json',{'deviceId':'Synthetic Desktop'})
        with self.assertRaises(ValueError): settings.save(self.root,{**self.value,'upstream':'https://other.invalid'},'new-synthetic-key')
        self.assertEqual((self.root/'remote-secret.bin').read_bytes(),old)
    def test_confirmed_migration_preserves_pending_and_resets_old_retry(self):
        settings.save(self.root,self.value,'old-synthetic-key')
        pending={'deviceId':'Synthetic Desktop','allTime':{'totalTokens':123}}
        atomic_json(self.root/'pending.json',pending)
        atomic_json(self.root/'metrics.json',{'upload_schedule':{'next_at':1234,'retry_at':999,'failures':4},'last_upload_error':{'status':404},'daily':{'synthetic':1}})
        cfg=settings.save(self.root,{**self.value,'upstream':'https://other.invalid'},'new-synthetic-key',confirm_migration=True)
        self.assertEqual(cfg['upstream'],'https://other.invalid')
        self.assertEqual(settings.remote_secret(self.root,cfg),'new-synthetic-key')
        self.assertEqual(json.loads((self.root/'pending.json').read_text()),pending)
        metrics=json.loads((self.root/'metrics.json').read_text())
        self.assertEqual(metrics['upload_schedule'],{'next_at':1234,'retry_at':0,'failures':0})
        self.assertEqual(metrics['daily'],{'synthetic':1})
        self.assertTrue(list((self.root/'backups').glob('hub-switch-*/pending.json')))
    def test_rejected_new_hub_does_not_change_config_key_or_pending(self):
        settings.save(self.root,self.value,'old-synthetic-key')
        atomic_json(self.root/'pending.json',{'deviceId':'Synthetic Desktop'})
        before={p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        with patch('settings.verify_remote',side_effect=ValueError('新 Hub 认证失败')):
            with self.assertRaises(ValueError): settings.save(self.root,{**self.value,'upstream':'https://other.invalid'},'new-synthetic-key',confirm_migration=True)
        for name,data in before.items():self.assertEqual((self.root/name).read_bytes(),data)
    def test_config_write_failure_restores_key_and_metrics(self):
        settings.save(self.root,self.value,'old-synthetic-key')
        atomic_json(self.root/'metrics.json',{'upload_schedule':{'retry_at':99,'failures':2}})
        before={n:(self.root/n).read_bytes() for n in ('config.json','remote-secret.bin','metrics.json')}
        original=settings.atomic_json
        def fail(path,value):
            if Path(path).name=='config.json':raise OSError('synthetic disk failure')
            return original(path,value)
        with patch('settings.atomic_json',side_effect=fail):
            with self.assertRaises(OSError):settings.save(self.root,{**self.value,'upstream':'https://other.invalid'},'new-synthetic-key')
        for n,data in before.items():self.assertEqual((self.root/n).read_bytes(),data)
    def test_remote_validation_rejects_http_and_invalid_schema(self):
        from unittest.mock import MagicMock
        for code,body in [(401,b'private server error'),(404,b'Not found'),(200,b'{"role":"other"}')]:
            conn=MagicMock();response=MagicMock();response.status=code;response.read.return_value=body;response.getheader.return_value=None;conn.getresponse.return_value=response
            with patch('settings.http.client.HTTPSConnection',return_value=conn):
                with self.assertRaises(ValueError) as caught:VERIFY_REMOTE('https://example.invalid','synthetic-secret')
                self.assertNotIn('private server error',str(caught.exception));self.assertNotIn('synthetic-secret',str(caught.exception))
            conn.close.assert_called_once()
    def test_reject_credentials_in_address_and_bad_periods(self):
        for url in ['http://example.invalid','https://u:p@example.invalid','https://example.invalid?key=synthetic']:
            with self.assertRaises(ValueError): settings.validate({**self.value,'upstream':url})
        with self.assertRaises(ValueError): settings.validate({**self.value,'interval_seconds':0})
    def test_connect_client_backup_and_local_route(self):
        client=self.root/'client';client.mkdir()
        atomic_json(client/'settings.json',{'hubUrl':'https://example.invalid','deviceId':'Synthetic Desktop'})
        with patch('settings.client_root',return_value=client),patch('settings.local_secret',return_value='synthetic'):
            settings.connect_client(self.root,{'port':17322,'upload_interval_ms':1800000})
        d=json.loads((client/'settings.json').read_text());self.assertEqual(d['syncUploadIntervalMs'],0)
        self.assertEqual(d['hubUrl'],'http://127.0.0.1:17322');self.assertEqual(len(list((self.root/'backups').glob('*.json'))),1)
    def test_new_periods_and_legacy_save(self):
        for minutes in [1,5,10,15,30]:
            value={**self.value,'interval_seconds':minutes*60,'upload_interval_ms':minutes*60000}
            self.assertEqual(settings.validate(value)['interval_seconds'],minutes*60)
        with self.assertRaises(ValueError):
            settings.save(self.root,{**self.value,'interval_seconds':3600},'synthetic')
        atomic_json(self.root/'config.json',{**self.value,'interval_seconds':3600})
        self.assertEqual(settings.save(self.root,{**self.value,'interval_seconds':3600},'synthetic')['interval_seconds'],3600)

if __name__=='__main__':unittest.main(verbosity=2)
