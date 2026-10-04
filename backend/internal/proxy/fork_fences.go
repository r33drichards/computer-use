package proxy

import (
	"context"
	"net/http"
)

// ForkFences consumes pre-existing durable source fences. Legacy sources cannot
// enter pause: this is not provider quiescence or a fork enable switch.
type ForkFences interface {
	CheckForkFence(context.Context, string, string) error
	AdmitForward(context.Context, string) error
}

func (p *Proxy) admitForward(ctx context.Context, id string) error {
	if p.ForkFences == nil {
		return nil
	}
	return p.ForkFences.AdmitForward(ctx, id)
}
func (p *Proxy) guardedRoundTrip(ctx context.Context, id string, req *http.Request, transport http.RoundTripper) (*http.Response, error) {
	if err := p.admitForward(ctx, id); err != nil {
		return nil, err
	}
	return transport.RoundTrip(req)
}
