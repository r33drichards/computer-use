package proxy

import (
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/r33drichards/computer-use/backend/internal/sessions"
)

const historyName = "1720000000000-1234abcd.mp4"

func TestHistoryAccessAndRange(t *testing.T) {
	e := newEnv(t)
	e.respondWith(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Cookie") != "" || r.Header.Get("Authorization") != "" || r.Header.Get("Sec-Fetch-Dest") != "" || r.Header.Get("Origin") != "" {
			t.Error("history request leaked caller headers")
		}
		if r.URL.Path == "/history" {
			fmt.Fprintf(w, `{"seconds":300,"max_bytes":268435456,"clips":[{"name":%q,"start":1720000000000,"duration":5,"bytes":10},{"name":"../secret","start":1,"duration":5,"bytes":1}],"error":""}`, historyName)
		} else {
			w.Header().Set("Content-Type", "text/html")
			w.Header().Set("Set-Cookie", "evil=yes")
			w.Header().Set("Content-Range", "bytes 2-5/10")
			w.WriteHeader(206)
			io.WriteString(w, "2345")
		}
	})
	base := "/api/sessions/" + e.id + "/history"
	for _, user := range []string{alice, root, bob, ""} {
		for _, suffix := range []string{"", "/" + historyName} {
			rec := e.historyApp("GET", base+suffix, user, "", "Range", "bytes=2-5", "Origin", "https://app.example", "Sec-Fetch-Dest", "video")
			if user == bob && rec.Code != 404 {
				t.Errorf("other owner: %d", rec.Code)
			}
			if user == "" && rec.Code != 401 {
				t.Errorf("anonymous: %d", rec.Code)
			}
			if user == alice || user == root {
				if suffix == "" {
					if rec.Code != 200 || strings.Contains(rec.Body.String(), "../secret") {
						t.Errorf("index: %d %s", rec.Code, rec.Body.String())
					}
				} else if rec.Code != 206 || rec.Header().Get("Content-Type") != "video/mp4" || rec.Header().Get("Set-Cookie") != "" {
					t.Errorf("clip: %d %v", rec.Code, rec.Header())
				}
			}
		}
	}
	for _, name := range []string{"bad.mp4", "..%2Fsecret", "settings.json"} {
		if rec := e.historyApp("GET", base+"/"+name, alice, ""); rec.Code != 404 {
			t.Errorf("path %q: %d", name, rec.Code)
		}
	}
}

func TestHistoryDoesNotWakeOrKeepSessionAwake(t *testing.T) {
	e := newEnv(t)
	e.respondWith(func(w http.ResponseWriter, r *http.Request) {
		io.WriteString(w, `{"seconds":300,"max_bytes":268435456,"clips":[],"error":""}`)
	})
	base := "/api/sessions/" + e.id + "/history"
	before, _ := e.store.Get(t.Context(), e.id)
	if rec := e.historyApp("GET", base, alice, ""); rec.Code != 200 {
		t.Fatal(rec.Code)
	}
	after, _ := e.store.Get(t.Context(), e.id)
	if !before.LastActive.Equal(after.LastActive) {
		t.Fatal("history touched activity")
	}
	e.asleep(t)
	for _, method := range []string{"GET", "PUT"} {
		if rec := e.historyApp(method, base, alice, `{"seconds":0}`, "Content-Type", "application/json"); rec.Code != 409 {
			t.Errorf("asleep %s: %d", method, rec.Code)
		}
	}
	after, _ = e.store.Get(t.Context(), e.id)
	if after.State != sessions.Asleep {
		t.Fatal("history woke the session")
	}
}

func TestHistorySettingsValidation(t *testing.T) {
	e := newEnv(t)
	base := "/api/sessions/" + e.id + "/history"
	for _, body := range []string{`{}`, `{"seconds":-1}`, `{"seconds":3601}`, `{"seconds":1.5}`, `{"seconds":"300"}`} {
		if rec := e.historyApp("PUT", base, alice, body, "Content-Type", "application/json"); rec.Code != 400 {
			t.Errorf("%s: %d", body, rec.Code)
		}
	}
	if len(e.seen()) != 0 {
		t.Fatal("invalid settings reached the pod")
	}
}

func (e *env) historyApp(method, path, user, body string, headers ...string) *httptest.ResponseRecorder {
	req := request(method, appHost, path, user, body)
	for i := 0; i < len(headers); i += 2 {
		req.Header.Set(headers[i], headers[i+1])
	}
	rec := httptest.NewRecorder()
	e.handler.ServeHTTP(rec, req)
	return rec
}
