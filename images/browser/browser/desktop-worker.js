// The process nut.js runs in (see desktop.js for why it is not the server).
// One message in, one out: { id, size, operations, config } ->
// { id, results, images, screen, released? } or { id, error }.

import { runOperations } from './desktop.js';

let nutPromise = null;

// Loaded on the first call, so a platform the native addon has no build for
// answers with the reason instead of failing to start.
function loadNut() {
  nutPromise ||= import('@nut-tree-fork/nut-js').then((m) => m.default);
  return nutPromise;
}

let nextSeq = 1;
const acknowledgments = new Map();
function reportHeld(id, held) {
  return new Promise((resolve, reject) => {
    const seq = nextSeq++;
    acknowledgments.set(seq, resolve);
    process.send({ id, seq, held }, (err) => {
      if (!err) return;
      acknowledgments.delete(seq);
      reject(err);
    });
  });
}

process.on('message', async (msg) => {
  if (msg.ackHeld !== undefined) {
    const resolve = acknowledgments.get(msg.ackHeld);
    acknowledgments.delete(msg.ackHeld);
    resolve?.();
    return;
  }
  try {
    let nut;
    try {
      nut = await loadNut();
    } catch (err) {
      nutPromise = null;
      throw new Error(`nut.js could not be loaded (${process.platform}/${process.arch}, DISPLAY=${process.env.DISPLAY || ''}): ${err.message || err}`);
    }
    if (msg.recoverHeld) {
      const { keys, buttons } = msg.recoverHeld;
      if (keys.length) await nut.keyboard.releaseKey(...[...keys].reverse().map((name) => nut.Key[name]));
      for (const name of buttons) await nut.mouse.releaseButton(nut.Button[name]);
      process.send({ id: msg.id, recovered: true });
      return;
    }
    process.send({ id: msg.id, ...(await runOperations(nut, msg, {
      size: msg.size || undefined, reportHeld: (held) => reportHeld(msg.id, held),
    })) });
  } catch (err) {
    process.send({ id: msg.id, error: (err && err.message) || String(err) });
  }
});

// The server went away: nothing left to answer to.
process.on('disconnect', () => process.exit(0));
