package sessions_test

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"testing"
	"time"

	coordinationv1 "k8s.io/api/coordination/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/apimachinery/pkg/types"
	dynamicfake "k8s.io/client-go/dynamic/fake"
	ktesting "k8s.io/client-go/testing"

	"github.com/r33drichards/computer-use/backend/internal/sessions"
	"github.com/r33drichards/computer-use/backend/internal/sessions/sessionstest"
)

func TestLargeColdStartReservesCapacityAndWaitsForWarmPodsToYield(t *testing.T) {
	store, client := sessionstest.NewSized(t)
	validated := 0
	// The dynamic fake does not validate typed API fields. Decode Lease
	// patches as Kubernetes does, so malformed MicroTime values are refused.
	client.(*dynamicfake.FakeDynamicClient).PrependReactor("patch", "leases", func(action ktesting.Action) (bool, runtime.Object, error) {
		var lease coordinationv1.Lease
		if err := json.Unmarshal(action.(ktesting.PatchAction).GetPatch(), &lease); err != nil {
			return true, nil, err
		}
		// Require the canonical Kubernetes MicroTime wire encoding,
		// including fixed six-digit fractional precision.
		var raw struct {
			Spec struct {
				RenewTime string `json:"renewTime"`
			} `json:"spec"`
		}
		if err := json.Unmarshal(action.(ktesting.PatchAction).GetPatch(), &raw); err != nil {
			return true, nil, err
		}
		if raw.Spec.RenewTime != "" {
			validated++
		}
		if raw.Spec.RenewTime != "" && raw.Spec.RenewTime != lease.Spec.RenewTime.UTC().Format(metav1.RFC3339Micro) {
			return true, nil, fmt.Errorf("renewTime must use Kubernetes MicroTime precision")
		}
		return false, nil, nil
	})
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
	if validated == 0 {
		t.Fatal("Lease renewTime validation was not exercised")
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
