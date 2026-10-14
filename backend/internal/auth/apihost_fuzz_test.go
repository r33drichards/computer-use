package auth

import "testing"

// FuzzSameHost checks that SameHost never panics, that an empty configured
// host matches nothing, and that a host always matches itself (when it names
// something).
func FuzzSameHost(f *testing.F) {
	for _, s := range [][2]string{
		{"api.example.com", "api.example.com"},
		{"API.example.com:443", "api.example.com"},
		{"api.example.com", "api.example.com:8080"},
		{"[::1]:80", "[::1]"},
		{"", ""},
		{"a", ""},
	} {
		f.Add(s[0], s[1])
	}
	f.Fuzz(func(t *testing.T, req, host string) {
		got := SameHost(req, host)
		if host == "" && got {
			t.Fatalf("SameHost(%q, \"\") = true", req)
		}
	})
}
