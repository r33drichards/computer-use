"""Whitelisted fixture metadata only: never log response bodies/errors/env."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

STAGES = {'contract','source','image','network','files','opa-create','http-create','http-ready','opa-ready','grant-spoof','mcp-create','mcp-ready','native','module','probe','counter','mode-complete','complete'}
MODES = {'restrictive','unrestricted','undefined','legacy','grant-wrongtype','wrongtype','error','timeout'}
INPUTS = ('images/mcp-js/test-module-policy-image.py','images/mcp-js/test-module-http.py','images/mcp-js/module_fixture_receipt.py','images/mcp-js/modules.rego','images/mcp-js/Dockerfile','docs/contracts/policy/decision-module.rego.tmpl','.github/workflows/images.yml')

def private_write(path, payload):
    encoded = json.dumps(payload, sort_keys=True).encode()
    if len(encoded) > 8192: raise ValueError('receipt byte cap')
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent = path.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid(): raise OSError('unsafe receipt directory')
    path.parent.chmod(0o700)
    if os.path.lexists(path):
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1: raise OSError('unsafe receipt inode')
        finally: os.close(fd)
    fd, temporary = tempfile.mkstemp(prefix='.fixture-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream: stream.write(encoded)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)

class Receipt:
    def __init__(self, path, expected, run, job):
        if not re.fullmatch('[0-9a-f]{40}', expected) or not re.fullmatch('[0-9]{1,20}', run) or not re.fullmatch('[a-zA-Z0-9_-]{1,64}', job): raise ValueError('receipt association')
        source, tree = subprocess.check_output(['git','rev-parse','HEAD','HEAD^{tree}'],text=True,timeout=5).splitlines()
        if source != expected: raise ValueError('receipt source mismatch')
        if subprocess.call(['git','diff','--quiet']) or subprocess.call(['git','diff','--cached','--quiet']): raise ValueError('receipt tracked source dirty')
        self.path = path
        self.data = {'schemaVersion':1,'source':source,'tree':tree,'runId':run,'job':job,'imageTag':'mcp-js:ci','mcpPin':'723fe32d4cc31c18f8255af2639059f7d8450324','opaPin':'sha256:60b6af32b58377718546ac7d4634eecbfe50ec36f7d3ca3f8ebf515f9826c2ac','inputs':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in INPUTS},'stage':'source','mode':None,'operation':None,'status':'running','reason':'none','exitCode':None,'counterBefore':None,'counterAfter':None,'imageId':None,'imageSource':None}
        self.flush()
    def flush(self): private_write(self.path, self.data)
    def mark(self, stage, mode=None, operation=None):
        if stage not in STAGES or (mode is not None and mode not in MODES) or (operation is not None and (type(operation) is not int or not 0<=operation<=16)): raise ValueError('receipt stage')
        if mode != self.data.get('mode'):
            self.data.update(counterBefore=None,counterAfter=None)
        self.data.update(stage=stage,mode=mode,operation=operation); self.flush()
    def counter(self, key, value):
        if key not in ('counterBefore','counterAfter') or type(value) is not int or not 0<=value<=2147483647: raise ValueError('receipt counter')
        self.data[key]=value; self.flush()
    def image(self, source, ident):
        if not re.fullmatch('[0-9a-f]{40}', source) or not re.fullmatch('sha256:[0-9a-f]{64}', ident): raise ValueError('image metadata shape')
        self.data.update(imageSource=source,imageId=ident); self.flush()
        if source != self.data['source']: raise AssertionError('image source mismatch')
    def fail(self, error):
        # Fixed reasons, not exception text or arbitrary stdout/stderr.
        reason = 'assertion' if isinstance(error, AssertionError) else 'docker-exit' if isinstance(error, subprocess.CalledProcessError) else 'process-timeout' if isinstance(error, subprocess.TimeoutExpired) else 'io-or-http' if isinstance(error, OSError) else 'schema-or-json' if isinstance(error, (ValueError,TypeError,KeyError)) else 'unknown'
        self.data.update(status='failure',reason=reason,exitCode=1); self.flush()
    def complete(self):
        self.mark('complete'); self.data.update(status='success',reason='none',exitCode=0); self.flush()

if __name__ == "__main__":
    import sys
    Receipt(*sys.argv[1:5]).mark("contract")
