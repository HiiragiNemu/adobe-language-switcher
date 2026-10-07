"""Reproducible synthetic apply/rollback; no Adobe installation is required."""
from pathlib import Path
import hashlib
import json
import os
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adobe_language_switcher.adapters import inspect_installation, build_plan, pref_path
from adobe_language_switcher.resources import preference
from adobe_language_switcher.transaction import Engine


class MemoryRegistry:
    value = 'en_US'
    def get(self, path, name): return self.value
    def set(self, path, name, value): self.value = value


def main():
    with tempfile.TemporaryDirectory(prefix='als-demo-') as tmp:
        base = Path(tmp)
        app_root = base / 'Synthetic Premiere'
        app_root.mkdir()
        (app_root / 'Adobe Premiere Pro.exe').write_bytes(b'Synthetic fixture; never execute')
        for lang, text in [('en_US', 'File'), ('fr_FR', 'Fichier'), ('zh_CN', '文件')]:
            folder = app_root / 'Dictionaries' / lang
            folder.mkdir(parents=True)
            (folder / f'demo_{lang}.dat').write_bytes(f'\ufeff"$$$/Demo/File={text}"\r\n'.encode('utf-8'))
        reg = MemoryRegistry()
        with patch.dict(os.environ, {'APPDATA': str(base / 'profile')}), patch('adobe_language_switcher.windows.file_version', return_value='26.5.2.5'):
            app = inspect_installation(app_root)
            pref = pref_path(app)
            pref.parent.mkdir(parents=True)
            pref.write_bytes(b'ApplicationLanguage\ten_US\ten_US\r\r\n')
            paths = [p for p in app_root.rglob('*') if p.is_file()] + [pref]
            before = {p: p.read_bytes() for p in paths}
            engine = Engine(base / 'state', registry=reg, closed=lambda _: None, identity=lambda: 'synthetic-user')
            plan = build_plan(app, 'zh_CN', 'mapped', 'fr_FR', reg, True)
            transaction = engine.apply(plan)
            carrier = app_root / 'Dictionaries/fr_FR/demo_fr_FR.dat'
            applied = {'text': carrier.read_text(encoding='utf-8-sig').strip(), 'preference': preference(pref.read_bytes()), 'registry': reg.value}
            assert '文件' in applied['text'] and applied['preference'] == applied['registry'] == 'fr_FR'
            result = engine.rollback(transaction)
            assert result == 'restored' and reg.value == 'en_US'
            assert all(p.read_bytes() == original for p, original in before.items())
            print(json.dumps({'mode': 'synthetic fixture only', 'files_modified': len(plan.edits), 'applied': applied,
                              'rollback': result, 'all_original_bytes_restored': True,
                              'executable_unchanged': hashlib.sha256(before[app.exe]).hexdigest() == hashlib.sha256(app.exe.read_bytes()).hexdigest()}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
