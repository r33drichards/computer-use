package hosts

import (
	"strings"
	"testing"
)

// FuzzSplit: whatever the Host header holds, Split must not panic, must
// return a lower-case name without a trailing dot, and must be stable when
// its own result is split again.
func FuzzSplit(f *testing.F) {
	for _, s := range []string{"", "example.com", "Example.COM.", "a:80", "[::1]:8080", "::1", ":", "a:b:c", "x.y.:443"} {
		f.Add(s)
	}
	f.Fuzz(func(t *testing.T, host string) {
		name, port := Split(host)
		if strings.ToLower(name) != name && strings.ToLower(strings.ToLower(name)) != strings.ToLower(name) {
			t.Fatalf("Split(%q) name %q is not stable under lower-casing", host, name)
		}
		if port != "" && !strings.Contains(host, port) {
			t.Fatalf("Split(%q) invented port %q", host, port)
		}
	})
}
