"""Private-network stdio HTTP client. No proxy/env/header/error-body logging."""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None

LIMIT = 65536
TARGETS = {'fixture':8080,'opa':8181,'mcp':8080}
def probe(payload, opener=None):
    url=urllib.parse.urlsplit(payload['url'])
    if url.scheme!='http' or url.hostname not in TARGETS or url.port!=TARGETS[url.hostname] or url.username or url.password or url.fragment:
        raise ValueError('url-refused')
    if not (url.path in ('/count','/control','/health','/api/exec') or url.path.startswith('/api/executions/') or url.path.startswith('/v1/data/browserjs/decision/')):
        raise ValueError('path-refused')
    body=None if payload.get('data') is None else json.dumps(payload['data']).encode()
    if body is not None and len(body)>8192: raise ValueError('input-cap')
    req=urllib.request.Request(payload['url'],data=body,headers={'Content-Type':'application/json'})
    opener=opener or urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    with opener.open(req,timeout=3) as response:
        raw=response.read(LIMIT+1)
        if len(raw)>LIMIT: raise ValueError('response-cap')
        result=json.loads(raw)
    output={'ok':True,'result':result}
    if len(json.dumps(output).encode())>LIMIT: raise ValueError('response-cap')
    return output

def main():
    try:
        raw=sys.stdin.buffer.read(8193)
        if len(raw)>8192: raise ValueError('input-cap')
        output=probe(json.loads(raw))
    except urllib.error.HTTPError:
        output={'ok':False,'reason':'http-error'}
    except (ValueError,TypeError,KeyError):
        output={'ok':False,'reason':'protocol-error'}
    except OSError:
        output={'ok':False,'reason':'request-error'}
    sys.stdout.write(json.dumps(output))
if __name__=='__main__': main()
