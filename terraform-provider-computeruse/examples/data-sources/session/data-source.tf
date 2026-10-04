data "session" "by_name" {
  provider = computeruse

  name = "research"
}

data "session" "by_id" {
  provider = computeruse

  id = "s-ab2cd"
}

output "mcp_url" {
  value = data.session.by_name.mcp_url
}
