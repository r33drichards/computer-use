package diskfork

import (
	"context"
	"encoding/json"
	"errors"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"testing"
	"time"
)

type erasedAPI struct {
	base           *fakeAPI
	reads, eraseAt int
	conflict       bool
	writes         int
}

func (a *erasedAPI) erase() {
	a.base.mu.Lock()
	defer a.base.mu.Unlock()
	ann := a.base.obj.GetAnnotations()
	delete(ann, Annotation)
	a.base.obj.SetAnnotations(ann)
}
func (a *erasedAPI) Get(ctx context.Context, n string, o metav1.GetOptions, _ ...string) (*unstructured.Unstructured, error) {
	a.reads++
	if a.reads == a.eraseAt {
		a.erase()
	}
	return a.base.Get(ctx, n, o)
}
func (a *erasedAPI) Update(ctx context.Context, o *unstructured.Unstructured, opts metav1.UpdateOptions, _ ...string) (*unstructured.Unstructured, error) {
	a.writes++
	if a.conflict {
		a.conflict = false
		a.erase()
		return nil, apierrors.NewConflict(schema.GroupResource{Resource: "sandboxes"}, o.GetName(), errors.New("erased during CAS"))
	}
	return a.base.Update(ctx, o, opts)
}
func TestLedgerRemovalEveryProtocolMutation(t *testing.T) {
	for _, name := range []string{"admit", "begin", "complete", "abort"} {
		for _, window := range []string{"read", "conflict"} {
			t.Run(name+"/"+window, func(t *testing.T) {
				base, src := fixture()
				s, _ := read(base.obj)
				s.Receipts["uncertain"] = false
				s.Receipts["work"] = false
				s.Operations["old"] = Operation{ID: "old", Phase: "cancelled", Deadline: time.Unix(1, 0)}
				if name == "abort" {
					s.Gate = "fork"
					s.Operations["fork"] = Operation{ID: "fork", Phase: "draining", Deadline: time.Unix(1, 0)}
				}
				raw, _ := json.Marshal(s)
				ann := base.obj.GetAnnotations()
				ann[Annotation] = string(raw)
				base.obj.SetAnnotations(ann)
				a := &erasedAPI{base: base}
				if window == "conflict" {
					a.conflict = true
				} else {
					a.eraseAt = 1
					if name == "admit" || name == "begin" {
						a.eraseAt = 2
					}
				}
				b := New(a)
				var err error
				switch name {
				case "admit":
					err = b.Admit(t.Context(), src, "new")
				case "begin":
					err = b.Begin(t.Context(), src, "new", time.Unix(10, 0))
				case "complete":
					err = b.Complete(t.Context(), src, "work")
				case "abort":
					err = b.AbortDeadline(t.Context(), src, "fork", time.Unix(2, 0))
				}
				if !errors.Is(err, ErrQuiescenceUnsupported) {
					t.Fatalf("mutation authorized after loss: %v", err)
				}
				if base.obj.GetAnnotations()[Annotation] != "" {
					t.Fatal("recreated erased receipts/tombstones")
				}
				want := 0
				if window == "conflict" {
					want = 1
				}
				if a.writes != want {
					t.Fatalf("writes=%d", a.writes)
				}
				if _, err := b.Inspect(t.Context(), src); !errors.Is(err, ErrQuiescenceUnsupported) {
					t.Fatal("missing ledger fabricated inspection/drain", err)
				}
				if err := Fence(base.obj); err != nil {
					t.Fatal("legacy fence inspection changed", err)
				}
				if changed, err := IntentOnFence(base.obj, "stop"); changed || err != nil {
					t.Fatal("legacy intent initialized ledger", err)
				}
				// The external erasure destroyed evidence, NOT the outstanding execution.
				if s.Drained() || s.Receipts["uncertain"] || s.Operations["old"].Phase != "cancelled" {
					t.Fatal("bad uncertainty fixture")
				}
			})
		}
	}
}
