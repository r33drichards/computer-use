package sessions

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"k8s.io/apimachinery/pkg/types"
	"time"

	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime/schema"
)

var volumeSnapshotGVR = schema.GroupVersionResource{Group: "snapshot.storage.k8s.io", Version: "v1", Resource: "volumesnapshots"}
var podGVR = schema.GroupVersionResource{Version: "v1", Resource: "pods"}
var snapshotPolicyGVR = schema.GroupVersionResource{Group: "podsnapshot.gke.io", Version: "v1", Resource: "podsnapshotpolicies"}

const (
	annDiskSnapshot = "browserjs.dev/disk-snapshot"
	annSourceClaim  = "browserjs.dev/source-claim"
	annDataClaim    = "browserjs.dev/data-claim"
	annDiskGB       = "browserjs.dev/disk-gb"
	annCheckpoint   = "browserjs.dev/checkpoint-started"
	annColdDisk     = "browserjs.dev/cold-disk-snapshot"
	annColdSource   = "browserjs.dev/cold-source-claim"
)

func dataClaim(obj *unstructured.Unstructured) string {
	if claim := obj.GetAnnotations()[annDataClaim]; claim != "" {
		return claim
	}
	return "data-" + obj.GetName()
}

// All writers must have been stopped by GKE's checkpoint, not by graceful
// shutdown. Capture the disk only after observing the SAME pod terminated.
func (n *snapshotter) stoppedPod(ctx context.Context, id, uid string) error {
	return n.until(ctx, func() (bool, error) {
		pod, err := n.pods.Get(ctx, id, metav1.GetOptions{})
		if err != nil {
			return false, err
		}
		if string(pod.GetUID()) != uid {
			return false, fmt.Errorf("checkpoint pod was replaced")
		}
		phase, _, _ := unstructured.NestedString(pod.Object, "status", "phase")
		if phase != "Succeeded" {
			return false, nil
		}
		containers, _, _ := unstructured.NestedSlice(pod.Object, "spec", "containers")
		statuses, _, _ := unstructured.NestedSlice(pod.Object, "status", "containerStatuses")
		if len(containers) == 0 || len(statuses) != len(containers) {
			return false, nil
		}
		for _, raw := range statuses {
			s, ok := raw.(map[string]any)
			if !ok {
				return false, nil
			}
			if _, ok, _ := unstructured.NestedMap(s, "state", "terminated"); !ok {
				return false, nil
			}
		}
		return true, nil
	})
}

func (n *snapshotter) captureDisk(ctx context.Context, sandbox *unstructured.Unstructured, memory, uid string) error {
	if err := n.stoppedPod(ctx, sandbox.GetName(), uid); err != nil {
		return err
	}
	diskName := "disk-" + memory
	obj := &unstructured.Unstructured{Object: map[string]any{
		"apiVersion": volumeSnapshotGVR.GroupVersion().String(), "kind": "VolumeSnapshot",
		"metadata": map[string]any{"name": diskName, "labels": map[string]any{LabelSession: sandbox.GetName()}, "ownerReferences": []any{map[string]any{"apiVersion": sandbox.GetAPIVersion(), "kind": sandbox.GetKind(), "name": sandbox.GetName(), "uid": string(sandbox.GetUID())}}},
		"spec":     map[string]any{"volumeSnapshotClassName": n.diskClass, "source": map[string]any{"persistentVolumeClaimName": dataClaim(sandbox)}},
	}}
	if _, err := n.disks.Create(ctx, obj, metav1.CreateOptions{}); err != nil {
		return fmt.Errorf("disk snapshot: %w", err)
	}
	if err := n.until(ctx, func() (bool, error) {
		if err := n.stoppedPod(ctx, sandbox.GetName(), uid); err != nil {
			return false, err
		}
		disk, err := n.disks.Get(ctx, diskName, metav1.GetOptions{})
		if err != nil {
			return false, err
		}
		if message, _, _ := unstructured.NestedString(disk.Object, "status", "error", "message"); message != "" {
			return false, fmt.Errorf("disk snapshot: %s", message)
		}
		ready, _, _ := unstructured.NestedBool(disk.Object, "status", "readyToUse")
		return ready, nil
	}); err != nil {
		return err
	}
	// Publish only after BOTH artifacts are ready. An unpaired memory checkpoint
	// must never be restored by the backend or left for GKE's implicit selection.
	return n.until(ctx, func() (bool, error) {
		mem, err := n.snapshots.Get(ctx, memory, metav1.GetOptions{})
		if err != nil {
			return false, err
		}
		setAnnotation(mem, annDiskSnapshot, diskName)
		setAnnotation(mem, annSourceClaim, dataClaim(sandbox))
		_, err = n.snapshots.Update(ctx, mem, metav1.UpdateOptions{})
		if apierrors.IsConflict(err) {
			return false, nil
		}
		return err == nil, err
	})
}

// Restore into a new PVC. Never overwrite or delete the original working
// claim: both it and failed restore branches remain owned by the Sandbox.
func (s *Store) prepareSnapshotDisk(ctx context.Context, obj *unstructured.Unstructured, memory string) error {
	ctx, cancel := context.WithTimeout(ctx, s.snap.timeout)
	defer cancel()
	// A rapid explicit Resume must not race the controller deleting the old pod.
	if err := s.snap.until(ctx, func() (bool, error) {
		_, err := s.snap.pods.Get(ctx, obj.GetName(), metav1.GetOptions{})
		if apierrors.IsNotFound(err) {
			return true, nil
		}
		return false, err
	}); err != nil {
		return err
	}

	mem, err := s.snap.snapshots.Get(ctx, memory, metav1.GetOptions{})
	if err != nil {
		return err
	}
	disk := mem.GetAnnotations()[annDiskSnapshot]
	source := mem.GetAnnotations()[annSourceClaim]
	if disk == "" || source == "" {
		return fmt.Errorf("memory snapshot has no disk pair")
	}
	return s.prepareDiskClone(ctx, obj, memory, disk, source)
}

func (s *Store) prepareDiskClone(ctx context.Context, obj *unstructured.Unstructured, memory, disk, source string) error {
	ctx, cancel := context.WithTimeout(ctx, s.snap.timeout)
	defer cancel()
	if err := s.snap.until(ctx, func() (bool, error) {
		_, err := s.snap.pods.Get(ctx, obj.GetName(), metav1.GetOptions{})
		if apierrors.IsNotFound(err) {
			return true, nil
		}
		return false, err
	}); err != nil {
		return err
	}
	saved, err := s.snap.disks.Get(ctx, disk, metav1.GetOptions{})
	if err != nil {
		return err
	}
	ready, _, _ := unstructured.NestedBool(saved.Object, "status", "readyToUse")
	savedSource, _, _ := unstructured.NestedString(saved.Object, "spec", "source", "persistentVolumeClaimName")
	if !ready || saved.GetDeletionTimestamp() != nil || savedSource != source {
		return fmt.Errorf("disk snapshot is not the ready source pair")
	}
	sourcePVC, err := s.pvcs.Get(ctx, source, metav1.GetOptions{})
	if err != nil {
		return err
	}
	attempt := "memory"
	if obj.GetAnnotations()[annColdDisk] != "" {
		attempt = "cold"
	}
	sum := sha256.Sum256([]byte(fmt.Sprintf("%s/%s/%d", memory, attempt, obj.GetGeneration())))
	claimName := "restore-" + obj.GetName() + "-" + hex.EncodeToString(sum[:6])
	spec, _, _ := unstructured.NestedMap(sourcePVC.Object, "spec")
	delete(spec, "volumeName")
	delete(spec, "selector")
	delete(spec, "dataSourceRef")
	if gb := FromSandbox(obj).DiskGB; gb > 0 {
		if err := unstructured.SetNestedField(spec, fmt.Sprintf("%dGi", gb), "resources", "requests", "storage"); err != nil {
			return err
		}
	}
	spec["dataSource"] = map[string]any{"apiGroup": volumeSnapshotGVR.Group, "kind": "VolumeSnapshot", "name": disk}
	claim := &unstructured.Unstructured{Object: map[string]any{"apiVersion": "v1", "kind": "PersistentVolumeClaim", "metadata": map[string]any{"name": claimName, "labels": map[string]any{LabelSession: obj.GetName()}, "ownerReferences": []any{map[string]any{"apiVersion": obj.GetAPIVersion(), "kind": obj.GetKind(), "name": obj.GetName(), "uid": string(obj.GetUID())}}}, "spec": spec}}
	_, err = s.pvcs.Create(ctx, claim, metav1.CreateOptions{})
	if apierrors.IsAlreadyExists(err) {
		existing, e := s.pvcs.Get(ctx, claimName, metav1.GetOptions{})
		if e != nil {
			return e
		}
		paired, _, _ := unstructured.NestedString(existing.Object, "spec", "dataSource", "name")
		owners := existing.GetOwnerReferences()
		owned := false
		for _, owner := range owners {
			owned = owned || owner.UID == obj.GetUID()
		}
		if !owned || paired != disk || existing.GetDeletionTimestamp() != nil {
			return fmt.Errorf("restore claim %s does not belong to this pair", claimName)
		}
		err = nil
	}
	if err != nil {
		return err
	}
	return useDataClaim(obj, claimName)
}

func useDataClaim(obj *unstructured.Unstructured, claimName string) error {
	if obj.GetAnnotations()[annDiskGB] == "" {
		setAnnotation(obj, annDiskGB, fmt.Sprint(FromSandbox(obj).DiskGB))
	}
	volumes, _, _ := unstructured.NestedSlice(obj.Object, "spec", "podTemplate", "spec", "volumes")
	filtered := []any{}
	for _, raw := range volumes {
		v, ok := raw.(map[string]any)
		if !ok || v["name"] != "data" {
			filtered = append(filtered, raw)
		}
	}
	filtered = append(filtered, map[string]any{"name": "data", "persistentVolumeClaim": map[string]any{"claimName": claimName}})
	if err := unstructured.SetNestedSlice(obj.Object, filtered, "spec", "podTemplate", "spec", "volumes"); err != nil {
		return err
	}
	// Template volumes otherwise take priority over an explicit data volume.
	unstructured.RemoveNestedField(obj.Object, "spec", "volumeClaimTemplates")
	setAnnotation(obj, annDataClaim, claimName)
	return nil
}

// Recover a checkpoint operation whose backend died or whose final sleep
// condition changed. GKE may already have stopped the pod; clearing a flag
// alone would leave a Running Sandbox with no serving processes.
func (s *Store) recoverCheckpoint(ctx context.Context, id, token string) error {
	ctx, cancel := context.WithTimeout(context.WithoutCancel(ctx), s.snap.timeout)
	defer cancel()
	restart := false
	if err := s.modify(ctx, id, func(obj *unstructured.Unstructured) (bool, error) {
		restart = false
		if obj.GetAnnotations()[annCheckpoint] != token {
			return false, nil
		}
		if operatingMode(obj) == "Suspended" {
			setAnnotation(obj, annCheckpoint, "")
			return true, nil
		}
		if _, err := s.snap.prune(ctx, id, obj.GetAnnotations()[annColdDisk]); err != nil {
			return false, err
		}
		if err := setSnapshot(obj, nil); err != nil {
			return false, err
		}
		setAnnotation(obj, AnnStoppedBy, StoppedByIdle)
		restart = true
		return true, unstructured.SetNestedField(obj.Object, "Suspended", "spec", "operatingMode")
	}); err != nil {
		return err
	}
	if !restart {
		return nil
	}
	if err := s.snap.until(ctx, func() (bool, error) {
		obj, err := s.client.Get(ctx, id, metav1.GetOptions{})
		if err != nil {
			return false, err
		}
		c := conditions(obj)["Suspended"]
		return c.status == "True" && c.observedGeneration >= obj.GetGeneration(), nil
	}); err != nil {
		return err
	}
	if err := s.modify(ctx, id, func(obj *unstructured.Unstructured) (bool, error) {
		if obj.GetAnnotations()[annCheckpoint] != token {
			return false, nil
		}
		setAnnotation(obj, annCheckpoint, "")
		return true, nil
	}); err != nil {
		return err
	}
	return s.Wake(ctx, id)
}

func (n *snapshotter) deletePair(ctx context.Context, memory string) error {
	if err := n.snapshots.Delete(ctx, memory, metav1.DeleteOptions{}); err != nil && !apierrors.IsNotFound(err) {
		return err
	}
	if err := n.disks.Delete(ctx, "disk-"+memory, metav1.DeleteOptions{}); err != nil && !apierrors.IsNotFound(err) {
		return err
	}
	return nil
}

// Partition legacy resume policies from the paired stop policy before triggering.
func (n *snapshotter) selectPairedPolicy(ctx context.Context, pod *unstructured.Unstructured) error {
	policy, err := n.policies.Get(ctx, "session-sleep", metav1.GetOptions{})
	if err != nil {
		return err
	}
	expressions, _, _ := unstructured.NestedSlice(policy.Object, "spec", "selector", "matchExpressions")
	excluded := false
	for _, raw := range expressions {
		e, ok := raw.(map[string]any)
		if !ok {
			continue
		}
		values, _, _ := unstructured.NestedStringSlice(e, "values")
		for _, v := range values {
			if e["key"] == "browserjs.dev/paired-snapshots" && e["operator"] == "NotIn" && v == "true" {
				excluded = true
			}
		}
	}
	if !excluded {
		return fmt.Errorf("legacy snapshot policy must exclude paired pods")
	}
	body, _ := json.Marshal(map[string]any{"metadata": map[string]any{"resourceVersion": pod.GetResourceVersion(), "labels": map[string]any{"browserjs.dev/paired-snapshots": "true"}}})
	_, err = n.pods.Patch(ctx, pod.GetName(), types.MergePatchType, body, metav1.PatchOptions{})
	return err
}

// Sandbox status can lag a restore. Route only to the actual ready pod
// mounting the selected clone, and use that pod's current address.
func (n *snapshotter) servingPod(ctx context.Context, obj *unstructured.Unstructured) (string, bool, error) {
	pod, err := n.pods.Get(ctx, obj.GetName(), metav1.GetOptions{})
	if apierrors.IsNotFound(err) {
		return "", false, nil
	}
	if err != nil {
		return "", false, err
	}
	containers, _, _ := unstructured.NestedSlice(pod.Object, "spec", "containers")
	statuses, _, _ := unstructured.NestedSlice(pod.Object, "status", "containerStatuses")
	if len(containers) == 0 || len(statuses) != len(containers) {
		return "", false, nil
	}
	for _, raw := range statuses {
		status, ok := raw.(map[string]any)
		if !ok || status["ready"] != true {
			return "", false, nil
		}
	}
	volumes, _, _ := unstructured.NestedSlice(pod.Object, "spec", "volumes")
	matched := false
	for _, raw := range volumes {
		v, ok := raw.(map[string]any)
		if !ok || v["name"] != "data" {
			continue
		}
		claim, _, _ := unstructured.NestedString(v, "persistentVolumeClaim", "claimName")
		matched = claim == dataClaim(obj)
	}
	ip, _, _ := unstructured.NestedString(pod.Object, "status", "podIP")
	return ip, matched && ip != "", nil
}

// Abandon only memory, then retry cold into another fresh clone of the saved
// disk. Keep its snapshot until the clone is bound and actually serving.
// Neither the source nor a failed restore branch is used as the retry target.
func (s *Store) coldPair(ctx context.Context, id, memory, by string, resume bool) error {
	ctx, cancel := context.WithTimeout(ctx, s.snap.timeout)
	defer cancel()
	token := time.Now().UTC().Format(time.RFC3339Nano)
	if err := s.modify(ctx, id, func(obj *unstructured.Unstructured) (bool, error) {
		if obj.GetAnnotations()[annCheckpoint] != "" {
			return false, ErrStateChanged
		}
		if resume && operatingMode(obj) == "Suspended" && !wakes(obj.GetAnnotations()[AnnStoppedBy]) {
			return false, ErrStateChanged
		}
		if obj.GetAnnotations()[AnnSnapshot] != memory {
			return false, ErrStateChanged
		}
		source := obj.GetAnnotations()[annSourceClaim]
		if source == "" {
			return false, fmt.Errorf("checkpoint source claim is missing")
		}
		setAnnotation(obj, annColdDisk, memory)
		setAnnotation(obj, annColdSource, source)
		setAnnotation(obj, annCheckpoint, token)
		setAnnotation(obj, AnnStoppedBy, by)
		return true, unstructured.SetNestedField(obj.Object, "Suspended", "spec", "operatingMode")
	}); err != nil {
		return err
	}
	if err := s.snap.until(ctx, func() (bool, error) {
		obj, err := s.client.Get(ctx, id, metav1.GetOptions{})
		if err != nil {
			return false, err
		}
		c := conditions(obj)["Suspended"]
		return c.status == "True" && c.observedGeneration >= obj.GetGeneration(), nil
	}); err != nil {
		return err
	}
	if err := s.snap.snapshots.Delete(ctx, memory, metav1.DeleteOptions{}); err != nil && !apierrors.IsNotFound(err) {
		return err
	}
	if _, err := s.snap.prune(ctx, id, memory); err != nil {
		return err
	}
	if err := s.snap.until(ctx, func() (bool, error) { names, err := s.snap.of(ctx, id); return len(names) == 0, err }); err != nil {
		return err
	}
	if err := s.modify(ctx, id, func(obj *unstructured.Unstructured) (bool, error) {
		if obj.GetAnnotations()[annCheckpoint] != token {
			return false, ErrStateChanged
		}
		if err := setSnapshot(obj, nil); err != nil {
			return false, err
		}
		setAnnotation(obj, annCheckpoint, "")
		return true, nil
	}); err != nil {
		return err
	}
	if resume {
		return s.Wake(ctx, id)
	}
	return nil
}
