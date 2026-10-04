package sessions

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"

	"github.com/r33drichards/computer-use/backend/internal/diskfork"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/types"
)

var ErrInvalidDisk = errors.New("invalid session disk capacity")

type diskContextKey struct{}

// WithDiskGB specifies storage independently of the CPU/memory size.
func WithDiskGB(ctx context.Context, gb int) context.Context {
	return context.WithValue(ctx, diskContextKey{}, gb)
}

func diskGBOf(spec map[string]any) int {
	claims, _ := spec["volumeClaimTemplates"].([]any)
	for _, claim := range claims {
		c, _ := claim.(map[string]any)
		name, _, _ := unstructured.NestedString(c, "metadata", "name")
		if name != "data" {
			continue
		}
		storage, _, _ := unstructured.NestedString(c, "spec", "resources", "requests", "storage")
		if q, err := resource.ParseQuantity(storage); err == nil {
			return int((q.Value() + (1 << 30) - 1) >> 30)
		}
	}
	return 0
}

func setDiskGB(spec map[string]any, gb int) error {
	claims, _ := spec["volumeClaimTemplates"].([]any)
	for _, claim := range claims {
		c, _ := claim.(map[string]any)
		name, _, _ := unstructured.NestedString(c, "metadata", "name")
		if name == "data" {
			return unstructured.SetNestedField(c, fmt.Sprintf("%dGi", gb), "spec", "resources", "requests", "storage")
		}
	}
	return fmt.Errorf("blueprint has no data volume: %w", ErrInvalidDisk)
}

// GrowDisk never shrinks or changes the storage class. PVC expansion preserves
// data; filesystem expansion may complete when a suspended session next mounts.
func (s *Store) GrowDisk(ctx context.Context, id string, gb int) error {
	obj, err := s.client.Get(ctx, id, metav1.GetOptions{})
	if err != nil {
		return err
	}
	if err := diskfork.Fence(obj); err != nil {
		return err
	}
	sourceUID := obj.GetUID()
	spec, _ := obj.Object["spec"].(map[string]any)
	if gb < diskGBOf(spec) || gb <= 0 {
		return ErrInvalidDisk
	}
	pvc, err := s.pvcs.Get(ctx, "data-"+id, metav1.GetOptions{})
	if err != nil {
		return err
	}
	current, _, _ := unstructured.NestedString(pvc.Object, "spec", "resources", "requests", "storage")
	q, err := resource.ParseQuantity(current)
	if err != nil {
		return err
	}
	if int64(gb)<<30 < q.Value() {
		return ErrInvalidDisk
	}
	body, _ := json.Marshal(map[string]any{"metadata": map[string]any{"resourceVersion": pvc.GetResourceVersion(), "uid": pvc.GetUID()}, "spec": map[string]any{"resources": map[string]any{"requests": map[string]any{"storage": fmt.Sprintf("%dGi", gb)}}}})
	if _, err := s.pvcs.Patch(ctx, pvc.GetName(), types.MergePatchType, body, metav1.PatchOptions{}); err != nil {
		return err
	}
	return s.modifyIntentUID(ctx, id, "", &sourceUID, func(obj *unstructured.Unstructured) (bool, error) {
		spec, _ := obj.Object["spec"].(map[string]any)
		if diskGBOf(spec) >= gb {
			return false, nil
		}
		return true, setDiskGB(spec, gb)
	})
}
