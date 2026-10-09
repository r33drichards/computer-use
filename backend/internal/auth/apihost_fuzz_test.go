package auth

import "testing"

// FuzzSameHost: it never panics, an empty configured host matches nothing,
// and a host always matches itself when it names something.
func FuzzSameHost(f *testing.F) {
	for _, s := range []string{"", "a", "A.", "a:80", "[::1]:1", ":80"} {
		f.Add(s, s)
	}
	f.Add("api.example.com", "API.example.com.:443")
	f.Fuzz(func(t *testing.T, req, host string) {
		got := SameHost(req, host)
		if SameHost(req, "") {
			t.Fatalf("SameHost(%q, \"\") = true", req)
		}
		if got && !SameHost(host, req) {
			t.Fatalf("SameHost not symmetric for %q, %q", req, host)
		}
	})
}
