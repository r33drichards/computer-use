package api_test

import (
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/r33drichards/computer-use/backend/internal/featureflags"
	"github.com/r33drichards/computer-use/backend/internal/sessions"
)

func TestDiskCapacityIndependentOfComputeAndAccountOverride(t *testing.T) {
	f := sized(t)
	path := filepath.Join(t.TempDir(), "flags.json")
	write := func(value string) {
		t.Helper()
		if err := os.WriteFile(path, []byte(value), 0600); err != nil {
			t.Fatal(err)
		}
	}
	write(`{"session-disk-max-gb":{"default":128,"accounts":{"` + sessions.OwnerLabel(alice.Subject) + `":256}}}`)
	flags, err := featureflags.Client(path)
	if err != nil {
		t.Fatal(err)
	}
	f.api.SetDiskFlags(flags)
	for _, test := range []struct {
		body   string
		status int
	}{
		{`{"size":"small","diskGB":256}`, http.StatusCreated},
		{`{"size":"medium","diskGB":32}`, http.StatusCreated},
		{`{"size":"small","diskGB":257}`, http.StatusBadRequest},
		{`{"diskGB":-1}`, http.StatusBadRequest},
	} {
		rec := f.do(alice, "POST", "/api/sessions", test.body)
		if rec.Code != test.status {
			t.Fatalf("%s: %d %s", test.body, rec.Code, rec.Body)
		}
		if rec.Code == http.StatusCreated {
			created := decode[session](t, rec)
			if created.DiskGB == 0 {
				t.Fatalf("missing disk capacity: %s", rec.Body)
			}
			f.do(alice, "DELETE", "/api/sessions/"+created.ID, "")
		}
	}
	if rec := f.do(bob, "POST", "/api/sessions", `{"diskGB":129}`); rec.Code != http.StatusBadRequest {
		t.Fatalf("override leaked to another account: %d %s", rec.Code, rec.Body)
	}
	write(`{"session-disk-max-gb":{"default":128,"accounts":{}}}`)
	if rec := f.do(alice, "POST", "/api/sessions", `{"diskGB":129}`); rec.Code != http.StatusBadRequest {
		t.Fatalf("config update not observed: %d %s", rec.Code, rec.Body)
	}
	write(`invalid`)
	if rec := f.do(alice, "GET", "/api/sizes", ""); !strings.Contains(rec.Body.String(), `"maxGB":128`) {
		t.Fatalf("invalid flags did not use safe default: %s", rec.Body)
	}
}
