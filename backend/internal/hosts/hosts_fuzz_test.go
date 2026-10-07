package hosts

import (
	"strings"
	"testing"
)

// FuzzSplit checks that Split never panics, that the name it returns is in
// lower case, and that spelling the host in upper case changes nothing but
// the case (so two spellings of one host compare equal).
func FuzzSplit(f *testing.F) {
	for _, s := range []string{
		"", "example.com", "Example.COM.", "example.com:8080", "[::1]:443",
		"[::1]", "::1", "a:b:c", ":80", "host:", "host.:80",
	} {
		f.Add(s)
	}
	f.Fuzz(func(t *testing.T, s string) {
		name, port := Split(s)
		if name != strings.ToLower(name) {
			t.Fatalf("Split(%q) name %q is not lower case", s, name)
		}
		if !isASCII(s) {
			return
		}
		n2, p2 := Split(strings.ToUpper(s))
		if n2 != name || p2 != strings.ToUpper(port) && p2 != port {
			t.Fatalf("Split(%q) = %q, %q but upper case gives %q, %q", s, name, port, n2, p2)
		}
	})
}

func isASCII(s string) bool {
	for i := 0; i < len(s); i++ {
		if s[i] >= 0x80 {
			return false
		}
	}
	return true
}
