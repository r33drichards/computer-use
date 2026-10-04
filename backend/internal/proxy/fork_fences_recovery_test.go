package proxy

import (
	"context"
	"encoding/json"
	"github.com/r33drichards/computer-use/backend/internal/diskfork"
	"github.com/r33drichards/computer-use/backend/internal/policy"
	"github.com/r33drichards/computer-use/backend/internal/sessions"
	"github.com/r33drichards/computer-use/backend/internal/sessions/sessionstest"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	dynfake "k8s.io/client-go/dynamic/fake"
	k8stesting "k8s.io/client-go/testing"
	"reflect"
	"testing"
	"time"
)

type restoreFenceStore struct {
	*sessions.Store
	install       func()
	woken, failed bool
	cold          int
}

func (s *restoreFenceStore) Wake(ctx context.Context, id string) error {
	if err := s.Store.Wake(ctx, id); err != nil {
		return err
	}
	s.woken = true
	s.install()
	return nil
}
func (s *restoreFenceStore) Get(ctx context.Context, id string) (sessions.Session, error) {
	v, err := s.Store.Get(ctx, id)
	if err == nil && s.woken {
		v.State = sessions.Starting
		v.Node = "synthetic-node"
		if s.failed {
			v.State = sessions.Failed
		}
	}
	return v, err
}
func (s *restoreFenceStore) ColdStart(ctx context.Context, id string) (bool, error) {
	s.cold++
	return s.Store.ColdStart(ctx, id)
}
func TestForkFenceWakerRestoreFallbackDoesNotClean(t *testing.T) {
	for _, failed := range []bool{true, false} {
		name := "timeout"
		if failed {
			name = "failed"
		}
		t.Run(name, func(t *testing.T) {
			store, c, _ := sessionstest.NewWithSnapshots(t, sessions.SnapshotOptions{Timeout: time.Second})
			s, err := store.Create(t.Context(), "source", "user-1")
			if err != nil {
				t.Fatal(err)
			}
			sessionstest.SetStatus(t, c, s.ID, sessionstest.Ready("10.0.0.7"))
			if err := store.Sleep(t.Context(), s.ID, sessions.StoppedByIdle, nil); err != nil {
				t.Fatal(err)
			}
			sessionstest.SetStatus(t, c, s.ID, sessionstest.Suspended())
			fake := c.(*dynfake.FakeDynamicClient)
			res := c.Resource(sessions.SandboxGVR).Namespace(sessionstest.Namespace)
			marker := 0
			var before *unstructured.Unstructured
			wrapper := &restoreFenceStore{Store: store, failed: failed}
			wrapper.install = func() {
				o, e := res.Get(context.Background(), s.ID, metav1.GetOptions{})
				if e != nil {
					t.Fatal(e)
				}
				state := diskfork.State{Version: 1, SourceUID: o.GetUID(), Gate: "fork", Receipts: map[string]bool{"uncertain": false}, Operations: map[string]diskfork.Operation{"fork": {ID: "fork", Phase: "draining", Deadline: time.Unix(1, 0)}}}
				raw, _ := json.Marshal(state)
				ann := o.GetAnnotations()
				ann[diskfork.Annotation] = string(raw)
				o.SetAnnotations(ann)
				before, e = res.Update(context.Background(), o, metav1.UpdateOptions{})
				if e != nil {
					t.Fatal(e)
				}
				marker = len(fake.Actions())
			}
			// Exercise the production policy wrapper's embedded ColdStart path. No
			// policy summary is consulted for these Starting/Failed synthetic states.
			tick := int64(0)
			w := &Waker{Store: &policy.Gated{SessionStore: wrapper}, Timeout: 10 * time.Second, RestoreTimeout: time.Millisecond, Poll: time.Millisecond, now: func() time.Time { tick++; return time.Unix(tick, 0) }}
			if _, err := w.EnsureAwake(t.Context(), s.ID); err == nil {
				t.Fatal("fenced restore succeeded")
			}
			if wrapper.cold != 1 {
				t.Fatalf("cold fallback calls=%d", wrapper.cold)
			}
			for _, a := range fake.Actions()[marker:] {
				if a.GetVerb() == "delete" || a.GetVerb() == "update" || a.GetVerb() == "patch" {
					t.Fatal("effect after installed gate", a)
				}
			}
			after, e := res.Get(t.Context(), s.ID, metav1.GetOptions{})
			if e != nil || !reflect.DeepEqual(before.Object, after.Object) || len(sessionstest.Snapshots(t, c)) != 1 {
				t.Fatal("source/snapshot modified")
			}
		})
	}
}

type removalFences struct {
	store  *sessions.Store
	client *dynfake.FakeDynamicClient
}

func (f *removalFences) CheckForkFence(ctx context.Context, id, intent string) error {
	return f.store.CheckForkFence(ctx, id, intent)
}
func (f *removalFences) AdmitForward(ctx context.Context, id string) error {
	n := 0
	f.client.PrependReactor("get", sessions.SandboxGVR.Resource, func(a k8stesting.Action) (bool, runtime.Object, error) {
		if a.(k8stesting.GetAction).GetName() == id {
			n++
			if n == 3 {
				o, e := f.client.Tracker().Get(sessions.SandboxGVR, sessionstest.Namespace, id)
				if e != nil {
					return true, nil, e
				}
				v := o.(*unstructured.Unstructured).DeepCopy()
				ann := v.GetAnnotations()
				delete(ann, diskfork.Annotation)
				v.SetAnnotations(ann)
				if e = f.client.Tracker().Update(sessions.SandboxGVR, v, sessionstest.Namespace); e != nil {
					return true, nil, e
				}
			}
		}
		return false, nil, nil
	})
	return f.store.AdmitForward(ctx, id)
}
func TestForkFenceLedgerRemovalRefusesActualForward(t *testing.T) {
	eachForm(t, func(t *testing.T, e *env) {
		res := e.client.Resource(sessions.SandboxGVR).Namespace(sessionstest.Namespace)
		o, err := res.Get(t.Context(), e.id, metav1.GetOptions{})
		if err != nil {
			t.Fatal(err)
		}
		state := diskfork.State{Version: 1, SourceUID: o.GetUID(), Receipts: map[string]bool{"uncertain": false}, Operations: map[string]diskfork.Operation{"old": {ID: "old", Phase: "cancelled", Deadline: time.Unix(1, 0)}}}
		raw, _ := json.Marshal(state)
		ann := o.GetAnnotations()
		ann[diskfork.Annotation] = string(raw)
		o.SetAnnotations(ann)
		if _, err = res.Update(t.Context(), o, metav1.UpdateOptions{}); err != nil {
			t.Fatal(err)
		}
		e.proxy.ForkFences = &removalFences{store: e.store, client: e.client.(*dynfake.FakeDynamicClient)}
		before := len(e.seen())
		rec := e.do("POST", "/mcp", alice, "{}")
		if rec.Code >= 200 && rec.Code < 300 || len(e.seen()) != before {
			t.Fatal("dispatched after ledger disappeared", rec.Code)
		}
		got, err := res.Get(t.Context(), e.id, metav1.GetOptions{})
		if err != nil || got.GetAnnotations()[diskfork.Annotation] != "" {
			t.Fatal("ledger recreated")
		}
	})
}
