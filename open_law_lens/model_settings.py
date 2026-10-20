"""OpenLawLens-owned presence-aware shared Agent selection. No app import."""
from ._model_store import serve
from ._model_schema import raw,triple,pi_values,slot,global_path

def resolve():
    from .paths import config_path,pi_settings_path
    paths={'config':config_path(),'pi':pi_settings_path(),'global-pi':global_path()}; data=raw(paths['config'])
    modern='agent_runtime_profile' in data
    value=triple(data.get('agent_runtime_profile')) if modern else triple((data.get('agent_runtime_profiles') or {}).get('law')) if isinstance(data.get('agent_runtime_profiles'),dict) else None
    if value: ident,thinking=value
    else:
        ident,thinking,_=pi_values(paths)
    def replace(raw,target):
        entry=dict(raw['agent_runtime_profile']) if modern and isinstance(raw.get('agent_runtime_profile'),dict) else {}
        entry.update(provider=target['provider'],model=target['model'],thinking=thinking)
        raw['agent_runtime_profile']=entry
    status='active' if modern and value else 'fallback' if value else 'inherited'
    return paths,[slot('shared-agent','config',ident,dict(requested=thinking),replace,status=status,creation=not(modern and value))]

def main(): return serve('open-law-lens',resolve)
