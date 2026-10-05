package sessions

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"github.com/r33drichards/computer-use/backend/internal/diskfork"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
)

// CheckForkFence consumes existing trusted-controller ledgers. No initializer
// exists: legacy traffic is unchanged and cannot start a fork in this slice.
func (s *Store) CheckForkFence(ctx context.Context, id, intent string) error {
	return s.modifyIntent(ctx, id, intent, func(*unstructured.Unstructured) (bool, error) { return false, nil })
}

// AdmitForward records an unresolved receipt before actual pod dispatch on an
// already-tracked source. HTTP completion NEVER acknowledges its descendants.
// Ambiguous writes refuse dispatch. Only a future trusted execution supervisor
// can resolve receipts; capacity and malformed state fail closed.
func (s *Store) AdmitForward(ctx context.Context, id string) error {
	obj, err := s.client.Get(ctx, id, metav1.GetOptions{})
	if err != nil {
		return err
	}
	if obj.GetAnnotations()[diskfork.Annotation] == "" {
		return nil
	}
	var token [16]byte
	if _, err = rand.Read(token[:]); err != nil {
		return err
	}
	size := obj.GetAnnotations()[AnnSize]
	if size == "" {
		size = DefaultSize
	}
	return diskfork.New(s.client).Admit(ctx, diskfork.Source{Name: id, UID: obj.GetUID(), Owner: obj.GetAnnotations()[AnnOwner], Size: size}, hex.EncodeToString(token[:]))
}

// BeginDiskFork is deliberately unavailable, including for tracked sources:
// pinned mcp-exec has no atomic close-admission/descendant-drained certificate.
func (s *Store) BeginDiskFork(context.Context, string) error {
	return diskfork.ErrQuiescenceUnsupported
}
