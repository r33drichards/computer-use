package diskfork

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strconv"
	"sync"
	"testing"
	"time"

	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/apimachinery/pkg/types"
)

// Fake API server implements the identity/resourceVersion semantics missing
// from client-go's simple object tracker. It can commit then lose a response.
// This is not a live Kubernetes or CSI test.
type fakeAPI struct {
	mu        sync.Mutex
	obj       *unstructured.Unstructured
	version   int
	lose      bool
	conflicts int
	before    func(*unstructured.Unstructured)
}

func fixture() (*fakeAPI, Source) {
	src := Source{Name: "s-aaaaaaaaaa", UID: types.UID("source-uid"), Owner: "owner", Size: "small"}
	obj := &unstructured.Unstructured{Object: map[string]any{"apiVersion": "agents.x-k8s.io/v1beta1", "kind": "Sandbox"}}
	obj.SetName(src.Name)
	obj.SetUID(src.UID)
	obj.SetResourceVersion("1")
	obj.SetAnnotations(map[string]string{"browserjs.dev/owner-id": src.Owner, "browserjs.dev/in-flight." + "dead": "2000-01-01T00:00:00Z"})
	initial := State{Version: 1, SourceUID: src.UID, Receipts: map[string]bool{}, Operations: map[string]Operation{}}
	raw, _ := json.Marshal(initial)
	ann := obj.GetAnnotations()
	ann[Annotation] = string(raw)
	obj.SetAnnotations(ann)
	return &fakeAPI{obj: obj, version: 1}, src
}
func (a *fakeAPI) Get(ctx context.Context, name string, _ metav1.GetOptions, _ ...string) (*unstructured.Unstructured, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.obj.DeepCopy(), nil
}
func (a *fakeAPI) Update(ctx context.Context, obj *unstructured.Unstructured, _ metav1.UpdateOptions, _ ...string) (*unstructured.Unstructured, error) {
	if a.before != nil {
		a.before(obj)
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.conflicts > 0 {
		a.conflicts--
		a.version++
		a.obj.SetResourceVersion(strconv.Itoa(a.version))
	}
	if obj.GetResourceVersion() != a.obj.GetResourceVersion() || obj.GetUID() != a.obj.GetUID() {
		return nil, apierrors.NewConflict(schema.GroupResource{Group: "agents.x-k8s.io", Resource: "sandboxes"}, obj.GetName(), errors.New("CAS conflict"))
	}
	a.version++
	a.obj = obj.DeepCopy()
	a.obj.SetResourceVersion(strconv.Itoa(a.version))
	if a.lose {
		a.lose = false
		return nil, errors.New("response lost after durable commit")
	}
	return a.obj.DeepCopy(), nil
}
func check(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatal(err)
	}
}
func TestGateAndAdmissionRace(t *testing.T) {
	for i := 0; i < 50; i++ {
		server, src := fixture()
		one, two := New(server), New(server)
		start := make(chan struct{})
		var admitErr, gateErr error
		var wg sync.WaitGroup
		wg.Add(2)
		go func() { defer wg.Done(); <-start; admitErr = one.Admit(t.Context(), src, "work") }()
		go func() { defer wg.Done(); <-start; gateErr = two.Begin(t.Context(), src, "fork", time.Unix(100, 0)) }()
		close(start)
		wg.Wait()
		check(t, gateErr)
		s, err := New(server).Inspect(t.Context(), src)
		check(t, err)
		if admitErr == nil {
			if s.Drained() || s.Receipts["work"] {
				t.Fatal("lost actual work")
			}
		} else if !errors.Is(admitErr, ErrGated) {
			t.Fatal(admitErr)
		}
		if err := two.Admit(t.Context(), src, "late"); !errors.Is(err, ErrGated) {
			t.Fatalf("late admission: %v", err)
		}
	}
}
func TestLostResponsesRestartAndHungDeadline(t *testing.T) {
	server, src := fixture()
	b := New(server)
	server.lose = true
	if err := b.Admit(t.Context(), src, "hung"); err == nil {
		t.Fatal("expected ambiguous response")
	}
	b = New(server) // worker restart; memory lost
	if err := b.Admit(t.Context(), src, "hung"); !errors.Is(err, ErrReplay) {
		t.Fatalf("duplicate execution: %v", err)
	}
	deadline := time.Unix(100, 0)
	server.lose = true
	if err := b.Begin(t.Context(), src, "fork", deadline); err == nil {
		t.Fatal("expected ambiguous response")
	}
	b = New(server)
	check(t, b.Begin(t.Context(), src, "fork", deadline))
	s, err := b.Inspect(t.Context(), src)
	check(t, err)
	if s.Drained() {
		t.Fatal("expired mark fabricated completion")
	}
	if err := b.AbortDeadline(t.Context(), src, "fork", deadline.Add(-time.Second)); !errors.Is(err, ErrOperation) {
		t.Fatal(err)
	}
	server.lose = true
	if err := b.AbortDeadline(t.Context(), src, "fork", deadline); err == nil {
		t.Fatal("expected ambiguous response")
	}
	b = New(server)
	check(t, b.AbortDeadline(t.Context(), src, "fork", deadline))
	check(t, b.Begin(t.Context(), src, "fork", deadline)) // replay must NOT reopen gate
	s, err = b.Inspect(t.Context(), src)
	check(t, err)
	if s.Gate != "" || s.Drained() || s.Operations["fork"].Phase != "cancelled" {
		t.Fatalf("unsafe abort: %+v", s)
	}
	check(t, b.Admit(t.Context(), src, "new-work"))
	check(t, b.Complete(t.Context(), src, "hung"))
	check(t, b.Complete(t.Context(), src, "new-work"))
	s, err = b.Inspect(t.Context(), src)
	check(t, err)
	if !s.Drained() {
		t.Fatal(s)
	}
}
func TestFencesConflictAndMalformedState(t *testing.T) {
	server, src := fixture()
	b := New(server)
	server.conflicts = 1
	check(t, b.Admit(t.Context(), src, "work"))
	for _, bad := range []Source{{Name: src.Name, UID: "other", Owner: src.Owner, Size: src.Size}, {Name: src.Name, UID: src.UID, Owner: "other", Size: src.Size}, {Name: src.Name, UID: src.UID, Owner: src.Owner, Size: "large"}} {
		if err := b.Begin(t.Context(), bad, "fork", time.Unix(100, 0)); !errors.Is(err, ErrIdentity) {
			t.Fatal(err)
		}
	}
	if err := b.Complete(t.Context(), src, "unknown"); !errors.Is(err, ErrOperation) {
		t.Fatal(err)
	}
	server.mu.Lock()
	ann := server.obj.GetAnnotations()
	ann[Annotation] = "invalid JSON"
	server.obj.SetAnnotations(ann)
	server.mu.Unlock()
	if err := b.Admit(t.Context(), src, "late"); err == nil {
		t.Fatal("corrupt ledger accepted")
	}
	server.mu.Lock()
	server.obj.SetUID("replacement")
	server.mu.Unlock()
	if _, err := b.Inspect(t.Context(), src); !errors.Is(err, ErrIdentity) {
		t.Fatal(err)
	}
}
func TestReceiptLimitFailsClosed(t *testing.T) {
	server, src := fixture()
	b := New(server)
	for i := 0; i < maxReceipts; i++ {
		id := fmt.Sprint(i)
		check(t, b.Admit(t.Context(), src, id))
		check(t, b.Complete(t.Context(), src, id))
	}
	if err := b.Admit(t.Context(), src, "overflow"); !errors.Is(err, ErrCapacity) {
		t.Fatal(err)
	}
}

// Force an admission read before the gate, but its write AFTER gate commit.
// A check-then-register implementation would incorrectly admit this request.
func TestStaleAdmissionCASLosesToGate(t *testing.T) {
	server, src := fixture()
	readDone, release := make(chan struct{}), make(chan struct{})
	server.before = func(obj *unstructured.Unstructured) {
		state, err := read(obj)
		if err != nil {
			panic(err)
		}
		if _, ok := state.Receipts["stale"]; ok && state.Gate == "" {
			close(readDone)
			<-release
		}
	}
	done := make(chan error, 1)
	go func() { done <- New(server).Admit(t.Context(), src, "stale") }()
	<-readDone
	check(t, New(server).Begin(t.Context(), src, "fork", time.Unix(100, 0)))
	close(release)
	if err := <-done; !errors.Is(err, ErrGated) {
		t.Fatalf("stale registration admitted: %v", err)
	}
	state, err := New(server).Inspect(t.Context(), src)
	check(t, err)
	if _, ok := state.Receipts["stale"]; ok {
		t.Fatal("stale request persisted")
	}
}

func TestLegacyCannotBeginOrFabricateQuiescence(t *testing.T) {
	server, src := fixture()
	ann := server.obj.GetAnnotations()
	delete(ann, Annotation)
	server.obj.SetAnnotations(ann)
	if err := New(server).Begin(t.Context(), src, "fork", time.Unix(100, 0)); !errors.Is(err, ErrQuiescenceUnsupported) {
		t.Fatal(err)
	}
	if err := New(server).Admit(t.Context(), src, "new-work"); !errors.Is(err, ErrQuiescenceUnsupported) {
		t.Fatal(err)
	}
	if server.obj.GetAnnotations()[Annotation] != "" {
		t.Fatal("legacy initialization occurred")
	}
}
func TestIntentEpochAndReplacementUIDFailClosed(t *testing.T) {
	server, src := fixture()
	b := New(server)
	check(t, b.Begin(t.Context(), src, "fork", time.Unix(100, 0)))
	obj, err := server.Get(t.Context(), src.Name, metav1.GetOptions{})
	check(t, err)
	changed, err := IntentOnFence(obj, "stop")
	if !changed || !errors.Is(err, ErrGated) {
		t.Fatal(changed, err)
	}
	changed, err = IntentOnFence(obj, "delete")
	if !changed || !errors.Is(err, ErrGated) {
		t.Fatal(changed, err)
	}
	changed, err = IntentOnFence(obj, "resume")
	if changed || !errors.Is(err, ErrGated) {
		t.Fatal(changed, err)
	}
	state, err := read(obj)
	check(t, err)
	if state.Intent != "delete" || state.IntentEpoch != 2 {
		t.Fatal(state)
	}
	obj.SetUID("replacement")
	if err := Fence(obj); !errors.Is(err, ErrIdentity) {
		t.Fatal(err)
	}
}
