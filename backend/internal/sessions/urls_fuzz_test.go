package sessions

import (
	"net/url"
	"testing"
)

// FuzzURLTemplate checks that no template string panics the parser, and that
// a template it accepts hands out URLs that Match reads back as the session
// they were made for.
func FuzzURLTemplate(f *testing.F) {
	for _, s := range []string{
		"https://sessions.example.com/{id}",
		"https://{id}.sessions.example.com",
		"http://{id}.localhost:8080/",
		"https://sessions.example.com:443/{id}/",
		"{id}",
		"https://{id}",
		"https://u@{id}.example.com",
		"https://{id}.example.com/?q#f",
		"Http://{id}...", // found by the nightly fuzz run: a host of only dots
		"https://{id}.a..b",
	} {
		f.Add(s)
	}
	f.Fuzz(func(t *testing.T, s string) {
		tmpl, err := ParseURLTemplate(s)
		if err != nil {
			return
		}
		const id = "s-abcdefg234"
		base, err := url.Parse(tmpl.Base(id))
		if err != nil {
			t.Fatalf("template %q: Base is not a URL: %v", s, err)
		}
		m, session := tmpl.Match(base.Host, base.EscapedPath()+"/x")
		if !session || m.ID != id || m.Path != "/x" {
			t.Fatalf("template %q: Match(%q, %q) = %+v, %v", s, base.Host, base.EscapedPath()+"/x", m, session)
		}
	})
}
