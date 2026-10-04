package proxy

import (
	"encoding/json"
	"errors"
	"github.com/r33drichards/computer-use/backend/internal/diskfork"
	"github.com/r33drichards/computer-use/backend/internal/sessions"
	"github.com/r33drichards/computer-use/backend/internal/sessions/sessionstest"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"net/http"
	"testing"
	"time"
)

func TestForkFenceRuntimeDispatchAndNoHTTPDrain(t *testing.T) {
	eachForm(t, func(t *testing.T, e *env) {
		e.proxy.ForkFences = e.store
		resource := e.client.Resource(sessions.SandboxGVR).Namespace(sessionstest.Namespace)
		obj, err := resource.Get(t.Context(), e.id, metav1.GetOptions{})
		if err != nil {
			t.Fatal(err)
		}
		uid := obj.GetUID()
		if uid == "" {
			uid = types.UID("source-uid")
			obj.SetUID(uid)
		}
		state := diskfork.State{Version: 1, SourceUID: uid, Receipts: map[string]bool{}, Operations: map[string]diskfork.Operation{}}
		set := func() {
			raw, _ := json.Marshal(state)
			ann := obj.GetAnnotations()
			ann[diskfork.Annotation] = string(raw)
			obj.SetAnnotations(ann)
			var err error
			obj, err = resource.Update(t.Context(), obj, metav1.UpdateOptions{})
			if err != nil {
				t.Fatal(err)
			}
		}
		set()
		rec := e.do("POST", "/mcp", alice, "{}")
		if rec.Code != http.StatusOK {
			t.Fatal(rec.Code)
		}
		obj, err = resource.Get(t.Context(), e.id, metav1.GetOptions{})
		if err != nil {
			t.Fatal(err)
		}
		if err = json.Unmarshal([]byte(obj.GetAnnotations()[diskfork.Annotation]), &state); err != nil {
			t.Fatal(err)
		}
		if len(state.Receipts) != 1 || state.Drained() {
			t.Fatal("HTTP completion fabricated drain")
		}
		ticket := e.ticket(t, alice)
		state.Gate = "fork"
		state.Operations["fork"] = diskfork.Operation{ID: "fork", Phase: "draining", Deadline: time.Unix(100, 0)}
		set()
		before := len(e.seen())
		for _, c := range []struct{ method, path, user string }{
			{"POST", "/mcp", alice}, {"GET", "/mcp", alice}, {"PUT", "/api/artifact-uploads/" + uploadToken, ""},
		} {
			rec := e.do(c.method, c.path, c.user, "{}")
			if rec.Code == 200 {
				t.Fatal("gated dispatch allowed")
			}
		}
		for _, c := range fileRoutes(e.id) {
			rec := e.app(c.method, c.path, alice, "payload")
			if rec.Code == http.StatusOK || rec.Code == http.StatusCreated || rec.Code == http.StatusNoContent {
				t.Fatal("fenced file dispatch allowed")
			}
		}
		if rec := e.doUpgrade(e.id, "/vnc?ticket="+ticket); rec.Code != http.StatusConflict {
			t.Fatalf("VNC fence: %d", rec.Code)
		}
		if err = e.proxy.askBrowserStart(t.Context(), e.id); !errors.Is(err, diskfork.ErrGated) {
			t.Fatal(err)
		}
		if len(e.seen()) != before {
			t.Fatal("request reached pod after fence")
		}
	})
}
