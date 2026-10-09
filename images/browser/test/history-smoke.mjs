// Real X11/FFmpeg smoke check, invoked by the browser image build.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const { createHistory } = await import(pathToFileURL(process.env.HISTORY_JS).href);
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'history-smoke-'));
const recorder = createHistory({ dir });
const server = http.createServer((req, res) => recorder.handle(req, res));
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const url = `http://127.0.0.1:${server.address().port}/history`;

// Node's fetch sends Sec-Fetch-Mode, which this private endpoint correctly
// refuses as a browser request. Match the backend's plain HTTP client.
function call(target, { method = 'GET', headers = {}, body } = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request(target, { method, headers }, res => {
      const chunks = [];
      res.on('data', chunk => chunks.push(chunk));
      res.on('end', () => {
        const data = Buffer.concat(chunks);
        resolve({ status: res.statusCode, json: () => JSON.parse(data.toString()), arrayBuffer: () => data });
      });
    });
    req.on('error', reject);
    req.end(body);
  });
}

try {
  let status;
  const deadline = Date.now() + 25000;
  do {
    const response = await call(url);
    status = response.json();
    assert.equal(response.status, 200, `history endpoint: ${JSON.stringify(status)}`);
    if (status.clips.length) break;
    await new Promise(resolve => setTimeout(resolve, 250));
  } while (Date.now() < deadline);
  assert.ok(status.clips.length, `recorder produced no clips: ${JSON.stringify(status)}`);
  const clip = status.clips[0];
  assert.ok(clip.duration >= 4.5 && clip.duration <= 5.5);
  const file = path.join(dir, clip.name);
  const probe = JSON.parse(execFileSync('ffprobe', ['-v', 'error', '-select_streams', 'v:0',
    '-show_entries', 'stream=codec_name,width,height,pix_fmt', '-of', 'json', file], { encoding: 'utf8' }));
  assert.equal(probe.streams[0].codec_name, 'h264');
  assert.equal(probe.streams[0].pix_fmt, 'yuv420p');
  assert.equal(probe.streams[0].width, 1280);
  assert.equal(probe.streams[0].height, 800);
  execFileSync('ffmpeg', ['-v', 'error', '-i', file, '-f', 'null', '-']);
  const range = await call(`${url}/${clip.name}`, { headers: { Range: 'bytes=0-99' } });
  assert.equal(range.status, 206);
  assert.equal((await range.arrayBuffer()).byteLength, 100);
  const off = await call(url, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: '{"seconds":0}' });
  assert.equal(off.status, 200);
  assert.deepEqual((await off.json()).clips, []);
  console.log('ok desktop history: real X11 capture, H.264 decode, ranges, and disabling');
} finally {
  recorder.close();
  await new Promise(resolve => server.close(resolve));
  // The recorder's killed subprocess finishes its cleanup asynchronously.
  await new Promise(resolve => setTimeout(resolve, 100));
  fs.rmSync(dir, { recursive: true, force: true });
}
