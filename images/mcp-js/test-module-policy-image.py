"""Actual image/pinned loader + pinned real OPA, private dummy transport only."""
import json
import pathlib
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid

OPA = 'openpolicyagent/opa:1.9.0-static@sha256:60b6af32b58377718546ac7d4634eecbfe50ec36f7d3ca3f8ebf515f9826c2ac'
image = sys.argv[1]
prefix = 'module-smoke-' + uuid.uuid4().hex[:10]
owned = {}
network = None
def docker(*args):
    return subprocess.check_output(['docker', *args], timeout=60, text=True, stderr=subprocess.DEVNULL).strip()
def start(name, *args):
    ident = docker('create', '--name', name, *args)
    owned[name] = ident
    docker('start', ident)

def request(base, path, data=None):
    body = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(base + path, data=body, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=3) as response:
        raw = response.read(65537)
        assert len(raw) <= 65536, 'fixture response byte cap'
        return json.loads(raw)
def ready(base, path):
    for _ in range(60):
        try: request(base, path); return
        except Exception: time.sleep(0.25)
    raise AssertionError('fixture readiness deadline')
def execute(base, code):
    started = request(base, '/api/exec', {'code': code})
    ident = started.get('execution_id')
    assert ident, 'execution identifier required'
    for _ in range(80):
        result = request(base, '/api/executions/' + ident)
        if result.get('status') in ('completed', 'failed', 'timed_out', 'cancelled'): return result
        time.sleep(0.25)
    raise AssertionError('module execution deadline')
def port(name, service='8080/tcp'): return 'http://' + docker('port', name, service).splitlines()[0]
try:
    network = docker('network', 'create', '--internal', prefix)
    with tempfile.TemporaryDirectory(prefix=prefix) as tmp:
        directory = pathlib.Path(tmp); directory.chmod(0o755)
        decision = pathlib.Path('docs/contracts/policy/decision-module.rego.tmpl').read_text()
        for sid in ('s-abcdefghij', 's-klmnopqrst', 's-cdefghijkl', 's-defghijklm'):
            (directory/(sid+'.rego')).write_text(decision.replace('{{SESSION_ID}}', sid))
        (directory/'tenant.rego').write_text('package browserjs.tenant["s-abcdefghij"]\nimport rego.v1\ndefault allow_tool_call := false\nallow_tool_call if { input.operation == "fetch"; input.url_parsed.host == "allowed.fixture" }\n')
        (directory/'unrestricted.rego').write_text('package browserjs.tenant["s-klmnopqrst"]\nimport rego.v1\nallow_tool_call := true\nallow_unrestricted_modules := true\n')
        (directory/'wronggrant.rego').write_text('package browserjs.tenant["s-cdefghijkl"]\nimport rego.v1\nallow_tool_call := true\nallow_unrestricted_modules := "true"\n')
        (directory/'legacy.rego').write_text('package browserjs.tenant["s-defghijklm"]\nimport rego.v1\nallow_tool_call := true\n')
        opa = prefix+'-opa'
        start(opa, '--network', network, '--network-alias', 'opa', '--memory', '128m', '--cpus', '0.5', '--pids-limit', '64', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '-p', '127.0.0.1::8181', '-v', tmp+':/policies:ro', OPA, 'run', '--server', '--addr=0.0.0.0:8181', '/policies')
        fixture = prefix+'-http'
        start(fixture, '--network', network, '--network-alias', 'fixture', '--network-alias', 'esm.sh', '--memory', '128m', '--cpus', '0.5', '--pids-limit', '64', '--user', '1000:1000', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '-p', '127.0.0.1::8080', '-v', str(pathlib.Path('images/mcp-js/test-module-http.py').resolve())+':/fixture.py:ro', 'python:3.13-slim', 'python3', '-B', '/fixture.py')
        http = port(fixture); ready(http, '/count')
        opa_api = port(opa, '8181/tcp'); ready(opa_api, '/health')
        spoof = {'input': {'specifier':'http://fixture:8080/module.js', 'resolved_url':'http://fixture:8080/module.js','url_parsed':{'scheme':'http'},'allow_unrestricted_modules':True}}
        assert request(opa_api, '/v1/data/browserjs/decision/s-abcdefghij/mcp_tools', spoof).get('result',{}).get('allow') is False, 'input-supplied grant accepted'
        for mode, sid, remote in [('restrictive','s-abcdefghij','http://opa:8181'), ('unrestricted','s-klmnopqrst','http://opa:8181'), ('undefined','s-uvwxyzabcd','http://opa:8181'), ('legacy','s-defghijklm','http://opa:8181'), ('grant-wrongtype','s-cdefghijkl','http://opa:8181'), ('wrongtype','s-abcdefghij','http://fixture:8080'), ('error','s-abcdefghij','http://fixture:8080'), ('timeout','s-abcdefghij','http://fixture:8080')]:
            name = prefix+'-'+mode
            policy = {'modules': {'mode':'all','policies':[{'url':'file:///etc/mcp/modules.rego'},{'url':remote,'policy_path':'browserjs/decision/'+sid+('/'+mode if mode in ('error','timeout') else '/mcp_tools')}]}}
            start(name,'--network',network,'--memory','512m','--cpus','1','--pids-limit','128','--cap-drop','ALL','--security-opt','no-new-privileges','-p','127.0.0.1::8080','-e','MCP_V8_MCP_CONFIG=[]','-e','MCP_V8_POLICIES_JSON='+json.dumps(policy),'--entrypoint','/usr/local/bin/mcp-v8',image,'--allow-external-modules')
            api = port(name)
            for _ in range(60):
                try:
                    if execute(api, '1+1').get('status') == 'completed': break
                except Exception: time.sleep(0.25)
            else: raise AssertionError('MCP readiness deadline')
            assert execute(api, 'import path from "node:path"; console.log(path.basename("/synthetic/fixture"));')['status'] == 'completed', 'native builtin regressed'
            codes = ['import {value} from "http://fixture:8080/module.js?synthetic='+mode+'"; console.log(value);', 'import {value} from "http://fixture:8080/redirect?synthetic='+mode+'"; console.log(value);']
            codes.append('import {value} from "http://fixture:8080/parent.js?synthetic='+mode+'"; console.log(value);')
            if mode != 'unrestricted':
                codes += ['import x from "http://fixture:8080/invalid?synthetic=yes";', 'import x from "npm:synthetic-fixture@1.0.0";', 'import x from "jsr:@synthetic/fixture@1.0.0";', 'import x from "https://esm.sh/invalid?synthetic='+mode+'";']
            if mode == 'timeout': codes = codes[:1]
            before = request(http, '/count')
            for code in codes:
                result = execute(api, code)
                assert result['status'] == ('completed' if mode == 'unrestricted' else 'failed'), 'module policy outcome'
                if mode != 'unrestricted': assert 'Module ' in json.dumps(result), 'failure was not module hook denial'
            if mode == 'unrestricted':
                probe_before = request(http, '/count')
                probe = execute(api, 'import x from "https://esm.sh/transport-control?synthetic=yes";')
                assert probe['status'] == 'failed' and request(http, '/count') > probe_before, 'esm.sh transport trap positive control failed'
            after = request(http, '/count')
            assert (after > before) if mode == 'unrestricted' else (after == before), 'module transport escaped policy'
            print('ok actual module loader: ' + mode, flush=True)
            docker('rm','-f',owned[name]); del owned[name]
finally:
    for ident in reversed(list(owned.values())):
        try: docker('rm','-f',ident)
        except Exception: pass
    if network is not None:
        try: docker('network','rm',network)
        except Exception: pass
