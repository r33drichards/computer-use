package main

import (
	"context"
	"log/slog"
	"net"
	"net/http"
	"time"

	"github.com/r33drichards/computer-use/backend/internal/config"
	gh "github.com/r33drichards/computer-use/backend/internal/github"
	"github.com/r33drichards/computer-use/backend/internal/sessions"
	"k8s.io/client-go/dynamic"
)

func newGitHub(cfg config.Config, dyn dynamic.Interface, store *sessions.Store) (*gh.Service, error) {
	if cfg.GitHubClientID == "" {
		return nil, nil
	}
	records, err := gh.NewStore(dyn, cfg.Namespace, []byte(cfg.GitHubEncryptionKey.Reveal()))
	if err != nil {
		return nil, err
	}
	return &gh.Service{Store: records, Client: gh.NewClient(cfg.GitHubClientID, cfg.GitHubClientSecret.Reveal(), cfg.PublicURL, cfg.GitHubAppSlug), Sessions: store, BrokerURL: cfg.GitHubBrokerURL}, nil
}
func serveGitHubBroker(ctx context.Context, addr string, service *gh.Service) error {
	if service == nil {
		return nil
	}
	ln, err := net.Listen("tcp", addr)
	if err != nil {
		return err
	}
	server := &http.Server{Handler: service.Broker(), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 10 * time.Second, WriteTimeout: 30 * time.Second, IdleTimeout: 30 * time.Second, MaxHeaderBytes: 8192}
	go func() {
		<-ctx.Done()
		closeCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = server.Shutdown(closeCtx)
	}()
	go func() {
		if err := server.Serve(ln); err != nil && err != http.ErrServerClosed {
			slog.Error("GitHub credential broker stopped", "err", err)
		}
	}()
	return nil
}
