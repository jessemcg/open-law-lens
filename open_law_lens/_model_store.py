"""Application-owned, standard-library-only settings safety and protocol v1.
Vendored independently in each owner; no sibling runtime dependency. No discovery,
GUI, credentials, provider requests or migrations. Only explicit saves publish.
"""
from __future__ import annotations
import contextlib
import copy
import decimal
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import uuid

LIMIT = 1048576
class Failure(OSError):
    pass

def fail(code):
    raise Failure(code)

def digest(value):
    return hashlib.sha256(value).hexdigest()

def parse(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                fail('invalid_json')
            result[key] = value
        return result
    try:
        if len(data) > LIMIT:
            fail('settings_too_large')
        result = json.loads(data, object_pairs_hook=pairs, parse_float=decimal.Decimal,
                            parse_constant=lambda _: fail('invalid_json'))
        if not isinstance(result, dict):
            fail('invalid_json')
        return result
    except (ValueError, UnicodeError, RecursionError):
        fail('invalid_json')

def encode(value):
    def render(v, depth=0):
        if depth > 100:
            fail('invalid_json')
        if isinstance(v, dict):
            if any(not isinstance(k, str) for k in v): fail('invalid_json')
            return '{' + ','.join(json.dumps(k, ensure_ascii=True)+':'+render(x, depth+1) for k,x in sorted(v.items())) + '}'
        if isinstance(v, (list, tuple)):
            return '[' + ','.join(render(x, depth+1) for x in v) + ']'
        if isinstance(v, decimal.Decimal):
            if not v.is_finite(): fail('invalid_json')
            return str(v)
        return json.dumps(v, ensure_ascii=True, allow_nan=False)
    data = (render(value)+'\n').encode()
    if len(data) > LIMIT: fail('settings_too_large')
    return data

def directory(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts: fail('unsafe_settings_path')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in path.parts[1:]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd); fd = nxt
            m = os.fstat(fd)
            if m.st_uid not in (0, os.getuid()) or (m.st_mode & 0o002 and not m.st_mode & stat.S_ISVTX):
                fail('unsafe_settings_directory')
        return fd
    except BaseException:
        os.close(fd)
        raise

def private_dir(path):
    path = Path(path)
    if not path.is_absolute(): fail('unsafe_state_path')
    try:
        fd = directory(path)
    except FileNotFoundError:
        if not path.parent.exists(): private_dir(path.parent)
        parent = directory(path.parent)
        try:
            try: os.mkdir(path.name, 0o700, dir_fd=parent)
            except FileExistsError: pass
            os.fsync(parent)
        finally: os.close(parent)
        fd = directory(path)
    try:
        m = os.fstat(fd)
        if m.st_uid != os.getuid() or m.st_mode & 0o077: fail('unsafe_state_directory')
    finally: os.close(fd)

class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.fd = directory(self.path.parent)
        if os.fstat(self.fd).st_uid!=os.getuid():
            os.close(self.fd); self.fd=None; fail('unsafe_settings_directory')
    def close(self):
        if self.fd is not None: os.close(self.fd); self.fd = None
    def __enter__(self): return self
    def __exit__(self, *args): self.close()
    def check(self):
        fd = directory(self.path.parent)
        try:
            a,b=os.fstat(fd),os.fstat(self.fd)
            if (a.st_dev,a.st_ino)!=(b.st_dev,b.st_ino): fail('stale_settings')
        finally: os.close(fd)
        stem = self.path.stem.lower()
        for name in os.listdir(self.fd):
            if name.lower().startswith(stem) and any(x in name.lower() for x in ('conflicted copy','sync-conflict','sync_conflict')):
                fail('sync_conflict')
    def open(self, name, flags, mode=0o600):
        return os.open(name, flags | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, mode, dir_fd=self.fd)
    def read_fd(self, fd):
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or before.st_nlink != 1 or before.st_mode & 0o022:
            fail('unsafe_settings_file')
        if before.st_size > LIMIT: fail('settings_too_large')
        os.lseek(fd,0,0); data = b''
        while len(data) <= LIMIT:
            part = os.read(fd, min(65536, LIMIT+1-len(data)))
            if not part: break
            data += part
        after = os.fstat(fd)
        fields=lambda m:(m.st_dev,m.st_ino,m.st_size,m.st_mtime_ns)
        if fields(before)!=fields(after): fail('stale_settings')
        parse(data)
        revision=digest(encode({'bytes':digest(data),'stat':list(fields(after))}))
        return {'revision':revision,'bytes':data,'mode':after.st_mode}
    def read(self):
        self.check()
        fd = self.open(self.path.name, os.O_RDONLY)
        try: result = self.read_fd(fd)
        finally: os.close(fd)
        fd = self.open(self.path.name, os.O_RDONLY)
        try:
            if self.read_fd(fd)['revision'] != result['revision']: fail('stale_settings')
        finally: os.close(fd)
        return result
    @contextlib.contextmanager
    def lock(self):
        self.check()
        fd = self.open('.'+self.path.name+'.writer.lock', os.O_RDWR | os.O_CREAT)
        try:
            m=os.fstat(fd)
            if not stat.S_ISREG(m.st_mode) or m.st_uid!=os.getuid() or m.st_nlink!=1 or m.st_mode & 0o077: fail('unsafe_settings_lock')
            try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: fail('settings_busy')
            self.check()
            yield self
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN); os.close(fd)
    def revision(self):
        try: return self.read()['revision']
        except FileNotFoundError: return 'missing'
    def replace(self, expected, data, intent=lambda revision: None):
        parse(data); self.check()
        if self.revision()!=expected: fail('stale_settings')
        name='.'+self.path.name+'.'+uuid.uuid4().hex+'.tmp'
        fd=self.open(name,os.O_RDWR|os.O_CREAT|os.O_EXCL)
        try:
            view=memoryview(data)
            while view: view=view[os.write(fd,view):]
            os.fsync(fd)
            revision=self.read_fd(fd)['revision']
            intent(revision)
            if self.revision()!=expected: fail('stale_settings')
            os.rename(name,self.path.name,src_dir_fd=self.fd,dst_dir_fd=self.fd)
            os.fsync(self.fd)
            if self.read()['revision']!=revision: fail('settings_readback_failed')
            return revision
        finally:
            os.close(fd)
            try: os.unlink(name,dir_fd=self.fd)
            except FileNotFoundError: pass
    def create(self,data):
        parse(data); self.check()
        fd=self.open(self.path.name,os.O_WRONLY|os.O_CREAT|os.O_EXCL)
        try:
            view=memoryview(data)
            while view: view=view[os.write(fd,view):]
            os.fsync(fd); os.fsync(self.fd)
        finally: os.close(fd)
    def remove(self,expected,intent):
        if self.revision()!=expected: fail('rollback_conflict')
        intent('missing')
        if self.revision()!=expected: fail('rollback_conflict')
        os.unlink(self.path.name,dir_fd=self.fd); os.fsync(self.fd)

def snapshot(path):
    try:
        with Store(path) as store: return store.read()
    except FileNotFoundError: return {'revision':'missing','bytes':b'{}','mode':0}

def private_bytes(path):
    fd=directory(path.parent)
    try:
        m=os.fstat(fd)
        if m.st_uid!=os.getuid() or m.st_mode & 0o077: fail('unsafe_state_directory')
    finally: os.close(fd)
    with Store(path) as store: result=store.read()
    if result['mode'] & 0o077: fail('unsafe_state_file')
    return result['bytes']

def private_read(path):
    return parse(private_bytes(path))

def state_write(path,value,exclusive=False):
    private_dir(path.parent)
    with Store(path) as store:
        if exclusive: store.create(encode(value))
        else:
            with store.lock(): store.replace(store.revision(),encode(value))

class Tracked(dict): pass
_BASELINES={}
def capture_ordinary(path):
    snap=snapshot(path)
    _BASELINES.setdefault(str(Path(path)),snap['revision'])
    return snap

def read_ordinary(path):
    snap=capture_ordinary(path)
    if snap['revision']=='missing': raise FileNotFoundError(str(path))
    # Runtime consumers retain normal Python number types; publication below
    # independently preserves the original lexical numeric values.
    result=Tracked(json.loads(snap['bytes']))
    result.revision=snap['revision']; result.path=Path(path)
    return result

def preserve_numbers(old,new):
    if isinstance(old,dict) and isinstance(new,dict): return {k:preserve_numbers(old.get(k),v) for k,v in new.items()}
    if isinstance(old,list) and isinstance(new,list): return [preserve_numbers(old[i] if i<len(old) else None,v) for i,v in enumerate(new)]
    if isinstance(old,decimal.Decimal) and isinstance(new,float) and float(old)==new: return old
    return new

def save_ordinary(path,value,expected=None,backup_path=None):
    path=Path(path)
    # Ordinary explicit Settings may initialize its own absent parent. Never
    # use this helper from inventory/preview.
    if not path.parent.exists(): private_dir(path.parent)
    with Store(path) as store, store.lock():
        current=snapshot(path)
        baseline=expected or _BASELINES.get(str(path),getattr(value,'revision',current['revision']))
        if current['revision']!=baseline: fail('stale_settings: close and reopen the application before saving the retained draft')
        if backup_path is not None and current['revision']!='missing':
            with Store(backup_path) as backup, backup.lock():
                backup.replace(backup.revision(),current['bytes'])
        revision=store.replace(baseline,encode(preserve_numbers(parse(current['bytes']),value)))
        _BASELINES[str(path)]=revision
        return revision

def exact(value, keys):
    if not isinstance(value,dict) or set(value)!=set(keys): fail('invalid_arguments')

def identity(value):
    exact(value,('provider','model'))
    if (not isinstance(value['provider'],str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',value['provider']) or
        not isinstance(value['model'],str) or not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,512}',value['model'])): fail('invalid_arguments')
    return value

class Endpoint:
    def __init__(self, app, resolver):
        self.app,self.resolver=app,resolver
        self.state=Path(os.environ.get('XDG_STATE_HOME') or Path.home()/'.local/state')/app/'model-settings'
    def inspect(self):
        paths,slots=self.resolver()
        package=Path(self.resolver.__code__.co_filename).resolve().parent
        sources=[]; total=0
        for path in sorted(package.rglob('*.py')):
            if path.is_symlink(): fail('unsafe_adapter_source')
            data=path.read_bytes(); total+=len(data)
            if total>52428800: fail('adapter_source_too_large')
            sources.append((path.relative_to(package).as_posix(),digest(data)))
        deps={'adapter':digest(encode(sources))}
        for role,path in paths.items():
            deps[role]=snapshot(path)['revision']
            deps['path-'+role]=digest(str(path).encode())
        return paths,slots,deps
    def plan_dir(self,id):
        if not isinstance(id,str) or not re.fullmatch('[0-9a-f]{32}',id): fail('invalid_arguments')
        return self.state/id
    def load(self,id,binding):
        directory=self.plan_dir(id); plan=private_read(directory/'plan.json')
        if digest(encode(plan))!=binding or plan.get('app_id')!=self.app or plan.get('plan_id')!=id: fail('plan_mismatch')
        return directory,plan
    def execute(self,op,args):
        if op in ('apply','rollback','operation-status','reconcile','retain'):
            private_dir(self.state)
            lockpath=self.state.parent/'.model-settings-maintenance.json'
            with Store(lockpath) as store:
                try: store.create(b'{}\n')
                except FileExistsError: pass
                with store.lock(): return self._execute(op,args)
        return self._execute(op,args)
    def _execute(self,op,args):
        if op=='capabilities':
            exact(args,())
            return dict(app_id=self.app,protocol_versions=[1],operations=['capabilities','inspect','preview','apply','operation-status','rollback','reconcile','retain'],target_providers=['fireworks'],storage='application-owned')
        if op=='inspect':
            exact(args,()); paths,slots,deps=self.inspect()
            return dict(app_id=self.app,revision=digest(encode(deps)),dependencies=deps,slots=[s['public'] for s in slots if not s.get('inactive')],inactive_slots=[s['public'] for s in slots if s.get('inactive')])
        if op=='preview':
            exact(args,('source','target')); source=identity(args['source']); target=identity(args['target'])
            if source==target: fail('same_model')
            if target['provider']!='fireworks' or not re.fullmatch(r'accounts/fireworks/models/[A-Za-z0-9_.-]{1,200}',target['model']): fail('unsupported_target')
            paths,slots,deps=self.inspect(); changes=[]
            for slot in slots:
                if slot['public'].get('identity')==source:
                    if slot.get('blocker'): fail(slot['blocker'])
                    changes.append(dict(slot_id=slot['public']['slot_id'],old=source,new=target,
                                        reasoning=slot['public']['reasoning'],creation=slot.get('creation',False)))
            if not changes: fail('no_matching_slots')
            id=uuid.uuid4().hex
            plan=dict(version=1,app_id=self.app,plan_id=id,source=source,target=target,dependencies=deps,changes=changes)
            private_dir(self.state)
            for other in self.state.iterdir():
                if other.is_symlink(): fail('unsafe_state_path')
            state_write(self.plan_dir(id)/'plan.json',plan,True)
            return dict(app_id=self.app,plan_id=id,plan_binding=digest(encode(plan)),baseline_revision=digest(encode(deps)),dependencies=deps,changes=changes,
                        compatibility=dict(catalog_revalidation_required=True,effective_effort_validation_required=True,live_provider_verified=False))
        if op not in ('apply','operation-status','rollback','reconcile','retain'): fail('invalid_operation')
        exact(args,('plan_id','plan_binding','expected_revision') if op=='apply' else ('operation_id','plan_binding','expected_revision') if op=='retain' else ('operation_id','plan_binding'))
        id=args.get('plan_id',args.get('operation_id')); directory,plan=self.load(id,args['plan_binding'])
        receipt_path=directory/'receipt.json'
        receipt=private_read(receipt_path) if receipt_path.exists() or receipt_path.is_symlink() else None
        if receipt is not None and not receipt: fail('invalid_receipt')
        paths,slots,deps=self.inspect()
        if any(deps.get(k)!=v for k,v in plan['dependencies'].items() if k.startswith('path-')): fail('stale_dependencies')
        expected_roles={slot['role'] for slot in slots if slot['public']['slot_id'] in {change['slot_id'] for change in plan['changes']}}
        if receipt and (receipt.get('plan_binding')!=args['plan_binding'] or receipt.get('state') not in ('intent','rollback-intent','applied','restored','retained') or not isinstance(receipt.get('files'),dict) or not receipt['files'] or set(receipt['files'])!=expected_roles or set(receipt['files'])-set(paths)): fail('invalid_receipt')
        def status(no_op=False):
            if not receipt: return dict(status='not_started',current_revision=digest(encode(deps)),current_matches_baseline=deps==plan['dependencies'])
            if not isinstance(receipt.get('files'),dict) or not receipt['files'] or set(receipt['files'])-set(paths): fail('invalid_receipt')
            states={}; observed_deps=dict(deps)
            for role,data in receipt['files'].items():
                current=snapshot(paths[role])['revision']; observed_deps[role]=current
                states[role]=('retained' if receipt['state']=='retained' and current==data.get('retained') else 'restored' if current==data.get('restored') else 'published' if current==data.get('published') else 'baseline' if current==data['before'] else 'conflict')
            terminal=receipt['state'] if receipt['state'] in ('applied','restored','retained') else ('applied' if states and all(s=='published' for s in states.values()) else 'restored' if states and all(s=='restored' for s in states.values()) else 'not_published_needs_reconciliation' if receipt['state']=='intent' and all(s=='baseline' for s in states.values()) else 'recovery_required')
            matches=all(s==('retained' if terminal=='retained' else 'restored' if terminal=='restored' else 'published') for s in states.values())
            return dict(status=terminal,current_revision=digest(encode(observed_deps)),reconciled=terminal!=receipt['state'],
                        no_op=no_op,current_matches_operation=matches,files=states)
        if op=='operation-status': return status()
        if op=='retain':
            if not receipt: fail('operation_not_found')
            # Explicit native-reviewed acknowledgment of the current valid
            # settings, including partial publication or later edits. This
            # changes receipts ONLY, never configuration or rollback authority.
            with contextlib.ExitStack() as stack:
                stores={}
                for role in sorted(receipt['files']):
                    store=stack.enter_context(Store(paths[role]));stack.enter_context(store.lock());stores[role]=store
                paths,_,deps=self.inspect()
                if status()['current_revision']!=args['expected_revision']: fail('stale_settings')
                receipt.setdefault('retained_from',receipt['state'])
                for role,store in stores.items(): receipt['files'][role]['retained']=store.revision()
                receipt['state']='retained';state_write(receipt_path,receipt)
                return status(True)
        if op=='reconcile':
            if not receipt: return status(True)
            # Receipt-only recovery under every ordinary writer lock. Never
            # resend Apply or publish config to resolve a lost acknowledgment.
            with contextlib.ExitStack() as stack:
                for role in sorted(receipt['files']):
                    store=stack.enter_context(Store(paths[role])); stack.enter_context(store.lock())
                observed=status(True)
                if observed['status'] in ('applied','restored') and observed['current_matches_operation']:
                    receipt['state']=observed['status']
                elif receipt['state']=='intent' and all(s=='baseline' for s in observed['files'].values()):
                    for data in receipt['files'].values(): data['restored']=data['before']
                    receipt['state']='restored'
                else: fail('recovery_required')
                state_write(receipt_path,receipt)
                return status(True)
        if op=='apply' and receipt:
            observed=status(True)
            if observed['status'] in ('applied','restored'):
                if observed['reconciled']:
                    receipt['state']=observed['status']; state_write(receipt_path,receipt)
                return observed
            fail('recovery_required')
        if op=='rollback' and (not receipt or receipt['state']=='restored'): return status(True)
        if op=='apply':
            if args['expected_revision']!=digest(encode(plan['dependencies'])): fail('plan_mismatch')
            if deps!=plan['dependencies']: fail('stale_settings')
            for index,entry in enumerate(self.state.iterdir()):
                if index>=1000: fail('recovery_inventory_too_large')
                if entry.is_symlink() or not re.fullmatch('[0-9a-f]{32}',entry.name): fail('unsafe_state_path')
                if entry.name!=id and (entry/'receipt.json').exists():
                    old=private_read(entry/'receipt.json')
                    if old.get('state') not in ('applied','restored','retained'): fail('recovery_required')
        # Resolve again under every participating ordinary-writer lock. The
        # application, never stdin, owns role-to-path and model-only mutation.
        selected=[s for s in slots if s['public'].get('identity')==plan['source']]
        roles=sorted({s['role'] for s in selected} if op=='apply' else receipt['files'])
        with contextlib.ExitStack() as stack:
            stores={}
            for role in roles:
                if op=='apply' and not paths[role].parent.exists(): private_dir(paths[role].parent)
                store=stack.enter_context(Store(paths[role])); stack.enter_context(store.lock()); stores[role]=store
            if op=='apply':
                _,fresh,newdeps=self.inspect()
                if newdeps!=plan['dependencies']: fail('stale_settings')
                selected=[s for s in fresh if s['public'].get('identity')==plan['source']]
                receipt=dict(plan_binding=args['plan_binding'],state='intent',files={})
                candidates={}
                for role in roles:
                    before=snapshot(paths[role]); raw=parse(before['bytes']); candidates[role]=raw
                    backup_path=directory/(role+'-before.json')
                    if backup_path.exists():
                        if private_bytes(backup_path)!=before['bytes']: fail('recovery_required')
                    else:
                        with Store(backup_path) as backup: backup.create(before['bytes'])
                    receipt['files'][role]=dict(before=before['revision'],existed=before['revision']!='missing',before_digest=digest(before['bytes']))
                for slot in selected: slot['replace'](candidates[slot['role']],plan['target'])
                state_write(receipt_path,receipt,True)
                for role in roles:
                    def intent(revision,role=role):
                        receipt['files'][role]['published']=revision; state_write(receipt_path,receipt)
                    stores[role].replace(receipt['files'][role]['before'],encode(candidates[role]),intent)
                receipt['state']='applied'; state_write(receipt_path,receipt)
            else:
                # Original inherited/fallback selections may depend on files
                # no longer consulted after publication. Keep their revisions
                # guarded too; never restore into changed dependency semantics.
                if any(deps.get(role)!=plan['dependencies'].get(role) for role in paths if role not in receipt['files']): fail('rollback_conflict')
                for role in roles:
                    data=receipt['files'][role]; current=stores[role].revision()
                    allowed={data.get('published')}
                    if receipt['state']=='intent' or (receipt['state']=='retained' and data.get('retained')==data['before']): allowed.add(data['before'])
                    if receipt['state'] in ('rollback-intent','restored') or (receipt['state']=='retained' and data.get('retained')==data.get('restored')): allowed.add(data.get('restored'))
                    if current not in allowed: fail('rollback_conflict')
                for role in roles:
                    data=receipt['files'][role]; current=stores[role].revision()
                    if current in (data['before'],data.get('restored')):
                        data['restored']=current; continue
                    original=private_bytes(directory/(role+'-before.json'))
                    if digest(original)!=data['before_digest']: fail('invalid_backup')
                    def intent(revision,role=role):
                        receipt['state']='rollback-intent'; receipt['files'][role]['restored']=revision; state_write(receipt_path,receipt)
                    if data['existed']: stores[role].replace(current,original,intent)
                    else: stores[role].remove(current,intent)
                receipt['state']='restored'; state_write(receipt_path,receipt)
            return status()

def serve(app,resolver,argv=None):
    request_id=None
    try:
        if (sys.argv[1:] if argv is None else argv)!=['model-settings','--stdin']: fail('invalid_arguments')
        data=sys.stdin.buffer.read(65537)
        if len(data)>65536: fail('request_too_large')
        request=parse(data); exact(request,('version','request_id','operation','arguments'))
        if type(request['version']) is not int or request['version']!=1 or not isinstance(request['request_id'],str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}',request['request_id']): fail('invalid_request')
        request_id=request['request_id']
        result=Endpoint(app,resolver).execute(request['operation'],request['arguments'])
        response=dict(version=1,request_id=request_id,ok=True,result=result); code=0
    except Exception as exc:
        value=str(exc) if isinstance(exc,Failure) else 'operation_failed'
        code=2 if value in ('invalid_arguments','invalid_request','invalid_json','request_too_large','invalid_operation') else 1
        response=dict(version=1,request_id=request_id,ok=False,error=dict(code=value,message='Model settings request failed; raw settings are not included.'))
    try:
        try: output=encode(response)
        except Exception:
            output=encode(dict(version=1,request_id=request_id,ok=False,error=dict(code='response_too_large',message='Response exceeds protocol budget.'))); code=1
        sys.stdout.buffer.write(output); sys.stdout.buffer.flush()
    except Exception: return 1
    return code
