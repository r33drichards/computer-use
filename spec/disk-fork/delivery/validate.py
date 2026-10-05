#!/usr/bin/env python3
"""Serial final-source validation with persistent bounded per-lane scratch."""
import pathlib,subprocess,os,json,hashlib,sys,time,shutil
ROOT=pathlib.Path(__file__).resolve().parents[3]
GO=ROOT/'.tools/go/bin/go'
ENV=dict(os.environ,GOTOOLCHAIN='local',GOCACHE=str(ROOT/'.tools/gocache'),GOMODCACHE=str(ROOT/'.tools/gomod'),GOTMPDIR=str(ROOT/'.tools/tmp'),TMPDIR=str(ROOT/'.tools/tmp'),GOPATH=str(ROOT/'.tools/gopath'),CGO_ENABLED='1',CC='/nix/store/z4c6k0mrlkwl3s4w9ysxc8vq1wylm3ms-gcc-wrapper-15.3.0/bin/cc',GOMAXPROCS='2',PYTHONDONTWRITEBYTECODE='1')
paths=sorted(list((ROOT/'backend').rglob('*.go'))+list((ROOT/'test/disk-fork').glob('*.py'))+[ROOT/'backend/go.mod'])
def hashes():return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
start_hashes=hashes();report={'source_sha256':start_hashes,'commands':[],'complete':False,'prior_interruption':'exec3718b813-df1f-4584-a52e-4f5e6500914c failed:interrupted: the session restarted while the command was running'}
OUT=ROOT/'spec/disk-fork/delivery/VALIDATION.json'
LOG=ROOT/'.tools/final-validation.log'
def run(args,cwd=ROOT/'backend',visible=True):
 start=time.time()
 with LOG.open('ab') as log:
  log.write(('COMMAND '+json.dumps(args)+'\n').encode());log.flush()
  p=subprocess.run(args,cwd=cwd,env=ENV,stdout=log,stderr=subprocess.STDOUT)
 item={'command':args,'returncode':p.returncode,'seconds':round(time.time()-start,2),'cwd':str(cwd)};report['commands'].append(item)
 OUT.write_text(json.dumps(report,indent=2)+'\n')
 if visible or p.returncode:print(json.dumps(item),flush=True)
 if p.returncode:raise SystemExit(p.returncode)
def list_json(args):
 p=subprocess.run(args,cwd=ROOT/'backend',env=ENV,capture_output=True,text=True)
 if p.returncode:print(p.stderr);raise SystemExit(p.returncode)
 return p.stdout
# Warming each library individually avoids retaining all newly-built archives
# twice in a single enormous go-build directory while filling the cache.
text=list_json([str(GO),'list','-deps','-test','-json','./...']);dec=json.JSONDecoder();deps=[]
while text.strip():
 obj,pos=dec.raw_decode(text.lstrip());text=text.lstrip()[pos:]
 name=obj['ImportPath']
 if obj.get('DepOnly') and not obj.get('Standard') and obj.get('Name')!='main' and '[' not in name and not name.endswith('.test') and name not in deps:deps.append(name)
print('Warming '+str(len(deps))+' libraries, serially',flush=True)
for i,name in enumerate(deps):
 run([str(GO),'build','-race','-p=1',name],visible=False)
 if (i+1)%25==0:print('Warm libraries: '+str(i+1)+'; free bytes '+str(shutil.disk_usage(ROOT).free),flush=True)
packages=list_json([str(GO),'list','./...']).splitlines()
first=['github.com/r33drichards/computer-use/backend/internal/auth','github.com/r33drichards/computer-use/backend/internal/api','github.com/r33drichards/computer-use/backend/internal/diskfork','github.com/r33drichards/computer-use/backend/cmd/server']
ordered=first+[p for p in packages if p not in first]
for package in ordered:
 run([str(GO),'vet','-race','-p=1',package])
 run([str(GO),'test','-race','-p=1','-count=1',package])
run(['python3','-m','unittest','discover','-s','test/disk-fork','-v'],cwd=ROOT)
run(['git','diff','--check'],cwd=ROOT)
report['source_unchanged']=hashes()==start_hashes
report['packages_checked']=ordered
report['complete']=report['source_unchanged']
report['free_bytes_after']=shutil.disk_usage(ROOT).free
OUT.write_text(json.dumps(report,indent=2)+'\n')
if not report['complete']:raise SystemExit('source changed during validation')
print('PASS all '+str(len(ordered))+' backend packages: explicit vet + race tests; Python offline tests and diff check; final sources unchanged',flush=True)
