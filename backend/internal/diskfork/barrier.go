// Package diskfork contains a fail-closed admission foundation with limited backend consumers.
// It is NOT a disk fork controller. No caller may use it to certify unmount.
package diskfork

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/client-go/util/retry"
	"time"
)

const Annotation = "browserjs.dev/disk-fork-barrier-v1"
const maxReceipts = 256
const maxOperations = 16

var (
	ErrGated                 = errors.New("disk fork admission closed")
	ErrIdentity              = errors.New("source identity changed")
	ErrReplay                = errors.New("execution token already recorded; do not execute again")
	ErrCapacity              = errors.New("barrier receipt capacity exhausted")
	ErrOperation             = errors.New("operation conflict")
	ErrQuiescenceUnsupported = errors.New("execution supervisor quiescence contract unavailable")
)

// Resource is satisfied by a namespaced dynamic Sandbox client. Updates MUST
// enforce resourceVersion and UID identity (the Kubernetes API server does).
type Resource interface {
	Get(context.Context, string, metav1.GetOptions, ...string) (*unstructured.Unstructured, error)
	Update(context.Context, *unstructured.Unstructured, metav1.UpdateOptions, ...string) (*unstructured.Unstructured, error)
}
type Source struct {
	Name        string
	UID         types.UID
	Owner, Size string
}
type Operation struct {
	ID       string
	Deadline time.Time
	Phase    string
}
type State struct {
	Version     int
	SourceUID   types.UID
	Intent      string
	IntentEpoch uint64
	Gate        string
	// Receipts never expire. A dead proxy or expired activity mark cannot
	// attest that an upstream process (or its background descendants) ended.
	Receipts   map[string]bool      // true: actual completion acknowledged
	Operations map[string]Operation // durable idempotency tombstones
}
type Barrier struct{ resource Resource }

func New(resource Resource) *Barrier { return &Barrier{resource: resource} }

func read(obj *unstructured.Unstructured) (State, error) {
	s := State{Version: 1, SourceUID: obj.GetUID(), Receipts: map[string]bool{}, Operations: map[string]Operation{}}
	if raw := obj.GetAnnotations()[Annotation]; raw != "" {
		s = State{}
		if err := json.Unmarshal([]byte(raw), &s); err != nil {
			return s, fmt.Errorf("invalid barrier: %w", err)
		}
		if s.SourceUID == "" || s.SourceUID != obj.GetUID() {
			return s, ErrIdentity
		}
		if s.Version != 1 || s.Receipts == nil || s.Operations == nil || len(s.Receipts) > maxReceipts || len(s.Operations) > maxOperations {
			return s, errors.New("invalid barrier schema")
		}
		for id := range s.Receipts {
			if !token(id) {
				return s, errors.New("invalid receipt")
			}
		}
		for id, op := range s.Operations {
			if !token(id) || op.ID != id || op.Deadline.IsZero() || (op.Phase != "draining" && op.Phase != "cancelled") || (op.Phase == "draining" && s.Gate != id) {
				return s, errors.New("invalid operation")
			}
		}
		if s.Gate != "" {
			op, ok := s.Operations[s.Gate]
			if !ok || op.Phase != "draining" {
				return s, errors.New("invalid barrier gate")
			}
		}
	}
	return s, nil
}
func validSource(obj *unstructured.Unstructured, src Source) bool {
	size := obj.GetAnnotations()["browserjs.dev/size"]
	if size == "" {
		size = "small"
	}
	return obj.GetName() == src.Name && src.UID != "" && obj.GetUID() == src.UID && obj.GetDeletionTimestamp() == nil && src.Owner != "" && obj.GetAnnotations()["browserjs.dev/owner-id"] == src.Owner && size == src.Size
}
func token(s string) bool { return len(s) > 0 && len(s) <= 128 }
func (b *Barrier) change(ctx context.Context, src Source, f func(*State) (bool, error)) error {
	return retry.RetryOnConflict(retry.DefaultRetry, func() error {
		obj, err := b.resource.Get(ctx, src.Name, metav1.GetOptions{})
		if err != nil {
			return err
		}
		if !validSource(obj, src) {
			return ErrIdentity
		}
		s, err := read(obj)
		if err != nil {
			return err
		}
		changed, err := f(&s)
		if err != nil || !changed {
			return err
		}
		raw, err := json.Marshal(s)
		if err != nil {
			return err
		}
		ann := obj.GetAnnotations()
		if ann == nil {
			ann = map[string]string{}
		}
		ann[Annotation] = string(raw)
		obj.SetAnnotations(ann)
		_, err = b.resource.Update(ctx, obj, metav1.UpdateOptions{})
		// Ambiguous non-conflict errors reach the caller. Retry with the SAME
		// execution token/key discovers the durable receipt, not an expired lease.
		return err
	})
}

// Admit linearizes with Begin on the SAME Sandbox resourceVersion. This is
// only useful once EVERY forwarding and mutation path uses it, before waking,
// touching disk, or starting upstream work. Not wired in this slice.
func (b *Barrier) Admit(ctx context.Context, src Source, id string) error {
	obj, err := b.resource.Get(ctx, src.Name, metav1.GetOptions{})
	if err != nil {
		return err
	}
	if obj.GetAnnotations()[Annotation] == "" {
		return ErrQuiescenceUnsupported
	}
	if !token(id) {
		return errors.New("invalid execution token")
	}
	return b.change(ctx, src, func(s *State) (bool, error) {
		if _, ok := s.Receipts[id]; ok {
			return false, ErrReplay
		}
		if s.Gate != "" {
			return false, ErrGated
		}
		if len(s.Receipts) >= maxReceipts {
			return false, ErrCapacity
		}
		s.Receipts[id] = false
		return true, nil
	})
}

// Complete is restricted to a trusted execution supervisor's positive ACK
// that actual execution and all descendants ended. HTTP completion, socket
// closure, cancellation request, worker death, and expiry are NOT this ACK.
func (b *Barrier) Complete(ctx context.Context, src Source, id string) error {
	return b.change(ctx, src, func(s *State) (bool, error) {
		done, ok := s.Receipts[id]
		if !ok {
			return false, ErrOperation
		}
		if done {
			return false, nil
		}
		s.Receipts[id] = true
		return true, nil
	})
}
func (b *Barrier) Begin(ctx context.Context, src Source, key string, deadline time.Time) error {
	if !token(key) || deadline.IsZero() {
		return ErrOperation
	}
	obj, err := b.resource.Get(ctx, src.Name, metav1.GetOptions{})
	if err != nil {
		return err
	}
	if obj.GetAnnotations()[Annotation] == "" {
		return ErrQuiescenceUnsupported
	}
	return b.change(ctx, src, func(s *State) (bool, error) {
		if op, ok := s.Operations[key]; ok {
			if !op.Deadline.Equal(deadline) {
				return false, ErrOperation
			}
			return false, nil
		}
		if s.Gate != "" {
			return false, ErrGated
		}
		if len(s.Operations) >= maxOperations {
			return false, ErrCapacity
		}
		s.Operations[key] = Operation{ID: key, Deadline: deadline, Phase: "draining"}
		s.Gate = key
		return true, nil
	})
}

// AbortDeadline only releases admission. It does not kill, resume, stop,
// snapshot, or forget actual work. There is NO transition into shutdown here.
func (b *Barrier) AbortDeadline(ctx context.Context, src Source, key string, now time.Time) error {
	return b.change(ctx, src, func(s *State) (bool, error) {
		op, ok := s.Operations[key]
		if !ok {
			return false, ErrOperation
		}
		if op.Phase == "cancelled" {
			return false, nil
		}
		if s.Gate != key || op.Phase != "draining" || now.Before(op.Deadline) {
			return false, ErrOperation
		}
		op.Phase = "cancelled"
		s.Operations[key] = op
		s.Gate = ""
		return true, nil
	})
}
func (b *Barrier) Inspect(ctx context.Context, src Source) (State, error) {
	obj, err := b.resource.Get(ctx, src.Name, metav1.GetOptions{})
	if err != nil {
		return State{}, err
	}
	if !validSource(obj, src) {
		return State{}, ErrIdentity
	}
	return read(obj)
}

// Drained is a ledger predicate, NOT proof of physical quiescence/unmount.
func (s State) Drained() bool {
	for _, done := range s.Receipts {
		if !done {
			return false
		}
	}
	return true
}

// Fence consumes an existing durable gate. Corruption or a copied ledger from
// another UID fails closed. It does not initialize tracking or certify drain.
func Fence(obj *unstructured.Unstructured) error {
	state, err := read(obj)
	if err != nil {
		return err
	}
	if state.Gate != "" {
		return ErrGated
	}
	return nil
}

// IntentOnFence records attempted current intent atomically with a refusal.
// The request still fails; this is not an accepted user action or auto-resume.
func IntentOnFence(obj *unstructured.Unstructured, intent string) (bool, error) {
	state, err := read(obj)
	if err != nil {
		return false, err
	}
	if state.Gate == "" {
		return false, nil
	}
	if intent == "" || state.Intent == intent || state.Intent == "delete" {
		return false, ErrGated
	}
	state.Intent = intent
	state.IntentEpoch++
	raw, err := json.Marshal(state)
	if err != nil {
		return false, err
	}
	ann := obj.GetAnnotations()
	ann[Annotation] = string(raw)
	obj.SetAnnotations(ann)
	return true, ErrGated
}
