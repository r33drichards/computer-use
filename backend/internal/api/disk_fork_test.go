package api_test

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestDiskForkDisabledBothSurfacesNoMutation(t *testing.T) {
	f := newFixture(t)
	s, err := f.store.Create(t.Context(), "parent", alice.Subject)
	if err != nil {
		t.Fatal(err)
	}
	before, err := f.store.Get(t.Context(), s.ID)
	if err != nil {
		t.Fatal(err)
	}
	for _, prefix := range []string{"/api", "/v1"} {
		for i := 0; i < 2; i++ {
			rec := f.do(alice, "POST", prefix+"/sessions/"+s.ID+"/fork", "{}")
			if rec.Code != http.StatusNotImplemented {
				t.Fatalf("%s: %d %s", prefix, rec.Code, rec.Body)
			}
			body := decode[map[string]string](t, rec)
			if body["code"] != "disk_fork_disabled" {
				t.Fatal(body)
			}
		}
		if rec := f.do(bob, "POST", prefix+"/sessions/"+s.ID+"/fork", "{}"); rec.Code != http.StatusNotFound {
			t.Fatal(rec.Code)
		}
		if rec := f.do(alice, "GET", prefix+"/fork-operations/unknown", ""); rec.Code != http.StatusNotImplemented {
			t.Fatal(rec.Code)
		}
		rec := httptest.NewRecorder()
		f.handler.ServeHTTP(rec, httptest.NewRequest("POST", prefix+"/sessions/"+s.ID+"/fork", nil))
		if rec.Code != http.StatusUnauthorized {
			t.Fatal(rec.Code)
		}
	}
	after, err := f.store.Get(t.Context(), s.ID)
	if err != nil {
		t.Fatal(err)
	}
	if before.State != after.State || before.StateSaved != after.StateSaved {
		t.Fatalf("source changed: %+v -> %+v", before, after)
	}
	all, err := f.store.ListAll(t.Context())
	if err != nil || len(all) != 1 {
		t.Fatalf("unexpected child: %+v %v", all, err)
	}
}
