// Package featureflags evaluates account limits through OpenFeature.
package featureflags

import (
	"context"
	"encoding/json"
	"os"

	"github.com/open-feature/go-sdk/openfeature"
)

const MaxSessionDiskGB = "session-disk-max-gb"

// FileProvider reads a mounted ConfigMap on every evaluation, including updates
// made without restarting the backend. Account keys are stable owner labels.
type FileProvider struct {
	openfeature.NoopProvider
	Path string
}

type IntegerFlag struct {
	Default  int64            `json:"default"`
	Accounts map[string]int64 `json:"accounts"`
}

func (p FileProvider) Metadata() openfeature.Metadata {
	return openfeature.Metadata{Name: "account-configmap"}
}

func (p FileProvider) IntEvaluation(_ context.Context, key string, fallback int64, ctx openfeature.FlattenedContext) openfeature.IntResolutionDetail {
	result := openfeature.IntResolutionDetail{Value: fallback, ProviderResolutionDetail: openfeature.ProviderResolutionDetail{Reason: openfeature.DefaultReason}}
	raw, err := os.ReadFile(p.Path)
	if err != nil {
		return result
	}
	var flags map[string]IntegerFlag
	if json.Unmarshal(raw, &flags) != nil {
		return result
	}
	flag, ok := flags[key]
	if !ok {
		return result
	}
	result.Value = flag.Default
	if account, ok := ctx[openfeature.TargetingKey].(string); ok {
		if value, ok := flag.Accounts[account]; ok {
			result.Value = value
			result.Reason = openfeature.TargetingMatchReason
		}
	}
	return result
}

func Client(path string) (*openfeature.Client, error) {
	if err := openfeature.SetNamedProviderAndWait("session-limits", FileProvider{Path: path}); err != nil {
		return nil, err
	}
	return openfeature.NewClient("session-limits"), nil
}
