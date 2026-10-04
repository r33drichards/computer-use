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
env=dict(os.environ,GOTOOLCHAIN='local',GOMAXPROCS='1',GOMEMLIMIT='384MiB',CGO_ENABLED='1',CC='/nix/store/z4c6k0mrlkwl3s4w9ysxc8vq1wylm3ms-gcc-wrapper-15.3.0/bin/cc',GOCACHE=str(root/'.tools/gocache'),GOMODCACHE=str(root/'.tools/gomod'),GOTMPDIR=str(root/'.tools/tmp'),TMPDIR=str(root/'.tools/tmp'),GOPATH=str(root/'.tools/gopath'))
commands=[['mod','tidy'],['vet','-p=1','./...'],['test','-race','-timeout=120s','-p=1','-json','./...']]
files=[p for p in (root/'backend').rglob('*') if p.is_file() and p.suffix in ['.go','.mod','.sum','.rego']]
report={'commands':[],'complete':False,'mode':'full backend vet/race/test serial; no quiescence or platform proof','selected_main':'55ba20bae6525c5ba5397bf108984feb3e38671b','source_sha256':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
out=root/'spec/disk-fork/delivery/MAIN55BA-FULL-VALIDATION.json'
for args in commands:
 args=[str(root/'.tools/go/bin/go')]+args;print('COMMAND '+json.dumps(args),flush=True)
 start=time.time()
 if '-json' in args:
  count=0;top=0;packages=set();p=subprocess.Popen(args,cwd=root/'backend',env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
  for line in p.stdout:
   try:e=json.loads(line)
   except json.JSONDecodeError:print(line,end='',flush=True);continue
   if e.get('Action')=='pass':
    if 'Test' in e:count+=1;top+=('/' not in e['Test'])
    else:packages.add(e['Package']);print('PACKAGE_PASS '+e['Package'],flush=True)
   if e.get('Action')=='fail':print(line,end='',flush=True)
  p.wait();report['test_counts']={'pass_events_including_subtests':count,'top_level_passes':top,'packages_passed':len(packages)}
 else:p=subprocess.run(args,cwd=root/'backend',env=env)
 
 report['commands'].append({'command':args,'returncode':p.returncode,'seconds':round(time.time()-start,2)});out.write_text(json.dumps(report,indent=2)+'\n')
 if p.returncode:raise SystemExit(p.returncode)
report['source_unchanged']=all(hashlib.sha256((root/p).read_bytes()).hexdigest()==h for p,h in report['source_sha256'].items());report['complete']=report['source_unchanged'];out.write_text(json.dumps(report,indent=2)+'\n')
print('PASS targeted admission slice' if report['complete'] else 'FAIL source changed',flush=True)
