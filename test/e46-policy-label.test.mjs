import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync('web/src/policyApi.ts','utf8');
const section=source.slice(source.indexOf('const UNRESTRICTED'),source.indexOf('// The link of a policy managed as code'));
const js=section.replace('export function isUnrestricted(p: Pick<Policy, "kind" | "source">): boolean {','function isUnrestricted(p) {');
const classify=vm.runInNewContext(js+';isUnrestricted');
const policy=(s)=>({kind:'rego',source:s});
test('current explicit two-grant preset label, not legacy grant or extra authority',()=>{
 assert.equal(classify(policy(fs.readFileSync('docs/contracts/policy/examples/unrestricted.rego','utf8'))),true);
 assert.equal(classify(policy('package computeruse.policy\nimport rego.v1\nallow_tool_call := true')),false);
 assert.equal(classify(policy('package computeruse.policy\nimport rego.v1\nallow_tool_call := true\nallow_unrestricted_modules := false')),false);
 assert.equal(classify(policy('package computeruse.policy\nimport rego.v1\nallow_tool_call := true\nallow_unrestricted_modules := "true"')),false);
 assert.equal(classify(policy(fs.readFileSync('docs/contracts/policy/examples/unrestricted.rego','utf8')+'\nx := 1')),false);
});
