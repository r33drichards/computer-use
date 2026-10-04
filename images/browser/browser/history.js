// Desktop DVR. Recording is local to the awake pod, never an idle lease.
// Settings and completed clips live on its volume; unfinished clips are private.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { execFile, spawn } from 'node:child_process';
import { promisify } from 'node:util';
import { mcpCallerRefusal } from './callers.js';

const exec = promisify(execFile);
export const CLIP_NAME = /^\d{13}-[a-f0-9]{8}\.mp4$/;
export const MAX_BYTES = 256 * 1024 * 1024;
const CLIP_SECONDS = 5;

export function validHistorySeconds(value) {
  return Number.isInteger(value) && value >= 0 && value <= 3600;
}

export function pruneClips(clips, seconds, now, maxBytes = MAX_BYTES) {
  const kept = clips.filter(c => seconds > 0 && c.start + c.duration * 1000 > now - seconds * 1000);
  let bytes = kept.reduce((sum, c) => sum + c.bytes, 0);
  while (bytes > maxBytes && kept.length) bytes -= kept.shift().bytes;
  return kept;
}

function send(res, status, body) {
  res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
  res.end(JSON.stringify(body));
}

export function createHistory({ dir, display = process.env.DISPLAY || ':99', record = true, now = Date.now }) {
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  const settings = path.join(dir, 'settings.json');
  let seconds = 300;
  try {
    const saved = JSON.parse(fs.readFileSync(settings, 'utf8')).seconds;
    if (validHistorySeconds(saved)) seconds = saved;
  } catch (err) {
    // Corrupt settings fail closed, rather than unexpectedly recording.
    if (err.code !== 'ENOENT') seconds = 0;
  }
  let clips = [];
  let error = '';
  let child;
  let stopped = false;
  let generation = 0;
  let timer;
  // Only complete clips with valid metadata survive a fresh start.
  for (const name of fs.readdirSync(dir)) {
    if (name.endsWith('.tmp')) fs.rmSync(path.join(dir, name), { force: true });
    if (!CLIP_NAME.test(name)) continue;
    try {
      const c = JSON.parse(fs.readFileSync(path.join(dir, name + '.json'), 'utf8'));
      const stat = fs.lstatSync(path.join(dir, name));
      if (!stat.isFile() || c.name !== name || !Number.isFinite(c.start) ||
          !Number.isFinite(c.duration) || c.duration <= 0 || c.duration > 6) throw new Error('invalid clip');
      clips.push({ name, start: c.start, duration: c.duration, bytes: stat.size });
    } catch {
      fs.rmSync(path.join(dir, name), { force: true });
      fs.rmSync(path.join(dir, name + '.json'), { force: true });
    }
  }
  clips.sort((a, b) => a.start - b.start);

  function prune() {
    const kept = pruneClips(clips, seconds, now());
    const names = new Set(kept.map(c => c.name));
    for (const c of clips) if (!names.has(c.name)) {
      fs.rmSync(path.join(dir, c.name), { force: true });
      fs.rmSync(path.join(dir, c.name + '.json'), { force: true });
    }
    clips = kept;
  }
  function status() {
    prune();
    return { seconds, max_bytes: MAX_BYTES, clips, error };
  }

  async function capture() {
    const mine = generation;
    let tmp;
    try {
      prune();
      if (!seconds || stopped) return;
      const { stdout } = await exec('xdpyinfo', ['-display', display], { timeout: 3000 });
      const size = stdout.match(/dimensions:\s+(\d+)x(\d+) pixels/);
      if (!size) throw new Error('display size unavailable');
      if (mine !== generation || stopped) return;
      const start = now();
      const name = `${start}-${crypto.randomBytes(4).toString('hex')}.mp4`;
      tmp = path.join(dir, name + '.tmp');
      await new Promise((resolve, reject) => {
        child = spawn('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-nostdin',
          '-f', 'x11grab', '-draw_mouse', '1', '-framerate', '10', '-video_size', `${size[1]}x${size[2]}`,
          '-i', display, '-t', String(CLIP_SECONDS), '-an',
          '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2', '-c:v', 'libx264', '-preset', 'ultrafast',
          '-crf', '28', '-pix_fmt', 'yuv420p', '-threads', '2', '-fs', String(16 * 1024 * 1024),
          '-movflags', '+faststart', '-f', 'mp4', tmp],
          { stdio: ['ignore', 'ignore', 'pipe'] });
        const active = child;
        let diagnostic = '';
        active.stderr.on('data', chunk => { diagnostic = (diagnostic + chunk.toString()).slice(-4096); });
        const timeout = setTimeout(() => active.kill('SIGKILL'), 15000);
        active.once('error', reject);
        active.once('close', code => {
          clearTimeout(timeout);
          if (child === active) child = undefined;
          code === 0 ? resolve() : reject(new Error(`capture failed (${code}): ${diagnostic.trim()}`));
        });
      });
      if (mine !== generation || stopped) return;
      const { stdout: probe } = await exec('ffprobe', ['-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', tmp], { timeout: 3000 });
      if (mine !== generation || stopped) return;
      const duration = Number(probe.trim());
      if (!Number.isFinite(duration) || duration <= 0 || duration > 6) throw new Error('invalid duration');
      const bytes = fs.statSync(tmp).size;
      const clip = { name, start, duration, bytes };
      fs.writeFileSync(path.join(dir, name + '.json'), JSON.stringify(clip), { mode: 0o600 });
      fs.renameSync(tmp, path.join(dir, name));
      clips.push(clip);
      error = '';
      prune();
    } catch (err) {
      if (mine === generation && !stopped) {
        if (!error) console.error('desktop history capture:', err.message);
        error = 'Desktop recording is unavailable; retrying.';
      }
    } finally {
      if (tmp) fs.rmSync(tmp, { force: true });
      if (!stopped) timer = setTimeout(capture, seconds ? (error ? 2000 : 50) : 1000);
    }
  }
  prune();
  if (record) timer = setTimeout(capture, 0);

  return {
    close() { stopped = true; generation++; clearTimeout(timer); child?.kill('SIGTERM'); },
    async handle(req, res) {
      const raw = req.url.split('?')[0];
      if (raw !== '/history' && !raw.startsWith('/history/')) return false;
      // Unlike downloads, recording data must never be readable by a page
      // running on the recorded desktop, including through DNS rebinding.
      if (mcpCallerRefusal({ headers: { ...req.headers, 'content-type': 'application/json' } })) {
        send(res, 403, { error: 'forbidden' }); return true;
      }
      try {
        if (raw === '/history') {
          if (req.method === 'GET') send(res, 200, status());
          else if (req.method === 'PUT') {
            if (String(req.headers['content-type']).split(';')[0] !== 'application/json') {
              send(res, 415, { error: 'the body must be JSON' }); return true;
            }
            let body = '';
            for await (const chunk of req) {
              body += chunk;
              if (body.length > 1024) { send(res, 413, { error: 'body too large' }); return true; }
            }
            let asked;
            try { asked = JSON.parse(body); } catch {}
            if (!validHistorySeconds(asked?.seconds)) {
              send(res, 400, { error: 'history must be 0 to 3600 whole seconds' }); return true;
            }
            fs.writeFileSync(settings + '.tmp', JSON.stringify({ seconds: asked.seconds }), { mode: 0o600 });
            fs.renameSync(settings + '.tmp', settings);
            seconds = asked.seconds;
            generation++;
            child?.kill('SIGTERM');
            error = '';
            send(res, 200, status());
          } else send(res, 405, { error: 'method not allowed' });
          return true;
        }
        const name = raw.slice('/history/'.length);
        prune();
        if (req.method !== 'GET' || !CLIP_NAME.test(name)) {
          send(res, 404, { error: 'clip not found' }); return true;
        }
        const clip = clips.find(c => c.name === name);
        if (!clip) { send(res, 404, { error: 'clip expired' }); return true; }
        // Open before writing headers: expiry can race a later range request.
        const fd = fs.openSync(path.join(dir, name), fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
        let start = 0, end = clip.bytes - 1;
        const range = req.headers.range;
        if (range) {
          const match = /^bytes=(\d*)-(\d*)$/.exec(range);
          if (!match || (!match[1] && !match[2])) {
            fs.closeSync(fd); res.writeHead(416, { 'Content-Range': `bytes */${clip.bytes}` }).end(); return true;
          }
          start = match[1] ? Number(match[1]) : Math.max(0, clip.bytes - Number(match[2]));
          end = match[1] && match[2] ? Math.min(Number(match[2]), end) : end;
          if (start > end || start >= clip.bytes) {
            fs.closeSync(fd); res.writeHead(416, { 'Content-Range': `bytes */${clip.bytes}` }).end(); return true;
          }
        }
        res.writeHead(range ? 206 : 200, {
          'Content-Type': 'video/mp4', 'Cache-Control': 'no-store', 'Accept-Ranges': 'bytes',
          'Content-Length': end - start + 1,
          ...(range ? { 'Content-Range': `bytes ${start}-${end}/${clip.bytes}` } : {}),
        });
        const stream = fs.createReadStream('', { fd, start, end, autoClose: true });
        stream.on('error', () => res.destroy());
        res.on('close', () => stream.destroy());
        stream.pipe(res);
      } catch {
        if (!res.headersSent) send(res, 500, { error: 'history is unavailable' });
        else res.destroy();
      }
      return true;
    },
  };
}
