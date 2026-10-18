# MCP session profiles

MCP profiles let an operator attach a reviewed mcp-js configuration to selected sessions without giving the caller, guest, API response, or repository the credential itself. A profile can set:

- a host-scoped `MCP_V8_FETCH_HEADER_CONFIG` from one Kubernetes Secret key;
- server instructions; and
- one or more skill directories already packaged in the mcp-js image.

Profiles are off when `MCP_PROFILES_PATH` is unset. The file is strict YAML:

```yaml
profiles:
  example:
    fetchHeaderSecret:
      name: mcp-profile-example
      key: fetch-header-config
    instructions: '@/etc/mcp/profiles/example/instructions.md'
    skillsDirs:
      - /etc/mcp/skills
      - /etc/mcp/profiles/example/skills
```

The referenced Secret must exist in the session namespace. Its value is the mcp-js fetch-header JSON, not a shell fragment. Keep it out of Git, ConfigMaps, API bodies, logs, annotations, and session disks. Prefer an exact host rule with `override: true`; do not use a wildcard host for credentials.

The production fetch hook stack is `@policy`, `@inject`, `@execute`: local and remote OPA authorize the caller-supplied request before the credential is added. This prevents the injected value from entering policy inputs while preserving host/method authorization. Keep that order when enabling secret-backed profiles.

Only identities named by the backend's admin list may select a profile, including when they authenticate with an API token (tokens intentionally do not carry the admin bit). Other callers receive `403`; unknown profile names receive `400`. The API exposes only the selected profile name as `mcpProfile`.

## Create and retrofit

Create a cold session with a profile:

```json
{"name":"agent","mcpProfile":"example"}
```

Profiled sessions bypass the warm pool so the secret-backed environment is present from their first process.

To add a profile to an existing session without deleting its disk:

1. `PATCH /sessions/{id}` with `{"action":"stop"}` and wait until `state` is `stopped`. A user stop deliberately has no saved process snapshot.
2. Send a separate `PATCH /sessions/{id}` with `{"mcpProfile":"example"}`. It returns `409` unless the session is fully stopped with no saved state.
3. Resume it with `{"action":"resume"}`. This is a fresh pod using the same persistent disk.
4. Verify the MCP initialize instructions, published skill, and a safe read-only call. Audit pod/backend logs for startup errors and secret markers without printing the secret.

A profile change is deliberately a request of its own and removing a profile is not currently supported. The Kubernetes update uses the Sandbox resource version, so a concurrent lifecycle change conflicts rather than silently overwriting it.

## Production NocoDB profile

The production overlay defines `nocodb`. The mcp-js image contains its instructions and skill, while the GitHub Actions secret `NOCODB_MCP_FETCH_HEADER_CONFIG` is validated and synchronized to Kubernetes Secret `mcp-profile-nocodb` during a production release. The release accepts exactly one rule for `nocodb-render-mvp.onrender.com`, with exactly one nonempty `xc-token` header and `override: true`.
