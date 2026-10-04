"""Regression checks for the publication-unit verifier; not native proof."""
import importlib.util
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("archives", ROOT / "sdk/release/verify-crates.py")
archives = importlib.util.module_from_spec(spec)
spec.loader.exec_module(archives)

class ArchiveTests(unittest.TestCase):
    def test_normalized_dependency(self):
        archives.verify_dependency({"dependencies":{"computeruse-sdk-macros":{"version":"0.1.0"}}},"0.1.0")
    def test_wrong_or_path_dependency_refused(self):
        for dep in ({"version":"0.2.0"},{"version":"0.1.0","path":"../workspace"},{"version":"0.1.0","registry":"fixture"}):
            with self.subTest(dep=dep), self.assertRaises(ValueError):
                archives.verify_dependency({"dependencies":{"computeruse-sdk-macros":dep}},"0.1.0")
    def test_archive_gate_before_publish(self):
        text=(ROOT/".github/workflows/sdk-release.yml").read_text()
        job=text.split("  publish-crates:",1)[1].split("  publish-pypi:",1)[0]
        self.assertLess(job.index("verify-crates.py"),job.index("cargo publish --locked -p computeruse-sdk-macros"))

    def test_all_cargo_phases_have_isolated_target_behavior(self):
        import json, os, tempfile, textwrap
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory); sdk=base/'sdk'; sdk.mkdir(); (sdk/'crates').mkdir()
            (sdk/'Cargo.toml').write_text('[workspace]\n[workspace.package]\nversion="0.1.0"\n')
            (sdk/'Cargo.lock').write_text('# fixture only\n'); (sdk/'LICENSE').write_text('fixture')
            bin_dir=base/'bin'; bin_dir.mkdir(); calls=base/'calls.jsonl'; output=base/'out'
            fixture=bin_dir/'cargo'
            fixture.write_text(textwrap.dedent(r'''
                #!/usr/bin/env python3
                import json,os,sys,tarfile,io
                from pathlib import Path
                args=sys.argv[1:]; target=Path(os.environ['CARGO_TARGET_DIR'])
                with open(os.environ['FIXTURE_CALLS'],'a') as f: f.write(json.dumps({'args':args,'target':str(target)})+'\n')
                if args[0]=='package':
                    name=args[args.index('-p')+1]; prefix=name+'-0.1.0'; destination=target/'package'; destination.mkdir(parents=True,exist_ok=True)
                    manifest='[package]\nname="'+name+'"\nversion="0.1.0"\n'
                    if name=='computeruse-sdk': manifest+='[dependencies.computeruse-sdk-macros]\nversion="0.1.0"\n'
                    with tarfile.open(destination/(prefix+'.crate'),'w:gz') as t:
                        data=manifest.encode(); member=tarfile.TarInfo(prefix+'/Cargo.toml'); member.size=len(data); t.addfile(member,io.BytesIO(data))
                elif args[0]=='metadata':
                    print(json.dumps({'packages':[{'name':'computeruse-sdk-macros','version':'0.1.0','manifest_path':str(Path(os.environ['FIXTURE_OUTPUT'])/'extracted/computeruse-sdk-macros-0.1.0/Cargo.toml')}]}))
                # test commands are recording fixtures, never native success.
                ''').lstrip()); fixture.chmod(0o755)
            inherited=base/'workspace-target'
            with patch.dict(os.environ,PATH=str(bin_dir)+os.pathsep+os.environ['PATH'],CARGO_TARGET_DIR=str(inherited),FIXTURE_CALLS=str(calls),FIXTURE_OUTPUT=str(output)):
                archives.verify(sdk,output)
            recorded=[json.loads(line) for line in calls.read_text().splitlines()]
            self.assertEqual([row['args'][0] for row in recorded],['package','package','metadata','test','test'])
            targets={Path(row['target']) for row in recorded}; self.assertEqual(len(targets),1)
            for target in targets:
                self.assertNotEqual(target,inherited)
                self.assertTrue(target.is_relative_to(inherited))
            self.assertFalse((inherited/'package').exists())
