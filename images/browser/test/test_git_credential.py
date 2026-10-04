import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import unittest

HELPER = Path(__file__).resolve().parents[1] / "browser/git-credential-computeruse.py"


class Handler(http.server.BaseHTTPRequestHandler):
    calls = []
    mode = "ok"

    def do_POST(self):
        self.calls.append((self.path, self.headers.get("Authorization"), json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
        if self.mode == "redirect":
            self.send_response(302)
            self.send_header("Location", self.server.redirect_url)
            self.end_headers()
            return
        if self.mode == "denied":
            self.send_response(403)
            self.end_headers()
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({"username": "alice", "password": "ghu_test"}).encode())

    def log_message(self, *args):
        pass


class HelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = "http://127.0.0.1:" + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        Handler.calls = []
        Handler.mode = "ok"
        self.env = {**os.environ, "CU_GITHUB_BROKER_URL": self.url, "CU_GITHUB_CREDENTIAL": "session-secret", "CU_GITHUB_SESSION": "s-aaaaaaaaaa", "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}

    def helper(self, operation="get", host="github.com"):
        return subprocess.run([sys.executable, str(HELPER), operation], input=f"protocol=https\nhost={host}\npath=alice/private.git\n\n", text=True, capture_output=True, env=self.env)

    def test_git_calls_helper_and_receives_credentials(self):
        # Exercise Git's actual credential protocol rather than just the adapter.
        helper = f"!{sys.executable} {HELPER}"
        result = subprocess.run(["git", "-c", "credential.helper=" + helper, "credential", "fill"], input="protocol=https\nhost=github.com\n\n", text=True, capture_output=True, env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("username=alice\npassword=ghu_test", result.stdout)
        self.assertEqual(Handler.calls[0][1], "Bearer session-secret")
        self.assertEqual(Handler.calls[0][2]["session"], "s-aaaaaaaaaa")
        self.assertNotIn("session-secret", result.stdout + result.stderr)

    def test_other_hosts_and_store_do_not_contact_broker(self):
        self.assertEqual(self.helper(host="evil.example").stdout, "")
        self.assertEqual(self.helper("store").stdout, "")
        self.assertEqual(self.helper("erase").stdout, "")
        self.assertEqual(Handler.calls, [])

    def test_disconnected_errors_do_not_print_credentials(self):
        Handler.mode = "denied"
        result = self.helper()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertNotIn("session-secret", result.stderr)

    def test_redirects_are_never_followed(self):
        Handler.mode = "redirect"
        self.server.redirect_url = self.url + "/leak"
        result = self.helper()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(Handler.calls), 1)


if __name__ == "__main__":
    unittest.main()
