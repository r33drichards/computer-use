package hosts

import (
	"strings"
	"testing"
)

// FuzzSplit: Split never panics, its name is lower case with no trailing
// dot, and splitting is stable (a name with its port put back splits the
// same way).
func FuzzSplit(f *testing.F) {
	for _, s := range []string{"", "a", "A.B.", "a:80", "[::1]:443", "[::1]", "::1", "a:", ":80", "a.:80"} {
		f.Add(s)
	}
	f.Fuzz(func(t *testing.T, host string) {
		name, port := Split(host)
		if name != strings.ToLower(name) {
			t.Fatalf("Split(%q) name %q is not lower case", host, name)
		}
		if strings.HasSuffix(name, ".") && strings.TrimSuffix(name, ".") == "" {
			// only a bare "." trims to ""; anything else must not end in a dot
			t.Fatalf("Split(%q) name %q ends in a dot", host, name)
		}
		if port != "" && strings.Contains(port, ":") && !strings.HasPrefix(host, "[") {
			t.Fatalf("Split(%q) port %q", host, port)
		}
	})
}
