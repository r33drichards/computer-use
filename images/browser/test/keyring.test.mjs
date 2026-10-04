import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, readdirSync, statSync, chmodSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

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
 assert.match(flake, /gnome-keyring = pkgs.gnome-keyring.override \{ useWrappedDaemon = false; \}/);
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
 assert.match(smoke, /pid=\$!\nwait_service\nwait_unlocked\nstop\nstart\nlocked/);
 assert.equal((smoke.match(/^locked$/gm) || []).length, 2);
 assert.match(smoke, /secret-tool store/);
 assert.match(smoke, /Secret appeared unencrypted on disk/);
 assert.equal((smoke.match(/secret-tool lookup/g) || []).length, 2);
 const runtime = readFileSync(helper, 'utf8');
 assert.doesNotMatch(runtime, /--unlock|--login/);
});
