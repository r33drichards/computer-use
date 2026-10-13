package mcp.modules

import rego.v1

# Transport shape guard, not a tenant/network grant.
default allow := false
allow if {
	input.url_parsed.scheme in {"http", "https"}
	input.resolved_url == input.specifier
}
