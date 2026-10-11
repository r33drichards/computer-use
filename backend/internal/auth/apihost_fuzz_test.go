package auth

import "testing"

// FuzzSameHost checks that SameHost never panics, never matches an empty
// configured host, and treats a host as the same as itself when it names one.
func FuzzSameHost(f *testing.F) {
	for _, s := range [][2]string{
		{"api.example.com", "api.example.com"},
		{"API.example.com:443", "api.example.com"},
		{"api.example.com.", "api.example.com:8080"},
		{"[::1]:80", "[::1]"},
		{"", ""},
		{"evil.com", "api.example.com"},
	} {
		f.Add(s[0], s[1])
	}
	f.Fuzz(func(t *testing.T, request, host string) {
		if SameHost(request, "") || SameHost(request, ".") {
			t.Fatalf("SameHost(%q, empty host) matched", request)
		}
		if SameHost(request, host) && !SameHost(host, host) && host != request {
			// a match implies the configured host is a usable host
			t.Fatalf("SameHost(%q, %q) matched but %q is not its own host", request, host, host)
		}
	})
}
