---
name: nocodb
description: Use the operator-configured NocoDB API through host-scoped automatic authentication.
---

# NocoDB API

Use this skill only when the active server instructions advertise the NocoDB integration.

## Endpoint and authentication

- API origin: `https://nocodb-render-mvp.onrender.com`.
- Call it with `fetch` inside `run_js`.
- Authentication is injected by the MCP server as an `xc-token` header for that exact host. Do not request, inspect, print, persist, or forward the token. Do not add an authentication header yourself.
- Redirects to another host do not receive the injected header.

## Safe workflow

1. Start with a read-only request such as `GET /api/v2/meta/bases/` and check the HTTP status before parsing JSON.
2. The free service can cold start. For an idempotent read only, wait and retry after a transient 404/502/503 if the first request is waking it; do not blindly retry writes.
3. Discover IDs from API responses rather than guessing them. Keep output minimal and never log response fields that the user has not asked to disclose.
4. Use write, schema, upload, or delete endpoints only with explicit user authorization for that change. Verify the resulting state with a follow-up read.
5. Do not send credentials, personal data, or unrelated local files to NocoDB.

## Example read

```js
const response = await fetch("https://nocodb-render-mvp.onrender.com/api/v2/meta/bases/");
console.log(JSON.stringify({ status: response.status, ok: response.ok }));
if (!response.ok) throw new Error("NocoDB HTTP " + response.status);
const body = await response.json();
console.log(JSON.stringify({ count: Array.isArray(body?.list) ? body.list.length : undefined }));
```
