package github

import (
	"context"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/r33drichards/computer-use/backend/internal/auth"
	"github.com/r33drichards/computer-use/backend/internal/sessions"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
)

type SessionReader interface {
	Get(context.Context, string) (sessions.Session, error)
}
type Service struct {
	Store     *Store
	Client    *Client
	Sessions  SessionReader
	BrokerURL string
}

func (s *Service) Register(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/connections/github", s.user(s.status))
	mux.HandleFunc("POST /api/connections/github/connect", s.user(s.start))
	mux.HandleFunc("GET /api/connections/github/callback", s.user(s.callback))
	mux.HandleFunc("DELETE /api/connections/github", s.user(s.disconnect))
}
func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
func failed(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, map[string]string{"error": message})
}
func (s *Service) user(next func(http.ResponseWriter, *http.Request, auth.User)) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		u, ok := auth.UserFrom(r.Context())
		if !ok {
			failed(w, 401, "not signed in")
			return
		}
		if u.Token != nil {
			failed(w, 403, "manage connections in the browser")
			return
		}
		// Browser writes must originate at the configured app, including connect.
		if r.Method != "GET" && r.Header.Get("Origin") != s.Client.PublicURL {
			failed(w, 403, "invalid request origin")
			return
		}
		next(w, r, u)
	}
}
func (s *Service) status(w http.ResponseWriter, r *http.Request, u auth.User) {
	_, c, err := s.Store.load(r.Context(), u.Subject)
	if errors.Is(err, ErrDisconnected) {
		writeJSON(w, 200, map[string]any{"connected": false, "install_url": s.Client.installURL()})
		return
	}
	if err != nil {
		failed(w, 503, "GitHub connection unavailable")
		return
	}
	writeJSON(w, 200, map[string]any{"connected": true, "login": c.Login, "install_url": s.Client.installURL(), "needs_reconnect": !time.Now().Before(c.RefreshExpires)})
}

const cookieName = "cu_github_oauth"

type oauthState struct {
	Owner, State, Verifier string
	Expires                time.Time
}

func (s *Service) cookie(value string, age int) *http.Cookie {
	return &http.Cookie{Name: cookieName, Value: value, Path: "/api/connections/github", MaxAge: age, HttpOnly: true, Secure: strings.HasPrefix(s.Client.PublicURL, "https://"), SameSite: http.SameSiteLaxMode}
}
func (s *Service) start(w http.ResponseWriter, r *http.Request, u auth.User) {
	state, err := randomID()
	if err != nil {
		failed(w, 503, "could not start GitHub authorization")
		return
	}
	verifier, err := randomID()
	if err != nil {
		failed(w, 503, "could not start GitHub authorization")
		return
	}
	sealed, err := s.Store.seal("oauth-state", oauthState{u.Subject, state, verifier, time.Now().Add(10 * time.Minute)})
	if err != nil {
		failed(w, 503, "could not start GitHub authorization")
		return
	}
	http.SetCookie(w, s.cookie(sealed, 600))
	hash := sha256.Sum256([]byte(verifier))
	q := url.Values{"client_id": {s.Client.ClientID}, "redirect_uri": {s.Client.callbackURL()}, "state": {state}, "code_challenge": {base64.RawURLEncoding.EncodeToString(hash[:])}, "code_challenge_method": {"S256"}, "prompt": {"select_account"}}
	writeJSON(w, 200, map[string]string{"url": s.Client.oauthURL + "/login/oauth/authorize?" + q.Encode()})
}
func (s *Service) callback(w http.ResponseWriter, r *http.Request, u auth.User) {
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Referrer-Policy", "no-referrer")
	cookie, err := r.Cookie(cookieName)
	http.SetCookie(w, s.cookie("", -1))
	var state oauthState
	if err != nil || s.Store.open("oauth-state", cookie.Value, &state) != nil || state.Owner != u.Subject || !time.Now().Before(state.Expires) || state.State == "" || subtle.ConstantTimeCompare([]byte(state.State), []byte(r.URL.Query().Get("state"))) != 1 || r.URL.Query().Get("code") == "" {
		http.Redirect(w, r, "/connections?github=error", http.StatusSeeOther)
		return
	}
	c, err := s.Client.exchange(r.Context(), url.Values{"code": {r.URL.Query().Get("code")}, "redirect_uri": {s.Client.callbackURL()}, "code_verifier": {state.Verifier}})
	if err == nil {
		c.Login, c.UserID, err = s.Client.identify(r.Context(), c.Access)
	}
	if err == nil {
		err = s.Store.connect(r.Context(), u.Subject, c)
	}
	if err != nil {
		http.Redirect(w, r, "/connections?github=error", http.StatusSeeOther)
		return
	}
	http.Redirect(w, r, "/connections?github=connected", http.StatusSeeOther)
}
func (s *Service) disconnect(w http.ResponseWriter, r *http.Request, u auth.User) {
	obj, c, err := s.Store.load(r.Context(), u.Subject)
	if errors.Is(err, ErrDisconnected) {
		w.WriteHeader(204)
		return
	}
	if err != nil {
		failed(w, 503, "GitHub connection unavailable")
		return
	}
	// Delete locally first, so no further session can obtain credentials.
	uid, rv := obj.GetUID(), obj.GetResourceVersion()
	if err = s.Store.client.Delete(r.Context(), obj.GetName(), metav1.DeleteOptions{Preconditions: &metav1.Preconditions{UID: &uid, ResourceVersion: &rv}}); err != nil {
		failed(w, 409, "connection changed; try disconnecting again")
		return
	}
	// Revoking the grant also invalidates issued tokens. A revoked token is already disconnected.
	if err = s.Client.revoke(r.Context(), c.Access); err != nil && !errors.Is(err, ErrDisconnected) {
		failed(w, 502, "Disconnected locally. GitHub revocation failed; revoke Computer Use in GitHub settings to invalidate issued tokens immediately.")
		return
	}
	w.WriteHeader(204)
}

// PrepareCreate defaults new sessions to the current connection. An explicit
// opt-out uses the warm pool normally; connected sessions start cold because a
// running warm pod cannot acquire per-session environment variables.
func (s *Service) PrepareCreate(ctx context.Context, owner string, enabled *bool) (context.Context, error) {
	if enabled != nil && !*enabled {
		return ctx, nil
	}
	_, c, err := s.Store.load(ctx, owner)
	if errors.Is(err, ErrDisconnected) && enabled == nil {
		return ctx, nil
	}
	if err != nil {
		return ctx, err
	}
	if !time.Now().Before(c.RefreshExpires) {
		return ctx, ErrDisconnected
	}
	token, err := randomID()
	if err != nil {
		return ctx, err
	}
	return sessions.WithGitHub(ctx, c.ID, token, s.BrokerURL), nil
}

// access serializes refresh-token rotation with Kubernetes resource versions.
// A replica that loses the CAS waits for the winner to persist the new pair.
func (s *Service) access(ctx context.Context, owner, binding string) (connection, error) {
	ctx, cancel := context.WithTimeout(ctx, 20*time.Second)
	defer cancel()
	for {
		obj, c, err := s.Store.load(ctx, owner)
		if err != nil {
			return c, err
		}
		if c.ID != binding {
			return c, ErrDisconnected
		}
		now := time.Now()
		if c.Expires.After(now.Add(time.Minute)) {
			return c, nil
		}
		if !now.Before(c.RefreshExpires) {
			return c, ErrDisconnected
		}
		lock, _, _ := unstructured.NestedString(obj.Object, "spec", "lockUntil")
		until, _ := time.Parse(time.RFC3339Nano, lock)
		if now.Before(until) {
			select {
			case <-ctx.Done():
				return c, ctx.Err()
			case <-time.After(150 * time.Millisecond):
				continue
			}
		}
		_ = unstructured.SetNestedField(obj.Object, now.Add(30*time.Second).Format(time.RFC3339Nano), "spec", "lockUntil")
		locked, err := s.Store.client.Update(ctx, obj, metav1.UpdateOptions{})
		if apierrors.IsConflict(err) {
			continue
		}
		if err != nil {
			return c, err
		}
		next, err := s.Client.exchange(ctx, url.Values{"grant_type": {"refresh_token"}, "refresh_token": {c.Refresh}})
		if err != nil {
			// Preserve the lock after an uncertain exchange: retrying a single-use
			// refresh token immediately could race a request still executing at GitHub.
			return c, err
		}
		next.ID, next.Login, next.UserID = c.ID, c.Login, c.UserID
		if err = s.Store.save(ctx, owner, next, locked); err != nil {
			return c, err
		}
		return next, nil
	}
}

// Broker is served on a separate cluster-only port. It accepts no Pomerium
// assertions or account API tokens, only a credential bound to one live session.
func (s *Service) Broker() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("POST /internal/github/credentials", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		var body struct {
			Session  string `json:"session"`
			Protocol string `json:"protocol"`
			Host     string `json:"host"`
		}
		if json.NewDecoder(http.MaxBytesReader(w, r.Body, 4096)).Decode(&body) != nil || !sessions.ValidID(body.Session) || body.Protocol != "https" || body.Host != "github.com" {
			failed(w, 400, "invalid GitHub credential request")
			return
		}
		session, err := s.Sessions.Get(r.Context(), body.Session)
		supplied := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
		hash := sha256.Sum256([]byte(supplied))
		if err != nil || session.GitHubConnection == "" || supplied == "" || !strings.HasPrefix(r.Header.Get("Authorization"), "Bearer ") || subtle.ConstantTimeCompare([]byte(session.GitHubCredentialHash), []byte(hex.EncodeToString(hash[:]))) != 1 {
			failed(w, 401, "invalid session credential")
			return
		}
		if session.State != sessions.Running || session.Draining != "" {
			failed(w, 403, "session is not running")
			return
		}
		c, err := s.access(r.Context(), session.Owner, session.GitHubConnection)
		if err != nil {
			failed(w, 403, "GitHub authorization unavailable; reconnect GitHub and create a new session")
			return
		}
		// Re-read after refresh: disconnect/reconnect must not return a stale grant.
		_, current, err := s.Store.load(r.Context(), session.Owner)
		if err != nil || current.ID != c.ID {
			failed(w, 403, "GitHub connection disconnected")
			return
		}
		writeJSON(w, 200, map[string]string{"username": c.Login, "password": c.Access})
	})
	return mux
}
