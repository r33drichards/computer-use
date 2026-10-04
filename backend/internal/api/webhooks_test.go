package api_test

import (
	"encoding/json"
	"errors"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/runtime"
	dynfake "k8s.io/client-go/dynamic/fake"
	ktesting "k8s.io/client-go/testing"
	"strings"
	"testing"

	"github.com/r33drichards/computer-use/backend/internal/sessions"
	"github.com/r33drichards/computer-use/backend/internal/sessions/sessionstest"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
)

func TestWebhookSettingsOwnershipScopesAndSecret(t *testing.T) {
	f := newPolicyFixture(t, false)
	id := f.newSession(`{"name":"export"}`)
	path := "/api/sessions/" + id + "/webhook"
	for _, test := range []struct {
		who    string
		method string
		status int
	}{
		{"bob", "GET", 404}, {"bob", "PUT", 404}, {"read", "PUT", 403}, {"write", "GET", 403},
	} {
		u := bob
		if test.who == "read" {
			u = token("sessions:read")
		}
		if test.who == "write" {
			u = token("sessions:write")
		}
		if got := f.do(u, test.method, path, `{"url":"https://example.com"}`); got.Code != test.status {
			t.Fatalf("%+v: %d %s", test, got.Code, got.Body)
		}
	}
	body := `{"url":"https://example.com/hook","batch_size":2,"filter":"previous-filter","signing_secret":"sixteen-byte-secret"}`
	if rec := f.do(alice, "PUT", path, body); rec.Code != 204 {
		t.Fatalf("save: %d %s", rec.Code, rec.Body)
	}
	rec := f.do(alice, "GET", path, "")
	if rec.Code != 200 || strings.Contains(rec.Body.String(), "sixteen-byte-secret") || !strings.Contains(rec.Body.String(), `"has_signing_secret":true`) {
		t.Fatalf("read: %d %s", rec.Code, rec.Body)
	}
	if rec := f.do(alice, "PUT", path, `{"url":"https://new.example.com"}`); rec.Code != 204 {
		t.Fatalf("update: %d %s", rec.Code, rec.Body)
	}
	read := f.do(alice, "GET", path, "")
	var updated map[string]any
	if err := json.Unmarshal(read.Body.Bytes(), &updated); err != nil || updated["filter"] != "" || updated["batch_size"] != float64(100) || updated["flush_interval_seconds"] != float64(5) {
		t.Fatalf("PUT defaults not persisted: %s", read.Body)
	}
	sent := f.operator.sent("/v1/webhooks/validate")
	if sent["signing_secret"] != "sixteen-byte-secret" {
		t.Fatal("omission did not preserve secret")
	}
	if rec := f.do(alice, "PUT", path, `{"url":"https://bad.example.com","filter":"INVALID"}`); rec.Code != 422 {
		t.Fatalf("bad filter: %d %s", rec.Code, rec.Body)
	}
	rec = f.do(alice, "GET", path, "")
	if !strings.Contains(rec.Body.String(), "new.example.com") {
		t.Fatal("invalid filter replaced existing settings")
	}
	f.operator.setDown(true)
	if rec := f.do(alice, "PUT", path, body); rec.Code != 503 {
		t.Fatalf("unavailable: %d %s", rec.Code, rec.Body)
	}
	f.operator.setDown(false)
	if rec := f.do(alice, "DELETE", path, ""); rec.Code != 204 {
		t.Fatalf("delete: %d %s", rec.Code, rec.Body)
	}
	var doc any
	if json.Unmarshal(f.do(alice, "GET", path, "").Body.Bytes(), &doc) != nil || doc != nil {
		t.Fatal("delete left settings")
	}
	obj, err := f.client.Resource(sessions.PolicyGVR).Namespace(sessionstest.Namespace).Get(t.Context(), id, metav1.GetOptions{})
	if err != nil {
		t.Fatal(err)
	}
	source, _, _ := unstructured.NestedString(obj.Object, "spec", "source")
	if source == "" {
		t.Fatal("webhook delete removed enforcement policy")
	}
}

func TestWebhookUpdateRetriesConflictWithoutRestoringOldSecret(t *testing.T) {
	f := newPolicyFixture(t, false)
	id := f.newSession(`{"name":"export"}`)
	path := "/api/sessions/" + id + "/webhook"
	if rec := f.do(alice, "PUT", path, `{"url":"https://example.com","signing_secret":"original-secret-value"}`); rec.Code != 204 {
		t.Fatal(rec.Code, rec.Body)
	}
	attempts := 0
	f.client.(*dynfake.FakeDynamicClient).PrependReactor("patch", "sessionpolicies", func(action ktesting.Action) (bool, runtime.Object, error) {
		attempts++
		if attempts != 1 {
			return false, nil, nil
		}
		obj, err := f.client.(*dynfake.FakeDynamicClient).Tracker().Get(sessions.PolicyGVR, sessionstest.Namespace, id)
		if err != nil {
			t.Fatal(err)
		}
		u := obj.(*unstructured.Unstructured)
		if err := unstructured.SetNestedField(u.Object, "concurrently-rotated-secret", "spec", "webhook", "signing_secret"); err != nil {
			t.Fatal(err)
		}
		u.SetResourceVersion("2")
		if err := f.client.(*dynfake.FakeDynamicClient).Tracker().Update(sessions.PolicyGVR, u, sessionstest.Namespace); err != nil {
			t.Fatal(err)
		}
		return true, nil, apierrors.NewConflict(sessions.PolicyGVR.GroupResource(), id, errors.New("concurrent update"))
	})
	if rec := f.do(alice, "PUT", path, `{"url":"https://new.example.com"}`); rec.Code != 204 {
		t.Fatal(rec.Code, rec.Body)
	}
	obj, err := f.client.Resource(sessions.PolicyGVR).Namespace(sessionstest.Namespace).Get(t.Context(), id, metav1.GetOptions{})
	if err != nil {
		t.Fatal(err)
	}
	secret, _, _ := unstructured.NestedString(obj.Object, "spec", "webhook", "signing_secret")
	if attempts != 2 || secret != "concurrently-rotated-secret" {
		t.Fatalf("attempts=%d secret=%q", attempts, secret)
	}
}
