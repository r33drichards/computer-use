import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

spec = importlib.util.spec_from_file_location('render', 'hack/gitops/render.py')
render = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render)

SHA = 'a' * 40
IMAGE = 'us-west1-docker.pkg.dev/browserjs-sessions/browserjs/backend@sha256:' + 'b' * 64
SITE = 'us-west1-docker.pkg.dev/browserjs-sessions/browserjs/site@sha256:' + 'c' * 64


class ReleaseTests(unittest.TestCase):
    def test_foreign_commit_cannot_deploy(self):
        with tempfile.TemporaryDirectory() as work:
            path = Path(work)
            (path / 'image.json').write_text(json.dumps({'source_sha':'d'*40,'name':'backend','image':IMAGE}))
            with self.assertRaisesRegex(ValueError, 'another commit'):
                render.render(SHA, {'images':{'site':SITE}}, path, path / 'out')

    def test_mutable_tag_or_foreign_registry_is_rejected(self):
        for image in ['us-west1-docker.pkg.dev/browserjs-sessions/browserjs/backend:main', IMAGE.replace('browserjs-sessions/', 'attacker/')]:
            with self.assertRaises(ValueError):
                render.validate_image('backend', image)

    def test_unbuilt_images_are_preserved_and_canary_requires_secret(self):
        doc = {'apiVersion':'argoproj.io/v1alpha1','kind':'AnalysisTemplate','metadata':{'name':'release-canary'},'spec':{'metrics':[{'provider':{'job':{'spec':{'template':{'spec':{'containers':[{'command':['sh','-c','exit 0'],'env':[{'name':'CANARY_API_TOKEN','valueFrom':{'secretKeyRef':{'name':'release-canary','key':'token','optional':True}}}]}]}}}}}}]}}
        with tempfile.TemporaryDirectory() as work:
            path = Path(work)
            (path / 'image.json').write_text(json.dumps({'source_sha':SHA,'name':'backend','image':IMAGE}))
            with patch.object(render.subprocess, 'run') as run, patch.object(render.subprocess, 'check_output', return_value=yaml.safe_dump(doc)):
                render.render(SHA, {'images':{'site':SITE}}, path, path / 'out')
            release = json.loads((path / 'out/release.json').read_text())
            self.assertEqual(release['images'], {'site':SITE,'backend':IMAGE})
            docs = list(yaml.safe_load_all((path / 'out/manifests.yaml').read_text()))
            container = docs[0]['spec']['metrics'][0]['provider']['job']['spec']['template']['spec']['containers'][0]
            self.assertEqual(container['command'][2], 'exit 1')
            self.assertNotIn('optional', container['env'][0]['valueFrom']['secretKeyRef'])
            self.assertEqual(docs[1]['kind'], 'ConfigMap')
            self.assertIn('canary.py', docs[1]['data'])
            self.assertEqual(run.call_count, 2)


if __name__ == '__main__':
    unittest.main()
