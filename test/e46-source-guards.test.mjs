import test from 'node:test';
import {execFileSync} from 'node:child_process';
for (const file of ['images/mcp-js/test-module-policy-contract.py','test/image-helper-trigger-test.py','test/private-diagnostic-file-test.py','images/mcp-js/test-module-fixture-receipt.py','images/mcp-js/test-module-fixture-client.py']) {
  test(file, () => execFileSync('python3', ['-B', file], {timeout:15000, maxBuffer:65536}));
}
