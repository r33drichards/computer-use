package sessions

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/types"
)

// EnableWarmCapacity enables the DaemonSet/Lease handshake in production.
// The Lease serializes cold starts across replicas while idle warm pods drain.
func (s *Store) EnableWarmCapacity() { s.warmCapacity = true }

func isWarm(obj *unstructured.Unstructured) bool {
	ref := metav1.GetControllerOf(obj)
	return ref != nil && ref.Kind == "SandboxWarmPool"
}

func (s *Store) prepareStart(ctx context.Context, id string) (func(), error) {
	if !s.warmCapacity {
		return func() {}, nil
	}
	obj, err := s.client.Get(ctx, id, metav1.GetOptions{})
	if err != nil {
		return nil, err
	}
	if operatingMode(obj) != "Suspended" {
		return func() {}, nil
	}
	if _, err := s.applyResize(obj); err != nil {
		return nil, err
	}
	spec, _ := obj.Object["spec"].(map[string]any)
	return s.prepareCapacity(ctx, sizeOf(obj), spec, id)
}

func (s *Store) prepareCapacity(ctx context.Context, size string, spec map[string]any, exclude string) (func(), error) {
	noop := func() {}
	if !s.warmCapacity {
		return noop, nil
	}
	if err := s.roomWithWarm(ctx, size, spec, exclude, false); err != nil {
		return nil, err
	}
	wait, cancel := context.WithTimeout(ctx, 100*time.Second)
	defer cancel()
	holder := newID()
	var acquired bool
	for !acquired {
		lease, err := s.capacityLease.Get(wait, "session-capacity", metav1.GetOptions{})
		if err != nil {
			return nil, err
		}
		old, _, _ := unstructured.NestedString(lease.Object, "spec", "holderIdentity")
		renew, _, _ := unstructured.NestedString(lease.Object, "spec", "renewTime")
		at, _ := time.Parse(time.RFC3339Nano, renew)
		if old == "" || time.Since(at) > 120*time.Second {
			cpu, mem := requestsOf(spec)
			annotations := map[string]string{"browserjs.dev/capacity-cpu": fmt.Sprint(cpu), "browserjs.dev/capacity-memory": fmt.Sprint(mem >> 20), "browserjs.dev/capacity-exclude": exclude, "browserjs.dev/capacity-new-slot": fmt.Sprint(exclude == "")}
			body, _ := json.Marshal(map[string]any{"metadata": map[string]any{"resourceVersion": lease.GetResourceVersion(), "annotations": annotations}, "spec": map[string]any{"holderIdentity": holder, "leaseDurationSeconds": int64(120), "renewTime": time.Now().UTC().Format(time.RFC3339Nano)}})
			_, err = s.capacityLease.Patch(wait, "session-capacity", types.MergePatchType, body, metav1.PatchOptions{})
			if err == nil {
				acquired = true
				break
			}
			if !apierrors.IsConflict(err) {
				return nil, err
			}
		}
		select {
		case <-wait.Done():
			return nil, &NoCapacityError{Size: size}
		case <-time.After(100 * time.Millisecond):
		}
	}
	release := func() {
		cleanup, done := context.WithTimeout(context.WithoutCancel(ctx), 5*time.Second)
		defer done()
		lease, err := s.capacityLease.Get(cleanup, "session-capacity", metav1.GetOptions{})
		if err != nil {
			return
		}
		owner, _, _ := unstructured.NestedString(lease.Object, "spec", "holderIdentity")
		if owner != holder {
			return
		}
		body, _ := json.Marshal(map[string]any{"metadata": map[string]any{"resourceVersion": lease.GetResourceVersion()}, "spec": map[string]any{"holderIdentity": ""}})
		_, _ = s.capacityLease.Patch(cleanup, "session-capacity", types.MergePatchType, body, metav1.PatchOptions{})
	}
	for {
		// Recheck after the lock: another start or warm claim may have won.
		if err := s.roomWithWarm(wait, size, spec, exclude, false); err != nil {
			release()
			return nil, err
		}
		list, err := s.client.List(wait, metav1.ListOptions{})
		if err != nil {
			release()
			return nil, err
		}
		owned := 0
		for i := range list.Items {
			if !isWarm(&list.Items[i]) {
				owned++
			}
		}
		if exclude == "" && owned >= 3 {
			release()
			return nil, &NoCapacityError{Size: size}
		}
		room := s.room(wait, size, spec, exclude)
		if room == nil && (exclude != "" || len(list.Items) < 3) {
			return release, nil
		}
		if room != nil && !errors.Is(room, ErrNoCapacity) {
			release()
			return nil, room
		}
		select {
		case <-wait.Done():
			release()
			return nil, &NoCapacityError{Size: size}
		case <-time.After(250 * time.Millisecond):
		}
	}
}
