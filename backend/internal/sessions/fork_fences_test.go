package sessions_test

import (
	"encoding/json"
	"errors"
	"github.com/r33drichards/computer-use/backend/internal/diskfork"
	"github.com/r33drichards/computer-use/backend/internal/sessions"
	"github.com/r33drichards/computer-use/backend/internal/sessions/sessionstest"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"testing"
	"time"
)

func TestForkFenceLifecycleIntentAndNoPauseCapability(t *testing.T) {
	store, client := sessionstest.New(t)
	src, err := store.Create(t.Context(), "source", "owner")
	if err != nil {
		t.Fatal(err)
	}
	resource := client.Resource(sessions.SandboxGVR).Namespace(sessionstest.Namespace)
	obj, err := resource.Get(t.Context(), src.ID, metav1.GetOptions{})
	if err != nil {
		t.Fatal(err)
	}
	uid := obj.GetUID()
	if uid == "" {
		uid = types.UID("source-uid")
		obj.SetUID(uid)
	}
	state := diskfork.State{Version: 1, SourceUID: uid, Gate: "fork", Receipts: map[string]bool{}, Operations: map[string]diskfork.Operation{"fork": {ID: "fork", Phase: "draining", Deadline: time.Unix(100, 0)}}}
	raw, _ := json.Marshal(state)
	ann := obj.GetAnnotations()
	ann[diskfork.Annotation] = string(raw)
	obj.SetAnnotations(ann)
	if _, err = resource.Update(t.Context(), obj, metav1.UpdateOptions{}); err != nil {
		t.Fatal(err)
	}
	for _, call := range []func() error{
		func() error { return store.Update(t.Context(), src.ID, nil, sessions.ActionStop) },
		func() error { return store.SetDraining(t.Context(), src.ID, sessions.StoppedByCredit) },
		func() error { return store.Wake(t.Context(), src.ID) },
		func() error { return store.Sleep(t.Context(), src.ID, sessions.StoppedBySleep, nil) },
		func() error { return store.Delete(t.Context(), src.ID) },
		func() error { return store.Resume(t.Context(), src.ID) },
		func() error { return store.AdmitForward(t.Context(), src.ID) },
		func() error { return store.GrowDisk(t.Context(), src.ID, 8) },
	} {
		if err := call(); !errors.Is(err, diskfork.ErrGated) {
			t.Fatal(err)
		}
	}
	after, err := resource.Get(t.Context(), src.ID, metav1.GetOptions{})
	if err != nil {
		t.Fatal(err)
	}
	var got diskfork.State
	if err = json.Unmarshal([]byte(after.GetAnnotations()[diskfork.Annotation]), &got); err != nil {
		t.Fatal(err)
	}
	if got.Intent != "delete" || got.IntentEpoch < 3 {
		t.Fatalf("intent lost: %+v", got)
	}
	if after.GetUID() != uid || after.Object["spec"].(map[string]any)["operatingMode"] != obj.Object["spec"].(map[string]any)["operatingMode"] {
		t.Fatal("physical source mutated")
	}
	if err = store.BeginDiskFork(t.Context(), src.ID); !errors.Is(err, diskfork.ErrQuiescenceUnsupported) {
		t.Fatal(err)
	}
	legacy, err := store.Create(t.Context(), "legacy", "owner")
	if err != nil {
		t.Fatal(err)
	}
	if err = store.BeginDiskFork(t.Context(), legacy.ID); !errors.Is(err, diskfork.ErrQuiescenceUnsupported) {
		t.Fatal(err)
	}
	if err = store.AdmitForward(t.Context(), legacy.ID); err != nil {
		t.Fatal(err)
	}
	legacyObj, err := resource.Get(t.Context(), legacy.ID, metav1.GetOptions{})
	if err != nil {
		t.Fatal(err)
	}
	if legacyObj.GetAnnotations()[diskfork.Annotation] != "" {
		t.Fatal("untracked session initialized")
	}
}
