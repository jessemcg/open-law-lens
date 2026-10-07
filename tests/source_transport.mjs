// Installed Pi read tool, offline: no session/auth/provider/model is created.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const [modulePath, artifactDir, originalPath] = process.argv.slice(2);
const { createReadToolDefinition } = await import(pathToFileURL(modulePath));
const tool = createReadToolDefinition(artifactDir);
const manifest = JSON.parse(await fs.readFile(path.join(artifactDir, 'manifest.json'), 'utf8'));
const original = await fs.readFile(originalPath, 'utf8');
// Reproduce the default extraction's oversized JSON-string transport failure.
const baselinePath = path.join(path.dirname(artifactDir), 'baseline.json');
await fs.writeFile(baselinePath, JSON.stringify({ text: original }, null, 2), { mode: 0o600 });
const baseline = await tool.execute('offline-baseline', { path: baselinePath });
const baselineTruncated = Boolean(baseline.details?.truncation?.truncated);
let delivered = '';
let reads = 0;
const started = performance.now();
for (const part of manifest.parts) {
  const result = await tool.execute(`offline-part-${++reads}`, { path: path.join(artifactDir, part.name) });
  assert(!result.details?.truncation?.truncated, 'Part was truncated');
  const content = result.content.find(block => block.type === 'text')?.text;
  const actual = await fs.readFile(path.join(artifactDir, part.name), 'utf8');
  assert.equal(content, actual, 'Transport changed source text');
  delivered += content;
}
assert.equal(delivered, original, 'Incomplete source delivery');
console.log(JSON.stringify({ installed_read_module: modulePath, baseline_truncated: baselineTruncated,
                            part_reads: reads, delivered_bytes: Buffer.byteLength(delivered),
                            delivery_complete: true, extraction_count: 1,
                            transport_ms: performance.now() - started }));
