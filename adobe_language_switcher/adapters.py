"""Capability-based adapters; installer publisher is not a compatibility gate."""
from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import xml.etree.ElementTree as ET
from .resources import SwitchError, LOCALE, locale, preference, map_dictionary, map_json
from . import windows

PRODUCTS = {
    'premiere': ('Adobe Premiere Pro.exe',),
    'after-effects': ('AfterFX.exe',),
    'media-encoder': ('Adobe Media Encoder.exe',),
    'audition': ('Adobe Audition.exe',),
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def inside(root, path):
    root, path = Path(root).resolve(), Path(path).resolve()
    if not path.is_relative_to(root):
        raise SwitchError(f'Path escapes installation: {path}')
    return path


@dataclass
class Installation:
    root: Path
    product: str
    exe: Path
    resource_root: Path
    version: str | None
    locales: list[str]
    installed_languages: list[str]

    def summary(self):
        return dict(root=str(self.root), product=self.product, version=self.version,
                    locales=self.locales, installed_languages=self.installed_languages,
                    native_supported=self.product == 'premiere',
                    mapping_status='Method user-confirmed on Premiere 26.5.2.5; this installation is not runtime-tested by inspect' if self.product == 'premiere' else 'experimental / fixture-tested only')


def inspect_installation(root):
    root = Path(root).absolute()
    if not root.is_dir():
        raise SwitchError('Choose an existing application installation directory')
    if root.is_symlink() or (hasattr(root, 'is_junction') and root.is_junction()):
        raise SwitchError('Choose the real installation directory, not a link/junction')
    root = root.resolve()
    for folder in (root, root/'Support Files'):
        for product, names in PRODUCTS.items():
            for name in names:
                exe = folder/name
                if exe.is_file():
                    inside(root, exe)
                    resource = folder if (folder/'Dictionaries').is_dir() else root
                    directory = inside(root, resource/'Dictionaries')
                    locales = sorted(p.name for p in directory.iterdir() if p.is_dir() and LOCALE.fullmatch(p.name)) if directory.is_dir() else []
                    installed = []
                    xml = resource/'AMT/application.xml'
                    if xml.is_file():
                        inside(root, xml)
                        try:
                            for node in ET.fromstring(xml.read_bytes()).iter('Data'):
                                if node.attrib.get('key') == 'installedLanguages':
                                    import re
                                    installed.extend(re.findall(r'\b[a-z]{2}_[A-Z]{2}\b', node.text or ''))
                        except ET.ParseError:
                            pass
                    return Installation(root, product, exe, resource, windows.file_version(exe), locales, installed)
    raise SwitchError('No supported executable layout found (Premiere / AE / AME / Audition)')


def pref_path(app):
    if app.product != 'premiere' or not app.version:
        raise SwitchError('Native preference switching requires a detected Premiere file version')
    major = app.version.split('.')[0]
    if not major.isdecimal():
        raise SwitchError('Invalid Premiere major version')
    roaming = os.environ.get('APPDATA')
    if not roaming:
        raise SwitchError('APPDATA is missing')
    return Path(roaming).resolve()/'Adobe/Premiere Pro'/f'{major}.0'/'Debug Database.txt'


def registry_path(app):
    return rf'Software\Adobe\Premiere Pro\{app.version.split(".")[0]}.0'


@dataclass
class Edit:
    path: Path
    before: bytes
    after: bytes
    kind: str
    stats: dict = field(default_factory=dict)


@dataclass
class Plan:
    app: Installation
    mode: str
    target: str
    carrier: str | None
    edits: list[Edit]
    registry: dict | None
    guards: list[dict]
    warnings: list[str]

    def summary(self):
        return dict(installation=self.app.summary(), mode=self.mode, target=self.target,
                    carrier=self.carrier, files=[dict(path=str(e.path),kind=e.kind,before=digest(e.before),after=digest(e.after),**e.stats) for e in self.edits],
                    registry=self.registry, warnings=self.warnings,
                    result='Plan only; application startup not tested')


def validate_target(app, path, kind):
    path = Path(path).absolute()
    if kind == 'preference':
        expected = pref_path(app)
        if path != expected or path.resolve() != expected:
            raise SwitchError('Unexpected or redirected preference path')
        return
    relative = inside(app.root, path).relative_to(app.resource_root)
    parts = relative.parts
    if kind == 'dictionary' and len(parts) == 3 and parts[0] == 'Dictionaries' and LOCALE.fullmatch(parts[1]) and path.suffix in ('.dat','.dict'):
        return
    allowed = [
        ('UXP','plugins','com.adobe.ccx.start','locale'),
        ('UXP','plugins','com.adobe.ccx.start','cmdn-locale'),
        ('UXP','plugins','com.adobe.unifiedpanel','locale'),
    ]
    if kind == 'json' and any(parts[:len(prefix)] == prefix and len(parts)==len(prefix)+2 and parts[-1]=='strings.json' for prefix in allowed):
        return
    raise SwitchError(f'Not a supported language resource: {path}')


def resource_pairs(app, target, carrier):
    dictionary = app.resource_root/'Dictionaries'
    source_root = inside(app.root, dictionary/target)
    base = inside(app.root, dictionary/carrier)
    pairs = []
    for path in sorted(base.iterdir()):
        if path.is_file() and path.suffix in ('.dat','.dict'):
            source = source_root/path.name.replace(carrier,target)
            if source.is_file():
                inside(app.root, source)
                pairs.append((path,source,'dictionary'))
    if not pairs:
        raise SwitchError('No matching text dictionaries found for these locales')
    uxp = app.resource_root/'UXP/plugins'
    for part in ('locale','cmdn-locale'):
        base = uxp/'com.adobe.ccx.start'/part
        a,b = base/carrier/'strings.json',base/target/'strings.json'
        if a.is_file() and b.is_file():
            pairs.append((a,b,'json'))
    aliases = {'zh_CN':'zh-Hans','zh_TW':'zh-Hant','pt_BR':'pt'}
    short = lambda code: aliases.get(code,code.split('_')[0])
    base = uxp/'com.adobe.unifiedpanel/locale'
    a,b=base/short(carrier)/'strings.json',base/short(target)/'strings.json'
    if a.is_file() and b.is_file():
        pairs.append((a,b,'json'))
    return pairs


def build_plan(app, target, mode='native', carrier=None, registry=None, confirmed=False):
    locale(target)
    registry = registry or windows.Registry()
    if target not in app.locales:
        raise SwitchError('Target language resources are not installed. No download or guessed translation is performed.')
    if mode not in ('native','mapped'):
        raise SwitchError('Mode must be native or mapped')
    warnings=[];edits=[];guards=[];reg=None
    def guard(path):
        guards.append({'path':str(path),'sha256':digest(path.read_bytes())})
    guard(app.exe)
    metadata=app.resource_root/'AMT/application.xml'
    if metadata.exists():
        guard(metadata)
    if mode == 'mapped':
        locale(carrier or '')
        if carrier not in app.locales or carrier == target:
            raise SwitchError('Choose a different installed carrier locale')
        if carrier == 'en_US':
            raise SwitchError('English may use built-in strings and ignore external dictionaries; select a verified non-English carrier')
        if not confirmed:
            raise SwitchError('First verify that this carrier language launches normally; confirm it explicitly before mapping')
        if app.product != 'premiere' and (len(app.installed_languages)!=1 or carrier!=app.installed_languages[0]):
            raise SwitchError('Experimental products map only their single recorded install locale; native switching is not implemented for this product')
        warnings.append(f'Internal locale remains {carrier}; dates, shortcuts and some panels can retain that locale. This is a UI-text mapping, not a native {target} installation.')
        for dest, source, kind in resource_pairs(app,target,carrier):
            validate_target(app,dest,kind);inside(app.root,source);guard(source)
            before=dest.read_bytes()
            after,stats=(map_dictionary if kind=='dictionary' else map_json)(before,source.read_bytes())
            if stats['missing'] or stats['placeholder_mismatch']:
                warnings.append(f'{dest.name}: kept {stats["missing"]} unmatched keys and {stats["placeholder_mismatch"]} placeholder mismatches')
            if after != before:
                edits.append(Edit(dest,before,after,kind,stats))
        warnings.append('Embedded JavaScript and third-party panel translations are not rewritten; partial-language UI is possible.')
    elif app.product != 'premiere':
        raise SwitchError('Native adapter currently supports Premiere only; other products have an experimental resource-only mapped adapter')
    if app.product == 'premiere':
        path=pref_path(app);validate_target(app,path,'preference')
        if not path.is_file():
            raise SwitchError(f'Launch this Premiere version once to create its preference file: {path}')
        before=path.read_bytes();after=preference(before,target if mode=='native' else carrier)
        if before!=after:
            edits.append(Edit(path,before,after,'preference'))
        key=registry_path(app);old=registry.get(key,'Language')
        wanted=target if mode=='native' else carrier
        if old is not None:
            locale(old)
        if old!=wanted:
            reg=dict(path=key,name='Language',before=old,after=wanted)
    if mode=='native':
        warnings.append('This changes user language preferences, not subscription entitlements. If startup fails, close the dialog and restore this transaction.')
    return Plan(app,mode,target,carrier,edits,reg,guards,warnings)
