import os, subprocess, tempfile, unittest
from pathlib import Path
R=Path(__file__).resolve().parent
SHA="545783c99973d5e360a3d35635581ae747b8f21e"
class Guards(unittest.TestCase):
 def stage(self,sha,*extra):
  return subprocess.run(["bash",str(R/"stage.sh"),sha,*extra],env={**os.environ,"COPYBARA":__import__("shutil").which("false")},capture_output=True,text=True)
 def test_full_sha(self):
  for sha in ["main",SHA[:8],"0"*40,SHA+";true"]:
   self.assertNotEqual(self.stage(sha).returncode,0)
 def test_unintegrated_release_refused(self):
  p=self.stage(SHA); self.assertNotEqual(p.returncode,0);self.assertIn("committed release",p.stderr)
  # Guard-only fake git responses; these fixtures are not export/native proof.
  import tempfile, shutil
  with tempfile.TemporaryDirectory() as t:
   g=Path(t)/'git'
   g.write_text('#!/usr/bin/env bash'+chr(10)+'case "$3" in cat-file) [[ "$4" != -t ]] || echo commit;; rev-parse) echo '+SHA+';; diff) [[ "$GUARD_FIXTURE" != dirty ]];; ls-files) [[ "$GUARD_FIXTURE" != overlay ]] || echo untracked;; esac'+chr(10));g.chmod(0o755)
   for boundary in ['dirty','overlay']:
    env={**os.environ,'PATH':t+os.pathsep+os.environ['PATH'],'GUARD_FIXTURE':boundary,'COPYBARA':shutil.which('false')}
    p=subprocess.run(['bash',str(R/'stage.sh'),SHA],env=env,capture_output=True,text=True)
    self.assertNotEqual(p.returncode,0);self.assertIn('dirty source mismatch' if boundary=='dirty' else 'uncommitted release overlay',p.stderr)
 def test_no_overlay(self):
  s=(R/"stage.sh").read_text();self.assertNotIn('cp -R "$release"',s);self.assertNotIn('rev-parse HEAD)',s)
 def test_runtime_template(self):
  self.assertIn('internal/fakeapi/fakeapi_test.go',(R/'copy.bara.sky').read_text())
  self.assertIn("@@SOURCE_SHA@@",(R/"copy.bara.sky").read_text())
 def test_versions(self):
  for v in ["1.2.3;true","1.2.3'", "$(true)", "1.2.3\ntrue", "../1.2.3"]:
   p=subprocess.run(["bash",str(R/"validate-version.sh"),v],capture_output=True);self.assertNotEqual(p.returncode,0)
  self.assertEqual(subprocess.run(["bash",str(R/"validate-version.sh"),"1.2.3"],capture_output=True).returncode,0)
 def test_workflow_no_shell_interpolation(self):
  s=(R/"provider-release.yml").read_text(); self.assertNotIn("'"+"$"+"{{ inputs.version }}'",s);self.assertIn('"$VERSION"',s)
 def test_manual_build_baseline_contract(self):
  import re
  s=(R/'provider-release.yml').read_text()
  events=s.split('permissions:',1)[0]
  for event in ['workflow_call','workflow_dispatch']:
   with self.subTest(event=event):
    self.assertIn('  '+event+':',events)
    block=events.split('  '+event+':',1)[1].split(chr(10)+'  workflow_',1)[0]
    self.assertRegex(block,re.compile(r'inputs:\s+version:.*required: true.*type: string',re.S))
  for runner in ['ubuntu-22.04, os: linux, arch: amd64','ubuntu-22.04-arm, os: linux, arch: arm64']:
   with self.subTest(runner=runner): self.assertIn(runner,s)
  with self.subTest(toolchain='SDK-matched'):
   self.assertIn('rustup toolchain install 1.91.1 --profile minimal',s)
   self.assertIn('rustup default 1.91.1',s)
  self.assertIn('contents: read',s)
  for forbidden in ['contents: write','id-token: write','secrets:', 'gh release','git push','sign-checksums.sh dist/']:
   with self.subTest(boundary=forbidden): self.assertNotIn(forbidden,s)
if __name__=="__main__": unittest.main()
