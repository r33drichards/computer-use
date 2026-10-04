package github

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/r33drichards/computer-use/backend/internal/auth"
	"github.com/r33drichards/computer-use/backend/internal/sessions"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
	dynfake "k8s.io/client-go/dynamic/fake"
	ktest "k8s.io/client-go/testing"
)

const owner = "alice@example.com"
const sessionID = "s-aaaaaaaaaa"

type sessionReader struct{ session sessions.Session }

func (r *sessionReader) Get(_ context.Context, id string) (sessions.Session, error) {
	if id != r.session.ID {
		return sessions.Session{}, sessions.ErrNotFound
	}
	return r.session, nil
}
func harness(t *testing.T) (*Service, *dynfake.FakeDynamicClient) {
	t.Helper()
	client := dynfake.NewSimpleDynamicClient(runtime.NewScheme())
	store, err := NewStore(client, "test", []byte(strings.Repeat("k", 32)))
	if err != nil {
		t.Fatal(err)
	}
	return &Service{Store: store, Client: NewClient("id", "secret", "https://app.example.com", "computer-use"), BrokerURL: "http://github-broker:8082"}, client
}
func grant() connection {
	return connection{Login: "alice", UserID: 123, Access: "ghu_private", Refresh: "ghr_private", Expires: time.Now().Add(time.Hour), RefreshExpires: time.Now().Add(24 * time.Hour)}
}
func connect(t *testing.T, s *Service) connection {
	t.Helper()
	if err := s.Store.connect(context.Background(), owner, grant()); err != nil {
		t.Fatal(err)
	}
	_, c, err := s.Store.load(context.Background(), owner)
	if err != nil {
		t.Fatal(err)
	}
	return c
}
func userRequest(method, path string) *http.Request {
	r := httptest.NewRequest(method, path, nil)
	r.Header.Set("Origin", "https://app.example.com")
	return r.WithContext(auth.WithUser(r.Context(), auth.User{Subject: owner}))
}
func routes(s *Service) *http.ServeMux { mux := http.NewServeMux(); s.Register(mux); return mux }
func TestEncryptedRecordAndOwnerBinding(t *testing.T) {
	s, client := harness(t)
	c := connect(t, s)
	obj, err := client.Resource(GVR).Namespace("test").Get(context.Background(), recordName(owner), metav1.GetOptions{})
	if err != nil {
		t.Fatal(err)
	}
	data, _ := json.Marshal(obj.Object)
	if strings.Contains(string(data), "ghu_private") || strings.Contains(string(data), "ghr_private") {
		t.Fatal("token stored in plaintext")
	}
	encoded, _, _ := unstructured.NestedString(obj.Object, "spec", "encrypted")
	var decoded connection
	if err = s.Store.open("bob@example.com", encoded, &decoded); err == nil {
		t.Fatal("ciphertext accepted for another owner")
	}
	if err = s.Store.open(owner, encoded, &decoded); err != nil || decoded.ID != c.ID {
		t.Fatal("roundtrip", err)
	}
	if _, err = NewStore(client, "test", []byte("bad")); err == nil {
		t.Fatal("short key accepted")
	}
}
func TestOAuthPKCEAndCallback(t *testing.T) {
	s, _ := harness(t)
	var exchanged atomic.Int32
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/login/oauth/access_token":
			_ = r.ParseForm()
			if r.Form.Get("code_verifier") == "" || r.Form.Get("redirect_uri") != s.Client.callbackURL() {
				t.Error("missing PKCE or callback")
			}
			exchanged.Add(1)
			writeJSON(w, 200, map[string]any{"access_token": "ghu_private", "refresh_token": "ghr_private", "expires_in": 28800, "refresh_token_expires_in": 15897600})
		case "/user":
			writeJSON(w, 200, map[string]any{"login": "alice", "id": 123})
		default:
			t.Errorf("unexpected GitHub request %s", r.URL.Path)
			w.WriteHeader(404)
		}
	}))
	defer remote.Close()
	s.Client.oauthURL = remote.URL
	s.Client.apiURL = remote.URL
	mux := routes(s)
	start := httptest.NewRecorder()
	mux.ServeHTTP(start, userRequest("POST", "/api/connections/github/connect"))
	if start.Code != 200 {
		t.Fatal(start.Code, start.Body.String())
	}
	var answer map[string]string
	_ = json.Unmarshal(start.Body.Bytes(), &answer)
	target, _ := url.Parse(answer["url"])
	cookie := start.Result().Cookies()[0]
	if !cookie.HttpOnly || !cookie.Secure || cookie.SameSite != http.SameSiteLaxMode {
		t.Fatal("unsafe OAuth cookie")
	}
	var state oauthState
	if err := s.Store.open("oauth-state", cookie.Value, &state); err != nil {
		t.Fatal(err)
	}
	hash := sha256.Sum256([]byte(state.Verifier))
	if target.Query().Get("code_challenge") != base64URL(hash[:]) || target.Query().Get("code_challenge_method") != "S256" {
		t.Fatal("invalid PKCE challenge")
	}
	// A callback from another Computer Use account must not exchange its code.
	wrong := userRequest("GET", "/api/connections/github/callback?code=code&state="+target.Query().Get("state"))
	wrong = wrong.WithContext(auth.WithUser(wrong.Context(), auth.User{Subject: "bob@example.com"}))
	wrong.AddCookie(cookie)
	refused := httptest.NewRecorder()
	mux.ServeHTTP(refused, wrong)
	if refused.Header().Get("Location") != "/connections?github=error" || exchanged.Load() != 0 {
		t.Fatal("wrong owner callback accepted")
	}
	callback := userRequest("GET", "/api/connections/github/callback?code=code&state="+target.Query().Get("state"))
	callback.AddCookie(cookie)
	done := httptest.NewRecorder()
	mux.ServeHTTP(done, callback)
	if done.Header().Get("Location") != "/connections?github=connected" || exchanged.Load() != 1 {
		t.Fatal(done.Code, done.Header(), done.Body.String())
	}
	_, c, err := s.Store.load(context.Background(), owner)
	if err != nil || c.Login != "alice" {
		t.Fatal(err, c)
	}
	// Invalid state is refused before any request to GitHub.
	callback = userRequest("GET", "/api/connections/github/callback?code=code&state=wrong")
	callback.AddCookie(cookie)
	done = httptest.NewRecorder()
	mux.ServeHTTP(done, callback)
	if exchanged.Load() != 1 {
		t.Fatal("invalid state exchanged")
	}
}
func base64URL(b []byte) string { return base64.RawURLEncoding.EncodeToString(b) }
func TestBrowserWritesRequireOriginAndRefuseAPITokens(t *testing.T) {
	s, _ := harness(t)
	mux := routes(s)
	for _, method := range []string{"POST", "DELETE"} {
		path := "/api/connections/github"
		if method == "POST" {
			path += "/connect"
		}
		r := userRequest(method, path)
		r.Header.Set("Origin", "https://evil.example")
		w := httptest.NewRecorder()
		mux.ServeHTTP(w, r)
		if w.Code != 403 {
			t.Fatal("foreign origin", w.Code)
		}
	}
	r := userRequest("GET", "/api/connections/github")
	r = r.WithContext(auth.WithUser(r.Context(), auth.User{Subject: owner, Token: &auth.TokenInfo{}}))
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, r)
	if w.Code != 403 {
		t.Fatal("API token accepted")
	}
}
func brokerRequest(s *Service, token, host, id string) *httptest.ResponseRecorder {
	r := httptest.NewRequest("POST", "/internal/github/credentials", strings.NewReader(fmt.Sprintf(`{"session":%q,"protocol":"https","host":%q}`, id, host)))
	r.Header.Set("Authorization", "Bearer "+token)
	w := httptest.NewRecorder()
	s.Broker().ServeHTTP(w, r)
	return w
}
func TestBrokerBindingRevocationAndLifecycle(t *testing.T) {
	s, _ := harness(t)
	c := connect(t, s)
	hash := sha256.Sum256([]byte("session-secret"))
	reader := &sessionReader{sessions.Session{ID: sessionID, Owner: owner, State: sessions.Running, GitHubConnection: c.ID, GitHubCredentialHash: hex.EncodeToString(hash[:])}}
	s.Sessions = reader
	if w := brokerRequest(s, "session-secret", "github.com", sessionID); w.Code != 200 || !strings.Contains(w.Body.String(), "ghu_private") || w.Header().Get("Cache-Control") != "no-store" {
		t.Fatal("valid session", w.Code, w.Body.String())
	}
	for _, test := range []struct {
		token, host, id string
		code            int
	}{{"bad", "github.com", sessionID, 401}, {"session-secret", "evil.example", sessionID, 400}, {"session-secret", "github.com", "s-bbbbbbbbbb", 401}} {
		if w := brokerRequest(s, test.token, test.host, test.id); w.Code != test.code {
			t.Fatal(test, w.Code)
		}
	}
	reader.session.State = sessions.Asleep
	if w := brokerRequest(s, "session-secret", "github.com", sessionID); w.Code != 403 {
		t.Fatal("asleep session authenticated")
	}
	reader.session.State = sessions.Running
	reader.session.Owner = "bob@example.com"
	if w := brokerRequest(s, "session-secret", "github.com", sessionID); w.Code != 403 {
		t.Fatal("another owner's connection authenticated")
	}
	reader.session.Owner = owner
	connect(t, s)
	if w := brokerRequest(s, "session-secret", "github.com", sessionID); w.Code != 403 {
		t.Fatal("old session inherited new connection")
	}
}
func TestDisconnectDeletesAndRevokesGrant(t *testing.T) {
	s, _ := harness(t)
	connect(t, s)
	var revoked bool
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "DELETE" || r.URL.Path != "/applications/id/grant" {
			t.Error("wrong revoke request")
		}
		id, secret, ok := r.BasicAuth()
		if !ok || id != "id" || secret != "secret" {
			t.Error("missing app authentication")
		}
		revoked = true
		w.WriteHeader(204)
	}))
	defer remote.Close()
	s.Client.apiURL = remote.URL
	w := httptest.NewRecorder()
	routes(s).ServeHTTP(w, userRequest("DELETE", "/api/connections/github"))
	if w.Code != 204 || !revoked {
		t.Fatal(w.Code, w.Body.String())
	}
	if _, _, err := s.Store.load(context.Background(), owner); !errors.Is(err, ErrDisconnected) {
		t.Fatal("connection survived disconnect")
	}
}
func TestCreateDefaultAndOptOut(t *testing.T) {
	s, _ := harness(t)
	ctx := context.Background()
	if _, err := s.PrepareCreate(ctx, owner, nil); err != nil {
		t.Fatal("unconnected default", err)
	}
	yes, no := true, false
	if _, err := s.PrepareCreate(ctx, owner, &yes); !errors.Is(err, ErrDisconnected) {
		t.Fatal("explicit connect without connection")
	}
	connect(t, s)
	if result, err := s.PrepareCreate(ctx, owner, &no); err != nil || result != ctx {
		t.Fatal("opt-out configured GitHub")
	}
	if result, err := s.PrepareCreate(ctx, owner, nil); err != nil || result == ctx {
		t.Fatal("default did not configure GitHub")
	}
}
func TestRefreshAcrossReplicas(t *testing.T) {
	s, client := harness(t)
	c := connect(t, s)
	obj, _, _ := s.Store.load(context.Background(), owner)
	c.Expires = time.Now().Add(-time.Minute)
	if err := s.Store.save(context.Background(), owner, c, obj); err != nil {
		t.Fatal(err)
	}
	obj, _, _ = s.Store.load(context.Background(), owner)
	obj.SetResourceVersion("1")
	_ = client.Tracker().Update(GVR, obj, "test")
	// The dynamic fake lacks API-server CAS; emulate resourceVersion conflicts.
	var mu sync.Mutex
	version := 1
	client.PrependReactor("update", "githubconnections", func(action ktest.Action) (bool, runtime.Object, error) {
		mu.Lock()
		defer mu.Unlock()
		asked := action.(ktest.UpdateAction).GetObject().(*unstructured.Unstructured).DeepCopy()
		current, err := client.Tracker().Get(GVR, "test", asked.GetName())
		if err != nil {
			return true, nil, err
		}
		if asked.GetResourceVersion() != current.(*unstructured.Unstructured).GetResourceVersion() {
			return true, nil, apierrors.NewConflict(schema.GroupResource{Group: GVR.Group, Resource: GVR.Resource}, asked.GetName(), errors.New("changed"))
		}
		version++
		asked.SetResourceVersion(fmt.Sprint(version))
		err = client.Tracker().Update(GVR, asked, "test")
		return true, asked, err
	})
	var exchanges atomic.Int32
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = r.ParseForm()
		if r.Form.Get("refresh_token") != "ghr_private" || r.Form.Get("grant_type") != "refresh_token" {
			t.Error("wrong refresh")
		}
		exchanges.Add(1)
		time.Sleep(100 * time.Millisecond)
		writeJSON(w, 200, map[string]any{"access_token": "ghu_new", "refresh_token": "ghr_new", "expires_in": 28800, "refresh_token_expires_in": 15897600})
	}))
	defer remote.Close()
	s.Client.oauthURL = remote.URL
	replica := *s
	replica.Store, _ = NewStore(client, "test", []byte(strings.Repeat("k", 32)))
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Go(func() {
			next, err := replica.access(context.Background(), owner, c.ID)
			if err != nil || next.Access != "ghu_new" {
				t.Error("refresh", err)
			}
		})
	}
	wg.Wait()
	if exchanges.Load() != 1 {
		t.Fatal("refresh token used", exchanges.Load(), "times")
	}
	_, stored, _ := s.Store.load(context.Background(), owner)
	if stored.Refresh != "ghr_new" {
		t.Fatal("rotated refresh token not persisted")
	}
}
