import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { createHistory, pruneClips, validHistorySeconds } from '../browser/history.js';

test('retention expires by wall time and removes oldest clips to meet the byte cap', () => {
  const clips = [0, 5, 10].map(n => ({ name: String(n), start: n * 1000, duration: 5, bytes: 10 }));
  assert.deepEqual(pruneClips(clips, 6, 15000).map(c => c.name), ['5', '10']);
  assert.deepEqual(pruneClips(clips, 60, 15000, 15).map(c => c.name), ['10']);
  assert.deepEqual(pruneClips(clips, 0, 15000), []);
  for (const v of [null, -1, 3601, 1.5, '300']) assert.equal(validHistorySeconds(v), false);
});

async function fixture(t, options = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'history-test-'));
  let time = 1720000005000;
  const name = '1720000000000-1234abcd.mp4';
  fs.writeFileSync(path.join(dir, name), '0123456789');
  fs.writeFileSync(path.join(dir, name + '.json'), JSON.stringify({ name, start: time - 5000, duration: 5 }));
  fs.writeFileSync(path.join(dir, 'unfinished.tmp'), 'partial');
  const history = createHistory({ dir, record: false, now: () => time, ...options });
  const server = http.createServer(async (req, res) => {
    if (!(await history.handle(req, res))) res.writeHead(404).end();
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(async () => {
    history.close();
    await new Promise(resolve => server.close(resolve));
    fs.rmSync(dir, { recursive: true, force: true });
  });
  function call(method, raw = '/history', headers = {}, body) {
    return new Promise((resolve, reject) => {
      const req = http.request({ host: '127.0.0.1', port: server.address().port, method, path: raw,
        headers: { 'Content-Type': 'application/json', ...headers } }, res => {
        const chunks = [];
        res.on('data', c => chunks.push(c));
        res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks).toString() }));
      });
      req.on('error', reject); req.end(body);
    });
  }
  return { dir, name, history, call, advance: ms => { time += ms } };
}

test('completed clips recover, support byte ranges, expire, and unfinished files disappear', async t => {
  const f = await fixture(t);
  assert.equal(fs.existsSync(path.join(f.dir, 'unfinished.tmp')), false);
  assert.equal(JSON.parse((await f.call('GET')).body).clips.length, 1);
  const range = await f.call('GET', '/history/' + f.name, { Range: 'bytes=2-5' });
  assert.equal(range.status, 206);
  assert.equal(range.body, '2345');
  assert.equal(range.headers['content-range'], 'bytes 2-5/10');
  assert.equal((await f.call('GET', '/history/' + f.name, { Range: 'bytes=-3' })).body, '789');
  assert.equal((await f.call('GET', '/history/' + f.name, { Range: 'bytes=20-' })).status, 416);
  f.advance(300001);
  assert.equal((await f.call('GET', '/history/' + f.name)).status, 404);
  assert.equal(fs.existsSync(path.join(f.dir, f.name)), false);
});

test('per-session settings persist and disabling deletes recordings immediately', async t => {
  const f = await fixture(t);
  assert.equal((await f.call('PUT', '/history', {}, '{"seconds":1800}')).status, 200);
  assert.equal(JSON.parse(fs.readFileSync(path.join(f.dir, 'settings.json'))).seconds, 1800);
  const reopened = createHistory({ dir: f.dir, record: false, now: () => 1720000005000 });
  reopened.close();
  const off = await f.call('PUT', '/history', {}, '{"seconds":0}');
  assert.equal(off.status, 200);
  assert.deepEqual(JSON.parse(off.body).clips, []);
  assert.equal(fs.existsSync(path.join(f.dir, f.name)), false);
  for (const body of ['{}', '{"seconds":-1}', '{"seconds":2.5}', '{"seconds":3601}', 'garbage']) {
    assert.equal((await f.call('PUT', '/history', {}, body)).status, 400);
  }
});

test('pages on the recorded desktop cannot read or configure history; clip paths are confined', async t => {
  const f = await fixture(t);
  for (const headers of [{ Origin: 'https://example.com' }, { 'Sec-Fetch-Dest': 'video' }, { Host: 'attacker.example' }]) {
    assert.equal((await f.call('GET', '/history', headers)).status, 403);
    assert.equal((await f.call('PUT', '/history', headers, '{"seconds":0}')).status, 403);
  }
  for (const name of ['../settings.json', '%2e%2e/settings.json', '.hidden', 'bad.mp4', f.name + '/x']) {
    assert.equal((await f.call('GET', '/history/' + name)).status, 404);
  }
});
