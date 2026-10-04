import importlib.util,pathlib,unittest
from unittest.mock import patch
spec=importlib.util.spec_from_file_location("preflight",pathlib.Path(__file__).with_name("preflight.py"))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Response:
    def __init__(self,status,body):self.status,self.body=status,body
    def __enter__(self):return self
    def __exit__(self,*a):pass
    def read(self):return self.body
class TestProbe(unittest.TestCase):
    def test_api_host_disabled_surface(self):
        with patch.object(m.urllib.request,"build_opener") as opener:
            opener.return_value.open.return_value=Response(501,b'{"code":"disk_fork_disabled"}')
            m.probe("https://example.invalid","s-aaaaaaaaaa","test-only-token")
            self.assertEqual(opener.return_value.open.call_count,1)
            paths=[c.args[0].full_url for c in opener.return_value.open.call_args_list]
            self.assertEqual(paths,["https://example.invalid/v1/sessions/s-aaaaaaaaaa/fork"])
    def test_enabled_success_is_rejected(self):
        with patch.object(m.urllib.request,"build_opener") as opener:
            opener.return_value.open.return_value=Response(202,b'{}')
            with self.assertRaises(RuntimeError):m.probe("https://example.invalid","s-aaaaaaaaaa","test-only-token")
    def test_plaintext_and_redirect_refused(self):
        with self.assertRaises(ValueError):m.probe("http://example.invalid","s-aaaaaaaaaa","test-only-token")
        self.assertIsNone(m.NoRedirect().redirect_request(None,None,302,"",{},"https://other.invalid"))
if __name__=="__main__":unittest.main()
