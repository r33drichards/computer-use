package api

import (
	"context"
	"fmt"

	"github.com/open-feature/go-sdk/openfeature"
	"github.com/r33drichards/computer-use/backend/internal/featureflags"
	"github.com/r33drichards/computer-use/backend/internal/sessions"
)

type DiskSizer interface {
	GrowDisk(context.Context, string, int) error
}
type DiskFlagClient interface {
	IntValue(context.Context, string, int64, openfeature.EvaluationContext, ...openfeature.Option) (int64, error)
}

func (a *API) SetDiskFlags(client DiskFlagClient) { a.diskFlags = client }

func (a *API) diskLimit(ctx context.Context, owner string) int {
	limit := int64(128)
	if a.diskFlags != nil {
		account := sessions.OwnerLabel(owner)
		value, err := a.diskFlags.IntValue(ctx, featureflags.MaxSessionDiskGB, 128, openfeature.NewEvaluationContext(account, map[string]any{"accountId": account}))
		if err == nil && value >= 32 && value <= 1536 {
			limit = value
		}
	}
	return int(limit)
}

func (a *API) checkDisk(ctx context.Context, owner string, gb int) error {
	if gb < 10 || gb > a.diskLimit(ctx, owner) {
		return fmt.Errorf("diskGB must be between 10 and %d: %w", a.diskLimit(ctx, owner), sessions.ErrInvalidDisk)
	}
	return nil
}
