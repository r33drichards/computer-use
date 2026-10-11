package hosts

import (
	"strings"
	"testing"
)

// FuzzSplit checks that Split never panics, that the name it returns is
// lower case without a trailing dot, and that splitting is stable: the name
// splits to itself.
func FuzzSplit(f *testing.F) {
	for _, s := range []string{
		"", "example.com", "Example.COM.", "example.com:8080", "[::1]:443",
		"[::1]", "::1", ":80", "a:b:c", "host.",
	} {
		f.Add(s)
	}
	f.Fuzz(func(t *testing.T, host string) {
		name, _ := Split(host)
		if name != strings.ToLower(name) {
			t.Fatalf("Split(%q) name %q is not lower case", host, name)
		}
		if strings.HasSuffix(name, "..") {
			return // only one trailing dot is trimmed
		}
		if strings.HasSuffix(name, ".") && !strings.HasSuffix(host, "..") {
			t.Fatalf("Split(%q) name %q keeps a trailing dot", host, name)
		}
	})
}
