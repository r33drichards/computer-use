import os,stat,fcntl,time,subprocess,pathlib,json,hashlib
root=pathlib.Path(__file__).resolve().parents[3]
d=pathlib.Path('/data/chrome/home/.cuse-coordination');st=d.lstat()
assert stat.S_ISDIR(st.st_mode) and not d.is_symlink() and st.st_uid==os.getuid() and (stat.S_IMODE(st.st_mode)&0o777)==0o700 and not (stat.S_IMODE(st.st_mode)&0o5000)
fd=os.open(str(d/'heavy-build.lock'),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600);st=os.fstat(fd);assert stat.S_ISREG(st.st_mode) and stat.S_IMODE(st.st_mode)==0o600 and st.st_uid==os.getuid()
end=time.monotonic()+60
while True:
 try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);break
 except BlockingIOError:
  if time.monotonic()>end:raise SystemExit('BLOCKED heavy lock bounded wait')
  time.sleep(1)
print('ACQUIRED shared lock (directory02700 access0700, lock0600); CPU1 memory384MiB; no warming',flush=True)
env=dict(os.environ,GOTOOLCHAIN='local',GOMAXPROCS='1',GOMEMLIMIT='384MiB',CGO_ENABLED='0',GOCACHE=str(root/'.tools/gocache'),GOMODCACHE=str(root/'.tools/gomod'),GOTMPDIR=str(root/'.tools/tmp'),TMPDIR=str(root/'.tools/tmp'),GOPATH=str(root/'.tools/gopath'))
commands=[['test','-timeout=30s','-p=1','./internal/diskfork'],['test','-timeout=30s','-p=1','./internal/sessions'],['test','-timeout=30s','-p=1','./internal/proxy'],['test','-timeout=30s','-p=1','./internal/api','-run','DiskFork'],['test','-timeout=30s','-p=1','./internal/auth','-run','DiskFork']]
files=list((root/'backend/internal/diskfork').glob('*.go'))+list((root/'backend/internal').rglob('*fork*.go'))+[root/'docs/contracts/disk-fork-coordination.md',root/'spec/disk-fork/delivery/validate_p2.py',root/'backend/go.mod',root/'backend/internal/sessions/store.go',root/'backend/internal/sessions/snapshots.go',root/'backend/internal/sessions/policy.go',root/'backend/internal/proxy/proxy.go',root/'backend/internal/proxy/billing.go',root/'backend/internal/proxy/files.go',root/'backend/internal/proxy/browser.go',root/'backend/internal/api/api.go',root/'backend/internal/auth/apihost.go',root/'backend/internal/auth/apihost_test.go',root/'backend/cmd/server/main.go',root/'backend/cmd/server/disk_fork_test.go']
report={'commands':[],'complete':False,'mode':'targeted serial; full/race suite deferred to public CI; no quiescence proof','source_sha256':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
out=root/'spec/disk-fork/delivery/P2-VALIDATION.json'
for args in commands:
 args=[str(root/'.tools/go/bin/go')]+args;print('COMMAND '+json.dumps(args),flush=True)
 start=time.time();p=subprocess.run(args,cwd=root/'backend',env=env)
 report['commands'].append({'command':args,'returncode':p.returncode,'seconds':round(time.time()-start,2)});out.write_text(json.dumps(report,indent=2)+'\n')
 if p.returncode:raise SystemExit(p.returncode)
report['source_unchanged']=all(hashlib.sha256((root/p).read_bytes()).hexdigest()==h for p,h in report['source_sha256'].items());report['complete']=report['source_unchanged'];out.write_text(json.dumps(report,indent=2)+'\n')
print('PASS targeted admission slice' if report['complete'] else 'FAIL source changed',flush=True)
