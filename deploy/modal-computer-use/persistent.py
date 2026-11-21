"""Disk-only, single-writer checkpoint service for the existing MCP gateway."""
import base64
import json
import time
import uuid

import modal

# The Sandbox exposes no port. The bridge runs only over Modal's authenticated
# control plane and has a fixed upstream target. Never send owner auth to it.
BRIDGE = r"""
import base64,http.client,json,sys
r=json.load(sys.stdin)
allowed={'accept','content-type','mcp-session-id','mcp-protocol-version','last-event-id'}
headers={k:v for k,v in r['headers'].items() if k in allowed}
if r['method'] not in {'POST','DELETE'}: raise ValueError('invalid method')
c=http.client.HTTPConnection('127.0.0.1',8080,timeout=103)
c.request(r['method'],'/mcp',base64.b64decode(r['body'],validate=True),headers)
res=c.getresponse()
print(json.dumps({'status':res.status,'headers':dict(res.getheaders())}),flush=True)
while chunk:=res.read1(8192): print(base64.b64encode(chunk).decode(),flush=True)
c.close()
"""

# Controller and MCP run as distinct principals. No cloud credential, API
# bearer, or shared host mount is passed into this Sandbox.
BOOT = r"""
import asyncio,os,pathlib,signal,sys
import httpx
from runtime import *
slot=sys.argv[1]
pid=pathlib.Path('/run/'+slot+'.pid')
status=pathlib.Path('/run/'+slot+'.status')
async def main():
    loop=asyncio.get_running_loop()
    event=asyncio.Event()
    wants_run=True
    def request(run):
        nonlocal wants_run
        wants_run=run; event.set()
    loop.add_signal_handler(signal.SIGUSR1,request,False)
    loop.add_signal_handler(signal.SIGUSR2,request,True)
    status.write_text('starting')
    temporary=pid.with_suffix('.tmp')
    temporary.write_text(str(os.getpid())); temporary.chmod(0o600)
    temporary.replace(pid)
    desktop=mcp=None
    async with httpx.AsyncClient(trust_env=False) as client:
      try:
        while True:
          event.clear()
          if wants_run and desktop is None:
            status.write_text('starting')
            # The previous filesystem snapshot contains no live X server.
            for f in ('/tmp/.X99-lock','/tmp/.X11-unix/X99'):
                pathlib.Path(f).unlink(missing_ok=True)
            prepare_files()
            desktop=start_unprivileged('/desktop-entrypoint',DESKTOP_UID,desktop_env(),BROWSER_STATE)
            await wait_ready(client,desktop,BROWSER+'/healthz',30)
            mcp=start_unprivileged('/usr/local/bin/mcp-v8',MCP_UID,mcp_env(),MCP_STATE)
            await wait_ready(client,mcp,MCP+'/api/artifacts',30)
            status.write_text('ready')
          if not wants_run and desktop is not None:
            status.write_text('draining')
            # Desktop entrypoint handles a graceful Chromium shutdown.
            await asyncio.to_thread(terminate,mcp)
            await asyncio.to_thread(terminate,desktop)
            desktop=mcp=None
            status.write_text('drained')
          try: await asyncio.wait_for(event.wait(),.5)
          except TimeoutError: pass
          if desktop is not None and (desktop.poll() is not None or mcp.poll() is not None):
            raise RuntimeError('desktop runtime exited')
      finally:
        terminate(mcp);terminate(desktop)
asyncio.run(main())
"""
CONTROL = r"""
import os,pathlib,signal,sys,time
wanted,slot=sys.argv[1:]
p=pathlib.Path('/run/'+slot+'.pid')
s=pathlib.Path('/run/'+slot+'.status')
if wanted not in ('ready','drained'): raise ValueError('invalid desktop state')
for _ in range(300):
    if p.exists(): break
    time.sleep(.2)
else: raise RuntimeError('desktop supervisor not found')
os.kill(int(p.read_text()),signal.SIGUSR2 if wanted=='ready' else signal.SIGUSR1)
for _ in range(300):
    if s.exists() and s.read_text()==wanted: break
    time.sleep(.2)
else: raise RuntimeError('desktop did not reach expected state')
"""
BUSY = r"""
import pathlib
for d in pathlib.Path('/proc').iterdir():
    if not d.name.isdigit(): continue
    try:
        if (d/'comm').read_text().strip()!='mcp-exec': continue
        kids=d/'task'/d.name/'children'
        if kids.read_text().strip(): print('busy'); break
    except OSError: continue
"""

async def command(box, code, *args, timeout=65):
    p = await box.exec.aio('python3', '-c', code, *args, timeout=timeout)
    output = await p.stdout.read.aio()
    if await p.wait.aio() != 0:
        raise RuntimeError("private desktop supervisor command failed")
    return output


class Controller:
    """Owns exactly one named desktop. Caller serializes all methods."""

    def __init__(self, app_name, app, image, state, *, idle=600, block_network=False):
        self.app_name, self.app, self.image, self.state = app_name, app, image, state
        self.idle, self.block_network = idle, block_network

    async def record(self):
        return (await self.state.get.aio("desktop")) or {"fresh": True, "active": None, "disk": None, "last": 0}

    async def save(self, row, **changes):
        row = dict(row, **changes)
        await self.state.put.aio("desktop", row)
        return row

    async def active(self):
        row = await self.record()
        if row["active"]:
            try:
                box = await modal.Sandbox.from_id.aio(row["active"])
                if await box.poll.aio() is None:
                    return box
            except modal.exception.NotFoundError:
                pass
        # Recover an interrupted create only where Modal supports named lookup.
        # If create later reports an existing name, propagate instead of starting
        # a second desktop or relabeling an unknown generation.
        if not row.get("slot"):
            return None
        try:
            box = await modal.Sandbox.from_name.aio(self.app_name, row["slot"])
        except modal.exception.NotFoundError:
            return None
        return box if await box.poll.aio() is None else None

    async def ensure(self):
        row = await self.record()
        box = await self.active()
        if box is not None:
            if row["active"] not in (None, box.object_id):
                raise RuntimeError("conflicting desktop generation")
        else:
            if not row["fresh"] and not row["disk"]:
                raise RuntimeError("checkpoint missing: refusing empty workspace")
            image = modal.Image.from_id(row["disk"]) if row["disk"] else self.image
            if row["active"] or not row.get("slot"):
                row = await self.save(row, active=None, slot="owner-desktop-" + uuid.uuid4().hex[:16])
            box = await modal.Sandbox.create.aio(
                "python3", "-u", "-c", BOOT, row["slot"], app=self.app, image=image, name=row["slot"],
                timeout=86400, cpu=1.5, memory=3072, block_network=self.block_network,
            )
        # Store the binding before exposing any mutable session to the owner.
        row = await self.save(row, active=box.object_id, fresh=False, last=time.time())
        await command(box, CONTROL, "ready", row["slot"])
        if not row["disk"]:
            await self.seal(box, row, keep=True)
        return box

    async def seal(self, box, row, *, keep=False):
        # Mark the verified old checkpoint authoritative until replacement is
        # committed. A failed snapshot resumes this same desktop, not an empty one.
        await command(box, CONTROL, "drained", row["slot"])
        try:
            image = await box.snapshot_filesystem.aio(timeout=55, ttl=30*86400)
            row = await self.save(row, disk=image.object_id)
        except Exception:
            await command(box, CONTROL, "ready", row["slot"])
            raise
        if keep:
            await command(box, CONTROL, "ready", row["slot"])
        else:
            await box.terminate.aio()
            await self.save(row, active=None, slot=None)
        return row

    async def checkpoint_if_idle(self):
        row = await self.record()
        if not row["active"] or time.time()-row["last"] < self.idle or time.time() < row.get("bridge_deadline", 0):
            return False
        box = await self.active()
        if box is None:
            await self.save(row, active=None, slot=None)
            return False
        if box.object_id != row["active"]:
            raise RuntimeError("conflicting desktop generation")
        if (await command(box, BUSY, timeout=5)).strip() == "busy":
            return False
        await self.seal(box, row)
        return True

    async def exchange(self, method, headers, body):
        box = await self.ensure()
        await self.save(await self.record(), bridge_deadline=time.time()+112)
        p = await box.exec.aio("python3", "-c", BRIDGE, timeout=105)
        packet = json.dumps({"method":method, "headers":headers, "body":base64.b64encode(body).decode()})
        p.stdin.write(packet.encode())
        p.stdin.write_eof()
        await p.stdin.drain.aio()
        stream = framed_lines(p.stdout).__aiter__()
        yield json.loads(await anext(stream))
        remaining = 8*1024*1024
        async for line in stream:
            chunk = base64.b64decode(line, validate=True)
            remaining -= len(chunk)
            if remaining < 0:
                raise RuntimeError("desktop response limit exceeded")
            yield chunk
        if await p.wait.aio() != 0:
            raise RuntimeError("private desktop transport failed")
        row = await self.record()
        await self.save(row, last=time.time(), bridge_deadline=0)


async def framed_lines(stream):
    # Modal streams arbitrary chunks, not physical lines. Framing must also
    # tolerate coalescing of status + body and fragmentation of either.
    pending = ""
    async for chunk in stream:
        pending += chunk
        *lines, pending = pending.split("\n")
        for line in lines:
            if not line or len(line) > 32*1024:
                raise RuntimeError("invalid desktop frame")
            yield line
        if len(pending) > 32*1024:
            raise RuntimeError("invalid desktop frame")
    if pending:
        raise RuntimeError("partial desktop frame")
