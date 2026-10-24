package auth

import (
	"testing"

	"github.com/r33drichards/computer-use/backend/internal/hosts"
)

// FuzzSameHost: SameHost must not panic on any pair, and a non-empty host
// that names itself must match itself.
func FuzzSameHost(f *testing.F) {
	f.Add("api.example.com", "api.example.com")
	f.Add("API.example.com:8443", "api.example.com")
	f.Add("[::1]:80", "::1")
	f.Add("", "")
	f.Fuzz(func(t *testing.T, requestHost, host string) {
		_ = SameHost(requestHost, host)
		if name, _ := hosts.Split(host); name != "" && !SameHost(host, host) {
			t.Fatalf("SameHost(%q, %q) = false for a host with a name", host, host)
		}
	})
}
