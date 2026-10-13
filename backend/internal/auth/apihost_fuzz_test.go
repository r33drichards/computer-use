package auth

import (
	"testing"

	"github.com/r33drichards/computer-use/backend/internal/hosts"
)

// FuzzSameHost checks that no pair of host strings panics SameHost, and that
// a non-empty host is the same host as itself.
func FuzzSameHost(f *testing.F) {
	for _, s := range [][2]string{
		{"api.example.com", "api.example.com"},
		{"API.example.com:443", "api.example.com"},
		{"api.example.com.", "api.example.com:8080"},
		{"[::1]:80", "[::1]"},
		{"", ""},
	} {
		f.Add(s[0], s[1])
	}
	f.Fuzz(func(t *testing.T, requestHost, host string) {
		SameHost(requestHost, host)
		if name, _ := hosts.Split(host); name != "" && !SameHost(host, host) {
			t.Fatalf("SameHost(%q, %q) = false", host, host)
		}
	})
}
