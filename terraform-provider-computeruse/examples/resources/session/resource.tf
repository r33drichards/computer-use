resource "session" "research" {
  provider = computeruse

  name = "research"

  # Destroying a session deletes its disk and the browser's logins.
  lifecycle {
    prevent_destroy = true
  }
}

output "mcp_url" {
  value = session.research.mcp_url
}
