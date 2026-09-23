// Disposable Pi executable used by test_run_metrics_sdk.py; never a live provider.
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { pathToFileURL } from 'node:url';
const pkg = process.env.PI_METRICS_TEST_SDK || join(dirname(process.execPath), '../lib/node_modules/@earendil-works/pi-coding-agent');
if (process.argv.slice(2).includes('--version')) {
  console.log(JSON.parse(readFileSync(join(pkg, 'package.json'), 'utf8')).version);
  process.exit(0);
}
const sdk = await import(pathToFileURL(join(pkg, 'dist/index.js')));
const ai = await import(pathToFileURL(join(pkg, 'node_modules/@earendil-works/pi-ai/dist/index.js')));
globalThis.fetch = () => { throw new Error('Network forbidden during metrics acceptance'); };
const args = process.argv.slice(2);
const value = flag => args[args.indexOf(flag) + 1];
const extensions = args.flatMap((arg, i) => arg === '--extension' ? [args[i + 1]] : []);
assert.ok(args.includes('--no-extensions'));
assert.ok(!args.includes('--no-session'));
const root = process.cwd();
const runtime = await sdk.ModelRuntime.create({authPath: join(root, 'synthetic-auth.json'), modelsPath: join(root, 'synthetic-models.json')});
const usage = {input: 11, output: 7, cacheRead: 3, cacheWrite: 2, totalTokens: 23, cost: {input: .1, output: .1, cacheRead: .025, cacheWrite: .025, total: .25}};
const model = {id: 'synthetic', name: 'Synthetic', provider: 'metrics-test', api: 'openai-completions', baseUrl: 'http://127.0.0.1:1', reasoning: false, input: ['text'], contextWindow: 32768, maxTokens: 1024, cost: {input: 0, output: 0, cacheRead: 0, cacheWrite: 0}};
let calls = 0;
const contexts = [];
const provider = {...model, apiKey: 'synthetic-not-a-key', models: [model], streamSimple(_model, context) {
  contexts.push(context);
  const call = calls++;
  const stream = new ai.AssistantMessageEventStream();
  queueMicrotask(() => {
    const stopReason = call === 0 ? 'error' : call === 1 ? 'toolUse' : 'stop';
    const content = call === 1 ? [{type: 'toolCall', id: 'synthetic-read', name: 'read', arguments: {path: 'synthetic.txt'}}] : [{type: 'text', text: 'CANARY synthetic final answer'}];
    const message = {role: 'assistant', content, api: model.api, provider: model.provider, model: model.id, usage, stopReason, timestamp: 1,
      ...(call === 0 ? {errorMessage: '429 synthetic rate limit CANARY'} : {})};
    stream.push(call === 0 ? {type: 'error', reason: 'error', error: message} : {type: 'done', reason: stopReason, message});
    stream.end();
  });
  return stream;
}};
const settingsManager = sdk.SettingsManager.inMemory({compaction: {enabled: false}, retry: {enabled: true, maxRetries: 1, baseDelayMs: 1, maxDelayMs: 1}});
const loader = new sdk.DefaultResourceLoader({cwd: root, agentDir: join(root, 'agent-dir'), settingsManager,
  noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
  additionalExtensionPaths: extensions,
  extensionFactories: [pi => pi.registerProvider('metrics-test', provider)],
  systemPromptOverride: () => readFileSync(value('--system-prompt'), 'utf8'),
});
await loader.reload();
assert.equal(loader.getExtensions().errors.length, 0);
const sessionManager = sdk.SessionManager.create(root, process.env.PI_CODING_AGENT_SESSION_DIR);
const {session} = await sdk.createAgentSession({cwd: root, agentDir: join(root, 'agent-dir'), modelRuntime: runtime, model,
  resourceLoader: loader, settingsManager, sessionManager, tools: value('--tools').split(',')});
assert.deepEqual(session.getActiveToolNames().sort(), value('--tools').split(',').sort());
let settled = 0;
session.subscribe(e => { if (e.type === 'agent_settled') settled++; });
try {
  writeFileSync(join(root, 'synthetic.txt'), 'CANARY synthetic tool result é');
  await session.prompt(args.at(-1));
  await session.prompt('CANARY synthetic followup');
  assert.equal(settled, 2);
  assert.equal(calls, 4);
  assert.equal(session.getLastAssistantText(), 'CANARY synthetic final answer');
  const capture = {contexts, tools: session.getActiveToolNames(), answer: session.getLastAssistantText(), session_file: sessionManager.getSessionFile()};
  writeFileSync(process.env.PI_METRICS_TEST_CAPTURE, JSON.stringify(capture, (key, val) => key === 'timestamp' ? 0 : val));
} finally { session.dispose(); }
