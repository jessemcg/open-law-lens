"""OpenLawLens-owned presence-aware shared Agent selection. No app import."""
from ._model_store import serve, identity, fail
from ._model_schema import raw, triple, pi_values, slot, global_path, LEVELS


def resolve():
    from .paths import config_path, pi_settings_path
    paths = {'config': config_path(), 'pi': pi_settings_path(), 'global-pi': global_path()}
    data = raw(paths['config'])
    modern = 'agent_runtime_profile' in data
    entry = data.get('agent_runtime_profile') if modern else (
        (data.get('agent_runtime_profiles') or {}).get('law')
        if isinstance(data.get('agent_runtime_profiles'), dict) else None)
    value = triple(entry)
    # A new explicit model-only selection deliberately leaves effort inherited.
    pair = (modern and isinstance(entry, dict) and 'thinking' not in entry
            and all(isinstance(entry.get(k), str) and entry[k].strip() for k in ('provider', 'model')))
    if value:
        ident, thinking = value
    elif pair:
        ident = identity({k: entry[k].strip() for k in ('provider', 'model')})
        thinking = (raw(paths['pi']).get('defaultThinkingLevel')
                    or raw(paths['global-pi']).get('defaultThinkingLevel') or 'medium')
    else:
        ident, thinking, _ = pi_values(paths)

    if thinking not in LEVELS:
        fail('invalid_reasoning')

    def replace(raw, target):
        if modern and isinstance(entry, dict) and 'thinking' in entry and not value:
            fail('invalid_reasoning')
        updated = dict(raw['agent_runtime_profile']) if modern and isinstance(raw.get('agent_runtime_profile'), dict) else {}
        updated.update(provider=target['provider'], model=target['model'])
        if value:
            updated['thinking'] = value[1]  # Preserve a user's explicit existing effort.
        raw['agent_runtime_profile'] = updated

    selected = bool(value or pair)
    status = 'active' if modern and selected else 'fallback' if value else 'inherited'
    return paths, [slot('shared-agent', 'config', ident, dict(requested=thinking), replace,
                        status=status, creation=not (modern and selected))]


def main():
    return serve('open-law-lens', resolve)
