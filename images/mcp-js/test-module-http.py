# Private fixture: no credentials, request bodies or query data are logged.
import http.server
import socket
import threading
import time
import json
from pathlib import Path

count = 0
lock = threading.Lock()
def increment():
    global count
    with lock: count += 1
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        if self.path == '/control': body=json.dumps({'tlsListening':True,'privateNamespacePortStartZero':port_start_zero}).encode()
        elif self.path == '/count': body = str(count).encode()
        else:
            increment()
            if self.path.startswith('/redirect'):
                self.send_response(302); self.send_header('Location', '/module.js?redirect=synthetic'); self.end_headers(); return
            body = (b'import {value} from "/module.js?child=synthetic"; export {value};' if self.path.startswith('/parent') else (b'invalid javascript {{{' if self.path.startswith('/invalid') else b'export const value = 42;'))
        self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        if self.path.endswith('/timeout'): time.sleep(8)
        # Wrong-typed OPA response for error-chain test; not a module GET.
        body = b'{"result":"not-a-boolean"}'
        self.send_response(500 if self.path.endswith('/error') else 200); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
def tls_trap():
    while True:
        conn, _ = server.accept(); increment(); conn.close()
port_start_zero = Path('/proc/sys/net/ipv4/ip_unprivileged_port_start').read_text().strip() == '0'
assert port_start_zero, 'owned private namespace low-port setting required'
# Main-thread bind failure must fail readiness, never disable the transport trap.
server = socket.socket(); server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); server.bind(('0.0.0.0', 443)); server.listen()
threading.Thread(target=tls_trap, daemon=True).start()
http.server.ThreadingHTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
