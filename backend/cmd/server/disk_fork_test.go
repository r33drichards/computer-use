package main

import (
	"encoding/json"
	"net/http"
	"testing"
)

// Exercise the actual server route table, not only APIHost's dummy handler.
// Tokens are generated only against the test's fake object tracker/verifier.
func TestDiskForkAPITokenSurfaceDisabled(t *testing.T) {
	s, _ := tokenServer(t, alice, bob)
	mine := s.session(alice)
	theirs := s.session(bob)
	_, write := s.newToken(alice, "sessions:write")
	_, read := s.newToken(alice, "sessions:read")
	for _, c := range []struct {
		method, path, token string
		want                int
	}{
		{"POST", "/v1/sessions/" + mine.ID + "/fork", write, 501},
		{"POST", "/v1/sessions/" + theirs.ID + "/fork", write, 404},
		{"POST", "/v1/sessions/s-aaaaaaaaaa/fork", write, 404},
		{"POST", "/v1/sessions/not-an-id/fork", write, 404},
		{"POST", "/v1/sessions/" + mine.ID + "/fork", read, 403},
		{"GET", "/v1/fork-operations/unknown", read, 501},
		{"GET", "/v1/fork-operations/unknown", write, 403},
		{"GET", "/v1/fork-operations/unknown", "", 401},
	} {
		rec := s.bearer(c.method, apiHost, c.path, c.token, "{}")
		if rec.Code != c.want {
			t.Fatalf("%s %s: %d want %d", c.method, c.path, rec.Code, c.want)
		}
		if c.want == http.StatusNotImplemented {
			var body map[string]string
			if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil || body["code"] != "disk_fork_disabled" {
				t.Fatal("not the disabled API handler")
			}
		}
	}
	rec := s.bearer("GET", apiHost, "/v1/sessions", read, "")
	var list []sessionJSON
	if rec.Code != http.StatusOK || json.Unmarshal(rec.Body.Bytes(), &list) != nil || len(list) != 1 || list[0].ID != mine.ID {
		t.Fatal("unexpected child or changed ownership")
	}
	// Authorized application-host requests must reach the same disabled handler.
	if rec := s.do("POST", appHost, "/api/sessions/"+mine.ID+"/fork", alice, "{}"); rec.Code != 501 {
		t.Fatal(rec.Code)
	}
}
