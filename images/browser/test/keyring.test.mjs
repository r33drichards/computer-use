import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, readdirSync, statSync, chmodSync, symlinkSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import net from 'node:net';
import { spawn } from 'node:child_process';

const helper = fileURLToPath(new URL('../browser/keyring-server.sh', import.meta.url));
function fixture() {
 const dir = mkdtempSync(join(tmpdir(), 'computeruse-keyring-'));
 const home = join(dir, 'home'); const runtime = join(dir, 'runtime'); const bin = join(dir, 'bin');
 mkdirSync(home); mkdirSync(runtime); mkdirSync(bin);
 const capture = join(dir, 'args');
 writeFileSync(join(bin, 'gnome-keyring-daemon'), '#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$CAPTURE"\n');
 chmodSync(join(bin, 'gnome-keyring-daemon'), 0o700);
 const env = { ...process.env, HOME: home, XDG_RUNTIME_DIR: runtime, GNOME_KEYRING_CONTROL: '', DBUS_SESSION_BUS_ADDRESS: 'unix:path=' + join(runtime, 'bus'), PATH: bin + ':' + process.env.PATH, CAPTURE: capture };
 return { dir, home, runtime, capture, env };
}

test('starts foreground Secret Service with private persistent/control directories and no password', () => {
 const f = fixture();
 try {
  const run = spawnSync('bash', [helper], { env: f.env, encoding: 'utf8' });
  assert.equal(run.status, 0, run.stderr);
  const persistent = join(f.home, '.local/share/keyrings');
  assert.equal(statSync(persistent).mode & 0o777, 0o700);
  assert.equal(statSync(join(f.runtime, 'keyring')).mode & 0o777, 0o700);
  assert.deepEqual(readdirSync(persistent), []);
  assert.deepEqual(readFileSync(f.capture, 'utf8').trim().split('\n'), ['--foreground', '--components=secrets', '--control-directory=' + join(f.runtime, 'keyring')]);
 } finally { rmSync(f.dir, { recursive: true, force: true }); }
});

test('does not overwrite or unlock existing encrypted keyrings on a fresh start', () => {
 const f = fixture();
 try {
  const persistent = join(f.home, '.local/share/keyrings');
  mkdirSync(persistent, { recursive: true, mode: 0o755 });
  const file = join(persistent, 'login.keyring');
  const encrypted = Buffer.from([0, 255, 7, 42, 128]);
  writeFileSync(file, encrypted, { mode: 0o600 });
  const run = spawnSync('bash', [helper], { env: f.env, encoding: 'utf8' });
  assert.equal(run.status, 0, run.stderr);
  assert.deepEqual(readFileSync(file), encrypted);
  assert.equal(statSync(persistent).mode & 0o777, 0o700);
  assert.doesNotMatch(readFileSync(f.capture, 'utf8'), /--unlock|--login|--replace|ssh|pkcs11/);
 } finally { rmSync(f.dir, { recursive: true, force: true }); }
});

test('refuses to start without the desktop session bus', () => {
 const f = fixture();
 try {
  const run = spawnSync('bash', [helper], { env: { ...f.env, DBUS_SESSION_BUS_ADDRESS: '' }, encoding: 'utf8' });
  assert.notEqual(run.status, 0);
  assert.match(run.stderr, /start the desktop session bus first/);
 } finally { rmSync(f.dir, { recursive: true, force: true }); }
});

test('default image packages unprivileged daemon, libsecret, UI and D-Bus prompter', () => {
 const flake = readFileSync(new URL('../flake.nix', import.meta.url), 'utf8');
 assert.match(flake, /gnome-keyring = \(pkgs.gnome-keyring.override \{ useWrappedDaemon = false; \}/);
 for (const entry of ['gnome-keyring', 'pkgs.seahorse', 'pkgs.gcr_3', 'pkgs.libsecret']) assert.ok(flake.includes(entry));
 assert.match(flake, /export KEYRING_SERVER=/);
 const docker = readFileSync(new URL('../Dockerfile', import.meta.url), 'utf8');
 assert.ok(docker.indexOf('.#keyring-smoke') < docker.indexOf('.#runtime'));
 const startup = readFileSync(new URL('../browser/entrypoint.sh', import.meta.url), 'utf8');
 assert.ok(startup.indexOf('dbus-daemon --config-file=') < startup.indexOf('bash "$KEYRING_SERVER"'));
 assert.ok(startup.indexOf('bash "$KEYRING_SERVER"') < startup.indexOf('browser-mcp &'));
 assert.match(startup, /org.freedesktop.secrets/);
});

test('encrypted smoke seeds before export and exercises locked runtime twice', () => {
 const smoke = readFileSync(new URL('./keyring-smoke.sh', import.meta.url), 'utf8');
 assert.match(smoke, /--foreground --unlock --components=secrets/);
 // The fixture daemon must exit before testing the production helper locked.
 assert.match(smoke, /wait_unlocked\nstop\ncheck_keyring_files\nstart\nlocked/);
 assert.match(smoke, /python3 "\$KEYRING_UNLOCK" ok/);
 assert.equal((smoke.match(/^locked$/gm) || []).length, 3);
 assert.match(smoke, /keyring-smoke-wrong-password/);
 assert.match(smoke, /keyring-runtime-restarted/);
 assert.match(smoke, /secret-tool store/);
 assert.match(smoke, /Secret appeared unencrypted on disk/);
 assert.equal((smoke.match(/secret-tool lookup/g) || []).length, 2);
 const runtime = readFileSync(helper, 'utf8');
 assert.doesNotMatch(runtime, /--unlock|--login/);
});

// Independent packet oracle from GNOME 50's control protocol; not daemon mocks
// standing in for the real image gate. Validates stdin, framing and denial.
test('fixture unlock targets existing socket, validates replies and refuses empty passwords', async () => {
 const dir = mkdtempSync(join(tmpdir(), 'keyring-control-'));
 const path = join(dir, 'control');
 const unlock = fileURLToPath(new URL('./keyring-unlock.py', import.meta.url));
 let result = 0; let packets = [];
 const server = net.createServer(peer => {
  let data = Buffer.alloc(0);
  peer.on('data', chunk => {
   data = Buffer.concat([data, chunk]);
   if (data.length >= 5 && data.length === 1 + data.readUInt32BE(1)) {
    packets.push(data);
    const reply = Buffer.alloc(8); reply.writeUInt32BE(8); reply.writeUInt32BE(result, 4);
    peer.write(reply.subarray(0, 3)); peer.end(reply.subarray(3));
   }
  });
 });
 await new Promise(resolve => server.listen(path, resolve));
 async function run(password, expected) {
  const child = spawn('python3', [unlock, expected], { env: { ...process.env, GNOME_KEYRING_CONTROL: dir } });
  let stderr = ''; child.stderr.on('data', x => stderr += x);
  child.stdin.end(password);
  const code = await new Promise((resolve, reject) => { child.on('error', reject); child.on('close', resolve); });
  return { code, stderr };
 }
 try {
  assert.equal((await run('fixture-password', 'ok')).code, 0);
  const password = Buffer.from('fixture-password');
  const expected = Buffer.alloc(13); expected[0] = 0;
  expected.writeUInt32BE(12 + password.length, 1);
  expected.writeUInt32BE(1, 5); expected.writeUInt32BE(password.length, 9);
  assert.deepEqual(packets[0], Buffer.concat([expected, password]));
  result = 1;
  assert.equal((await run('wrong-password', 'denied')).code, 0);
  const failed = await run('wrong-password', 'ok');
  assert.notEqual(failed.code, 0);
  assert.doesNotMatch(failed.stderr, /wrong-password/);
  assert.notEqual((await run('', 'ok')).code, 0);
  assert.equal(packets.length, 3); // empty password never contacted the daemon
 } finally {
  await new Promise(resolve => server.close(resolve));
  rmSync(dir, { recursive: true, force: true });
 }
});

test('partial-capability patch retains only originally permitted IPC_LOCK and preserves failures', () => {
 const patch = readFileSync(new URL('../patches/gnome-keyring-partial-capabilities.patch', import.meta.url), 'utf8');
 assert.match(patch, /retain_ipc_lock = capng_have_capability \(CAPNG_PERMITTED/);
 assert.match(patch, /if \(retain_ipc_lock &&/);
 assert.ok(!patch.includes('case CAPNG_FULL'));
 assert.ok(!patch.includes('case CAPNG_NONE'));
 assert.ok(!patch.includes('-\t\t\tif ((rc = capng_apply'));
 const image = readFileSync(new URL('./keyring-capability-image-smoke.sh', import.meta.url), 'utf8');
 assert.ok(image.includes('--user 1000:1000 --cap-drop ALL --security-opt no-new-privileges'));
 assert.ok(!image.includes('--cap-add'));
 assert.ok(image.includes('legacy-partial'));
 assert.ok(!/[\x00-\x08]/.test(image));
 const workflow = readFileSync(new URL('../../../.github/workflows/canary-kind.yml', import.meta.url), 'utf8');
 assert.ok(!/[\x00-\x08]/.test(workflow));
 assert.ok(image.includes('int(s[\'CapPrm\'], 16) == 0'));
 assert.ok(image.includes('dbus-run-session --config-file='));
});

test('image encrypted fixture requires and forwards the packaged Nix session bus configuration', () => {
 const image = readFileSync(new URL('./keyring-capability-image-smoke.sh', import.meta.url), 'utf8');
 const command = image.split('\n').find(line => line.startsWith('dbus-run-session '));
 const flake = readFileSync(new URL('../flake.nix', import.meta.url), 'utf8');
 assert.match(flake, /export DBUS_SESSION_CONF=.*pkgs.dbus/);
 const f = fixture();
 try {
  const bin = join(f.dir, 'bin');
  writeFileSync(join(bin, 'dbus-run-session'), '#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$CAPTURE"\n');
  chmodSync(join(bin, 'dbus-run-session'), 0o700);
  const config = '/nix/store/fixture dbus/share/dbus-1/session.conf';
  const run = spawnSync('bash', ['-c', command], { env: { ...f.env, DBUS_SESSION_CONF: config }, encoding: 'utf8' });
  assert.equal(run.status, 0, run.stderr);
  assert.deepEqual(readFileSync(f.capture, 'utf8').trim().split('\n'), ['--config-file=' + config, '--', 'bash', '/tmp/keyring-smoke.sh']);
  rmSync(f.capture);
  const missing = spawnSync('bash', ['-c', command], { env: { ...f.env, DBUS_SESSION_CONF: '' }, encoding: 'utf8' });
  assert.notEqual(missing.status, 0);
  assert.match(missing.stderr, /packaged session bus config required/);
  assert.throws(() => readFileSync(f.capture));
 } finally { rmSync(f.dir, { recursive: true, force: true }); }
});

test('real image exposes gdbus and checks all encrypted fixture prerequisites', () => {
 const flake = readFileSync(new URL('../flake.nix', import.meta.url), 'utf8');
 const runtime = flake.slice(flake.indexOf('runtime = pkgs.writeShellApplication'), flake.indexOf('# Test the real Secret Service'));
 assert.ok(runtime.includes('pkgs.glib.bin'));
 const image = readFileSync(new URL('./keyring-capability-image-smoke.sh', import.meta.url), 'utf8');
 for (const tool of ['bash', 'dbus-send', 'dbus-run-session', 'gdbus', 'gnome-keyring-daemon', 'secret-tool', 'python3', 'stat', 'find', 'grep', 'sed', 'timeout', 'seq']) {
  assert.ok(image.includes(tool), tool);
 }
 assert.ok(image.includes('command -v "$tool"'));
 assert.ok(image.includes('missing encrypted fixture tool: $tool'));
 assert.ok(image.includes('exit 1; }'));
});

test('real daemon smoke checks persisted file UID/0600 and rejects nonregular/symlink files', () => {
 const smoke = readFileSync(new URL('./keyring-smoke.sh', import.meta.url), 'utf8');
 const fn = smoke.slice(smoke.indexOf('check_keyring_files() {'), smoke.indexOf('has_service() {'));
 assert.ok(fn.includes('info.st_uid == os.getuid()'));
 assert.ok(smoke.split('\n').filter(x => x === 'check_keyring_files').length >= 4);
 const f = fixture();
 try {
  const dir = join(f.home, '.local/share/keyrings'); mkdirSync(dir, { recursive: true });
  const file = join(dir, 'synthetic.keyring'); writeFileSync(file, 'synthetic-canary', { mode: 0o600 });
  const run = () => spawnSync('bash', ['-c', fn + '\ncheck_keyring_files'], { env: f.env, encoding: 'utf8' });
  assert.equal(run().status, 0);
  chmodSync(file, 0o644); assert.notEqual(run().status, 0);
  rmSync(file); const target = join(f.dir, 'target'); writeFileSync(target, 'synthetic-canary', { mode: 0o600 });
  symlinkSync(target, file); assert.notEqual(run().status, 0);
  rmSync(file); mkdirSync(file); assert.notEqual(run().status, 0);
  rmSync(file, { recursive: true }); assert.notEqual(run().status, 0);
 } finally { rmSync(f.dir, { recursive: true, force: true }); }
});
