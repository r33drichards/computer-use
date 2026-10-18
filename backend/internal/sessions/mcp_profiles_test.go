package sessions_test

import (
	"context"
	"errors"
	"testing"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"

	"github.com/r33drichards/computer-use/backend/internal/sessions"
	"github.com/r33drichards/computer-use/backend/internal/sessions/sessionstest"
)

func testMCPProfiles(t *testing.T) sessions.MCPProfilesFile {
	t.Helper()
	f, err := sessions.ParseMCPProfiles([]byte(`profiles:
  nocodb:
    fetchHeaderSecret: {name: mcp-profile-nocodb, key: fetch-header-config}
    instructions: '@/etc/mcp/profiles/nocodb/instructions.md'
    skillsDirs: [/etc/mcp/skills, /etc/mcp/profiles/nocodb/skills]
`))
	if err != nil {
		t.Fatal(err)
	}
	return f
}

func TestMCPProfileCreateUsesSecretReference(t *testing.T) {
	store, client := sessionstest.New(t)
	store.EnableMCPProfiles(testMCPProfiles(t))
	ctx := sessions.WithMCPProfile(context.Background(), "nocodb")
	s, err := store.Create(ctx, "integrated", "root@example.com")
	if err != nil {
		t.Fatal(err)
	}
	if s.MCPProfile != "nocodb" {
		t.Fatalf("profile = %q", s.MCPProfile)
	}
	obj, err := client.Resource(sessions.SandboxGVR).Namespace(sessionstest.Namespace).Get(ctx, s.ID, metav1.GetOptions{})
	if err != nil {
		t.Fatal(err)
	}
	containers, _, _ := unstructured.NestedSlice(obj.Object, "spec", "podTemplate", "spec", "containers")
	var env []any
	for _, raw := range containers {
		c := raw.(map[string]any)
		if c["name"] == "mcp-js" {
			env, _, _ = unstructured.NestedSlice(c, "env")
		}
	}
	values := map[string]map[string]any{}
	for _, raw := range env {
		m := raw.(map[string]any)
		values[m["name"].(string)] = m
	}
	ref, _, _ := unstructured.NestedString(values["MCP_V8_FETCH_HEADER_CONFIG"], "valueFrom", "secretKeyRef", "name")
	if ref != "mcp-profile-nocodb" {
		t.Errorf("secret ref = %q", ref)
	}
	if values["MCP_V8_INSTRUCTIONS"]["value"] != "@/etc/mcp/profiles/nocodb/instructions.md" {
		t.Errorf("instructions = %v", values["MCP_V8_INSTRUCTIONS"])
	}
	if values["MCP_V8_SKILLS_DIR"]["value"] != "/etc/mcp/skills,/etc/mcp/profiles/nocodb/skills" {
		t.Errorf("skills = %v", values["MCP_V8_SKILLS_DIR"])
	}
}

func TestMCPProfileValidationAndUnknownProfile(t *testing.T) {
	for _, raw := range []string{"", "profiles: {}", "profiles: {Bad: {}}", "profiles: {ok: {fetchHeaderSecret: {name: Bad, key: k}, instructions: x, skillsDirs: [/x]}}"} {
		if _, err := sessions.ParseMCPProfiles([]byte(raw)); err == nil {
			t.Errorf("ParseMCPProfiles(%q) succeeded", raw)
		}
	}
	store, _ := sessionstest.New(t)
	_, err := store.Create(sessions.WithMCPProfile(context.Background(), "missing"), "x", "root@example.com")
	if !errors.Is(err, sessions.ErrMCPProfile) {
		t.Fatalf("err = %v", err)
	}
}

func TestSetMCPProfileRequiresStoppedSession(t *testing.T) {
	store, client := sessionstest.New(t)
	store.EnableMCPProfiles(testMCPProfiles(t))
	s, err := store.Create(t.Context(), "existing", "root@example.com")
	if err != nil {
		t.Fatal(err)
	}
	if err := store.SetMCPProfile(t.Context(), s.ID, "nocodb"); !errors.Is(err, sessions.ErrMCPProfileState) {
		t.Fatalf("running profile change: %v", err)
	}
	resource := client.Resource(sessions.SandboxGVR).Namespace(sessionstest.Namespace)
	obj, err := resource.Get(t.Context(), s.ID, metav1.GetOptions{})
	if err != nil {
		t.Fatal(err)
	}
	if err := unstructured.SetNestedField(obj.Object, "Suspended", "spec", "operatingMode"); err != nil {
		t.Fatal(err)
	}
	ann := obj.GetAnnotations()
	ann[sessions.AnnStoppedBy] = sessions.StoppedByUser
	obj.SetAnnotations(ann)
	if err := unstructured.SetNestedSlice(obj.Object, []any{map[string]any{"type": "Suspended", "status": "True"}}, "status", "conditions"); err != nil {
		t.Fatal(err)
	}
	if _, err := resource.Update(t.Context(), obj, metav1.UpdateOptions{}); err != nil {
		t.Fatal(err)
	}
	if err := store.SetMCPProfile(t.Context(), s.ID, "nocodb"); err != nil {
		t.Fatal(err)
	}
	got, err := store.Get(t.Context(), s.ID)
	if err != nil {
		t.Fatal(err)
	}
	if got.MCPProfile != "nocodb" {
		t.Errorf("profile = %q", got.MCPProfile)
	}
}
