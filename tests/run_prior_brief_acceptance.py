"""Opt-in paid synthetic paired acceptance. Run from an isolated project copy.

Usage: uv run --no-sync python tests/run_prior_brief_acceptance.py OUTPUT_DIRECTORY
Uses the reviewed Fireworks DeepSeek V4.1 Flash/high profile, never changes it.
All corpus/config/cache/state is synthetic and temporary; no real archive input.
Uses existing Pi auth; this is not a security sandbox for arbitrary shell tools.
The completed-run cost gate is not an in-flight spending cap. Each run has a
240-second timeout. Raw events and metrics require manual source-reading and
answer-quality review. Discovery counts count CLI search invocations (including
multiple searches in one bash call), not all startup/reconnaissance commands.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from open_law_lens.config import DEFAULT_BRIEF_AGENT_PROMPT_TEMPLATE
from open_law_lens.agent_commands import AGENT_CLI_COMMAND_PREFIX
from open_law_lens.prior_briefs import PriorBriefLibrary, PriorBriefExtraction
from open_law_lens.pi_runtime import pi_command

QUESTIONS = {
    'direct': 'Find the strongest opening brief arguing for dependent-child inclusion under section 213.5; identify material contrary discussion.',
    'conflict': 'Which briefs offer conflicting arguments about dependent-child inclusion under section 213.5? Distinguish adult and nondependent-person discussions.',
    'noise': 'Find useful briefing about section 213.5 restraining order children, burdens of proof and review. Rank direct relevance, not token matches.',
    'late': 'What qualification limits the opening brief’s dependent-child inclusion argument under section 213.5?',
    'missing': 'Find the opening brief and any reply for B000001 concerning dependent-child inclusion under section 213.5.',
    'recency': 'Find the most recent directly relevant brief on dependent-child inclusion under section 213.5. Explain date provenance.',
}


def seed(root):
    source = root / 'archive'
    source.mkdir()
    texts = {
        'B000001_AOB_Dependent_Child.odt': (
            'SYNTHETIC OPENING BRIEF. Section 213.5 dependent-child inclusion.\n'
            'The opening brief argues that dependent children may be included without individual threats. '
            'It challenges the restrictive position reported in Fictional Bruno, not independently verified law. '
            'The brief describes Fictional Bruno as requiring child-specific evidence.\n'
            + '\n'.join(f'Background paragraph {i}: neutral procedural history without additional legal propositions.' for i in range(240))
            + '\nMATERIAL QUALIFICATION: The proposed dependent-child inclusion argument is limited to children '
            'who witnessed the threats; it does not claim all dependent children automatically qualify. '
            'The brief concedes that the cited restrictive position remains adverse to its requested extension.\n'
            'Dated: 01/03/2026 By: /s/ Synthetic'),
        'B000001_RB_Contrary.odt': 'SYNTHETIC RESPONDENT BRIEF. Section 213.5 dependent-child inclusion. '
            'Respondent argues that child-specific evidence is necessary and opposes the opening brief’s extension. '
            'This is advocacy, not an independently verified statement of current law.\nDated: 01/04/2026 By: /s/ Synthetic',
        'B000002_AOB_Adult.odt': 'SYNTHETIC adult protection section 213.5 restraining order. '
            'This brief discusses only protection of a mother, not dependent-child inclusion. '
            'Its proposed trial burden of proof is not a holding about children.\nDated: 01/05/2026 By: /s/ Synthetic',
        'B000003_AOB_Nondependent.odt': 'SYNTHETIC nondependent-person eligibility under section 213.5. '
            'This brief disputes eligibility of a nondependent sibling; it does not address dependent-child inclusion. '
            'Its appellate review argument is not a trial burden.\nDated: 01/06/2026 By: /s/ Synthetic',
        'B000004_AOB_Recent.odt': 'SYNTHETIC section 213.5 dependent-child inclusion opening brief. '
            'This short brief repeats B000001’s argument for children who witnessed the threats. '
            'It acknowledges the same adverse restrictive position; it adds no independent support. No signed date is present.',
    }
    for i in range(8):
        texts[f'B0001{i:02d}_Memo_Repetition.odt'] = 'SYNTHETIC companion memo. Section 213.5 dependent-child inclusion. Repeats B000001; no independent analysis.\nDated: 01/02/2026 By: /s/ Synthetic'
    for i in range(12):
        texts[f'B0002{i:02d}_Memo_Noise.odt'] = f'SYNTHETIC unrelated invoice: {213 if i % 2 else 5} items. No child protection analysis.'
    for name in texts:
        path = source / name
        path.write_text('synthetic extraction fixture')
        os.utime(path, (1788220800, 1788220800))
    library = PriorBriefLibrary(source, root / 'briefs.sqlite3')
    with patch('open_law_lens.prior_briefs.extract_prior_brief_document',
               side_effect=lambda path: PriorBriefExtraction(text=texts[path.name])):
        assert not library.sync().errors
    return library


def main():
    output = Path(sys.argv[1]).resolve()
    output.mkdir(exist_ok=False)
    corpus = seed(output)
    old = (PROJECT / 'tests/fixtures/prior_brief_prompt_previous.txt').read_text().replace('$OLL', AGENT_CLI_COMMAND_PREFIX)
    summaries = []
    spent = 0.0
    for case, question in QUESTIONS.items():
        for variant, template in (('baseline', old), ('candidate', DEFAULT_BRIEF_AGENT_PROMPT_TEMPLATE)):
            if spent > 0.5:
                raise SystemExit('Completed-cost safety stop; inspect existing runs, no substitution.')
            run = output / f'{case}-{variant}'
            run.mkdir()
            workspace = run / 'workspace'
            workspace.mkdir()
            shutil.copy2(corpus.path, run / 'briefs.sqlite3')
            (run / 'config.json').write_text('{}')
            env = os.environ.copy()
            env.pop('COURTLISTENER_TOKEN', None)
            env.update({
                'OPEN_LAW_LENS_PROJECT_DIR': str(PROJECT),
                'PYTHONPATH': str(PROJECT),
                'OPEN_LAW_LENS_CONFIG': str(run / 'config.json'),
                'OPEN_LAW_LENS_PRIOR_BRIEFS_DB': str(run / 'briefs.sqlite3'),
                'OPEN_LAW_LENS_PRIOR_BRIEFS_DIR': str(output / 'archive'),
                'OPEN_LAW_LENS_LIBRARY_DB': str(run / 'library.sqlite3'),
                'OPEN_LAW_LENS_CACHE_DIR': str(run / 'cache'),
                'XDG_STATE_HOME': str(run / 'state'),
            })
            prompt = template.format(question=question, brief_database=run / 'briefs.sqlite3', brief_count=corpus.count())
            command = [*pi_command(), '--offline', '--no-session', '--no-extensions',
                       '--no-skills', '--no-context-files', '--no-prompt-templates',
                       '--no-themes', '--tools', 'bash,read', '--provider', 'fireworks',
                       '--model', 'accounts/fireworks/models/deepseek-v4p1-flash',
                       '--thinking', 'high', '--mode', 'json', '--system-prompt',
                       (PROJECT / '.pi/SYSTEM.md').read_text(), '-p', prompt]
            started = time.monotonic()
            with (run / 'events.jsonl').open('w') as out, (run / 'stderr.log').open('w') as err:
                try:
                    proc = subprocess.run(command, cwd=workspace, env=env, stdout=out, stderr=err, timeout=240)
                    status = proc.returncode
                except subprocess.TimeoutExpired:
                    status = 'timeout'
            metric = {'case': case, 'variant': variant, 'status': status,
                      'seconds': round(time.monotonic() - started, 2), 'cost': 0,
                      'input': 0, 'output': 0, 'discovery_calls': 0, 'tool_calls': 0}
            for line in (run / 'events.jsonl').read_text().splitlines():
                event = json.loads(line)
                if event.get('type') == 'message_end':
                    msg = event.get('message', {})
                    if msg.get('role') == 'assistant':
                        usage = msg.get('usage', {})
                        metric['cost'] += usage.get('cost', {}).get('total', 0)
                        for key in ('input', 'output'):
                            metric[key] += usage.get(key, 0)
                        for block in msg.get('content', []):
                            if block.get('type') == 'toolCall':
                                metric['tool_calls'] += 1
                                args = json.dumps(block.get('arguments', {}))
                                metric['discovery_calls'] += args.count('search-briefs')
                        if msg.get('stopReason') == 'stop':
                            (run / 'answer.md').write_text('\n'.join(b.get('text', '') for b in msg.get('content', []) if b.get('type') == 'text'))
            spent += metric['cost']
            summaries.append(metric)
            (output / 'metrics.json').write_text(json.dumps(summaries, indent=2))
            print(json.dumps(metric), flush=True)


if __name__ == '__main__':
    main()
