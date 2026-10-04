#!/usr/bin/env python3
"""Read-only cluster prerequisites and disabled API probe, NOT live fork E2E."""
import argparse,json,os,subprocess,urllib.request,urllib.error

def probe(base,source,token):
    if not base.startswith("https://"):
        raise ValueError("HTTPS required; never send credentials over plaintext")
    for prefix in ("/v1",):
        req=urllib.request.Request(base.rstrip("/")+prefix+"/sessions/"+source+"/fork",
                                   data=b"{}",method="POST",headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"})
        # No redirects: a redirect must never forward the credential.
        opener=urllib.request.build_opener(NoRedirect())
        try:
            with opener.open(req,timeout=15) as response:
                status,body=response.status,response.read()
        except urllib.error.HTTPError as e:
            status,body=e.code,e.read()
        if status!=501 or json.loads(body).get("code")!="disk_fork_disabled":
            raise RuntimeError("disabled fork contract violated")

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        return None

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base",required=True,help="API_URL host, not the Pomerium app host")
    parser.add_argument("--source",required=True)
    parser.add_argument("--namespace",required=True)
    parser.add_argument("--cluster-prerequisites",action="store_true")
    args=parser.parse_args()
    token=os.environ.get("DISK_FORK_TOKEN","")
    if not token:raise RuntimeError("DISK_FORK_TOKEN required; do not pass secrets in argv")
    if args.cluster_prerequisites:
        for crd in ("sandboxes.agents.x-k8s.io","volumesnapshots.snapshot.storage.k8s.io","volumesnapshotclasses.snapshot.storage.k8s.io","volumesnapshotcontents.snapshot.storage.k8s.io"):
            subprocess.run(["kubectl","get","crd",crd,"-o","name"],check=True)
        for kind in ("volumesnapshotclasses","persistentvolumeclaims","sandboxes"):
            subprocess.run(["kubectl","get",kind,"-n",args.namespace,"-o","name"],check=True)
    probe(args.base,args.source,token)
    print("PASS: disabled API contract only; live fork E2E remains blocked")

if __name__=="__main__":main()
