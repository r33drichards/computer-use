package sessions_test

import (
	"errors"
	"testing"

	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/client-go/dynamic/fake"
	ktesting "k8s.io/client-go/testing"

	"github.com/r33drichards/computer-use/backend/internal/sessions"
	"github.com/r33drichards/computer-use/backend/internal/sessions/sessionstest"
)

func TestSessionQuotaIsNoCapacity(t *testing.T) {
	for _, test := range []struct {
		message    string
		noCapacity bool
	}{
		{"exceeded quota: session-slot-storage-quota", true},
		{"user cannot create sandboxes", false},
	} {
		t.Run(test.message, func(t *testing.T) {
			store, client := sessionstest.New(t)
			client.(*fake.FakeDynamicClient).PrependReactor("create", "sandboxes", func(ktesting.Action) (bool, runtime.Object, error) {
				return true, nil, apierrors.NewForbidden(schema.GroupResource{Group: "agents.x-k8s.io", Resource: "sandboxes"}, "session", errors.New(test.message))
			})
			_, err := store.Create(t.Context(), "session", "alice@example.com")
			if err == nil || errors.Is(err, sessions.ErrNoCapacity) != test.noCapacity {
				t.Fatalf("got %v, want no capacity = %v", err, test.noCapacity)
			}
		})
	}
}
