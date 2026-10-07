"""Backup-first transactions with crash journals and drift-aware rollback."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import uuid
from .adapters import Installation, digest, validate_target, pref_path, registry_path
from .resources import SwitchError, preference
from . import windows


def atomic_write(path, data):
    path=Path(path)
    fd,name=tempfile.mkstemp(prefix='.als-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def save(path, document):
    atomic_write(path,(json.dumps(document,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))


@contextmanager
def lock(root):
    root.mkdir(parents=True,exist_ok=True)
    with (root/'.lock').open('a+b') as stream:
        stream.seek(0);stream.write(b'0');stream.flush();stream.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as exc:
            raise SwitchError('Another language operation is running') from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name=='nt':
                msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:
                fcntl.flock(stream,fcntl.LOCK_UN)


class Engine:
    def __init__(self, root=None, registry=None, closed=None, identity=None):
        self.root=Path(root or windows.state_root()).resolve()
        self.registry=registry or windows.Registry()
        self.closed=closed or windows.require_closed
        self.identity=identity or windows.user_identity

    def histories(self):
        records=[]
        if not self.root.is_dir():
            return records
        for path in sorted(self.root.glob('*/transaction.json'),reverse=True):
            try:
                item=json.loads(path.read_text(encoding='utf-8'))
                records.append(dict(id=path.parent.name,status=item['status'],root=item['app']['root'],mode=item['mode'],target=item['target']))
            except (OSError,ValueError,KeyError):
                continue
        return records

    def apply(self, plan):
        with lock(self.root):
            self.closed(plan.app.exe.name)
            for item in self.histories():
                if Path(item['root']).resolve()==plan.app.root and item['status'] not in ('restored','failed_restored'):
                    raise SwitchError(f'Restore the previous transaction first: {item["id"]}')
            if not plan.edits and not plan.registry:
                raise SwitchError('No changes required. The current files are the baseline; existing manual mappings are not adopted automatically.')
            for guard in plan.guards:
                if digest(Path(guard['path']).read_bytes())!=guard['sha256']:
                    raise SwitchError('Application/source resources changed since preview; inspect again')
            for edit in plan.edits:
                validate_target(plan.app,edit.path,edit.kind)
                if edit.path.read_bytes()!=edit.before:
                    raise SwitchError(f'File changed since preview: {edit.path}')
            if plan.registry and self.registry.get(plan.registry['path'],plan.registry['name'])!=plan.registry['before']:
                raise SwitchError('Registry language changed since preview')
            stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:10]
            folder=self.root/stamp;folder.mkdir()
            app=plan.app
            document=dict(schema=1,id=stamp,identity=self.identity(),status='prepared',mode=plan.mode,target=plan.target,carrier=plan.carrier,
                          app=dict(root=str(app.root),product=app.product,exe=str(app.exe),resource_root=str(app.resource_root),version=app.version,locales=app.locales,installed_languages=app.installed_languages),
                          guards=plan.guards,registry=plan.registry,files=[],warnings=plan.warnings,runtime='Not tested; file verification is not startup verification')
            for i,edit in enumerate(plan.edits):
                backup=folder/f'{i}.before';modified=folder/f'{i}.after'
                backup.write_bytes(edit.before);modified.write_bytes(edit.after)
                if backup.read_bytes()!=edit.before or modified.read_bytes()!=edit.after:
                    raise SwitchError('Backup readback failed; target untouched')
                document['files'].append(dict(path=str(edit.path),kind=edit.kind,before=digest(edit.before),after=digest(edit.after),index=i))
            journal=folder/'transaction.json';save(journal,document)
            try:
                document['status']='applying';save(journal,document)
                self.closed(app.exe.name)
                for edit in plan.edits:
                    if edit.path.read_bytes()!=edit.before:
                        raise SwitchError('File drift during apply')
                    atomic_write(edit.path,edit.after)
                    if edit.path.read_bytes()!=edit.after:
                        raise SwitchError('Applied file verification failed')
                reg=plan.registry
                if reg:
                    if self.registry.get(reg['path'],reg['name'])!=reg['before']:
                        raise SwitchError('Registry drift during apply')
                    self.registry.set(reg['path'],reg['name'],reg['after'])
                    if self.registry.get(reg['path'],reg['name'])!=reg['after']:
                        raise SwitchError('Registry readback failed')
                for guard in plan.guards:
                    if digest(Path(guard['path']).read_bytes())!=guard['sha256']:
                        raise SwitchError('A protected application/source file changed during apply')
                document['status']='applied';save(journal,document)
            except Exception as exc:
                document['error']=str(exc)
                try:
                    self._restore(folder,document,app)
                    document['status']='failed_restored'
                except Exception as recovery:
                    document['status']='recovery_required';document['recovery_error']=str(recovery)
                save(journal,document)
                raise SwitchError(f'Apply failed; {document["status"]}; transaction {stamp}: {exc}') from exc
            return stamp

    def _load(self, transaction):
        if not transaction or Path(transaction).name!=transaction or '/' in transaction or '\\' in transaction:
            raise SwitchError('Use a transaction ID, not a path')
        folder=self.root/transaction
        if folder.resolve().parent!=self.root:
            raise SwitchError('Transaction path redirected')
        document=json.loads((folder/'transaction.json').read_text(encoding='utf-8'))
        if document.get('schema')!=1 or document.get('id')!=transaction or document.get('identity')!=self.identity():
            raise SwitchError('Transaction identity/schema mismatch; use the same Windows account')
        data=dict(document['app'])
        for key in ('root','exe','resource_root'):
            data[key]=Path(data[key])
        app=Installation(**data)
        if not app.exe.resolve().is_relative_to(app.root.resolve()) or not app.resource_root.resolve().is_relative_to(app.root.resolve()):
            raise SwitchError('Invalid application paths in transaction')
        return folder,document,app

    def rollback(self, transaction):
        with lock(self.root):
            folder,document,app=self._load(transaction)
            self.closed(app.exe.name)
            if document['status'] in ('restored','failed_restored'):
                return document['status']
            self._restore(folder,document,app)
            document['status']='restored';save(folder/'transaction.json',document)
            return 'restored'

    def _restore(self,folder,document,app):
        jobs=[]
        for number,entry in enumerate(document['files']):
            if entry['index']!=number:
                raise SwitchError('Invalid backup index')
            target=Path(entry['path']);validate_target(app,target,entry['kind'])
            original=(folder/f'{number}.before').read_bytes()
            modified=(folder/f'{number}.after').read_bytes()
            if digest(original)!=entry['before'] or digest(modified)!=entry['after']:
                raise SwitchError('Backup checksum mismatch; nothing restored')
            current=target.read_bytes();h=digest(current)
            if h==entry['before']:
                continue
            if h==entry['after']:
                restore=original
            elif entry['kind']=='preference' and preference(current)==preference(modified):
                restore=preference(current,preference(original))
            elif entry['kind']=='preference' and preference(current)==preference(original):
                continue
            else:
                raise SwitchError(f'Resource changed after switching (possibly an app update); preserved: {target}')
            jobs.append((target,current,restore))
        reg=document['registry']
        if reg:
            if app.product!='premiere' or reg['path']!=registry_path(app) or reg['name']!='Language':
                raise SwitchError('Invalid registry target')
            actual=self.registry.get(reg['path'],reg['name'])
            if actual not in (reg['before'],reg['after']):
                raise SwitchError('Language registry changed independently; preserved')
        for target,current,restore in jobs:
            if target.read_bytes()!=current:
                raise SwitchError('File drift during rollback')
            atomic_write(target,restore)
            if target.read_bytes()!=restore:
                raise SwitchError('Rollback file readback failed')
        if reg:
            self.registry.set(reg['path'],reg['name'],reg['before'])
            if self.registry.get(reg['path'],reg['name'])!=reg['before']:
                raise SwitchError('Rollback registry readback failed')
