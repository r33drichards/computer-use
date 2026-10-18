

NocoDB integration (operator-enabled profile):
- Authenticated API requests to https://nocodb-render-mvp.onrender.com are available through run_js fetch. The server injects the required xc-token only for that exact host; never ask for, print, store, or forward the token.
- Prefer read-only discovery and metadata requests. Make data or schema changes only when the user explicitly asks. Treat the service as cold-start capable: allow an initial wake to take about 90 seconds and retry only safe/idempotent reads after an observed transient response.
- Load the nocodb skill before using this integration.
