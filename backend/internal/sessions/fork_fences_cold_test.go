package sessions_test

import (
	"encoding/json"
	"errors"
	"github.com/r33drichards/computer-use/backend/internal/diskfork"
	"github.com/r33drichards/computer-use/backend/internal/sessions"
	"github.com/r33drichards/computer-use/backend/internal/sessions/sessionstest"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	dynfake "k8s.io/client-go/dynamic/fake"
	k8stesting "k8s.io/client-go/testing"
	"reflect"
	"testing"
	"time"
)

func TestForkFenceColdStartBeforeAnyCleanup(t *testing.T) {
	for _, kind := range []string{"gate", "malformed", "copied"} {
		t.Run(kind, func(t *testing.T) {
			store, c, _ := sessionstest.NewWithSnapshots(t, sessions.SnapshotOptions{Timeout: time.Second})
			id := running(t, store, c)
			addSnapshot(t, c, "snapshot", id)
			res := c.Resource(sessions.SandboxGVR).Namespace(sessionstest.Namespace)
			o := sandbox(t, c, id)
			o.SetUID(types.UID("source"))
			state := diskfork.State{Version: 1, SourceUID: o.GetUID(), Gate: "fork", Receipts: map[string]bool{"uncertain": false}, Operations: map[string]diskfork.Operation{"fork": {ID: "fork", Phase: "draining", Deadline: time.Unix(1, 0)}}}
			if kind == "copied" {
				state.SourceUID = "different"
			}
			raw, _ := json.Marshal(state)
			if kind == "malformed" {
				raw = []byte("{")
			}
			ann := o.GetAnnotations()
			ann[diskfork.Annotation] = string(raw)
			o.SetAnnotations(ann)
			if _, err := res.Update(t.Context(), o, metav1.UpdateOptions{}); err != nil {
				t.Fatal(err)
			}
			before := sandbox(t, c, id)
			fake := c.(*dynfake.FakeDynamicClient)
			start := len(fake.Actions())
			if did, err := store.ColdStart(t.Context(), id); did || err == nil {
				t.Fatalf("did=%v err=%v", did, err)
			}
			for _, a := range fake.Actions()[start:] {
				if a.GetVerb() == "delete" || a.GetVerb() == "update" || a.GetVerb() == "patch" {
					t.Fatalf("effect before refusal: %v", a)
				}
			}
			if !reflect.DeepEqual(before.Object, sandbox(t, c, id).Object) || len(sessionstest.Snapshots(t, c)) != 1 {
				t.Fatal("source/snapshot changed")
			}
		})
	}
}
func TestForkFenceColdStartReplacementGuards(t *testing.T) {
	for _, kind := range []string{"source-before-delete", "source-after-delete", "source-cas", "snapshot"} {
		t.Run(kind, func(t *testing.T) {
			store, c, _ := sessionstest.NewWithSnapshots(t, sessions.SnapshotOptions{Timeout: 10 * time.Millisecond})
			id := running(t, store, c)
			res := c.Resource(sessions.SandboxGVR).Namespace(sessionstest.Namespace)
			o := sandbox(t, c, id)
			o.SetUID("source")
			if _, err := res.Update(t.Context(), o, metav1.UpdateOptions{}); err != nil {
				t.Fatal(err)
			}
			fake := c.(*dynfake.FakeDynamicClient)
			snap := sessionstest.Snapshot("snapshot", id, "True")
			snap.SetUID("listed")
			snap.SetResourceVersion("7")
			if err := fake.Tracker().Add(snap); err != nil {
				t.Fatal(err)
			}
			replaceSource := func() {
				obj, err := fake.Tracker().Get(sessions.SandboxGVR, sessionstest.Namespace, id)
				if err != nil {
					t.Fatal(err)
				}
				cur := obj.(*unstructured.Unstructured).DeepCopy()
				cur.SetUID("replacement")
				if err := fake.Tracker().Update(sessions.SandboxGVR, cur, sessionstest.Namespace); err != nil {
					t.Fatal(err)
				}
			}
			if kind == "source-before-delete" {
				once := false
				fake.PrependReactor("list", sessions.PodSnapshotGVR.Resource, func(a k8stesting.Action) (bool, runtime.Object, error) {
					if !once {
						once = true
						replaceSource()
					}
					return false, nil, nil
				})
			}
			removed := false
			readsAfterDelete := 0
			fake.PrependReactor("get", sessions.SandboxGVR.Resource, func(a k8stesting.Action) (bool, runtime.Object, error) {
				if kind == "source-cas" && removed {
					readsAfterDelete++
					if readsAfterDelete == 2 {
						replaceSource()
					}
				}
				return false, nil, nil
			})
			deletes := 0
			fake.PrependReactor("delete", sessions.PodSnapshotGVR.Resource, func(a k8stesting.Action) (bool, runtime.Object, error) {
				deletes++
				removed = true
				d := a.(k8stesting.DeleteAction)
				p := d.GetDeleteOptions().Preconditions
				if p == nil || p.UID == nil || *p.UID != "listed" || p.ResourceVersion == nil || *p.ResourceVersion != "7" {
					t.Fatal("no listed UID/RV preconditions")
				}
				if kind == "snapshot" {
					replacement := snap.DeepCopy()
					replacement.SetUID("new-snapshot")
					if err := fake.Tracker().Update(sessions.PodSnapshotGVR, replacement, sessionstest.Namespace); err != nil {
						t.Fatal(err)
					}
					return true, nil, apierrors.NewConflict(sessions.PodSnapshotGVR.GroupResource(), d.GetName(), errors.New("UID changed"))
				}
				if kind == "source-after-delete" {
					replaceSource()
				}
				return false, nil, nil
			})
			_, err := store.ColdStart(t.Context(), id)
			if err == nil {
				t.Fatal("replacement accepted")
			}
			if kind != "snapshot" && !errors.Is(err, diskfork.ErrIdentity) {
				t.Fatal(err)
			}
			if kind == "source-before-delete" && deletes != 0 {
				t.Fatal("replacement source snapshot deleted")
			}
			if kind == "snapshot" {
				got, e := c.Resource(sessions.PodSnapshotGVR).Namespace(sessionstest.Namespace).Get(t.Context(), "snapshot", metav1.GetOptions{})
				if e != nil || got.GetUID() != "new-snapshot" {
					t.Fatal("replacement snapshot lost")
				}
			}
			if kind != "snapshot" {
				obj, err := fake.Tracker().Get(sessions.SandboxGVR, sessionstest.Namespace, id)
				if err != nil {
					t.Fatal(err)
				}
				cur := obj.(*unstructured.Unstructured).DeepCopy()
				if cur.GetUID() != "replacement" {
					t.Fatal("wrong source")
				}
				if !reflect.DeepEqual(cur.Object["spec"], o.Object["spec"]) {
					t.Fatal("replacement source mutated")
				}
			}
		})
	}
}

var _ = unstructured.Unstructured{}
