// Offline native Bash + real Python console entrypoint, attributed to Prose.
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { pathToFileURL } from 'node:url';
const [variant] = process.argv.slice(2);
const root = process.cwd();
const pkg = process.env.PI_METRICS_TEST_SDK || join(dirname(process.execPath), '../lib/node_modules/@earendil-works/pi-coding-agent');
const sdk = await import(pathToFileURL(join(pkg, 'dist/index.js')));
const ai = await import(pathToFileURL(join(pkg, 'node_modules/@earendil-works/pi-ai/dist/index.js')));
globalThis.fetch = () => { throw new Error('Network forbidden during workflow acceptance'); };
const usage = { input: 2, output: 2, cacheRead: 0, cacheWrite: 0, totalTokens: 4, cost: {input:0,output:0,cacheRead:0,cacheWrite:0,total:0} };
const model = {id:'synthetic',name:'Synthetic',provider:'metrics-test',api:'openai-completions',baseUrl:'http://127.0.0.1:1',reasoning:false,input:['text'],contextWindow:32768,maxTokens:1024,cost:{input:0,output:0,cacheRead:0,cacheWrite:0}};
const run = '\"$OPEN_LAW_LENS_CLI_BIN\" ';
const search = run + 'case-search "CANARY retry mixed" --compact --semantic --limit 5 > search-CANARY.json';
const batches = [[
  search, search,
  run + 'case-search "CANARY filtered" --compact',
  run + 'case-search "CANARY exhausted"',
  run + 'case-search "CANARY malformed"',
  run + 'case-search "CANARY shape"',
  run + 'lookup-citation "CANARY cached"',
  run + 'extract-case --cluster-id 42 --find "CANARY not present"',
  'false | true', 'exit 7', 'sleep 2',
], [run + 'case-search "CANARY empty" --limit 3 > followup-CANARY.json']];
let calls = 0;
const contexts = [], completion = [];
const provider = {...model, apiKey:'synthetic-not-a-key',models:[model],streamSimple(_model, context) {
  contexts.push(JSON.parse(JSON.stringify(context)));
  const i = calls++, commands = batches[i >> 1];
  const stream = new ai.AssistantMessageEventStream();
  queueMicrotask(() => {
    const stopReason = (i % 2) ? 'stop' : 'toolUse';
    const content = stopReason === 'stop' ? [{type:'text',text:'CANARY final answer'}] : commands.map((command, index) => (
      {type:'toolCall',id:`work-${i}-${index}`,name:'bash',arguments:{command, ...(command === 'sleep 2' ? {timeout: 0.03} : {})}}));
    const message = {role:'assistant',content,api:model.api,provider:model.provider,model:model.id,usage,stopReason,timestamp:1};
    stream.push({type:'done',reason:stopReason,message}); stream.end();
  });
  return stream;
}};
const settingsManager = sdk.SettingsManager.inMemory({compaction:{enabled:false},retry:{enabled:false}});
const modelRuntime = await sdk.ModelRuntime.create({authPath:join(root,'auth.json'),modelsPath:join(root,'models.json')});
const resourceLoader = new sdk.DefaultResourceLoader({cwd:root,agentDir:join(root,'agent'),settingsManager,
  noExtensions:true,noSkills:true,noContextFiles:true,noPromptTemplates:true,noThemes:true,
  additionalExtensionPaths: variant === 'missing' ? [] : [process.env.TEST_COLLECTOR],
  extensionFactories:[pi=>pi.registerProvider('metrics-test',provider)],systemPromptOverride:()=> 'CANARY system'});
await resourceLoader.reload();
assert.equal(resourceLoader.getExtensions().errors.length,0);
const sessionManager = sdk.SessionManager.inMemory(root);
const {session} = await sdk.createAgentSession({cwd:root,agentDir:join(root,'agent'),modelRuntime,model,
  resourceLoader,settingsManager,sessionManager,tools:['bash']});
assert.deepEqual(session.getActiveToolNames(),['bash']);
session.subscribe(e => {
  if (e.type === 'tool_execution_end') completion.push({id:e.toolCallId,error:e.isError,exit:e.result?.structuredContent?.exit_code});
});
try {
  await session.prompt('CANARY initial question');
  await session.prompt('CANARY followup question');
  assert.equal(calls,4);
  assert.equal(session.getLastAssistantText(),'CANARY final answer');
  writeFileSync(join(root,'capture.json'),JSON.stringify({contexts, tools:session.getActiveToolNames(),
    completions:completion.sort((a,b)=>a.id.localeCompare(b.id)), answer:session.getLastAssistantText(),
    files:['search-CANARY.json','followup-CANARY.json'].map(f=>readFileSync(f,'utf8'))},
    (k,v)=> ['timestamp','durationMs','wall_time_seconds'].includes(k) ? 0 : v));
} finally { session.dispose(); }
