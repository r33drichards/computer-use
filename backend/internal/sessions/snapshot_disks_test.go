package sessions_test

import (
	"github.com/r33drichards/computer-use/backend/internal/sessions"
	"github.com/r33drichards/computer-use/backend/internal/sessions/sessionstest"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
	dynfake "k8s.io/client-go/dynamic/fake"
	ktesting "k8s.io/client-go/testing"
	"strings"
	"testing"
	"time"
)

var diskSnapshots = schema.GroupVersionResource{Group: "snapshot.storage.k8s.io", Version: "v1", Resource: "volumesnapshots"}
var pairPods = schema.GroupVersionResource{Version: "v1", Resource: "pods"}
var pairPolicies = schema.GroupVersionResource{Group: "podsnapshot.gke.io", Version: "v1", Resource: "podsnapshotpolicies"}
var pairPVCs = schema.GroupVersionResource{Version: "v1", Resource: "persistentvolumeclaims"}

func pairedFixture(t *testing.T) (*sessions.Store, *dynfake.FakeDynamicClient, *sessionstest.GKE, string) {
	t.Helper()
	store, c, gke := sessionstest.NewWithSnapshots(t, sessions.SnapshotOptions{Timeout: 80 * time.Millisecond, DiskClass: "test-class"})
	client := c.(*dynfake.FakeDynamicClient)
	id := running(t, store, c)
	add := func(obj *unstructured.Unstructured) {
		obj.SetNamespace(sessionstest.Namespace)
		if err := client.Tracker().Add(obj); err != nil {
			t.Fatal(err)
		}
	}
	add(&unstructured.Unstructured{Object: map[string]any{"apiVersion": "podsnapshot.gke.io/v1", "kind": "PodSnapshotPolicy", "metadata": map[string]any{"name": "session-paired-sleep"}, "spec": map[string]any{"triggerConfig": map[string]any{"postCheckpoint": "stop"}}}})
	add(&unstructured.Unstructured{Object: map[string]any{"apiVersion": "podsnapshot.gke.io/v1", "kind": "PodSnapshotPolicy", "metadata": map[string]any{"name": "session-sleep"}, "spec": map[string]any{"selector": map[string]any{"matchExpressions": []any{map[string]any{"key": "browserjs.dev/paired-snapshots", "operator": "NotIn", "values": []any{"true"}}}}}}})
	add(&unstructured.Unstructured{Object: map[string]any{"apiVersion": "v1", "kind": "Pod", "metadata": map[string]any{"name": id, "uid": "checkpoint-pod"}, "spec": map[string]any{"containers": []any{map[string]any{"name": "browser"}, map[string]any{"name": "mcp-js"}}}, "status": map[string]any{"containerStatuses": []any{map[string]any{"name": "browser", "ready": true, "state": map[string]any{"running": map[string]any{}}}, map[string]any{"name": "mcp-js", "ready": true, "state": map[string]any{"running": map[string]any{}}}}}}})
	add(&unstructured.Unstructured{Object: map[string]any{"apiVersion": "v1", "kind": "PersistentVolumeClaim", "metadata": map[string]any{"name": "data-" + id, "uid": "working-disk"}, "spec": map[string]any{"storageClassName": "session-disk", "volumeName": "original-pv", "accessModes": []any{"ReadWriteOnce"}, "resources": map[string]any{"requests": map[string]any{"storage": "32Gi"}}}}})
	if err := store.GrowDisk(t.Context(), id, 32); err != nil {
		t.Fatal(err)
	}
	gke.OnTrigger = func() {
		raw, _ := client.Tracker().Get(pairPods, sessionstest.Namespace, id)
		pod := raw.(*unstructured.Unstructured)
		_ = unstructured.SetNestedField(pod.Object, "Succeeded", "status", "phase")
		_ = unstructured.SetNestedSlice(pod.Object, []any{map[string]any{"name": "browser", "ready": false, "state": map[string]any{"terminated": map[string]any{"exitCode": int64(0)}}}, map[string]any{"name": "mcp-js", "ready": false, "state": map[string]any{"terminated": map[string]any{"exitCode": int64(0)}}}}, "status", "containerStatuses")
		if err := client.Tracker().Update(pairPods, pod, sessionstest.Namespace); err != nil {
			t.Fatal(err)
		}
	}
	client.PrependReactor("create", diskSnapshots.Resource, func(a ktesting.Action) (bool, runtime.Object, error) {
		obj := a.(ktesting.CreateAction).GetObject().(*unstructured.Unstructured)
		_ = unstructured.SetNestedField(obj.Object, true, "status", "readyToUse")
		return false, nil, nil
	})
	// Emulate pod deletion after suspension and creation on a paired wake.
	client.PrependReactor("update", sessions.SandboxGVR.Resource, func(a ktesting.Action) (bool, runtime.Object, error) {
		obj := a.(ktesting.UpdateAction).GetObject().(*unstructured.Unstructured)
		if mode(obj) == "Suspended" {
			_ = unstructured.SetNestedSlice(obj.Object, []any{map[string]any{"type": "Suspended", "status": "True", "observedGeneration": obj.GetGeneration()}}, "status", "conditions")
			_ = client.Tracker().Delete(pairPods, sessionstest.Namespace, id)
		}
		if mode(obj) == "Running" && strings.HasPrefix(obj.GetAnnotations()["browserjs.dev/data-claim"], "restore-") {
			if _, err := client.Tracker().Get(pairPods, sessionstest.Namespace, id); apierrors.IsNotFound(err) {
				_ = client.Tracker().Add(&unstructured.Unstructured{Object: map[string]any{"apiVersion": "v1", "kind": "Pod", "metadata": map[string]any{"name": id, "namespace": sessionstest.Namespace, "uid": "restored-pod"}, "spec": map[string]any{"volumes": []any{map[string]any{"name": "data", "persistentVolumeClaim": map[string]any{"claimName": obj.GetAnnotations()["browserjs.dev/data-claim"]}}}, "containers": []any{map[string]any{"name": "browser"}, map[string]any{"name": "mcp-js"}}}, "status": map[string]any{"podIP": "10.0.0.8", "containerStatuses": []any{map[string]any{"name": "browser", "ready": false}, map[string]any{"name": "mcp-js", "ready": false}}}}})
			}
		}
		return false, nil, nil
	})
	return store, client, gke, id
}

func TestPairedSleepAndWakePreserveSourceDisk(t *testing.T) {
	for _, explicit := range []bool{false, true} {
		t.Run(map[bool]string{false: "wake", true: "explicit resume"}[explicit], func(t *testing.T) {
			store, client, _, id := pairedFixture(t)
			if err := store.Sleep(t.Context(), id, sessions.StoppedBySleep, nil); err != nil {
				t.Fatal(err)
			}
			obj := sandbox(t, client, id)
			memory := obj.GetAnnotations()[sessions.AnnSnapshot]
			if memory == "" {
				t.Fatal("pair was not published")
			}
			if obj.GetAnnotations()["browserjs.dev/checkpoint-started"] != "" {
				t.Fatal("checkpoint fence leaked")
			}
			disk, err := client.Resource(diskSnapshots).Namespace(sessionstest.Namespace).Get(t.Context(), "disk-"+memory, metav1.GetOptions{})
			if err != nil {
				t.Fatal(err)
			}
			source, _, _ := unstructured.NestedString(disk.Object, "spec", "source", "persistentVolumeClaimName")
			if source != "data-"+id {
				t.Fatalf("source=%s", source)
			}
			if explicit {
				err = store.Resume(t.Context(), id)
			} else {
				err = store.Wake(t.Context(), id)
			}
			if err != nil {
				t.Fatal(err)
			}
			obj = sandbox(t, client, id)
			claim := obj.GetAnnotations()["browserjs.dev/data-claim"]
			if !strings.HasPrefix(claim, "restore-"+id+"-") {
				t.Fatalf("not restored to a fresh clone: %s", claim)
			}
			restored, err := client.Resource(pairPVCs).Namespace(sessionstest.Namespace).Get(t.Context(), claim, metav1.GetOptions{})
			if err != nil {
				t.Fatal(err)
			}
			paired, _, _ := unstructured.NestedString(restored.Object, "spec", "dataSource", "name")
			if paired != "disk-"+memory {
				t.Fatal("clone does not reference the paired snapshot")
			}
			if bound, _, _ := unstructured.NestedString(restored.Object, "spec", "volumeName"); bound != "" {
				t.Fatal("clone still binds original PV")
			}
			sourcePVC, err := client.Resource(pairPVCs).Namespace(sessionstest.Namespace).Get(t.Context(), source, metav1.GetOptions{})
			if err != nil || sourcePVC.GetUID() != "working-disk" {
				t.Fatal("source disk changed or was deleted")
			}
			if sessions.FromSandbox(obj).DiskGB != 32 {
				t.Fatal("disk capacity lost after replacing claim templates")
			}
		})
	}
}

func TestPairedCaptureRejectsResumedOrReplacedPod(t *testing.T) {
	for _, failure := range []string{"resume policy", "pod replaced", "disk snapshot failed"} {
		t.Run(failure, func(t *testing.T) {
			store, client, gke, id := pairedFixture(t)
			switch failure {
			case "resume policy":
				obj, _ := client.Resource(pairPolicies).Namespace(sessionstest.Namespace).Get(t.Context(), "session-paired-sleep", metav1.GetOptions{})
				_ = unstructured.SetNestedField(obj.Object, "resume", "spec", "triggerConfig", "postCheckpoint")
				_, _ = client.Resource(pairPolicies).Namespace(sessionstest.Namespace).Update(t.Context(), obj, metav1.UpdateOptions{})
			case "pod replaced":
				previous := gke.OnTrigger
				gke.OnTrigger = func() {
					previous()
					raw, _ := client.Tracker().Get(pairPods, sessionstest.Namespace, id)
					pod := raw.(*unstructured.Unstructured)
					pod.SetUID("replacement-pod")
					_ = client.Tracker().Update(pairPods, pod, sessionstest.Namespace)
				}
			case "disk snapshot failed":
				client.PrependReactor("create", diskSnapshots.Resource, func(a ktesting.Action) (bool, runtime.Object, error) {
					obj := a.(ktesting.CreateAction).GetObject().(*unstructured.Unstructured)
					_ = unstructured.SetNestedField(obj.Object, "CSI snapshot failed", "status", "error", "message")
					return false, nil, nil
				})
			}
			if err := store.Sleep(t.Context(), id, sessions.StoppedBySleep, nil); err != nil {
				t.Fatal(err)
			}
			if sandbox(t, client, id).GetAnnotations()[sessions.AnnSnapshot] != "" {
				t.Fatal("unsafe/incomplete checkpoint was published")
			}
			if got := sessionstest.Snapshots(t, client); len(got) != 0 {
				t.Fatalf("unsafe memory snapshot left for implicit restore: %v", got)
			}
			if _, err := client.Resource(pairPVCs).Namespace(sessionstest.Namespace).Get(t.Context(), "data-"+id, metav1.GetOptions{}); err != nil {
				t.Fatal("working disk lost")
			}
		})
	}
}

// Emulate the controller acknowledging suspension; recovery must not wake
// until the old checkpointed pod is gone (observed generation is checked).
func acknowledgePairSuspension(client *dynfake.FakeDynamicClient) {
	client.PrependReactor("update", sessions.SandboxGVR.Resource, func(a ktesting.Action) (bool, runtime.Object, error) {
		obj := a.(ktesting.UpdateAction).GetObject().(*unstructured.Unstructured)
		m, _, _ := unstructured.NestedString(obj.Object, "spec", "operatingMode")
		if m == "Suspended" {
			_ = unstructured.SetNestedSlice(obj.Object, []any{map[string]any{"type": "Suspended", "status": "True", "observedGeneration": obj.GetGeneration()}}, "status", "conditions")
		}
		return false, nil, nil
	})
}

func TestCancelledPairCaptureRestartsFromWorkingDisk(t *testing.T) {
	store, client, _, id := pairedFixture(t)
	acknowledgePairSuspension(client)
	calls := 0
	err := store.Sleep(t.Context(), id, sessions.StoppedByIdle, func(s sessions.Session) bool { calls++; return calls == 1 })
	if err == nil {
		t.Fatal("changed sleep condition was ignored")
	}
	obj := sandbox(t, client, id)
	if mode(obj) != "Running" || obj.GetAnnotations()["browserjs.dev/checkpoint-started"] != "" {
		t.Fatal("cancelled checkpoint left a stopped pod marked running")
	}
	if len(sessionstest.Snapshots(t, client)) != 0 {
		t.Fatal("cancelled checkpoint left an implicit restore artifact")
	}
	if _, err := client.Resource(pairPVCs).Namespace(sessionstest.Namespace).Get(t.Context(), "data-"+id, metav1.GetOptions{}); err != nil {
		t.Fatal(err)
	}
}

func TestFailedPairedRestoreUsesColdCloneAndRetainsFailedClone(t *testing.T) {
	store, client, _, id := pairedFixture(t)
	acknowledgePairSuspension(client)
	if err := store.Sleep(t.Context(), id, sessions.StoppedBySleep, nil); err != nil {
		t.Fatal(err)
	}
	if err := store.Wake(t.Context(), id); err != nil {
		t.Fatal(err)
	}
	failedClaim := sandbox(t, client, id).GetAnnotations()["browserjs.dev/data-claim"]
	if did, err := store.ColdStart(t.Context(), id); err != nil || !did {
		t.Fatalf("cold start: %v, %v", did, err)
	}
	obj := sandbox(t, client, id)
	if claim := obj.GetAnnotations()["browserjs.dev/data-claim"]; claim == "data-"+id || claim == failedClaim {
		t.Fatal("cold fallback must use a fresh saved-disk clone")
	}
	if _, err := client.Resource(pairPVCs).Namespace(sessionstest.Namespace).Get(t.Context(), failedClaim, metav1.GetOptions{}); err != nil {
		t.Fatal("failed restore branch was deleted")
	}
	if len(sessionstest.Snapshots(t, client)) != 0 {
		t.Fatal("bad checkpoint can still be restored")
	}
	cold := obj.GetAnnotations()["browserjs.dev/cold-disk-snapshot"]
	if _, err := client.Resource(diskSnapshots).Namespace(sessionstest.Namespace).Get(t.Context(), "disk-"+cold, metav1.GetOptions{}); err != nil {
		t.Fatal("cold clone backup consumed before readiness")
	}
	pod, err := client.Resource(pairPods).Namespace(sessionstest.Namespace).Get(t.Context(), id, metav1.GetOptions{})
	if err != nil {
		t.Fatal(err)
	}
	_ = unstructured.SetNestedSlice(pod.Object, []any{map[string]any{"name": "browser", "ready": true}, map[string]any{"name": "mcp-js", "ready": true}}, "status", "containerStatuses")
	if _, err := client.Resource(pairPods).Namespace(sessionstest.Namespace).Update(t.Context(), pod, metav1.UpdateOptions{}); err != nil {
		t.Fatal(err)
	}
	sessionstest.SetStatus(t, client, id, sessionstest.Ready("10.0.0.7"))
	if view, err := store.Get(t.Context(), id); err != nil || view.State != sessions.Running {
		t.Fatalf("cold clone did not serve: %v, %v", view.State, err)
	}
	if _, err := client.Resource(diskSnapshots).Namespace(sessionstest.Namespace).Get(t.Context(), "disk-"+cold, metav1.GetOptions{}); !apierrors.IsNotFound(err) {
		t.Fatal("served cold clone retained consumed disk checkpoint")
	}
}

func TestPairedCheckpointConsumedOnlyAfterPodReady(t *testing.T) {
	store, client, _, id := pairedFixture(t)
	if err := store.Sleep(t.Context(), id, sessions.StoppedBySleep, nil); err != nil {
		t.Fatal(err)
	}
	if err := store.Wake(t.Context(), id); err != nil {
		t.Fatal(err)
	}
	sessionstest.SetStatus(t, client, id, sessionstest.Ready("10.0.0.7"))
	// Sandbox readiness is stale; the actual checkpointed pod is stopped.
	view, err := store.Get(t.Context(), id)
	if err != nil {
		t.Fatal(err)
	}
	if view.State != sessions.Starting || view.PodIP != "" {
		t.Fatal("stale Sandbox readiness exposed a stopped pod")
	}
	if len(sessionstest.Snapshots(t, client)) != 1 {
		t.Fatal("checkpoint consumed before restore served")
	}
	pod, err := client.Resource(pairPods).Namespace(sessionstest.Namespace).Get(t.Context(), id, metav1.GetOptions{})
	if err != nil {
		t.Fatal(err)
	}
	_ = unstructured.SetNestedSlice(pod.Object, []any{map[string]any{"name": "browser", "ready": true}, map[string]any{"name": "mcp-js", "ready": true}}, "status", "containerStatuses")
	_, err = client.Resource(pairPods).Namespace(sessionstest.Namespace).Update(t.Context(), pod, metav1.UpdateOptions{})
	if err != nil {
		t.Fatal(err)
	}
	view, err = store.Get(t.Context(), id)
	if err != nil {
		t.Fatal(err)
	}
	if view.State != sessions.Running || len(sessionstest.Snapshots(t, client)) != 0 {
		t.Fatal("served checkpoint was not consumed")
	}
	if sandbox(t, client, id).GetAnnotations()[sessions.AnnSnapshot] != "" {
		t.Fatal("consumed checkpoint reference retained")
	}
}

func TestUserStopDuringRestoreKeepsUsableSourceClaim(t *testing.T) {
	store, client, _, id := pairedFixture(t)
	if err := store.Sleep(t.Context(), id, sessions.StoppedBySleep, nil); err != nil {
		t.Fatal(err)
	}
	if err := store.Wake(t.Context(), id); err != nil {
		t.Fatal(err)
	}
	clone := sandbox(t, client, id).GetAnnotations()["browserjs.dev/data-claim"]
	if err := store.Suspend(t.Context(), id, sessions.StoppedByUser); err != nil {
		t.Fatal(err)
	}
	obj := sandbox(t, client, id)
	if obj.GetAnnotations()["browserjs.dev/cold-disk-snapshot"] == "" || obj.GetAnnotations()[sessions.AnnStoppedBy] != sessions.StoppedByUser {
		t.Fatal("stop did not retain saved disk for a cold clone on resume")
	}
	if _, err := client.Resource(pairPVCs).Namespace(sessionstest.Namespace).Get(t.Context(), clone, metav1.GetOptions{}); err != nil {
		t.Fatal("failed branch was deleted")
	}
	if err := store.Resume(t.Context(), id); err != nil {
		t.Fatal(err)
	}
	obj = sandbox(t, client, id)
	if obj.GetAnnotations()["browserjs.dev/data-claim"] == clone {
		t.Fatal("resume reused the failed memory restore branch")
	}
	cold := obj.GetAnnotations()["browserjs.dev/cold-disk-snapshot"]
	if _, err := client.Resource(diskSnapshots).Namespace(sessionstest.Namespace).Get(t.Context(), "disk-"+cold, metav1.GetOptions{}); err != nil {
		t.Fatal("disk snapshot removed before cold clone served")
	}
}

func TestPairedClaimExpansionDoesNotModifyPreservedSource(t *testing.T) {
	store, client, _, id := pairedFixture(t)
	if err := store.Sleep(t.Context(), id, sessions.StoppedBySleep, nil); err != nil {
		t.Fatal(err)
	}
	if err := store.Wake(t.Context(), id); err != nil {
		t.Fatal(err)
	}
	if err := store.GrowDisk(t.Context(), id, 34); err != nil {
		t.Fatal(err)
	}
	obj := sandbox(t, client, id)
	if sessions.FromSandbox(obj).DiskGB != 34 {
		t.Fatal("expanded claim capacity was not recorded")
	}
	source, _ := client.Resource(pairPVCs).Namespace(sessionstest.Namespace).Get(t.Context(), "data-"+id, metav1.GetOptions{})
	size, _, _ := unstructured.NestedString(source.Object, "spec", "resources", "requests", "storage")
	if size != "32Gi" {
		t.Fatal("expansion mutated preserved source")
	}
}

func TestAbandonedCheckpointFenceRecoversOnAccess(t *testing.T) {
	store, client, _, id := pairedFixture(t)
	acknowledgePairSuspension(client)
	obj := sandbox(t, client, id)
	ann := obj.GetAnnotations()
	ann["browserjs.dev/checkpoint-started"] = time.Now().Add(-time.Hour).UTC().Format(time.RFC3339Nano)
	obj.SetAnnotations(ann)
	if _, err := client.Resource(sessions.SandboxGVR).Namespace(sessionstest.Namespace).Update(t.Context(), obj, metav1.UpdateOptions{}); err != nil {
		t.Fatal(err)
	}
	if _, err := store.Get(t.Context(), id); err != nil {
		t.Fatal(err)
	}
	obj = sandbox(t, client, id)
	if obj.GetAnnotations()["browserjs.dev/checkpoint-started"] != "" || mode(obj) != "Running" {
		t.Fatal("abandoned checkpoint was not recovered")
	}
}
