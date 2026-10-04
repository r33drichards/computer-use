package sessions_test

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
	"time"

	"github.com/r33drichards/computer-use/backend/internal/sessions"
	"github.com/r33drichards/computer-use/backend/internal/sessions/sessionstest"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
	dynfake "k8s.io/client-go/dynamic/fake"
)

func TestGitHubColdProvisioningAndResume(t *testing.T) {
	client := dynfake.NewSimpleDynamicClientWithCustomListKinds(runtime.NewScheme(), map[schema.GroupVersionResource]string{sessions.SandboxGVR: "SandboxList", sessions.ClaimGVR: "SandboxClaimList"})
	store, err := sessions.NewStore(client, sessionstest.Namespace, sessionstest.Blueprint, sessionstest.PublicURL, sessionstest.URLs())
	if err != nil {
		t.Fatal(err)
	}
	store.EnableWarmPool("pool", time.Millisecond)
	ctx := sessions.WithGitHub(context.Background(), "connection-one", "session-secret", "http://github-broker:8082")
	session, err := store.Create(ctx, "github-session", "alice@example.com")
	if err != nil {
		t.Fatal(err)
	}
	for _, action := range client.Actions() {
		if action.GetResource() == sessions.ClaimGVR {
			t.Fatal("GitHub session claimed an already running warm pod")
		}
	}
	obj, err := client.Resource(sessions.SandboxGVR).Namespace(sessionstest.Namespace).Get(ctx, session.ID, metav1.GetOptions{})
	if err != nil {
		t.Fatal(err)
	}
	if !session.GitHub || session.GitHubConnection != "connection-one" || session.GitHubCredentialHash == "" {
		t.Fatal("session missing binding")
	}
	containers, _, _ := unstructured.NestedSlice(obj.Object, "spec", "podTemplate", "spec", "containers")
	var env map[string]string
	for _, item := range containers {
		c := item.(map[string]any)
		if c["name"] == "browser" {
			env = map[string]string{}
			for _, item := range c["env"].([]any) {
				e := item.(map[string]any)
				v, _ := e["value"].(string)
				env[e["name"].(string)] = v
			}
		}
	}
	if env["CU_GITHUB_SESSION"] != session.ID || env["CU_GITHUB_CREDENTIAL"] != "session-secret" {
		t.Fatal("helper was not provisioned")
	}
	public, _ := json.Marshal(session)
	if strings.Contains(string(public), "session-secret") || strings.Contains(string(public), "connection-one") || strings.Contains(string(public), session.GitHubCredentialHash) {
		t.Fatal("public session leaks credential material")
	}
	if err := store.Update(ctx, session.ID, nil, sessions.ActionStop); err != nil {
		t.Fatal(err)
	}
	if err := store.Update(ctx, session.ID, nil, sessions.ActionResume); err != nil {
		t.Fatal(err)
	}
	resumed, err := store.Get(ctx, session.ID)
	if err != nil || resumed.GitHubConnection != session.GitHubConnection || resumed.GitHubCredentialHash != session.GitHubCredentialHash {
		t.Fatal("resume lost binding", err)
	}
}
