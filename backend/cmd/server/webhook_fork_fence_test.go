package main

import (
	"encoding/json"
	"github.com/golang-jwt/jwt/v5"
	"github.com/r33drichards/computer-use/backend/internal/auth"
	"github.com/r33drichards/computer-use/backend/internal/config"
	"github.com/r33drichards/computer-use/backend/internal/diskfork"
	"github.com/r33drichards/computer-use/backend/internal/idle"
	"github.com/r33drichards/computer-use/backend/internal/sessions"
	"github.com/r33drichards/computer-use/backend/internal/sessions/sessionstest"
	"github.com/r33drichards/computer-use/backend/internal/tokens"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
	dynfake "k8s.io/client-go/dynamic/fake"
	ktesting "k8s.io/client-go/testing"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func TestWebhookForkFenceActualHosts(t *testing.T) {
	for _, host := range []string{appHost, apiHost} {
		for _, kind := range []string{"gate", "malformed", "copied"} {
			t.Run(host+"/"+kind, func(t *testing.T) {
				var validationCalls, patches atomic.Int64
				op := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
					if strings.HasSuffix(r.URL.Path, "/validate") {
						validationCalls.Add(1)
					}
					w.Header().Set("Content-Type", "application/json")
					_, _ = w.Write([]byte("{\"ok\":true,\"errors\":[],\"warnings\":[]}"))
				}))
				defer op.Close()
				base := newServer(t)
				store, client := sessionstest.NewWithPolicies(t)
				cfg := config.Config{WebDir: t.TempDir(), PublicURL: sessionstest.PublicURL, SessionURLs: sessionstest.URLs(), SignOutURL: "/.pomerium/sign_out", ReadyTimeout: time.Second, MaxSessionsPerUser: 5, PolicyOperatorURL: op.URL, OperatorAPIToken: "synthetic-operator-canary", APIURL: "https://" + apiHost, AllowedEmails: []string{alice, bob}}
				verifier, err := auth.NewAssertionVerifier(func(*jwt.Token) (any, error) { return &base.key.PublicKey, nil }, []string{root})
				if err != nil {
					t.Fatal(err)
				}
				app, _ := newHandler(cfg, verifier, store, idle.New(store, "test", 15*time.Minute, time.Now))
				ts := tokens.NewStore(dynfake.NewSimpleDynamicClientWithCustomListKinds(runtime.NewScheme(), map[schema.GroupVersionResource]string{tokens.GVR: "APITokenList"}), sessionstest.Namespace)
				s := &server{t: t, key: base.key, client: client}
				s.handler, err = withAPITokens(cfg, verifier, ts, app)
				if err != nil {
					t.Fatal(err)
				}
				mine := s.session(alice)
				_, all := s.newToken(alice, auth.Scopes...)
				_, read := s.newToken(alice, auth.ScopeSessionsRead)
				_, other := s.newToken(bob, auth.Scopes...)
				path := "/api/sessions/" + mine.ID + "/webhook"
				if host == apiHost {
					path = "/v1/sessions/" + mine.ID + "/webhook"
				}
				request := func(method, who, body string) *httptest.ResponseRecorder {
					if host == apiHost {
						return s.bearer(method, host, path, who, body)
					}
					return s.do(method, host, path, who, body)
				}
				who := alice
				if host == apiHost {
					who = all
				}
				const secret = "synthetic-e37-signing-secret"
				if rec := request("PUT", who, "{\"url\":\"https://example.com/hook\",\"signing_secret\":\""+secret+"\"}"); rec.Code != 204 {
					t.Fatal(rec.Code, rec.Body)
				}
				policyRes := client.Resource(sessions.PolicyGVR).Namespace(sessionstest.Namespace)
				before, err := policyRes.Get(t.Context(), mine.ID, metav1.GetOptions{})
				if err != nil {
					t.Fatal(err)
				}
				fake := client.(*dynfake.FakeDynamicClient)
				fake.PrependReactor("patch", sessions.PolicyGVR.Resource, func(a ktesting.Action) (bool, runtime.Object, error) { patches.Add(1); return false, nil, nil })
				resource := client.Resource(sessions.SandboxGVR).Namespace(sessionstest.Namespace)
				obj, err := resource.Get(t.Context(), mine.ID, metav1.GetOptions{})
				if err != nil {
					t.Fatal(err)
				}
				state := diskfork.State{Version: 1, SourceUID: obj.GetUID(), Gate: "fork", Receipts: map[string]bool{"uncertain": false}, Operations: map[string]diskfork.Operation{"fork": {ID: "fork", Phase: "draining", Deadline: time.Unix(100, 0)}}}
				if kind == "copied" {
					state.SourceUID = "copied-other-uid"
				}
				raw, _ := json.Marshal(state)
				if kind == "malformed" {
					raw = []byte("{")
				}
				ann := obj.GetAnnotations()
				ann[diskfork.Annotation] = string(raw)
				obj.SetAnnotations(ann)
				if _, err = resource.Update(t.Context(), obj, metav1.UpdateOptions{}); err != nil {
					t.Fatal(err)
				}
				baseline := validationCalls.Load()
				want := 500
				if kind == "gate" {
					want = 409
				}
				for i := 0; i < 2; i++ {
					for _, method := range []string{"PUT", "DELETE"} {
						rec := request(method, who, "{\"url\":\"https://example.com/new\",\"filter\":\"INVALID\"}")
						if rec.Code != want {
							t.Fatalf("%s: %d %s", method, rec.Code, rec.Body)
						}
						if kind == "gate" && !strings.Contains(rec.Body.String(), "disk_fork_fenced") {
							t.Fatal("wrong fence error")
						}
					}
				}
				if validationCalls.Load() != baseline || patches.Load() != 0 {
					t.Fatal("operator validation/policy effect after refusal")
				}
				after, err := policyRes.Get(t.Context(), mine.ID, metav1.GetOptions{})
				if err != nil || !reflect.DeepEqual(before.Object["spec"], after.Object["spec"]) {
					t.Fatal("policy/secret mutated")
				}
				rec := request("GET", who, "")
				if rec.Code != 200 || strings.Contains(rec.Body.String(), secret) || !strings.Contains(rec.Body.String(), "has_signing_secret") {
					t.Fatal("GET changed/leaked secret", rec.Code)
				}
				foreign := bob
				if host == apiHost {
					foreign = other
				}
				if rec := request("PUT", foreign, "{}"); rec.Code != 404 {
					t.Fatal("ownership precedence", rec.Code)
				}
				if host == apiHost {
					if rec := request("PUT", read, "{}"); rec.Code != 403 {
						t.Fatal("scope precedence", rec.Code)
					}
					if rec := request("GET", read, ""); rec.Code != 200 {
						t.Fatal("read scope", rec.Code)
					}
				}
				obj, err = resource.Get(t.Context(), mine.ID, metav1.GetOptions{})
				if err != nil {
					t.Fatal(err)
				}
				ann = obj.GetAnnotations()
				delete(ann, diskfork.Annotation)
				obj.SetAnnotations(ann)
				if _, err = resource.Update(t.Context(), obj, metav1.UpdateOptions{}); err != nil {
					t.Fatal(err)
				}
				if rec := request("PUT", who, "{\"url\":\"https://example.com/after\"}"); rec.Code != 204 {
					t.Fatal(rec.Code)
				}
				after, err = policyRes.Get(t.Context(), mine.ID, metav1.GetOptions{})
				if err != nil {
					t.Fatal(err)
				}
				got, _, _ := unstructured.NestedString(after.Object, "spec", "webhook", "signing_secret")
				if got != secret {
					t.Fatal("secret lost on unfenced retry")
				}
				if rec := request("DELETE", who, ""); rec.Code != 204 {
					t.Fatal(rec.Code)
				}
			})
		}
	}
}
