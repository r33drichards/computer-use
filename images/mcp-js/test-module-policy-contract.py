import json
from pathlib import Path
import re
import unittest

class ModuleWiring(unittest.TestCase):
    def test_enforcing_configs_install_all_chain_and_fixed_session_endpoint(self):
        for name in ('deploy/gke/blueprint.yaml','deploy/gke/warmpool.yaml','hack/policy-stage.sh'):
            text = Path(name).read_text()
            config = json.JSONDecoder().raw_decode(text[text.index('{"mcp_tools":'):])[0]
            modules = config['modules']
            self.assertEqual(modules['mode'], 'all')
            self.assertEqual(modules['policies'][0]['url'], 'file:///etc/mcp/modules.rego')
            self.assertEqual(modules['policies'][1], config['fetch']['policies'][1])
            self.assertTrue(modules['policies'][1]['policy_path'].endswith('/mcp_tools'))
    def test_installed_image_policy_and_unchanged_pin(self):
        text = Path('images/mcp-js/Dockerfile').read_text()
        self.assertIn('COPY images/mcp-js/modules.rego ', text)
        config = json.loads(re.search(r"MCP_V8_POLICIES_JSON='([^']+)'", text).group(1))
        self.assertEqual(config['modules']['policies'][0]['url'], 'file:///etc/mcp/modules.rego')
        self.assertIn('MCP_JS_COMMIT=723fe32d4cc31c18f8255af2639059f7d8450324', text)
    def test_full_authority_not_url_or_fetch_grant(self):
        text = Path('docs/contracts/policy/decision-module.rego.tmpl').read_text()
        self.assertIn('allow_unrestricted_modules == true with input as {}', text)
        for directory in ('backend/internal/policy/presets','docs/contracts/policy/examples'):
            for path in Path(directory).glob('*.rego'):
                if path.name == 'unrestricted.rego': self.assertIn('allow_unrestricted_modules := true', path.read_text())
                else: self.assertNotIn('allow_unrestricted_modules := true', path.read_text())
    def test_actual_opa_fixture_pin_matches_deployed_source(self):
        image = re.search(r'image: (openpolicyagent/opa:[^\n]+)', Path('deploy/base/opa.yaml').read_text()).group(1)
        self.assertIn(image, Path('images/mcp-js/test-module-policy-image.py').read_text())
    def test_actual_image_fixture_is_a_normal_source_bound_ci_gate(self):
        text = Path('.github/workflows/images.yml').read_text()
        self.assertIn('python3 -B images/mcp-js/test-module-policy-image.py mcp-js:ci', text)
        self.assertIn("if: matrix.name == 'mcp-js'", text)
        self.assertIn("ref: "+'$'+'{{ github.event.pull_request.head.sha || github.sha }}', text)

if __name__ == '__main__': unittest.main()
