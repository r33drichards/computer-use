package mcp.fetch

# General-purpose HTTP(S) access for run_js. Network reachability is still
# governed by the session pod's NetworkPolicy.
default allow = false

allow if input.url_parsed.scheme in {"http", "https"}
