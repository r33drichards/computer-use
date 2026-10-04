# Fetch permissions

JavaScript `fetch()` is enabled in both MCP images for HTTP and HTTPS.
When session policies are enforcing, each request must pass the image's
local HTTP(S) policy and the session's editable `allow_tool_call` rule.
Requests use the same OPA decision endpoint as tool calls, with a different
input shape. Undefined, false, errors, or an unavailable OPA deny the request.

## Edit permissions

Open a session's policy editor, add a fetch rule to the existing policy,
test it, and save. For example, this rule permits only HTTPS GET requests
to `api.example.com` under `/v1/`:

```rego
allow_tool_call if {
    input.operation == "fetch"
    input.url_parsed.scheme == "https"
    input.url_parsed.host == "api.example.com"
    input.method == "GET"
    startswith(input.url_parsed.path, "/v1/")
}
```

Keep the policy's existing `package computeruse.policy`, `import rego.v1`,
and any tool rules. This rule alone does not permit browser, desktop, or
shell calls. The policy editor's Test panel includes GET, POST, and another
host samples; you can also paste the request input below.

To allow all HTTP(S) fetch requests alongside existing tool rules, add:

```rego
allow_tool_call if input.operation == "fetch"
```

To deny fetch, remove every rule that can match fetch requests. Rego allow
rules combine with OR: adding a false rule does not override an existing
allow rule. `allow_tool_call := true` (the Unrestricted preset) permits all
tool calls and HTTP(S) fetch requests. Replace that broad rule with specific
tool and fetch rules to restrict access. Browser-only and other restrictive
presets deny fetch until an appropriate rule is added. `allow_fetch` is not
an entry rule; use `allow_tool_call`.

## Request input

```json
{
  "operation": "fetch",
  "url": "https://api.example.com/v1/data",
  "method": "GET",
  "headers": {},
  "url_parsed": {
    "scheme": "https",
    "host": "api.example.com",
    "port": null,
    "path": "/v1/data",
    "query": ""
  }
}
```

Fetch inputs have no `server`, `tool`, or `arguments`. Headers include any
server-injected headers. The policy receives request metadata, not the
response body. Check the exact host rather than a URL string prefix when
restricting destinations.

## Deployment and scope

Policy edits become effective through the existing policy bundle reload;
no session restart is required for subsequent requests once the updated
policy is ready. Initial rollout requires rebuilding the MCP and policy
operator images, deploying both plus the session templates, and restarting
existing session pods. The warm pool and `hack/policy-stage.sh` also include
the fetch decision chain so a stage change preserves enforcement.

With policies off, the image's local policy permits HTTP(S) without a
session rule. Pod NetworkPolicies still control network reachability in
both modes. This governs `fetch()` in `run_js`; browser navigation, page
scripts, external module downloads, and shell programs have separate
controls. Allowing those capabilities can permit other ways to contact a
host, so a fetch rule alone is not a network isolation boundary.
