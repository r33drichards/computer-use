"""Bounded stdout capture; stderr discarded, only our child group terminated."""
import os
import selectors
import signal
import subprocess
import time

class OutputLimitExceeded(RuntimeError):
    pass

def run_bounded(args, *, timeout, max_bytes, **kwargs):
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True, **kwargs)
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
    data = bytearray()
    deadline = time.monotonic() + timeout
    complete = False
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0: raise subprocess.TimeoutExpired('bounded child', timeout)
            for key, _ in selector.select(remaining):
                chunk = os.read(key.fileobj.fileno(), min(4096, max_bytes - len(data) + 1))
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                if len(data) + len(chunk) > max_bytes: raise OutputLimitExceeded('byte-limit')
                data.extend(chunk)
        proc.wait(timeout=max(0.001, deadline - time.monotonic()))
        complete = True
        return subprocess.CompletedProcess(args, proc.returncode, data.decode('utf-8', errors='replace'))
    finally:
        selector.close()
        if not complete:
            try: os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            proc.wait()
        proc.stdout.close()
