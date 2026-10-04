data "sessions" "all" {
  provider = computeruse
}

output "session_names" {
  value = [for s in data.sessions.all.sessions : s.name]
}
