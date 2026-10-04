import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const script = fileURLToPath(new URL('./ci-source-binding.sh', import.meta.url));
test('source receipt binds exact clean commit/tree and rejects mismatches or dirty checkout', () => {
 const dir = mkdtempSync(join(tmpdir(), 'ci-source-synthetic-'));
 const git = args => { const r = spawnSync('git', args, { cwd: dir, encoding: 'utf8' }); assert.equal(r.status, 0, r.stderr); return r.stdout.trim(); };
 try {
  git(['init', '--initial-branch=synthetic']); writeFileSync(join(dir, 'canary'), 'synthetic'); git(['add', 'canary']);
  git(['-c', 'user.name=Computer Use Agent', '-c', 'user.email=57335981+r33drichards@users.noreply.github.com', 'commit', '-m', 'synthetic']);
  const sha = git(['rev-parse', 'HEAD']); const tree = git(['rev-parse', 'HEAD^{tree}']);
  const output = join(dir, 'receipt'); const summary = join(dir, 'summary');
  const run = expected => spawnSync('bash', [script], { cwd: dir, env: { ...process.env, EXPECTED_SOURCE: expected, GITHUB_OUTPUT: output, GITHUB_STEP_SUMMARY: summary }, encoding: 'utf8' });
  const good = run(sha); assert.equal(good.status, 0, good.stderr);
  assert.ok(good.stdout.includes('sha=' + sha)); assert.ok(good.stdout.includes('tree=' + tree));
  assert.ok(readFileSync(output, 'utf8').includes('sha=' + sha)); assert.ok(readFileSync(summary, 'utf8').includes(tree));
  assert.notEqual(run('0'.repeat(40)).status, 0); assert.notEqual(run('main').status, 0);
  writeFileSync(join(dir, 'canary'), 'changed'); assert.notEqual(run(sha).status, 0);
 } finally { rmSync(dir, { recursive: true, force: true }); }
});
test('only nonpublishing builds/canary bind PR head; filter and publish remain unchanged', () => {
 const images = readFileSync(new URL('../.github/workflows/images.yml', import.meta.url), 'utf8');
 const build = images.slice(images.indexOf('  build:'), images.indexOf('  publish:'));
 const filter = images.slice(0, images.indexOf('  build:')); const publish = images.slice(images.indexOf('  publish:'));
 const canary = readFileSync(new URL('../.github/workflows/canary-kind.yml', import.meta.url), 'utf8');
 const ref = 'ref: $' + '{{ github.event.pull_request.head.sha || github.sha }}';
 assert.ok(build.includes(ref)); assert.ok(canary.includes(ref)); assert.ok(!filter.includes(ref)); assert.ok(!publish.includes(ref));
 assert.ok(build.includes('org.opencontainers.image.revision=$' + '{{ steps.source.outputs.sha }}'));
 for (const workflow of [build, canary]) { assert.ok(workflow.includes('persist-credentials: false')); assert.ok(workflow.includes('bash test/ci-source-binding.sh')); }
 assert.ok(publish.includes("github.ref == 'refs/heads/main'")); assert.ok(publish.includes("github.event_name != 'pull_request'"));
});
