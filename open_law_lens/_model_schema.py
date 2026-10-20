"""Pure app-owned selection helpers. Never import GUI/backend/config loaders."""
from pathlib import Path
from decimal import Decimal
import os
from urllib.parse import urlsplit
from ._model_store import parse,snapshot,fail,identity,digest
LEVELS=('off','minimal','low','medium','high','xhigh','max')

def raw(path): return parse(snapshot(path)['bytes'])
def global_path():
    return Path(os.environ.get('PI_CODING_AGENT_DIR') or Path.home()/'.pi/agent')/'settings.json'

def pi_values(paths,role='pi',*,thinking_fallback=None,seed_if_missing=None,required=False):
    paths['global-pi']=global_path()
    current=snapshot(paths[role]); data=parse(current['bytes'])
    if required and current['revision']=='missing': fail('settings_missing')
    if current['revision']=='missing' and seed_if_missing is not None: data=dict(seed_if_missing)
    if any(key in data for key in ('defaultProvider','defaultModel')) and not all(isinstance(data.get(key),str) and data[key].strip() for key in ('defaultProvider','defaultModel')): fail('partial_effective_selection')
    # Do not guess SDK fallback semantics for malformed explicit controls.
    # Billing's documented falsey/missing-value default is selected explicitly.
    if 'defaultThinkingLevel' in data and thinking_fallback is None and (not isinstance(data['defaultThinkingLevel'],str) or not data['defaultThinkingLevel']): fail('invalid_reasoning')
    if not data.get('defaultProvider') or (not data.get('defaultThinkingLevel') and thinking_fallback is None):
        global_data=raw(paths['global-pi'])
    else: global_data={}
    provider=data.get('defaultProvider') or global_data.get('defaultProvider')
    model=data.get('defaultModel') or global_data.get('defaultModel')
    thinking=data.get('defaultThinkingLevel') or thinking_fallback or global_data.get('defaultThinkingLevel') or 'medium'
    if not isinstance(provider,str) or not isinstance(model,str) or not provider.strip() or not model.strip(): fail('missing_effective_model')
    provider,model=provider.strip(),model.strip()
    if thinking not in LEVELS: fail('invalid_reasoning')
    inherited=not (data.get('defaultProvider') and data.get('defaultModel'))
    return identity(dict(provider=provider,model=model)),thinking,inherited

def slot(id,role,ident,reasoning,replace,*,status='active',kind='embedded-pi',credential=None,image=False,creation=False,blocker=None):
    return dict(role=role,replace=replace,creation=creation,blocker=blocker,
        public=dict(slot_id=id,identity=identity(ident),status=status,workload_kind=kind,
            reasoning=reasoning,connection_kind='pi-managed' if kind=='embedded-pi' else 'chat-completions',
            credential_present=credential,compatibility_requirements=dict(image_input=image)))

def pi_slot(paths,role='pi',id='shared-pi',*,thinking_fallback=None,seed_if_missing=None,required=False):
    ident,thinking,inherited=pi_values(paths,role,thinking_fallback=thinking_fallback,seed_if_missing=seed_if_missing,required=required)
    missing=snapshot(paths[role])['revision']=='missing'
    def replace(data,target):
        if missing and seed_if_missing is not None: data.update(seed_if_missing)
        data.update(defaultProvider=target['provider'],defaultModel=target['model'])
    return slot(id,role,ident,dict(requested=thinking),replace,status='inherited' if inherited else 'active',creation=inherited)

def triple(value):
    if not isinstance(value,dict) or any(not isinstance(value.get(k),str) for k in ('provider','model','thinking')): return None
    p,m,t=value['provider'].strip(),value['model'].strip(),value['thinking'].strip().lower()
    return (identity(dict(provider=p,model=m)),t) if p and m and t in LEVELS else None

def boolean(value,default=False,*,number_values=False):
    if isinstance(value,bool): return value
    if isinstance(value,str):
        if value.strip().lower() in ('1','true','yes','on'): return True
        if value.strip().lower() in ('0','false','no','off'): return False
    if number_values and isinstance(value,(int,float,Decimal)): return bool(value)
    return default

def direct_slot(id,role,profile,replace,*,model_key='model_id',url_key='api_url',key_key='api_key',image=False,creation=False,local=False):
    model=profile.get(model_key); endpoint=profile.get(url_key)
    if model is None or isinstance(model,str) and not model.strip():
        return dict(role=role,inactive=True,public=dict(slot_id=id,status='unconfigured',reason='no_named_model_selection'))
    if not isinstance(model,str) or not model.strip() or not isinstance(endpoint,str) or not endpoint.strip(): fail('missing_direct_selection')
    try: url=urlsplit(endpoint.strip())
    except ValueError: fail('invalid_direct_connection')
    if url.username or url.password or url.query or url.fragment: fail('unresolved_direct_identity')
    canonical=(url.scheme=='https' and url.hostname=='api.fireworks.ai' and not url.username and not url.password and
               url.port in (None,443) and not url.query and not url.fragment and
               url.path.rstrip('/') in ('/inference/v1/chat/completions','/inference/v1'))
    provider='fireworks' if canonical else 'direct-'+digest((url.scheme+'://'+str(url.hostname)+str(url.port)+url.path).encode())[:16]
    credential=bool(isinstance(profile.get(key_key),str) and profile[key_key].strip())
    return slot(id,role,dict(provider=provider,model=model.strip()),
                dict(requested='disabled' if profile.get('disable_reasoning') else 'provider-default',
                     priority_service_tier=bool(profile.get('priority_service_tier',False))),replace,
                kind='direct-ai',credential=credential,image=image,creation=creation,
                blocker='incompatible_direct_transport' if not canonical else ('missing_direct_credential' if not credential and not local else None))
