package config

import (
	"encoding/base64"
	"errors"
	"net/url"
	"regexp"
	"strings"
)

func (c *Config) githubFromEnv(get func(string) string) error {
	c.GitHubClientID = get("GITHUB_CLIENT_ID")
	c.GitHubClientSecret = Secret(get("GITHUB_CLIENT_SECRET"))
	c.GitHubAppSlug = get("GITHUB_APP_SLUG")
	raw := get("GITHUB_ENCRYPTION_KEY")
	if c.GitHubClientID == "" && c.GitHubClientSecret == "" && c.GitHubAppSlug == "" && raw == "" {
		return nil
	}
	if c.GitHubClientID == "" || c.GitHubClientSecret == "" || c.GitHubAppSlug == "" || raw == "" {
		return errors.New("GitHub connections require GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, GITHUB_APP_SLUG and GITHUB_ENCRYPTION_KEY")
	}
	if !regexp.MustCompile(`^[a-zA-Z0-9-]+$`).MatchString(c.GitHubAppSlug) {
		return errors.New("GITHUB_APP_SLUG must be a GitHub App slug")
	}
	key, err := base64.StdEncoding.DecodeString(raw)
	if err != nil || len(key) != 32 {
		return errors.New("GITHUB_ENCRYPTION_KEY must be a base64-encoded 32-byte key")
	}
	c.GitHubEncryptionKey = Secret(string(key))
	c.GitHubBrokerAddr = get("GITHUB_BROKER_ADDR")
	if c.GitHubBrokerAddr == "" {
		c.GitHubBrokerAddr = ":8082"
	}
	c.GitHubBrokerURL = strings.TrimRight(get("GITHUB_BROKER_URL"), "/")
	if c.GitHubBrokerURL == "" {
		c.GitHubBrokerURL = "http://github-broker." + c.Namespace + ".svc.cluster.local:8082"
	}
	u, err := url.Parse(c.GitHubBrokerURL)
	if err != nil || u.Host == "" || (u.Scheme != "http" && u.Scheme != "https") || u.User != nil || u.RawQuery != "" || u.Fragment != "" || u.Path != "" {
		return errors.New("GITHUB_BROKER_URL must be an absolute http(s) origin")
	}
	return nil
}
