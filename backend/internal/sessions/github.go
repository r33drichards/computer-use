package sessions

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
)

const (
	AnnGitHubConnection     = "browserjs.dev/github-connection"
	AnnGitHubCredentialHash = "browserjs.dev/github-credential-sha256"
)

type gitHubKey struct{}
type gitHubSetup struct{ connection, credential, brokerURL string }

func WithGitHub(ctx context.Context, connection, credential, brokerURL string) context.Context {
	return context.WithValue(ctx, gitHubKey{}, gitHubSetup{connection, credential, brokerURL})
}
func githubOf(ctx context.Context) *gitHubSetup {
	v, ok := ctx.Value(gitHubKey{}).(gitHubSetup)
	if !ok {
		return nil
	}
	return &v
}
func applyGitHub(spec map[string]any, annotations map[string]any, id string, setup *gitHubSetup) error {
	if setup == nil {
		return nil
	}
	if setup.connection == "" || setup.credential == "" || setup.brokerURL == "" {
		return errors.New("GitHub session configuration is incomplete")
	}
	for _, c := range containersOf(spec) {
		if c["name"] != "browser" {
			continue
		}
		env, _ := c["env"].([]any)
		for _, item := range []struct{ name, value string }{{"CU_GITHUB_SESSION", id}, {"CU_GITHUB_CREDENTIAL", setup.credential}, {"CU_GITHUB_BROKER_URL", setup.brokerURL}} {
			env = append(env, map[string]any{"name": item.name, "value": item.value})
		}
		c["env"] = env
		hash := sha256.Sum256([]byte(setup.credential))
		annotations[AnnGitHubConnection] = setup.connection
		annotations[AnnGitHubCredentialHash] = hex.EncodeToString(hash[:])
		return nil
	}
	return errors.New("GitHub authentication requires the browser container")
}
