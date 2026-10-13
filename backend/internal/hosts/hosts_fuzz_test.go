package hosts

import (
	"strings"
	"testing"
)

// FuzzSplit checks that no host string panics Split, that the name it
// returns is lower case, and that another spelling of one host (upper case,
// trailing dot) gives the same name.
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
	f.Fuzz(func(t *testing.T, host string) {
		name, port := Split(host)
		if name != strings.ToLower(name) {
			t.Fatalf("Split(%q) name %q is not lower case", host, name)
		}
		// Case and one trailing dot never change the name.
		// (ASCII only: Unicode case mapping does not round-trip, and host names are ASCII.)
		if port == "" && !strings.Contains(host, ":") && isASCII(host) {
			if again, _ := Split(strings.ToUpper(name) + "."); again != name {
				t.Fatalf("Split(%q) = %q but the upper-case, dotted spelling gave %q", host, name, again)
			}
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
