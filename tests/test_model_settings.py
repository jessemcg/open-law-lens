"""Actual import-light CLI and storage acceptance; disposable source/HOME only.
This identical contract suite is vendored in each Python application's tests.
"""
import copy
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

OWNERS={'Focus':'focus','BillingHelper':'billing_helper','OpenLawLens':'open_law_lens','Prose':'prose','EmailAgent':'email_agent','RecordPrep':'recordprep','OmniVoice':'omnivoice_app'}
OLD=dict(provider='fireworks',model='accounts/fireworks/models/fixture-old-001')
NEW=dict(provider='fireworks',model='accounts/fireworks/models/fixture-new-002')
SECRET='SYNTHETIC-SECRET-NEVER-IN-PROJECTION'

class Contract(unittest.TestCase):
    def setUp(self):
        self.source=Path(__file__).resolve().parents[1]
        self.package=OWNERS[self.source.name]
        self.temp=tempfile.TemporaryDirectory(prefix='model-settings-contract-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); pkg=self.root/self.package; pkg.mkdir(mode=0o700)
        for path in (self.source/self.package).glob('*.py'): shutil.copyfile(path,pkg/path.name)
        self.env=dict(os.environ)
        for key in ('FOCUS_CONFIG_DIR','OPEN_LAW_LENS_CONFIG','OPEN_LAW_LENS_STORAGE','RECORDPREP_CONFIG_DIR','RECORDPREP_PI_PROJECT_DIR','PYTHONPATH','PYTHONHOME'):
            self.env.pop(key,None)
        self.env.update(HOME=str(self.root/'home'),XDG_STATE_HOME=str(self.root/'state'),XDG_CONFIG_HOME=str(self.root/'xdg-config'),PI_CODING_AGENT_DIR=str(self.root/'global-pi'),PYTHONDONTWRITEBYTECODE='1')
        pi=dict(defaultProvider=OLD['provider'],defaultModel=OLD['model'],defaultThinkingLevel='high',unrelated={'secret':SECRET})
        profile=dict(name='Fixture',api_url='https://api.fireworks.ai/inference/v1/chat/completions',api_key=SECRET,model_id=OLD['model'],disable_reasoning=False,priority_service_tier=False,unknown={'keep':SECRET})
        triple=dict(provider=OLD['provider'],model=OLD['model'],thinking='high')
        config=dict(pi,agent_runtime_profile=triple,agent_runtime_profiles={'law':dict(provider='fixture-dormant',model='inactive',thinking='low')},
            agent_model_settings=dict(schema_version=1,model_mode='explicit',provider=OLD['provider'],model=OLD['model'],document='high',other='low'),
            model_profiles=[copy.deepcopy(profile),copy.deepcopy(profile),dict(model_id='inactive',api_key=SECRET)],
            draft_ai=dict(model_profiles=[copy.deepcopy(profile),copy.deepcopy(profile),dict(model_id='inactive',api_key=SECRET)],unknown=SECRET),
            classifier_api_url=profile['api_url'],classifier_api_key=SECRET,classifier_model_id=OLD['model'],classifier_disable_reasoning=False,
            classifier_thinking_enabled=False,llm_plain_api_url=profile['api_url'],llm_plain_api_key=SECRET,llm_plain_model=OLD['model'],llm_plain_disable_reasoning=False,
            llm_remove_cites_model='inactive',local_ocr_model='inactive',prompt=SECRET)
        self.config=self.root/'config.json'; self.pi=self.root/'.pi/settings.json'
        self.put(self.config,config); self.put(self.pi,pi); self.put(self.root/'global-pi/settings.json',pi)
        # Precision, large integers and serde's literal reserved names survive.
        for path in (self.config,self.pi):
            data=path.read_bytes().rstrip(); path.write_bytes(data[:-1]+b',"precise":1.234567890123456789001,"huge":987654321098765432109876543210987654321,"$serde_json::private::Number":{"keep":true}}\n')
        self.original={p:p.read_bytes() for p in (self.config,self.pi)}
    def put(self,path,data):
        path.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
        path.write_text(json.dumps(data)); path.chmod(0o600)
    def call(self,op,args=None,raw=None,ok=True):
        request=json.dumps(dict(version=1,request_id='fixture',operation=op,arguments=args or {})).encode() if raw is None else raw
        child=subprocess.run([sys.executable,'-S','-m',self.package,'model-settings','--stdin'],input=request,cwd=self.root,env=self.env,capture_output=True,timeout=10)
        self.assertEqual(child.stderr,b'')
        self.assertLessEqual(len(child.stdout),1048576)
        self.assertNotIn(SECRET.encode(),child.stdout)
        response=json.loads(child.stdout)
        self.assertEqual(response['ok'],ok,response)
        self.assertEqual(child.returncode==0,ok,response)
        return response.get('result') if ok else response['error']['code']
    def preview(self): return self.call('preview',dict(source=OLD,target=NEW))
    def apply(self,plan,ok=True):
        return self.call('apply',dict(plan_id=plan['plan_id'],plan_binding=plan['plan_binding'],expected_revision=plan['baseline_revision']),ok=ok)
    def recovery(self,plan,op='rollback',ok=True):
        return self.call(op,dict(operation_id=plan['plan_id'],plan_binding=plan['plan_binding']),ok=ok)
    def clear_named_direct_selections(self,data):
        if self.package=='email_agent': data['draft_ai']['model_profiles']=[]
        elif self.package=='prose': data['model_profiles']=[{}]
        elif self.package=='recordprep': data['classifier_model_id']=''
        elif self.package=='omnivoice_app': data['llm_plain_model']=''
        else: self.skipTest('owner has no covered direct-client slot')
    def test_empty_named_direct_slots_are_assessed_without_a_guessed_identity(self):
        data=json.loads(self.config.read_bytes());self.clear_named_direct_selections(data);self.put(self.config,data)
        before=self.config.read_bytes();result=self.call('inspect')
        self.assertFalse(any(s['workload_kind']=='direct-ai' for s in result['slots']))
        self.assertEqual(len(result['inactive_slots']),2 if self.package in ('email_agent','prose') else 1)
        for s in result['inactive_slots']:
            self.assertEqual(s['reason'],'no_named_model_selection');self.assertNotIn('identity',s)
        self.assertEqual(self.config.read_bytes(),before)
    def test_false_string_controls_match_the_owners_supported_normalization(self):
        data=json.loads(self.config.read_bytes())
        if self.package=='email_agent': profiles=data['draft_ai']['model_profiles'][:2]
        elif self.package=='prose': profiles=data['model_profiles'][:2]
        elif self.package=='recordprep': data['classifier_disable_reasoning']='false';profiles=[]
        else: self.skipTest('owner does not use this native boolean normalization')
        for profile in profiles: profile.update(disable_reasoning='false',priority_service_tier='false')
        self.put(self.config,data)
        direct=[s for s in self.call('inspect')['slots'] if s['workload_kind']=='direct-ai'];self.assertTrue(direct)
        for s in direct:
            self.assertEqual(s['reasoning']['requested'],'provider-default');self.assertFalse(s['reasoning']['priority_service_tier'])
    def test_retaining_a_later_cleared_model_is_receipt_only_and_not_restore_authority(self):
        if self.package not in ('email_agent','prose','recordprep','omnivoice_app'): self.skipTest('no covered direct slot')
        self.install_fault_fixture();plan=self.preview();self.crash(plan,'after-all')
        data=json.loads(self.config.read_bytes());self.clear_named_direct_selections(data);self.put(self.config,data)
        before={p:p.read_bytes() for p in self.original};status=self.recovery(plan,'operation-status')
        self.assertEqual(status['status'],'recovery_required')
        kept=self.call('retain',dict(operation_id=plan['plan_id'],plan_binding=plan['plan_binding'],expected_revision=status['current_revision']))
        self.assertEqual(kept['status'],'retained');self.assertEqual(self.recovery(plan,ok=False),'rollback_conflict')
        for p,original in before.items(): self.assertEqual(p.read_bytes(),original)
    def test_capabilities_inspect_and_preview_are_settings_read_only(self):
        self.call('capabilities'); result=self.call('inspect')
        self.assertTrue(result['slots'])
        for s in result['slots']: self.assertEqual(s['identity'],OLD)
        self.preview()
        for p,data in self.original.items(): self.assertEqual(p.read_bytes(),data)
        self.assertFalse(list((self.root/'state').rglob('*-before.json')))
    def test_apply_readback_idempotency_and_guarded_rollback(self):
        plan=self.preview(); result=self.apply(plan)
        self.assertEqual(result['status'],'applied'); self.assertTrue(result['current_matches_operation'])
        for s in self.call('inspect')['slots']: self.assertEqual(s['identity'],NEW)
        saved={p:p.read_bytes() for p in self.original}
        self.assertTrue(self.apply(plan)['no_op'])
        for p,data in saved.items(): self.assertEqual(p.read_bytes(),data)
        for p in self.original:
            after=json.loads(p.read_bytes()); before=json.loads(self.original[p])
            self.assertEqual(after['unrelated'] if 'unrelated' in after else after.get('prompt'),before['unrelated'] if 'unrelated' in before else before.get('prompt'))
            self.assertIn(b'1.234567890123456789001',p.read_bytes())
        self.assertEqual(self.recovery(plan)['status'],'restored')
        for p,data in self.original.items(): self.assertEqual(p.read_bytes(),data)
    def test_later_edits_block_rollback(self):
        plan=self.preview(); self.apply(plan)
        changed=[p for p in self.original if p.read_bytes()!=self.original[p]]
        self.assertTrue(changed)
        p=changed[0]; p.write_bytes(p.read_bytes()+b' ')
        before={p:p.read_bytes() for p in self.original}
        self.assertEqual(self.recovery(plan,ok=False),'rollback_conflict')
        for p,data in before.items(): self.assertEqual(p.read_bytes(),data)
    def test_stale_preview_never_saves(self):
        plan=self.preview()
        for p in self.original: p.write_bytes(p.read_bytes()+b' ')
        before={p:p.read_bytes() for p in self.original}
        self.assertEqual(self.apply(plan,ok=False),'stale_settings')
        for p,data in before.items(): self.assertEqual(p.read_bytes(),data)
    def test_strict_duplicate_unknown_and_oversized_input(self):
        self.call('ignored',raw=b'{"version":1,"version":1}',ok=False)
        self.call('inspect',dict(approval=True),ok=False)
        self.call('ignored',raw=b' '*65537,ok=False)
        self.call('ignored',raw=b'{}\n{}',ok=False)
    def test_binding_cannot_authorize_changed_target(self):
        plan=self.preview(); plan['plan_binding']='0'*64
        self.assertEqual(self.apply(plan,ok=False),'plan_mismatch')
        for p,data in self.original.items(): self.assertEqual(p.read_bytes(),data)
    def test_unsafe_symlink_is_not_followed_or_repaired(self):
        target=self.pi if self.package in ('focus','billing_helper') else self.config
        actual=target.with_name('actual.json'); target.rename(actual); target.symlink_to(actual.name)
        self.call('inspect',ok=False)
        self.assertTrue(target.is_symlink()); self.assertEqual(actual.read_bytes(),self.original[target])
    def test_private_plans_backups_and_receipts(self):
        plan=self.preview(); self.apply(plan)
        for p in (self.root/'state').rglob('*'):
            self.assertEqual(stat.S_IMODE(p.stat().st_mode),0o700 if p.is_dir() else 0o600)

    def install_fault_fixture(self):
        # Faults exist ONLY in this disposable source, before binding a plan.
        # Normal maintained adapters have no crash flags or injected hooks.
        path=self.root/self.package/'_model_store.py'
        path.write_text(path.read_text()+'''
_fixture_publish=Store.replace
_fixture_count=0
def _fixture_replace(self,expected,data,intent=lambda revision:None):
    global _fixture_count
    phase=os.environ.get('WORKHORSE_SYNTHETIC_CRASH','')
    config=Path(__file__).resolve().parents[1]
    active=self.path in (config/'config.json',config/'.pi/settings.json')
    if phase=='before' and active:
        def cut(revision):
            intent(revision)
            os._exit(75)
        return _fixture_publish(self,expected,data,cut)
    result=_fixture_publish(self,expected,data,intent)
    if phase and active:
        _fixture_count+=1
        receipts=list(Path(os.environ['XDG_STATE_HOME']).rglob('receipt.json'))
        roles=len(json.loads(receipts[0].read_bytes())['files'])
        if (phase=='after-first' and _fixture_count==1) or (phase=='after-all' and _fixture_count==roles): os._exit(75)
    return result
Store.replace=_fixture_replace
''')
    def crash(self,plan,phase,op='apply'):
        args=(dict(plan_id=plan['plan_id'],plan_binding=plan['plan_binding'],expected_revision=plan['baseline_revision']) if op=='apply' else dict(operation_id=plan['plan_id'],plan_binding=plan['plan_binding']))
        env=dict(self.env,WORKHORSE_SYNTHETIC_CRASH=phase)
        child=subprocess.run([sys.executable,'-S','-m',self.package,'model-settings','--stdin'],input=json.dumps(dict(version=1,request_id='crash',operation=op,arguments=args)).encode(),cwd=self.root,env=env,capture_output=True,timeout=10)
        self.assertEqual((child.returncode,child.stdout,child.stderr),(75,b'',b''))
    def test_intent_before_publication_reconciles_without_settings_writes(self):
        self.install_fault_fixture();plan=self.preview();self.crash(plan,'before')
        self.assertEqual(self.recovery(plan,'operation-status')['status'],'not_published_needs_reconciliation')
        before={p:p.read_bytes() for p in self.original}
        self.assertEqual(self.recovery(plan,'reconcile')['status'],'restored')
        for p,data in before.items(): self.assertEqual(p.read_bytes(),data)
        self.apply(self.preview()) # an acknowledged intent cannot wedge future work
    def test_published_lost_ack_is_receipt_only_reconciled(self):
        self.install_fault_fixture();plan=self.preview();self.crash(plan,'after-all')
        self.assertEqual(self.recovery(plan,'operation-status')['status'],'applied')
        before={p:p.read_bytes() for p in self.original}
        self.assertEqual(self.recovery(plan,'reconcile')['status'],'applied')
        for p,data in before.items(): self.assertEqual(p.read_bytes(),data)
        next_plan=self.call('preview',dict(source=NEW,target=OLD));self.apply(next_plan)
    def test_restored_lost_ack_is_receipt_only_reconciled(self):
        self.install_fault_fixture();plan=self.preview();self.apply(plan);self.crash(plan,'after-all','rollback')
        before={p:p.read_bytes() for p in self.original}
        self.assertEqual(self.recovery(plan,'reconcile')['status'],'restored')
        for p,data in self.original.items(): self.assertEqual(p.read_bytes(),data)
        for p,data in before.items(): self.assertEqual(p.read_bytes(),data)
    def test_multirole_partial_publication_restores_or_can_be_kept_explicitly(self):
        if self.package!='recordprep': self.skipTest('only RecordPrep publishes two independent settings roles')
        self.install_fault_fixture();plan=self.preview();self.crash(plan,'after-first')
        self.assertEqual(self.recovery(plan,'operation-status')['status'],'recovery_required')
        self.assertEqual(self.recovery(plan,'reconcile',ok=False),'recovery_required')
        self.assertEqual(self.recovery(plan)['status'],'restored')
        for p,data in self.original.items(): self.assertEqual(p.read_bytes(),data)
    def test_uncertain_later_edits_can_be_acknowledged_but_never_rolled_back(self):
        self.install_fault_fixture();plan=self.preview();self.crash(plan,'after-all')
        p=self.pi if self.package in ('focus','billing_helper') else self.config
        p.write_bytes(p.read_bytes()+b' ')
        current=self.recovery(plan,'operation-status');self.assertEqual(current['status'],'recovery_required')
        args=dict(operation_id=plan['plan_id'],plan_binding=plan['plan_binding'],expected_revision=current['current_revision'])
        before={p:p.read_bytes() for p in self.original}
        self.assertEqual(self.call('retain',args)['status'],'retained')
        for p,data in before.items(): self.assertEqual(p.read_bytes(),data)
        self.assertEqual(self.recovery(plan,ok=False),'rollback_conflict')
        next_plan=self.call('preview',dict(source=NEW,target=OLD));self.apply(next_plan)
    def test_retention_requires_exact_current_review_revision(self):
        plan=self.preview();self.apply(plan)
        current=self.recovery(plan,'operation-status');p=self.pi if self.package in ('focus','billing_helper') else self.config;p.write_bytes(p.read_bytes()+b' ')
        self.assertEqual(self.call('retain',dict(operation_id=plan['plan_id'],plan_binding=plan['plan_binding'],expected_revision=current['current_revision']),ok=False),'stale_settings')
    def test_empty_or_wrong_role_receipts_are_not_unstarted_operations(self):
        plan=self.preview();path=next((self.root/'state').rglob('plan.json')).parent/'receipt.json'
        self.put(path,{})
        self.assertEqual(self.recovery(plan,'operation-status',ok=False),'invalid_receipt')
        self.put(path,dict(plan_binding=plan['plan_binding'],state='intent',files={'global-pi':dict(before='missing')}))
        self.assertEqual(self.recovery(plan,'operation-status',ok=False),'invalid_receipt')
    def test_supported_inherited_or_legacy_selection_round_trips(self):
        if self.package in ('focus','billing_helper','email_agent'):
            path=self.pi if self.package!='email_agent' else self.config;data=json.loads(path.read_bytes());data.pop('defaultProvider');data.pop('defaultModel');self.put(path,data)
        elif self.package=='open_law_lens':
            path=self.config;data=json.loads(path.read_bytes());data.pop('agent_runtime_profile');data['agent_runtime_profiles']['law']=dict(provider=OLD['provider'],model=OLD['model'],thinking='high');self.put(path,data)
        elif self.package=='prose':
            path=self.config;data=json.loads(path.read_bytes());data['agent_model_settings'].update(model_mode='pi-default',document='inherit');self.put(path,data)
        else: self.skipTest('this owner has no supported inherited model slot')
        before={p:p.read_bytes() for p in self.original};global_before=(self.root/'global-pi/settings.json').read_bytes()
        plan=self.preview();self.apply(plan);self.assertEqual(self.recovery(plan,'operation-status')['status'],'applied');self.recovery(plan)
        for p,data in before.items(): self.assertEqual(p.read_bytes(),data)
        self.assertEqual((self.root/'global-pi/settings.json').read_bytes(),global_before)
    def test_focus_missing_pi_parent_is_read_only_until_explicit_apply(self):
        if self.package!='focus': self.skipTest('Focus owns its low-effort first-load seeding policy')
        shutil.rmtree(self.pi.parent);self.call('inspect');plan=self.preview();self.assertFalse(self.pi.parent.exists())
        self.apply(plan);saved=json.loads(self.pi.read_bytes());self.assertEqual(saved['defaultThinkingLevel'],'low');self.recovery(plan);self.assertFalse(self.pi.exists())
    def test_billing_uses_native_medium_not_global_effort_fallback(self):
        if self.package!='billing_helper': self.skipTest('BillingHelper owns this fixed native default')
        data=json.loads(self.pi.read_bytes());data.pop('defaultThinkingLevel');self.put(self.pi,data)
        self.assertEqual(self.call('inspect')['slots'][0]['reasoning']['requested'],'medium')
    def test_ordinary_draft_survives_concurrent_headless_apply(self):
        path=self.pi if self.package in ('focus','billing_helper') else self.config
        script=f'''from pathlib import Path
from {self.package}._model_store import read_ordinary,save_ordinary,Failure
import json,sys
path=Path(sys.argv[1]);draft=read_ordinary(path);draft['synthetic_draft']='retained'
print('ready',flush=True);sys.stdin.readline()
try: save_ordinary(path,draft)
except Failure as exc: print(json.dumps(dict(code=str(exc),draft=draft['synthetic_draft'])),flush=True)
else: raise AssertionError('stale ordinary save was accepted')
'''
        child=subprocess.Popen([sys.executable,'-S','-c',script,str(path)],cwd=self.root,env=self.env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        self.addCleanup(lambda:child.kill() if child.poll() is None else None)
        self.assertEqual(child.stdout.readline(),b'ready\n');self.apply(self.preview());before=path.read_bytes()
        out,err=child.communicate(b'continue\n',timeout=10);self.assertEqual((child.returncode,err),(0,b''));result=json.loads(out)
        self.assertTrue(result['code'].startswith('stale_settings'));self.assertEqual(result['draft'],'retained');self.assertEqual(path.read_bytes(),before)

if __name__=='__main__': unittest.main()
