package sessions_test

import (
	"context"
	"strings"
	"testing"
	"time"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/apimachinery/pkg/types"

	"github.com/r33drichards/computer-use/backend/internal/sessions"
	"github.com/r33drichards/computer-use/backend/internal/sessions/sessionstest"
)

func TestLargeColdStartReservesCapacityAndWaitsForWarmPodsToYield(t *testing.T) {
	store, client := sessionstest.NewSized(t)
	ctx, cancel := context.WithTimeout(t.Context(), 5*time.Second)
	defer cancel()
	sessionstest.EnableSizes(t, store, strings.Replace(sessionstest.Sizes, "nodes: 2", "nodes: 1", 1))
	lease := client.Resource(schema.GroupVersionResource{Group: "coordination.k8s.io", Version: "v1", Resource: "leases"}).Namespace(sessionstest.Namespace)
	_, err := lease.Create(ctx, &unstructured.Unstructured{Object: map[string]any{"apiVersion": "coordination.k8s.io/v1", "kind": "Lease", "metadata": map[string]any{"name": "session-capacity"}, "spec": map[string]any{}}}, metav1.CreateOptions{})
	if err != nil {
		t.Fatal(err)
	}
	var warm []string
	for range 2 {
		made, err := store.Create(ctx, "spare", "alice@example.com")
		if err != nil {
			t.Fatal(err)
		}
		resource := client.Resource(sessions.SandboxGVR).Namespace(sessionstest.Namespace)
		obj, _ := resource.Get(ctx, made.ID, metav1.GetOptions{})
		controller := true
		obj.SetOwnerReferences([]metav1.OwnerReference{{APIVersion: "extensions.agents.x-k8s.io/v1beta1", Kind: "SandboxWarmPool", Name: "s", UID: types.UID("pool"), Controller: &controller}})
		if _, err := resource.Update(ctx, obj, metav1.UpdateOptions{}); err != nil {
			t.Fatal(err)
		}
		warm = append(warm, made.ID)
	}
	store.EnableWarmCapacity()
	controllerDone := make(chan error, 1)
	go func() {
		for {
			select {
			case <-ctx.Done():
				controllerDone <- ctx.Err()
				return
			default:
			}
			obj, err := lease.Get(ctx, "session-capacity", metav1.GetOptions{})
			if err != nil {
				controllerDone <- err
				return
			}
			holder, _, _ := unstructured.NestedString(obj.Object, "spec", "holderIdentity")
			if holder != "" {
				for _, id := range warm {
					if err := client.Resource(sessions.SandboxGVR).Namespace(sessionstest.Namespace).Delete(ctx, id, metav1.DeleteOptions{}); err != nil {
						controllerDone <- err
						return
					}
				}
				controllerDone <- nil
				return
			}
			time.Sleep(time.Millisecond)
		}
	}()
	large, err := store.CreateSized(ctx, "large", "alice@example.com", "large", nil)
	if err != nil {
		t.Fatal(err)
	}
	if err := <-controllerDone; err != nil {
		t.Fatal(err)
	}
	if large.Size != "large" {
		t.Fatalf("wrong size: %+v", large)
	}
	obj, _ := lease.Get(ctx, "session-capacity", metav1.GetOptions{})
	holder, _, _ := unstructured.NestedString(obj.Object, "spec", "holderIdentity")
	if holder != "" {
		t.Fatalf("reservation not released: %s", holder)
	}
}
