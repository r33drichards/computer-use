package sessions_test

import (
	"context"
	"errors"
	"reflect"
	"testing"
	"time"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/client-go/dynamic"
	dynfake "k8s.io/client-go/dynamic/fake"

	"github.com/r33drichards/computer-use/backend/internal/sessions"
	"github.com/r33drichards/computer-use/backend/internal/sessions/sessionstest"
)

var nodes = schema.GroupVersionResource{Version: "v1", Resource: "nodes"}

func sandbox(t *testing.T, client dynamic.Interface, id string) *unstructured.Unstructured {
	t.Helper()
	obj, err := client.Resource(sessions.SandboxGVR).Namespace(sessionstest.Namespace).Get(t.Context(), id, metav1.GetOptions{})
	if err != nil {
		t.Fatal(err)
	}
	return obj
}

func pin(obj *unstructured.Unstructured) string {
	sel, _, _ := unstructured.NestedStringMap(obj.Object, "spec", "podTemplate", "spec", "nodeSelector")
	return sel[sessions.LabelPool]
}

// running creates a session whose pod runs on sessionstest.Node.
func running(t *testing.T, store *sessions.Store, client dynamic.Interface) string {
	t.Helper()
	s, err := store.Create(t.Context(), "a", "user-1")
	if err != nil {
		t.Fatal(err)
	}
	sessionstest.SetStatus(t, client, s.ID, sessionstest.Ready("10.0.0.7"))
	return s.ID
}

func addSnapshot(t *testing.T, client dynamic.Interface, name, id string) {
	t.Helper()
	if err := client.(*dynfake.FakeDynamicClient).Tracker().Add(sessionstest.Snapshot(name, id, "True")); err != nil {
		t.Fatal(err)
	}
}

func TestSleepSnapshotsThenSuspendsPinnedToThePool(t *testing.T) {
	ctx := t.Context()
	store, client, _ := sessionstest.NewWithSnapshots(t, sessions.SnapshotOptions{Timeout: 2 * time.Second})
	id := running(t, store, client)
	// What an earlier sleep left, and somebody else's.
	addSnapshot(t, client, "old", id)
	addSnapshot(t, client, "other", "s-aaaaaaaaaa")

	if err := store.Suspend(ctx, id, sessions.StoppedByIdle); err != nil {
		t.Fatal(err)
	}
	obj := sandbox(t, client, id)
	snap := "snap-" + id + "-1"
	if mode(obj) != "Suspended" || obj.GetAnnotations()[sessions.AnnStoppedBy] != sessions.StoppedByIdle {
		t.Errorf("mode %q, stopped-by %q", mode(obj), obj.GetAnnotations()[sessions.AnnStoppedBy])
	}
	if got := obj.GetAnnotations()[sessions.AnnSnapshot]; got != snap {
		t.Errorf("recorded snapshot = %q, want %q", got, snap)
	}
	if pin(obj) != sessionstest.Pool || obj.GetAnnotations()[sessions.AnnSnapshotPool] != sessionstest.Pool {
		t.Errorf("pin = %q, pool annotation = %q", pin(obj), obj.GetAnnotations()[sessions.AnnSnapshotPool])
	}
	// One snapshot a session; other sessions' are not touched.
	if got, want := sessionstest.Snapshots(t, client), []string{"other", snap}; !reflect.DeepEqual(got, want) {
		t.Errorf("snapshots = %v, want %v", got, want)
	}
	triggers, err := client.Resource(sessions.SnapshotTriggerGVR).Namespace(sessionstest.Namespace).List(ctx, metav1.ListOptions{})
	if err != nil || len(triggers.Items) != 0 {
		t.Errorf("triggers left behind: %v, %v", triggers.Items, err)
	}
}

func TestSleepWithoutASnapshotStillSleeps(t *testing.T) {
	for name, breakIt := range map[string]func(*testing.T, *sessionstest.GKE, dynamic.Interface){
		"snapshot never finishes": func(_ *testing.T, g *sessionstest.GKE, _ dynamic.Interface) { g.Hang = true },
		"checkpoint fails":        func(_ *testing.T, g *sessionstest.GKE, _ dynamic.Interface) { g.Fail = true },
		"snapshot never ready":    func(_ *testing.T, g *sessionstest.GKE, _ dynamic.Interface) { g.NotReady = true },
		// Without the pool there is nowhere to pin the restore to.
		"node names no pool": func(t *testing.T, _ *sessionstest.GKE, c dynamic.Interface) {
			node := &unstructured.Unstructured{Object: map[string]any{
				"apiVersion": "v1", "kind": "Node", "metadata": map[string]any{"name": sessionstest.Node},
			}}
			if _, err := c.Resource(nodes).Update(t.Context(), node, metav1.UpdateOptions{}); err != nil {
				t.Fatal(err)
			}
		},
	} {
		t.Run(name, func(t *testing.T) {
			ctx := t.Context()
			store, client, gke := sessionstest.NewWithSnapshots(t, sessions.SnapshotOptions{Timeout: 50 * time.Millisecond})
			breakIt(t, gke, client)
			id := running(t, store, client)
			addSnapshot(t, client, "old", id) // of an earlier sleep: now stale

			start := time.Now()
			if err := store.Sleep(ctx, id, sessions.StoppedByIdle, nil); err != nil {
				t.Fatal(err)
			}
			if took := time.Since(start); took > time.Second {
				t.Errorf("sleep took %s; the snapshot timeout is 50ms", took)
			}
			obj := sandbox(t, client, id)
			if mode(obj) != "Suspended" {
				t.Errorf("mode = %q", mode(obj))
			}
			if obj.GetAnnotations()[sessions.AnnSnapshot] != "" || pin(obj) != "" {
				t.Errorf("snapshot %q, pin %q: want neither", obj.GetAnnotations()[sessions.AnnSnapshot], pin(obj))
			}
			// Nothing to restore from: a stale or half-made snapshot would be.
			if got := sessionstest.Snapshots(t, client); len(got) != 0 {
				t.Errorf("snapshots left: %v", got)
			}
		})
	}
}

func TestSleepLeavesASessionUsedDuringTheSnapshot(t *testing.T) {
	store, client, _ := sessionstest.NewWithSnapshots(t, sessions.SnapshotOptions{Timeout: 2 * time.Second})
	id := running(t, store, client)

	err := store.Sleep(t.Context(), id, sessions.StoppedByIdle, func(sessions.Session) bool { return false })
	if !errors.Is(err, sessions.ErrStateChanged) {
		t.Fatalf("err = %v, want ErrStateChanged", err)
	}
	if obj := sandbox(t, client, id); mode(obj) != "Running" || pin(obj) != "" {
		t.Errorf("mode %q, pin %q", mode(obj), pin(obj))
	}
	if got := sessionstest.Snapshots(t, client); len(got) != 0 {
		t.Errorf("snapshots left: %v", got)
	}
}

func TestSleepDiscardsItsSnapshotIfTheUserStoppedFirst(t *testing.T) {
	store, client, _ := sessionstest.NewWithSnapshots(t, sessions.SnapshotOptions{Timeout: 2 * time.Second})
	id := running(t, store, client)

	checks := 0
	err := store.Sleep(t.Context(), id, sessions.StoppedByIdle, func(sessions.Session) bool {
		checks++
		if checks == 1 {
			return true
		}
		// While the snapshot was taken, the user stopped the session.
		if err := store.Suspend(t.Context(), id, sessions.StoppedByUser); err != nil {
			t.Error(err)
		}
		return true
	})
	if !errors.Is(err, sessions.ErrStateChanged) {
		t.Fatalf("err = %v, want ErrStateChanged", err)
	}
	obj := sandbox(t, client, id)
	if obj.GetAnnotations()[sessions.AnnStoppedBy] != sessions.StoppedByUser || pin(obj) != "" {
		t.Errorf("stopped-by %q, pin %q", obj.GetAnnotations()[sessions.AnnStoppedBy], pin(obj))
	}
	if got := sessionstest.Snapshots(t, client); len(got) != 0 {
		t.Errorf("snapshots left: %v", got)
	}
}

func asleep(t *testing.T, store *sessions.Store, client dynamic.Interface) string {
	t.Helper()
	id := running(t, store, client)
	if err := store.Sleep(t.Context(), id, sessions.StoppedByIdle, nil); err != nil {
		t.Fatal(err)
	}
	sessionstest.SetStatus(t, client, id, sessionstest.Suspended())
	return id
}

func TestWakeKeepsThePinWhileTheSnapshotIsGood(t *testing.T) {
	ctx := t.Context()
	store, client, _ := sessionstest.NewWithSnapshots(t, sessions.SnapshotOptions{Timeout: 2 * time.Second})
	id := asleep(t, store, client)

	if err := store.Wake(ctx, id); err != nil {
		t.Fatal(err)
	}
	obj := sandbox(t, client, id)
	if mode(obj) != "Running" || pin(obj) != sessionstest.Pool || obj.GetAnnotations()[sessions.AnnSnapshot] == "" {
		t.Errorf("mode %q, pin %q, snapshot %q", mode(obj), pin(obj), obj.GetAnnotations()[sessions.AnnSnapshot])
	}
}

func TestWakeColdWhenTheSnapshotIsGone(t *testing.T) {
	ctx := t.Context()
	store, client, _ := sessionstest.NewWithSnapshots(t, sessions.SnapshotOptions{Timeout: 2 * time.Second})
	id := asleep(t, store, client)
	// The blueprint's own node selector is not ours to remove.
	obj := sandbox(t, client, id)
	_ = unstructured.SetNestedField(obj.Object, "gvisor", "spec", "podTemplate", "spec", "nodeSelector", "sandbox.gke.io/runtime")
	if _, err := client.Resource(sessions.SandboxGVR).Namespace(sessionstest.Namespace).Update(ctx, obj, metav1.UpdateOptions{}); err != nil {
		t.Fatal(err)
	}
	name := obj.GetAnnotations()[sessions.AnnSnapshot]
	if err := client.Resource(sessions.PodSnapshotGVR).Namespace(sessionstest.Namespace).Delete(ctx, name, metav1.DeleteOptions{}); err != nil {
		t.Fatal(err)
	}

	if err := store.Wake(ctx, id); err != nil {
		t.Fatal(err)
	}
	obj = sandbox(t, client, id)
	sel, _, _ := unstructured.NestedStringMap(obj.Object, "spec", "podTemplate", "spec", "nodeSelector")
	if mode(obj) != "Running" || !reflect.DeepEqual(sel, map[string]string{"sandbox.gke.io/runtime": "gvisor"}) {
		t.Errorf("mode %q, nodeSelector %v", mode(obj), sel)
	}
	if ann := obj.GetAnnotations(); ann[sessions.AnnSnapshot] != "" || ann[sessions.AnnSnapshotPool] != "" {
		t.Errorf("annotations = %v", ann)
	}
}

// A user's stop takes no snapshot, so whatever snapshot there is predates
// what the session did since and must not come back.
func TestUserStopForgetsTheSnapshot(t *testing.T) {
	ctx := t.Context()
	store, client, _ := sessionstest.NewWithSnapshots(t, sessions.SnapshotOptions{Timeout: 2 * time.Second})
	id := asleep(t, store, client)
	if err := store.Wake(ctx, id); err != nil {
		t.Fatal(err)
	}

	if err := store.Suspend(ctx, id, sessions.StoppedByUser); err != nil {
		t.Fatal(err)
	}
	obj := sandbox(t, client, id)
	if mode(obj) != "Suspended" || pin(obj) != "" || obj.GetAnnotations()[sessions.AnnSnapshot] != "" {
		t.Errorf("mode %q, pin %q, snapshot %q", mode(obj), pin(obj), obj.GetAnnotations()[sessions.AnnSnapshot])
	}
	if got := sessionstest.Snapshots(t, client); len(got) != 0 {
		t.Errorf("snapshots left: %v", got)
	}
}

// Resuming a sleeping session from the UI is a wake: the snapshot is used.
func TestUserResumeOfASleepingSessionKeepsTheSnapshot(t *testing.T) {
	ctx := t.Context()
	store, client, _ := sessionstest.NewWithSnapshots(t, sessions.SnapshotOptions{Timeout: 2 * time.Second})
	id := asleep(t, store, client)

	if err := store.Resume(ctx, id); err != nil {
		t.Fatal(err)
	}
	if obj := sandbox(t, client, id); mode(obj) != "Running" || pin(obj) != sessionstest.Pool {
		t.Errorf("mode %q, pin %q", mode(obj), pin(obj))
	}
	if got := sessionstest.Snapshots(t, client); len(got) != 1 {
		t.Errorf("snapshots = %v", got)
	}
}

func TestDeleteRemovesTheSessionsSnapshots(t *testing.T) {
	ctx := t.Context()
	store, client, _ := sessionstest.NewWithSnapshots(t, sessions.SnapshotOptions{Timeout: 2 * time.Second})
	id := asleep(t, store, client)
	addSnapshot(t, client, "other", "s-aaaaaaaaaa")

	if err := store.Delete(ctx, id); err != nil {
		t.Fatal(err)
	}
	if got := sessionstest.Snapshots(t, client); !reflect.DeepEqual(got, []string{"other"}) {
		t.Errorf("snapshots = %v, want only the other session's", got)
	}
	if _, err := store.Get(ctx, id); !errors.Is(err, sessions.ErrNotFound) {
		t.Errorf("session still there: %v", err)
	}
}

func TestColdStartGivesUpTheSnapshotAndRestartsThePod(t *testing.T) {
	ctx := t.Context()
	store, client, _ := sessionstest.NewWithSnapshots(t, sessions.SnapshotOptions{Timeout: 2 * time.Second})
	id := asleep(t, store, client)
	if err := store.Wake(ctx, id); err != nil {
		t.Fatal(err)
	}
	// The restore is stuck: the pod is there and does not get ready. The
	// controller removes it once the session is suspended again.
	sessionstest.SetStatus(t, client, id, map[string]any{"nodeName": sessionstest.Node})
	controller := make(chan error, 1)
	go func() {
		for {
			obj, err := client.Resource(sessions.SandboxGVR).Namespace(sessionstest.Namespace).Get(ctx, id, metav1.GetOptions{})
			if err != nil {
				controller <- err
				return
			}
			if mode(obj) == "Suspended" {
				controller <- sessionstest.TrySetStatus(client, id, sessionstest.Suspended())
				return
			}
			time.Sleep(time.Millisecond)
		}
	}()

	did, err := store.ColdStart(ctx, id)
	if err != nil || !did {
		t.Fatalf("ColdStart = %v, %v", did, err)
	}
	if err := <-controller; err != nil {
		t.Fatal(err)
	}
	obj := sandbox(t, client, id)
	if mode(obj) != "Running" || pin(obj) != "" || obj.GetAnnotations()[sessions.AnnSnapshot] != "" {
		t.Errorf("mode %q, pin %q, snapshot %q", mode(obj), pin(obj), obj.GetAnnotations()[sessions.AnnSnapshot])
	}
	if got := sessionstest.Snapshots(t, client); len(got) != 0 {
		t.Errorf("snapshots left: %v", got)
	}

	// Nothing to give up a second time.
	if did, err := store.ColdStart(ctx, id); did || err != nil {
		t.Errorf("second ColdStart = %v, %v", did, err)
	}
}

// Without EnableSnapshots (a kind cluster) the store never asks for a
// snapshot resource, and a session's pod template is left as it was.
func TestSnapshotsAreOffByDefault(t *testing.T) {
	ctx := t.Context()
	store, client := sessionstest.New(t)
	id := running(t, store, client)
	before, _, _ := unstructured.NestedMap(sandbox(t, client, id).Object, "spec", "podTemplate")

	if err := store.Sleep(ctx, id, sessions.StoppedByIdle, func(sessions.Session) bool { return true }); err != nil {
		t.Fatal(err)
	}
	sessionstest.SetStatus(t, client, id, sessionstest.Suspended())
	if did, err := store.ColdStart(ctx, id); did || err != nil {
		t.Errorf("ColdStart = %v, %v", did, err)
	}
	if err := store.Wake(ctx, id); err != nil {
		t.Fatal(err)
	}
	after, _, _ := unstructured.NestedMap(sandbox(t, client, id).Object, "spec", "podTemplate")
	if !reflect.DeepEqual(before, after) {
		t.Errorf("pod template changed:\n%v\n%v", before, after)
	}
	if err := store.Delete(ctx, id); err != nil {
		t.Fatal(err)
	}
	for _, a := range client.(*dynfake.FakeDynamicClient).Actions() {
		if r := a.GetResource().Resource; r != sessions.SandboxGVR.Resource {
			t.Errorf("%s %s: only Sandboxes may be asked for", a.GetVerb(), r)
		}
	}
}

// A sleep its user asked for is an idle sleep in all but name: snapshotted,
// asleep rather than stopped, and woken by the next request (Wake).
func TestUserSleepSnapshotsAndWakesOnUse(t *testing.T) {
	ctx := t.Context()
	store, client, _ := sessionstest.NewWithSnapshots(t, sessions.SnapshotOptions{Timeout: 2 * time.Second})
	id := running(t, store, client)

	if err := store.Sleep(ctx, id, sessions.StoppedBySleep, nil); err != nil {
		t.Fatal(err)
	}
	obj := sandbox(t, client, id)
	snap := obj.GetAnnotations()[sessions.AnnSnapshot]
	if mode(obj) != "Suspended" || obj.GetAnnotations()[sessions.AnnStoppedBy] != sessions.StoppedBySleep || snap == "" || pin(obj) != sessionstest.Pool {
		t.Fatalf("mode %q, pin %q, annotations %v", mode(obj), pin(obj), obj.GetAnnotations())
	}
	if s, _ := store.Get(ctx, id); s.State != sessions.Stopping || !s.GoingToSleep() || !s.StateSaved {
		t.Errorf("while its pod goes: %+v", s)
	}
	sessionstest.SetStatus(t, client, id, sessionstest.Suspended())
	if s, _ := store.Get(ctx, id); s.State != sessions.Asleep || !s.StateSaved || s.StoppedBy != sessions.StoppedBySleep {
		t.Errorf("asleep: %+v", s)
	}
	// Asleep already: not taken over, by its user or for being idle.
	for _, by := range []string{sessions.StoppedBySleep, sessions.StoppedByIdle} {
		if err := store.Sleep(ctx, id, by, nil); !errors.Is(err, sessions.ErrStateChanged) {
			t.Errorf("sleep (%s) of a sleeping session: %v", by, err)
		}
	}

	if err := store.Wake(ctx, id); err != nil {
		t.Fatal(err)
	}
	obj = sandbox(t, client, id)
	if mode(obj) != "Running" || pin(obj) != sessionstest.Pool || obj.GetAnnotations()[sessions.AnnSnapshot] != snap {
		t.Errorf("mode %q, pin %q, snapshot %q", mode(obj), pin(obj), obj.GetAnnotations()[sessions.AnnSnapshot])
	}
	if s, _ := store.Get(ctx, id); s.StateSaved || s.StoppedBy != "" {
		t.Errorf("awake: %+v", s)
	}
}

// A stopped session says so: no state is saved, and it does not wake on use.
func TestUserStopSavesNoState(t *testing.T) {
	ctx := t.Context()
	store, client, _ := sessionstest.NewWithSnapshots(t, sessions.SnapshotOptions{Timeout: 2 * time.Second})
	id := asleep(t, store, client)
	if err := store.Suspend(ctx, id, sessions.StoppedByUser); err != nil {
		t.Fatal(err)
	}
	if s, _ := store.Get(ctx, id); s.State != sessions.Stopped || s.StateSaved || s.GoingToSleep() {
		t.Errorf("stopped: %+v", s)
	}
	if err := store.Wake(ctx, id); !errors.Is(err, sessions.ErrStateChanged) {
		t.Errorf("wake of a stopped session: %v", err)
	}
}

// Stop-policy checkpoints complete the old pod. Activity while uploading must
// recreate it, not leave that completed pod nominally running.
func TestActivityDuringCheckpointRestoresCompletedPod(t *testing.T) {
	store, client, _ := sessionstest.NewWithSnapshots(t, sessions.SnapshotOptions{Timeout: time.Second, Poll: time.Millisecond})
	id := running(t, store, client)
	controller := observeRecoverySuspend(t, client, id)
	checks := 0
	err := store.Sleep(t.Context(), id, sessions.StoppedByIdle, func(sessions.Session) bool { checks++; return checks == 1 })
	if !errors.Is(err, sessions.ErrStateChanged) {
		t.Fatalf("Sleep = %v", err)
	}
	if err := <-controller; err != nil {
		t.Fatal(err)
	}
	obj := sandbox(t, client, id)
	if mode(obj) != "Running" || obj.GetAnnotations()[sessions.AnnSnapshot] == "" {
		t.Fatalf("not restored: %v", obj.Object)
	}
}

func observeRecoverySuspend(t *testing.T, client dynamic.Interface, id string) <-chan error {
	t.Helper()
	done := make(chan error, 1)
	go func() {
		for {
			obj, err := client.Resource(sessions.SandboxGVR).Namespace(sessionstest.Namespace).Get(t.Context(), id, metav1.GetOptions{})
			if err != nil {
				done <- err
				return
			}
			if mode(obj) == "Suspended" {
				done <- sessionstest.TrySetStatus(client, id, sessionstest.Suspended())
				return
			}
			select {
			case <-t.Context().Done():
				done <- t.Context().Err()
				return
			case <-time.After(time.Millisecond):
			}
		}
	}()
	return done
}

func TestCancelledCheckpointFinishesSuspendAndRestores(t *testing.T) {
	store, client, gke := sessionstest.NewWithSnapshots(t, sessions.SnapshotOptions{Timeout: time.Second, Poll: time.Millisecond})
	gke.NotReady = true
	id := running(t, store, client)
	ctx, cancel := context.WithCancel(t.Context())
	defer cancel()
	controller := observeRecoverySuspend(t, client, id)
	go func() {
		for {
			list, err := client.Resource(sessions.PodSnapshotGVR).Namespace(sessionstest.Namespace).List(t.Context(), metav1.ListOptions{})
			if err != nil {
				return
			}
			if len(list.Items) > 0 {
				cancel()
				return
			}
			select {
			case <-t.Context().Done():
				return
			case <-time.After(time.Millisecond):
			}
		}
	}()
	err := store.Sleep(ctx, id, sessions.StoppedBySleep, nil)
	if !errors.Is(err, sessions.ErrStateChanged) {
		t.Fatalf("Sleep = %v", err)
	}
	if err := <-controller; err != nil {
		t.Fatal(err)
	}
	obj := sandbox(t, client, id)
	if mode(obj) != "Running" || obj.GetAnnotations()[sessions.AnnSnapshot] != "" {
		t.Fatalf("not restarted cold: %v", obj.Object)
	}
}

func setRestartPolicy(t *testing.T, client dynamic.Interface, id, policy string) {
	t.Helper()
	obj := sandbox(t, client, id)
	if policy == "" {
		unstructured.RemoveNestedField(obj.Object, "spec", "podTemplate", "spec", "restartPolicy")
	} else {
		_ = unstructured.SetNestedField(obj.Object, policy, "spec", "podTemplate", "spec", "restartPolicy")
	}
	if _, err := client.Resource(sessions.SandboxGVR).Namespace(sessionstest.Namespace).Update(t.Context(), obj, metav1.UpdateOptions{}); err != nil {
		t.Fatal(err)
	}
}

func TestSleepRefusesRestartablePodWithoutLosingMemory(t *testing.T) {
	for _, policy := range []string{"", "Always", "OnFailure"} {
		t.Run(policy, func(t *testing.T) {
			store, client, _ := sessionstest.NewWithSnapshots(t, sessions.SnapshotOptions{})
			id := running(t, store, client)
			setRestartPolicy(t, client, id, policy)
			if err := store.Sleep(t.Context(), id, sessions.StoppedBySleep, nil); !errors.Is(err, sessions.ErrSnapshotRestartPolicy) {
				t.Fatalf("Sleep = %v", err)
			}
			if obj := sandbox(t, client, id); mode(obj) != "Running" {
				t.Fatalf("live memory interrupted: %v", obj.Object)
			}
			for _, action := range client.(*dynfake.FakeDynamicClient).Actions() {
				if action.GetVerb() == "create" && action.GetResource() == sessions.SnapshotTriggerGVR {
					t.Fatal("unsafe pod checkpointed")
				}
			}
			if err := store.Suspend(t.Context(), id, sessions.StoppedByUser); err != nil {
				t.Fatal(err)
			}
			sessionstest.SetStatus(t, client, id, sessionstest.Suspended())
			if err := store.Resume(t.Context(), id); err != nil {
				t.Fatal(err)
			}
			obj := sandbox(t, client, id)
			got, _, _ := unstructured.NestedString(obj.Object, "spec", "podTemplate", "spec", "restartPolicy")
			if got != "Never" || mode(obj) != "Running" {
				t.Fatalf("stop/start did not migrate: %v", obj.Object)
			}
		})
	}
}

func TestWakeDoesNotSilentlyDropLegacyMemory(t *testing.T) {
	for _, explicit := range []bool{false, true} {
		store, client, _ := sessionstest.NewWithSnapshots(t, sessions.SnapshotOptions{})
		id := asleep(t, store, client)
		setRestartPolicy(t, client, id, "Always")
		var err error
		if explicit {
			err = store.Resume(t.Context(), id)
		} else {
			err = store.Wake(t.Context(), id)
		}
		if !errors.Is(err, sessions.ErrSnapshotRestartPolicy) {
			t.Fatalf("wake explicit=%v: %v", explicit, err)
		}
		if obj := sandbox(t, client, id); mode(obj) != "Suspended" || obj.GetAnnotations()[sessions.AnnSnapshot] == "" {
			t.Fatal("legacy memory lost")
		}
	}
}

func TestColdStartRecoversFailedNeverPodWithoutSnapshot(t *testing.T) {
	store, client, _ := sessionstest.NewWithSnapshots(t, sessions.SnapshotOptions{Poll: time.Millisecond})
	id := running(t, store, client)
	sessionstest.SetStatus(t, client, id, map[string]any{"conditions": []any{map[string]any{"type": "Finished", "status": "True", "reason": "PodFailed"}}})
	controller := observeRecoverySuspend(t, client, id)
	did, err := store.ColdStart(t.Context(), id)
	if err != nil || !did {
		t.Fatalf("ColdStart = %v, %v", did, err)
	}
	if err := <-controller; err != nil {
		t.Fatal(err)
	}
	if obj := sandbox(t, client, id); mode(obj) != "Running" {
		t.Fatal("failed pod not replaced")
	}
}

func actualPod(t *testing.T, client dynamic.Interface, id, policy string, status map[string]any) {
	t.Helper()
	obj := sandbox(t, client, id)
	controller := true
	pod := &unstructured.Unstructured{Object: map[string]any{"apiVersion": "v1", "kind": "Pod", "metadata": map[string]any{"name": id, "namespace": sessionstest.Namespace}, "spec": map[string]any{"restartPolicy": policy}, "status": status}}
	pod.SetOwnerReferences([]metav1.OwnerReference{{APIVersion: obj.GetAPIVersion(), Kind: "Sandbox", Name: id, UID: obj.GetUID(), Controller: &controller}})
	if err := client.(*dynfake.FakeDynamicClient).Tracker().Add(pod); err != nil {
		t.Fatal(err)
	}
}

func TestRapidStopResumeCannotCheckpointOldAlwaysPod(t *testing.T) {
	store, client, _ := sessionstest.NewWithSnapshots(t, sessions.SnapshotOptions{})
	id := running(t, store, client)
	setRestartPolicy(t, client, id, "Always")
	actualPod(t, client, id, "Always", map[string]any{"phase": "Running"})
	if err := store.Suspend(t.Context(), id, sessions.StoppedByUser); err != nil {
		t.Fatal(err)
	}
	// No controller suspension: the original pod still exists.
	if err := store.Resume(t.Context(), id); err != nil {
		t.Fatal(err)
	}
	sessionstest.SetStatus(t, client, id, sessionstest.Ready("10.0.0.7"))
	if err := store.Sleep(t.Context(), id, sessions.StoppedBySleep, nil); !errors.Is(err, sessions.ErrSnapshotRestartPolicy) {
		t.Fatalf("unsafe old pod Sleep = %v", err)
	}
	if mode(sandbox(t, client, id)) != "Running" {
		t.Fatal("live pod interrupted")
	}
	for _, action := range client.(*dynfake.FakeDynamicClient).Actions() {
		if action.GetVerb() == "create" && action.GetResource() == sessions.SnapshotTriggerGVR {
			t.Fatal("old immutable pod checkpointed")
		}
	}
}

func TestColdStartRecognizesPartialCrashButNotCompletedCheckpoint(t *testing.T) {
	for _, tc := range []struct {
		name, phase           string
		exit                  int64
		otherRunning, recover bool
	}{
		{"partial failure", "Running", 137, true, true},
		{"completed checkpoint", "Succeeded", 0, false, false},
		{"checkpoint finishing", "Running", 0, true, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			store, client, _ := sessionstest.NewWithSnapshots(t, sessions.SnapshotOptions{Poll: time.Millisecond})
			id := running(t, store, client)
			sessionstest.SetStatus(t, client, id, map[string]any{"conditions": []any{map[string]any{"type": "Ready", "status": "False", "reason": "PodNotReady"}}})
			other := map[string]any{"terminated": map[string]any{"exitCode": int64(0)}}
			if tc.otherRunning {
				other = map[string]any{"running": map[string]any{}}
			}
			actualPod(t, client, id, "Never", map[string]any{"phase": tc.phase, "containerStatuses": []any{
				map[string]any{"name": "browser", "state": map[string]any{"terminated": map[string]any{"exitCode": tc.exit}}},
				map[string]any{"name": "mcp-js", "state": other},
			}})
			var done <-chan error
			if tc.recover {
				done = observeRecoverySuspend(t, client, id)
			}
			did, err := store.ColdStart(t.Context(), id)
			if err != nil || did != tc.recover {
				t.Fatalf("ColdStart = %v, %v; want %v", did, err, tc.recover)
			}
			if done != nil {
				if err := <-done; err != nil {
					t.Fatal(err)
				}
			}
		})
	}
}
