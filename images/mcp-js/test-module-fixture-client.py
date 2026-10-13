import importlib.util
import http.server
import json
from pathlib import Path
import threading
import unittest
import urllib.request
spec=importlib.util.spec_from_file_location('client',Path(__file__).with_name('module_fixture_client.py'))
client=importlib.util.module_from_spec(spec); spec.loader.exec_module(client)
class HTTP(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        raw=(b'x'*65537 if self.path=='/count' else b'{"status":"completed"}')
        self.send_response(200); self.end_headers(); self.wfile.write(raw)
    def do_POST(self):
        data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        raw=json.dumps({'execution_id':'synthetic-owned','echo':data['code']}).encode()
        self.send_response(202); self.end_headers(); self.wfile.write(raw)
class Transport(unittest.TestCase):
    def test_real_dummy_http_post_get_and_response_cap(self):
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),HTTP)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        class Local:
            def open(self,req,timeout):
                url='http://127.0.0.1:'+str(server.server_port)+urllib.request.urlparse(req.full_url).path
                return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(urllib.request.Request(url,data=req.data,headers={'Content-Type':'application/json'}),timeout=timeout)
        try:
            out=client.probe({'url':'http://mcp:8080/api/exec','data':{'code':'synthetic'}},Local())
            self.assertEqual(out['result']['execution_id'],'synthetic-owned')
            out=client.probe({'url':'http://mcp:8080/api/executions/synthetic-owned'},Local())
            self.assertEqual(out['result']['status'],'completed')
            with self.assertRaises(ValueError): client.probe({'url':'http://fixture:8080/count'},Local())
        finally: server.shutdown(); server.server_close(); thread.join()
    def test_fixed_alias_transport_rejects_external_credentials_scheme_port_path(self):
        for url in ('http://example.com:8080/health','https://mcp:8080/api/exec','http://user:password@mcp:8080/api/exec','http://mcp:1234/api/exec','http://mcp:8080/not-approved'):
            with self.assertRaises(ValueError): client.probe({'url':url})
    def test_request_cap_before_open(self):
        with self.assertRaises(ValueError): client.probe({'url':'http://mcp:8080/api/exec','data':{'code':'x'*8192}})
    def test_fixture_source_keeps_internal_nonroot_caps_and_controls_without_publish(self):
        text=Path('images/mcp-js/test-module-policy-image.py').read_text()
        self.assertIn("'--internal'",text);self.assertNotIn("'-p'",text);self.assertNotIn("docker('port'",text)
        self.assertIn("'--user','1000:1000'",text);self.assertIn("'--cap-drop','ALL'",text)
        self.assertEqual(text.count('net.ipv4.ip_unprivileged_port_start=0'),1)
        for gate in ('npm:synthetic-fixture@1.0.0','jsr:@synthetic/fixture@1.0.0','/parent.js?synthetic=','esm.sh transport trap positive control failed','module transport escaped policy','private TLS namespace control failed'):
            self.assertIn(gate,text)
if __name__=='__main__': unittest.main()
