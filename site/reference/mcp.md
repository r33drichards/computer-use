# MCP endpoint and run_js

## Endpoint

One URL per session. **Copy MCP URL** in the app copies it; the API returns
it as `mcp_url`.

```
https://sessions.computeruse.site/<session id>/mcp
```

| | |
| --- | --- |
| Transport | Streamable HTTP |
| Sign-in | OAuth in a browser, with the account that owns the session |
| Who may call | The session's owner |
| Sleeping session | A call (`POST`) wakes it and waits. The event stream (`GET`) does not wake it and answers `405` until the session runs |
| With an API token | `https://api.computeruse.site/<session id>/mcp`, with `Authorization: Bearer <token>` and the `sessions:connect` scope |

## `run_js`

The tool an agent works through. It runs JavaScript or TypeScript in a fresh
V8 isolate and returns what the code printed.

| Parameter | Type | Meaning |
| --- | --- | --- |
| `code` | string | The code. TypeScript types are removed, not checked. |
| `heap_memory_max_mb` | number, optional | Heap limit in MB. Minimum 4, default 8. |
| `execution_timeout_secs` | number, optional | Time limit in seconds, 1 to 300. Default 30. |

Returns `output` (what was written with `console.log`, `console.info`,
`console.warn`, `console.error`) and `error` if the run failed or timed out.

No state carries from one call to the next. The desktop and the disk do.

### Available in the code

| | |
| --- | --- |
| `mcp.callTool(server, tool, arguments)` | Calls a capability of the desktop. See [Capabilities](/reference/capabilities). |
| `fs` | Node-style file functions, for `/data/` and its subdirectories. |
| `artifact(key, mime, bytes)` | Attaches an image or file to the result. Up to 16 MiB each. |
| `artifact.get(key)`, `artifact.list()` | Reads stored artifacts and uploaded files. |
| `fetch(url, options?)` | HTTP(S) requests, subject to the session policy. Returns a standard Fetch Response. |
| top-level `await` | Supported. |

### Not available in the code

Environment variables, DOM APIs, and `child_process`. Timers (`setTimeout`, `setInterval`) are available.

### Fetching HTTP data

```js
const response = await fetch("https://api.example.com/v1/data")
if (!response.ok) throw new Error(`HTTP ${response.status}`)
console.log(await response.json())
```

The default Unrestricted policy allows HTTP(S) fetch. Other presets deny
fetch until a matching rule is added. [Fetch permissions](/reference/policy#fetch-requests)
shows the request fields and how to allow a host, path, and method. Policy
edits apply to subsequent requests without restarting the session.

### Importing packages

External ES module imports are enabled in this deployment with
`--allow-external-modules` in the shared startup script. Use static `import`
or dynamic `await import()`; no package installation is needed.

- **npm**: `import { camelCase } from "npm:lodash-es@4.17.21";`
- **JSR**: `import { camelCase } from "jsr:@luca/cases@1.0.0";`
- **HTTPS URL**: `import { camelCase } from "https://esm.sh/lodash-es@4.17.21";`

```js
const { camelCase } = await import("npm:lodash-es@4.17.21");
console.log(camelCase("hello world")); // helloWorld
```

Pin package versions. `npm:` resolves through `https://esm.sh/`, and `jsr:`
through `https://esm.sh/jsr/`; URL imports are fetched directly. Prefer HTTPS.
Relative imports resolve against the importing module's URL. `file://`
imports are unsupported; read saved scripts with `fs.readFile` and execute
their source with an async `eval` wrapper.
Modules are fetched again in each fresh execution, so allow time for downloads
and import what you need in each call.

This V8 runtime is not a full Node.js installation. Choose packages compatible
with the runtime; enabling imports does not enable native addons, DOM APIs,
or arbitrary Node.js APIs. A package such as `pngjs` may need compatibility
features beyond the import flag. If a package needs Node.js or native code,
run it on the desktop through the exec MCP server.

Module loading is separate from the JavaScript `fetch` API. An operator can
restrict imports with a `modules` policy in `MCP_V8_POLICIES_JSON`; a policy
cannot enable imports when the startup flag is absent. If an import is denied,
report the denial rather than trying another route.
See [upstream module import documentation](https://r33drichards.github.io/mcp-js/concepts/module-imports/).
### Running programs

`mcp.callTool("exec", "exec", { bin: "ls", args: ["-la"], timeout: 60 })`
runs a program on the session's desktop, as the desktop's user and with its
files, and returns an id at once. The program is run
directly, with its arguments as given: no shell reads them. `timeout` is in
seconds; `cwd` and `env` are optional.
`mcp.callTool("exec", "stream_logs", { id, offset: 0 })` returns
`{ logs, next_offset, status }`: poll it, passing `next_offset`, until
`status` is no longer `"running"` (`"completed:0"` is success).
`search_logs { id, pattern }` returns the lines matching a regular
expression, and `kill { id }` stops a command. See
[Capabilities](/reference/capabilities#shell-exec).

### Memory

`/data/memory/` is on the session's disk. What is written there survives
calls, sleep, stop and resume. The server asks agents to keep an index at
`/data/memory/INDEX.md` and not to store passwords or tokens there.

## Other tools

| Tool | Does |
| --- | --- |
| `get_artifact_upload_url` | Takes `key` and `mime_type`, returns a one-time `url`. The agent uploads a file from its own environment with HTTP `PUT`, then reads it with `artifact.get(key)`. Valid once, for 10 minutes, up to 16 MiB. Works only while the session runs. |
| `get_artifact` | Returns a stored artifact by `key`. For results too large to come back inline (more than 8 MiB in total). |
| `list_artifacts` | Lists stored artifacts. |
