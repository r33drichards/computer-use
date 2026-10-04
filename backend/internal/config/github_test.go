package config

import (
	"encoding/base64"
	"strings"
	"testing"
)

func TestGitHubConfiguration(t *testing.T) {
	values := map[string]string{"PUBLIC_URL": "https://app.example.com", "SESSION_URL_TEMPLATE": "https://sessions.example.com/{id}", "POMERIUM_JWKS_URL": "https://app.example.com/jwks", "GITHUB_CLIENT_ID": "id", "GITHUB_CLIENT_SECRET": "secret", "GITHUB_APP_SLUG": "computer-use", "GITHUB_ENCRYPTION_KEY": base64.StdEncoding.EncodeToString([]byte(strings.Repeat("k", 32)))}
	c, err := FromEnv(env(values))
	if err != nil {
		t.Fatal(err)
	}
	if c.GitHubBrokerURL != "http://github-broker.browserjs-sessions.svc.cluster.local:8082" || c.GitHubBrokerAddr != ":8082" {
		t.Fatal("broker defaults", c.GitHubBrokerURL)
	}
	for _, field := range []string{"GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET", "GITHUB_APP_SLUG", "GITHUB_ENCRYPTION_KEY"} {
		copy := map[string]string{}
		for k, v := range values {
			copy[k] = v
		}
		delete(copy, field)
		if _, err := FromEnv(env(copy)); err == nil {
			t.Fatalf("partial config accepted: missing %s", field)
		}
	}
	for _, bad := range []string{"ftp://broker", "http://user:pass@broker", "http://broker?token=x", "http://broker/path"} {
		values["GITHUB_BROKER_URL"] = bad
		if _, err := FromEnv(env(values)); err == nil {
			t.Fatal("unsafe URL accepted", bad)
		}
	}
}
