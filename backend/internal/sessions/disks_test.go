package sessions_test

import (
	"errors"
	"testing"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime/schema"

	"github.com/r33drichards/computer-use/backend/internal/sessions"
	"github.com/r33drichards/computer-use/backend/internal/sessions/sessionstest"
)

func TestDiskExpansionPreservesComputeAndRefusesShrink(t *testing.T) {
	store, client := sessionstest.NewSized(t)
	ctx := t.Context()
	session, err := store.CreateSized(sessions.WithDiskGB(ctx, 32), "disk", "alice@example.com", "medium", nil)
	if err != nil {
		t.Fatal(err)
	}
	pvcs := client.Resource(schema.GroupVersionResource{Version: "v1", Resource: "persistentvolumeclaims"}).Namespace(sessionstest.Namespace)
	_, err = pvcs.Create(ctx, &unstructured.Unstructured{Object: map[string]any{"apiVersion": "v1", "kind": "PersistentVolumeClaim", "metadata": map[string]any{"name": "data-" + session.ID}, "spec": map[string]any{"storageClassName": "browserjs-session-hdd", "resources": map[string]any{"requests": map[string]any{"storage": "32Gi"}}}}}, metav1.CreateOptions{})
	if err != nil {
		t.Fatal(err)
	}
	if err := store.GrowDisk(ctx, session.ID, 64); err != nil {
		t.Fatal(err)
	}
	got, err := store.Get(ctx, session.ID)
	if err != nil || got.DiskGB != 64 || got.Size != "medium" {
		t.Fatalf("expanded: %+v, %v", got, err)
	}
	if err := store.GrowDisk(ctx, session.ID, 32); !errors.Is(err, sessions.ErrInvalidDisk) {
		t.Fatalf("shrink accepted: %v", err)
	}
	claim, _ := pvcs.Get(ctx, "data-"+session.ID, metav1.GetOptions{})
	storage, _, _ := unstructured.NestedString(claim.Object, "spec", "resources", "requests", "storage")
	if storage != "64Gi" {
		t.Fatalf("shrink changed claim: %s", storage)
	}
}
