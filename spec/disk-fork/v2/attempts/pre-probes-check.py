#!/usr/bin/env python3
"""Formal-only bounded sequential TLC runs. Immutable per-run evidence binding."""
import pathlib,hashlib,json,os,subprocess,time,uuid,re,sys
HERE=pathlib.Path(__file__).resolve().parent
TOOLS=pathlib.Path('/data/chrome/home/.cache/disk-fork-tlc')
PIN={'tla2tools.jar':'c2fe4e56e43bde19f213b4a7e441d037297fda733e503579623e859b79348239','jre.tar.gz':'4086cc7cb2d9e7810141f255063caad10a8a018db5e6b47fa5394c506ab65bff'}
LOADER='/nix/store/lm3pknxi0ipypy3lxh1wmm8wvvavdwrn-glibc-2.42-84/lib/ld-linux-x86-64.so.2'
TIMEOUT=int(os.environ.get('DISK_FORK_TIMEOUT','180'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
for cfg in sys.argv[1:]:
 for n,h in PIN.items():
  if sha(TOOLS/n)!=h:raise SystemExit('BLOCKED: tool hash mismatch '+n)
 module='DiskFork' if cfg.startswith('legacy-') else ('Resources' if cfg.startswith('resources') or cfg in ['unsafe-shared-disk','unsafe-fresh-fallback','unsafe-stale-commit'] else 'IntentCleanup')
 inputs={n:sha(HERE/n) for n in [module+'.tla',cfg+'.cfg','check.py']}
 run=uuid.uuid4().hex[:12];(HERE/'traces').mkdir(exist_ok=True)
 log=HERE/'traces'/(cfg+'.'+run+'.txt')
 command=[LOADER,'--library-path',str(pathlib.Path(LOADER).parent)+':'+str(TOOLS/'jdk-17.0.13+11-jre/lib'),str(TOOLS/'jdk-17.0.13+11-jre/bin/java'),'-XX:+UseParallelGC','-Xmx512m','-cp',str(TOOLS/'tla2tools.jar'),'tlc2.TLC','-workers','1','-coverage','1','-metadir',str(TOOLS/('states-v2-'+run)),'-config',cfg+'.cfg',module]
 info={'config':cfg,'module':module,'run':run,'inputs_sha256':inputs,'tools_sha256':PIN,'timeout_seconds':TIMEOUT,'command':command,'log':str(log.relative_to(HERE))}
 start=time.time()
 with log.open('w') as f:
  f.write(json.dumps(info)+'\n');f.flush()
  try:code=subprocess.run(command,cwd=HERE,stdout=f,stderr=subprocess.STDOUT,timeout=TIMEOUT).returncode
  except subprocess.TimeoutExpired:code='timeout'
 text=log.read_text();info.update(returncode=code,seconds=round(time.time()-start,2),expected_returncode=12 if 'unsafe' in cfg else 0)
 info['inputs_unchanged']=all(sha(HERE/n)==h for n,h in inputs.items())
 info['pass']=code==0 and 'Model checking completed. No error has been found.' in text
 info['counterexample']=code==12 and 'Invariant ' in text and 'is violated.' in text
 info['summary']=[l for l in text.splitlines() if any(x in l for x in ['Error:','states generated,','depth of the complete','Finished in','TLC2 Version'])]
 info['coverage']={n:[int(a),int(b)] for n,a,b in re.findall(r'^<([A-Za-z]+) line[^\n]*>: ([0-9]+):([0-9]+)',text,re.M)}
 with (HERE/'results.jsonl').open('a') as f:f.write(json.dumps(info)+'\n')
 print(json.dumps({k:v for k,v in info.items() if k not in ['command','coverage']}),flush=True)
 if not info['inputs_unchanged'] or code!=info['expected_returncode']:break
