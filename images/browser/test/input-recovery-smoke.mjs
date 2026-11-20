// Run on an isolated Xvnc/XFCE display. This sends keys to the focused window.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';

const [modulePath, receiptPath] = process.argv.slice(2);
const { createDesktop } = await import(pathToFileURL(modulePath));
const desktop = createDesktop({ timeoutMs: 3000 });
const op = (type, params) => ({ type, params });
const run = (...operations) => desktop({ operations });

try {
  // Start the worker outside the measured timeout and ensure the test terminal
  // is focused before either sending or attempting to deliver recovery input.
  assert.equal((await run(op('mouse.getPosition'))).isError, undefined);
  const target = execFileSync('xdotool', ['search', '--onlyvisible', '--name', '^DIPInputRecovery$'], { encoding: 'utf8' }).trim();
  assert.match(target, /^\d+$/);
  execFileSync('xdotool', ['windowactivate', '--sync', target], { timeout: 3000 });
  assert.equal(execFileSync('xdotool', ['getactivewindow'], { encoding: 'utf8' }).trim(), target);
  const stopped = await run(op('keyboard.pressKey', { keys: ['LeftControl'] }), op('sleep', { ms: 8000 }));
  assert.match(stopped.content[0].text, /took longer/);
  assert.equal(execFileSync('xdotool', ['getactivewindow'], { encoding: 'utf8' }).trim(), target);
  const typed = await run(op('keyboard.type', { text: 'typed-482' }), op('keyboard.type', { keys: ['Enter'] }));
  assert.equal(typed.isError, undefined, typed.content[0].text);
  const pasted = await run(
    op('clipboard.setContent', { text: 'pasted-736' }),
    op('keyboard.pressKey', { keys: ['LeftControl', 'LeftShift', 'V'] }),
    op('keyboard.releaseKey', { keys: ['V', 'LeftShift', 'LeftControl'] }),
    op('keyboard.type', { keys: ['Enter'] }),
  );
  assert.equal(pasted.isError, undefined, pasted.content[0].text);
  let received = '';
  for (let i = 0; i < 20; i++) {
    try { received = readFileSync(receiptPath, 'utf8'); } catch (err) { if (err.code !== 'ENOENT') throw err; }
    if (received.split('\n').length >= 3) break;
    await delay(200);
  }
  assert.equal(received, 'typed-482\npasted-736\n');
  console.log('PASS: real XFCE terminal received typed and pasted text after a forced Ctrl-down worker timeout.');
} finally {
  desktop.stop();
}
