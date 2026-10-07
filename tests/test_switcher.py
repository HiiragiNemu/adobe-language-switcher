import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from adobe_language_switcher.resources import SwitchError,map_dictionary,map_json,preference
from adobe_language_switcher.adapters import inspect_installation,build_plan,pref_path
from adobe_language_switcher.transaction import Engine


def dictionary(word):
    return ('\ufeff"$$$/Menu/File='+word+'"\r\n"$$$/Status/Count=@0 items"\r\n').encode('utf-8')


class Registry:
    def __init__(self):self.value='en_US'
    def get(self,path,name):return self.value
    def set(self,path,name,value):self.value=value


class TestResources(unittest.TestCase):
    def test_dictionary(self):
        result,stats=map_dictionary(dictionary('File'),dictionary('文件'))
        self.assertEqual(result,dictionary('文件'));self.assertEqual(stats['changed'],1)
    def test_preserve_missing(self):
        result,stats=map_dictionary(dictionary('File'),b'"$$$/Menu/File=Fichier"\n')
        self.assertIn(b'@0 items',result);self.assertEqual(stats['missing'],1)
    def test_placeholder(self):
        result,stats=map_dictionary(dictionary('File'),dictionary('文件').replace(b'@0',b'@1'))
        self.assertIn(b'@0 items',result);self.assertEqual(stats['placeholder_mismatch'],1)
    def test_duplicate(self):
        with self.assertRaises(SwitchError):map_dictionary(b'"$$$/A=x"\n"$$$/A=y"',b'"$$$/A=z"')
    def test_binary(self):
        with self.assertRaises(SwitchError):map_dictionary(b'\xff\xfe\x00',b'foo')
    def test_json(self):
        result,stats=map_json(b'{"File":"File","Extra":"Keep"}', '{"File":"文件"}'.encode())
        self.assertEqual(json.loads(result),{'File':'文件','Extra':'Keep'});self.assertEqual(stats['missing'],1)
    def test_json_types(self):
        with self.assertRaises(SwitchError):map_json(b'{"a":[]}',b'{"a":"oops"}')
    def test_json_duplicate(self):
        with self.assertRaises(SwitchError):map_json(b'{"a":"x","a":"y"}',b'{"a":"z"}')
    def test_preference(self):
        data=b'\xef\xbb\xbfOther\t1\t1\r\nApplicationLanguage\ten_US\ten_US\r\n'
        result=preference(data,'zh_CN')
        self.assertEqual(preference(result),'zh_CN');self.assertEqual(preference(result,'en_US'),data)
    def test_locale_path(self):
        with self.assertRaises(SwitchError):preference(b'ApplicationLanguage\ten_US\ten_US','../x')
    def test_preference_line_endings(self):
        for ending in (b'\n',b'\r\n',b'\r',b'\r\r\n',b''):
            for bom in (b'',b'\xef\xbb\xbf'):
                with self.subTest(ending=ending,bom=bom):
                    data=bom+b'ApplicationLanguage\ten_US\ten_US'+ending
                    changed=preference(data,'zh_CN')
                    self.assertEqual(preference(changed),'zh_CN')
                    self.assertEqual(preference(changed,'en_US'),data)
    def test_preference_double_cr_between_settings(self):
        data=b'Other\t1\t1\r\r\nApplicationLanguage\ten_US\ten_US\r\r\nLater\t2\t2\r\r\n'
        self.assertEqual(preference(data,'fr_FR'),data.replace(b'ApplicationLanguage\ten_US',b'ApplicationLanguage\tfr_FR'))
    def test_duplicate_preference(self):
        with self.assertRaises(SwitchError):preference(b'ApplicationLanguage\ten_US\ten_US\nApplicationLanguage\tfr_FR\ten_US')
    def test_json_crlf_bom(self):
        data=b'\xef\xbb\xbf{\r\n  "File": "File"\r\n}\r\n'
        output,_=map_json(data,'{"File":"文件"}'.encode())
        self.assertTrue(output.startswith(b'\xef\xbb\xbf'))
        self.assertNotIn(b'\n',output.replace(b'\r\n',b''))
    def test_json_placeholder(self):
        data=b'{"a":"Open {filename}"}'
        output,stats=map_json(data,b'{"a":"Open {name}"}')
        self.assertEqual(output,data);self.assertEqual(stats['placeholder_mismatch'],1)


class TestTransaction(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        self.root=self.base/'Adobe Premiere';self.root.mkdir()
        self.exe=self.root/'Adobe Premiere Pro.exe';self.exe.write_bytes(b'SYNTHETIC executable fixture, never executed')
        (self.root/'AMT').mkdir();(self.root/'AMT/application.xml').write_text('<Configuration><Data key="installedLanguages">en_US</Data></Configuration>')
        for loc,word in [('en_US','File'),('fr_FR','Fichier'),('zh_CN','文件')]:
            folder=self.root/'Dictionaries'/loc;folder.mkdir(parents=True)
            (folder/f'zdictionary_PPRO_{loc}.dat').write_bytes(dictionary(word))
        self.env=patch.dict(os.environ,{'APPDATA':str(self.base/'profile')});self.env.start()
        with patch('adobe_language_switcher.windows.file_version',return_value='26.5.2.5'):
            self.app=inspect_installation(self.root)
        self.pref=pref_path(self.app);self.pref.parent.mkdir(parents=True)
        self.original=b'Other\t1\t1\r\nApplicationLanguage\ten_US\ten_US\r\n';self.pref.write_bytes(self.original)
        self.registry=Registry()
        self.engine=Engine(self.base/'state',registry=self.registry,closed=lambda _:None,identity=lambda:'fixture-user')
    def tearDown(self):self.env.stop();self.temp.cleanup()
    def native(self):return build_plan(self.app,'zh_CN',registry=self.registry)
    def mapped(self):return build_plan(self.app,'zh_CN','mapped','fr_FR',self.registry,True)
    def test_native_roundtrip(self):
        tid=self.engine.apply(self.native());self.assertEqual(preference(self.pref.read_bytes()),'zh_CN');self.assertEqual(self.registry.value,'zh_CN')
        self.engine.rollback(tid);self.assertEqual(self.pref.read_bytes(),self.original);self.assertEqual(self.registry.value,'en_US')
    def test_mapped_roundtrip(self):
        plan=self.mapped();tid=self.engine.apply(plan)
        dest=self.root/'Dictionaries/fr_FR/zdictionary_PPRO_fr_FR.dat'
        self.assertEqual(dest.read_bytes(),dictionary('文件'));self.assertEqual(self.registry.value,'fr_FR')
        self.engine.rollback(tid);self.assertEqual(dest.read_bytes(),dictionary('Fichier'))
    def test_missing_locale(self):
        with self.assertRaises(SwitchError):build_plan(self.app,'de_DE',registry=self.registry)
    def test_confirmation(self):
        with self.assertRaises(SwitchError):build_plan(self.app,'zh_CN','mapped','fr_FR',self.registry)
    def test_english_carrier(self):
        with self.assertRaises(SwitchError):build_plan(self.app,'zh_CN','mapped','en_US',self.registry,True)
    def test_running(self):
        self.engine.closed=lambda _:(_ for _ in ()).throw(SwitchError('running'))
        with self.assertRaises(SwitchError):self.engine.apply(self.native())
        self.assertEqual(self.pref.read_bytes(),self.original)
    def test_apply_drift(self):
        plan=self.native();self.pref.write_bytes(self.original+b'New\t1\t1')
        with self.assertRaises(SwitchError):self.engine.apply(plan)
    def test_source_drift(self):
        plan=self.mapped();(self.root/'Dictionaries/zh_CN/zdictionary_PPRO_zh_CN.dat').write_bytes(dictionary('其他'))
        with self.assertRaises(SwitchError):self.engine.apply(plan)
    def test_resource_rollback_drift(self):
        tid=self.engine.apply(self.mapped());dest=self.root/'Dictionaries/fr_FR/zdictionary_PPRO_fr_FR.dat';dest.write_bytes(b'updated by installer')
        with self.assertRaises(SwitchError):self.engine.rollback(tid)
        self.assertEqual(dest.read_bytes(),b'updated by installer')
    def test_pref_other_settings_preserved(self):
        tid=self.engine.apply(self.native());self.pref.write_bytes(self.pref.read_bytes().replace(b'Other\t1',b'Other\t2'))
        self.engine.rollback(tid);self.assertIn(b'Other\t2',self.pref.read_bytes());self.assertEqual(preference(self.pref.read_bytes()),'en_US')
    def test_apply_failure_restores(self):
        real=__import__('adobe_language_switcher.transaction',fromlist=['atomic_write']).atomic_write
        calls=0
        def failing(path,data):
            nonlocal calls
            if Path(path)==self.pref and b'fr_FR' in data:
                calls+=1
                raise OSError('simulated access failure')
            return real(path,data)
        with patch('adobe_language_switcher.transaction.atomic_write',side_effect=failing):
            with self.assertRaises(SwitchError):self.engine.apply(self.mapped())
        self.assertEqual(calls,1);self.assertEqual(self.pref.read_bytes(),self.original)
        self.assertEqual((self.root/'Dictionaries/fr_FR/zdictionary_PPRO_fr_FR.dat').read_bytes(),dictionary('Fichier'))
        self.assertEqual(self.engine.histories()[0]['status'],'failed_restored')
    def test_no_stacking(self):
        self.engine.apply(self.native())
        with self.assertRaises(SwitchError):self.engine.apply(build_plan(self.app,'fr_FR',registry=self.registry))
    def test_backup_corruption(self):
        tid=self.engine.apply(self.native());(self.engine.root/tid/'0.before').write_bytes(b'corrupt')
        with self.assertRaises(SwitchError):self.engine.rollback(tid)
    def test_identity(self):
        tid=self.engine.apply(self.native());self.engine.identity=lambda:'different-account'
        with self.assertRaises(SwitchError):self.engine.rollback(tid)
    def test_invalid_transaction(self):
        with self.assertRaises(SwitchError):self.engine.rollback('../escape')
    def test_registry_drift(self):
        tid=self.engine.apply(self.native());self.registry.value='ja_JP'
        with self.assertRaises(SwitchError):self.engine.rollback(tid)
    def test_tampered_target(self):
        tid=self.engine.apply(self.native());path=self.engine.root/tid/'transaction.json';j=json.loads(path.read_text());j['files'][0]['path']=str(self.exe);path.write_text(json.dumps(j))
        with self.assertRaises(SwitchError):self.engine.rollback(tid)
    def test_recovery_applying_journal(self):
        tid=self.engine.apply(self.mapped());path=self.engine.root/tid/'transaction.json';j=json.loads(path.read_text());j['status']='applying';path.write_text(json.dumps(j))
        self.engine.rollback(tid);self.assertEqual(self.pref.read_bytes(),self.original)
    def test_absent_registry_restored(self):
        self.registry.value=None;tid=self.engine.apply(self.native());self.engine.rollback(tid);self.assertIsNone(self.registry.value)
    def test_product_adapters(self):
        for product,exe in [('after-effects','AfterFX.exe'),('media-encoder','Adobe Media Encoder.exe'),('audition','Adobe Audition.exe')]:
            with self.subTest(product=product):
                folder=self.base/product;folder.mkdir();(folder/exe).write_bytes(b'synthetic')
                resource=folder
                for loc,word in [('fr_FR','Fichier'),('zh_CN','文件')]:
                    d=resource/'Dictionaries'/loc;d.mkdir(parents=True);(d/f'app_{loc}.dat').write_bytes(dictionary(word))
                (resource/'AMT').mkdir();(resource/'AMT/application.xml').write_text('<Configuration><Data key="installedLanguages">fr_FR</Data></Configuration>')
                app=inspect_installation(folder);plan=build_plan(app,'zh_CN','mapped','fr_FR',self.registry,True)
                self.assertIsNone(plan.registry);self.assertEqual(len(plan.edits),1)
                tid=self.engine.apply(plan);self.engine.rollback(tid)
    def test_support_files_layout(self):
        from adobe_language_switcher.adapters import Installation
        folder=self.base/'AE'/'Support Files';folder.mkdir(parents=True)
        (folder/'AfterFX.exe').write_bytes(b'synthetic')
        for lang,word in [('fr_FR','Fichier'),('zh_CN','文件')]:
            d=folder/'Dictionaries'/lang;d.mkdir(parents=True)
            (d/f'ae_{lang}.dat').write_bytes(dictionary(word))
        (folder/'AMT').mkdir();(folder/'AMT/application.xml').write_text('<Configuration><Data key="installedLanguages">fr_FR</Data></Configuration>')
        app=inspect_installation(folder.parent)
        self.assertEqual(app.resource_root,folder)
        plan=build_plan(app,'zh_CN','mapped','fr_FR',self.registry,True)
        tid=self.engine.apply(plan);self.engine.rollback(tid)
        self.assertEqual((folder/'Dictionaries/fr_FR/ae_fr_FR.dat').read_bytes(),dictionary('Fichier'))
    def test_uxp_paths_and_aliases(self):
        for prefix,carrier,target in [('com.adobe.ccx.start/locale','fr_FR','zh_CN'),('com.adobe.ccx.start/cmdn-locale','fr_FR','zh_CN'),('com.adobe.unifiedpanel/locale','fr','zh-Hans')]:
            for lang,word in [(carrier,'File'),(target,'文件')]:
                d=self.root/'UXP/plugins'/prefix/lang;d.mkdir(parents=True)
                (d/'strings.json').write_text(json.dumps({'File':word,'count':3}),encoding='utf-8')
        plan=self.mapped()
        self.assertEqual(len([e for e in plan.edits if e.kind=='json']),3)
        tid=self.engine.apply(plan)
        self.assertEqual(json.loads((self.root/'UXP/plugins/com.adobe.unifiedpanel/locale/fr/strings.json').read_bytes())['File'],'文件')
        self.engine.rollback(tid)
    def test_inspection_is_read_only(self):
        before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        before[self.pref]=self.pref.read_bytes()
        self.native();self.mapped()
        self.assertTrue(all(p.read_bytes()==data for p,data in before.items()))
        self.assertEqual(self.registry.value,'en_US')
        self.assertFalse(self.engine.root.exists())
    def test_noop(self):
        plan=build_plan(self.app,'en_US',registry=self.registry)
        with self.assertRaisesRegex(SwitchError,'No changes required'):self.engine.apply(plan)
    def test_native_other_product_stops(self):
        from dataclasses import replace
        app=replace(self.app,product='after-effects')
        with self.assertRaisesRegex(SwitchError,'Premiere only'):build_plan(app,'zh_CN',registry=self.registry)
    def test_experimental_locale_ambiguous(self):
        from dataclasses import replace
        app=replace(self.app,product='audition',installed_languages=['en_US','fr_FR'])
        with self.assertRaisesRegex(SwitchError,'single recorded install locale'):build_plan(app,'zh_CN','mapped','fr_FR',self.registry,True)


if __name__=='__main__':unittest.main()
