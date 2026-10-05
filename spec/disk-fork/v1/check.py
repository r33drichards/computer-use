#!/usr/bin/env python3
"""Bounded formal-check harness; hash verification is mandatory before every JVM."""
import hashlib,json,pathlib,subprocess,time,sys,os
HERE=pathlib.Path(__file__).resolve().parent
TOOLS=pathlib.Path(os.environ.get("DISK_FORK_TOOLS", "/data/chrome/home/.cache/disk-fork-tlc"))
EXPECTED={"tla2tools.jar":"c2fe4e56e43bde19f213b4a7e441d037297fda733e503579623e859b79348239", "jre.tar.gz":"4086cc7cb2d9e7810141f255063caad10a8a018db5e6b47fa5394c506ab65bff"}
LOADER=os.environ.get("DISK_FORK_LOADER","/nix/store/lm3pknxi0ipypy3lxh1wmm8wvvavdwrn-glibc-2.42-84/lib/ld-linux-x86-64.so.2")
configs=sys.argv[1:] or ["atomic","cap-one","faults","liveness","liveness-races","unsafe-check","unsafe-lease","unsafe-lease-snapshot"]
results=json.loads((HERE/"traces/verified-results.json").read_text()) if (HERE/"traces/verified-results.json").exists() else []
TIMEOUT=int(os.environ.get("DISK_FORK_TIMEOUT","180"))
for cfg in configs:
 for name,digest in EXPECTED.items():
  actual=hashlib.sha256((TOOLS/name).read_bytes()).hexdigest()
  if actual!=digest: raise SystemExit(f"BLOCKED: {name}: expected {digest}, got {actual}")
 java=TOOLS/"jdk-17.0.13+11-jre/bin/java"
 command=[LOADER,"--library-path",str(pathlib.Path(LOADER).parent)+":"+str(TOOLS/"jdk-17.0.13+11-jre/lib"),str(java),"-XX:+UseParallelGC","-Xmx512m","-cp",str(TOOLS/"tla2tools.jar"),"tlc2.TLC","-workers","1","-coverage","1","-metadir",str(TOOLS/("states-verified-"+cfg)),"-config",cfg+".cfg","DiskFork"]
 path=HERE/"traces"/(cfg+"-verified.txt")
 started=time.time()
 with path.open("w") as out:
  out.write("Verified jar SHA256: "+EXPECTED["tla2tools.jar"]+"\nCommand: "+json.dumps(command)+"\n");out.flush()
  try: code=subprocess.run(command,cwd=HERE,stdout=out,stderr=subprocess.STDOUT,timeout=TIMEOUT).returncode
  except subprocess.TimeoutExpired: code=f"timeout{TIMEOUT}"
 text=path.read_text()
 result={"config":cfg,"returncode":code,"seconds":round(time.time()-started,2),"jar_sha256":EXPECTED["tla2tools.jar"],"completed":code==0 and "Model checking completed. No error has been found." in text,"summary":[l for l in text.splitlines() if any(s in l for s in ["Error:","states generated,", "depth of the complete", "Finished in", "TLC2 Version"])]}
 results.append(result);print(json.dumps(result),flush=True)
 (HERE/"traces/verified-results.json").write_text(json.dumps(results,indent=2)+"\n")
 if code not in [0,12]: break
