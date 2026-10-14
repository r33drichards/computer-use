package hosts

import (
	"strings"
	"testing"
)

// FuzzSplit checks that Split never panics, that the name it returns is
// lower case.
func FuzzSplit(f *testing.F) {
	for _, s := range []string{
		"example.com",
		"Example.COM.",
		"example.com:8080",
		"[::1]:443",
		"[::1]",
		"::1",
		":80",
		"",
		"a:b:c",
		"host.:80",
	} {
		f.Add(s)
	}
	f.Fuzz(func(t *testing.T, s string) {
		name, _ := Split(s)
		if name != strings.ToLower(name) {
			t.Fatalf("Split(%q) name %q is not lower case", s, name)
		}
	})
}
