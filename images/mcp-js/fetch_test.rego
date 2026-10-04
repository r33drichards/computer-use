package mcp.fetch

test_http_schemes_allowed if {
    every scheme in ["http", "https"] {
        allow with input as {"operation": "fetch", "url_parsed": {"scheme": scheme}}
    }
}

test_other_schemes_denied if {
    every scheme in ["file", "ftp", "data", "javascript"] {
        not allow with input as {"operation": "fetch", "url_parsed": {"scheme": scheme}}
    }
    not allow with input as {"operation": "fetch"}
}
