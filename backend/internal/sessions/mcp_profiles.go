package sessions

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"sort"
	"strings"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"sigs.k8s.io/yaml"
)

const AnnMCPProfile = "browserjs.dev/mcp-profile"

var (
	ErrMCPProfile      = errors.New("unknown MCP profile")
	ErrMCPProfileState = errors.New("MCP profile can only be changed while the session is stopped without saved state")
	mcpProfileName     = regexp.MustCompile("^[a-z][a-z0-9-]{0,62}$")
	secretName         = regexp.MustCompile("^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$")
)

type MCPSecretKeyRef struct {
	Name string `json:"name" yaml:"name"`
	Key  string `json:"key" yaml:"key"`
}

type MCPProfile struct {
	FetchHeaderSecret MCPSecretKeyRef `json:"fetchHeaderSecret" yaml:"fetchHeaderSecret"`
	Instructions      string          `json:"instructions" yaml:"instructions"`
	SkillsDirs        []string        `json:"skillsDirs" yaml:"skillsDirs"`
}

type MCPProfilesFile struct {
	Profiles map[string]MCPProfile `json:"profiles" yaml:"profiles"`
}

func ParseMCPProfiles(raw []byte) (MCPProfilesFile, error) {
	var f MCPProfilesFile
	if err := yaml.UnmarshalStrict(raw, &f); err != nil {
		return MCPProfilesFile{}, fmt.Errorf("MCP profiles: %w", err)
	}
	if len(f.Profiles) == 0 {
		return MCPProfilesFile{}, errors.New("MCP profiles: name at least one profile")
	}
	for name, p := range f.Profiles {
		if !mcpProfileName.MatchString(name) {
			return MCPProfilesFile{}, fmt.Errorf("MCP profiles: invalid profile name %q", name)
		}
		if !secretName.MatchString(p.FetchHeaderSecret.Name) || p.FetchHeaderSecret.Key == "" || strings.ContainsAny(p.FetchHeaderSecret.Key, "\x00\n") {
			return MCPProfilesFile{}, fmt.Errorf("MCP profiles: %q has an invalid fetchHeaderSecret", name)
		}
		if p.Instructions == "" || strings.ContainsRune(p.Instructions, '\x00') {
			return MCPProfilesFile{}, fmt.Errorf("MCP profiles: %q must name instructions", name)
		}
		if len(p.SkillsDirs) == 0 {
			return MCPProfilesFile{}, fmt.Errorf("MCP profiles: %q must name at least one skills directory", name)
		}
		for _, dir := range p.SkillsDirs {
			if dir == "" || strings.ContainsAny(dir, ",\x00\n") {
				return MCPProfilesFile{}, fmt.Errorf("MCP profiles: %q has an invalid skills directory", name)
			}
		}
	}
	return f, nil
}

func (s *Store) EnableMCPProfiles(f MCPProfilesFile) {
	s.mcpProfiles = make(map[string]MCPProfile, len(f.Profiles))
	for name, p := range f.Profiles {
		s.mcpProfiles[name] = p
	}
}

func (s *Store) MCPProfiles() []string {
	out := make([]string, 0, len(s.mcpProfiles))
	for name := range s.mcpProfiles {
		out = append(out, name)
	}
	sort.Strings(out)
	return out
}

type mcpProfileContextKey struct{}

func WithMCPProfile(ctx context.Context, name string) context.Context {
	return context.WithValue(ctx, mcpProfileContextKey{}, name)
}

func mcpProfileFrom(ctx context.Context) string {
	name, _ := ctx.Value(mcpProfileContextKey{}).(string)
	return name
}

func (s *Store) applyMCPProfile(spec map[string]any, name string) error {
	if name == "" {
		return nil
	}
	profile, ok := s.mcpProfiles[name]
	if !ok {
		return fmt.Errorf("%w: %q", ErrMCPProfile, name)
	}
	containers, found, err := unstructured.NestedSlice(spec, "podTemplate", "spec", "containers")
	if err != nil || !found {
		return errors.New("blueprint podTemplate.spec.containers is missing")
	}
	foundMCP := false
	for i, raw := range containers {
		c, ok := raw.(map[string]any)
		if !ok {
			continue
		}
		if c["name"] != "mcp-js" {
			continue
		}
		foundMCP = true
		env, _, err := unstructured.NestedSlice(c, "env")
		if err != nil {
			return fmt.Errorf("mcp-js env: %w", err)
		}
		managed := map[string]bool{"MCP_V8_FETCH_HEADER_CONFIG": true, "MCP_V8_INSTRUCTIONS": true, "MCP_V8_SKILLS_DIR": true}
		kept := make([]any, 0, len(env)+3)
		for _, item := range env {
			m, ok := item.(map[string]any)
			if ok {
				if n, _ := m["name"].(string); managed[n] {
					continue
				}
			}
			kept = append(kept, item)
		}
		kept = append(kept,
			map[string]any{"name": "MCP_V8_FETCH_HEADER_CONFIG", "valueFrom": map[string]any{"secretKeyRef": map[string]any{"name": profile.FetchHeaderSecret.Name, "key": profile.FetchHeaderSecret.Key}}},
			map[string]any{"name": "MCP_V8_INSTRUCTIONS", "value": profile.Instructions},
			map[string]any{"name": "MCP_V8_SKILLS_DIR", "value": strings.Join(profile.SkillsDirs, ",")},
		)
		c["env"] = kept
		containers[i] = c
	}
	if !foundMCP {
		return errors.New("blueprint has no mcp-js container")
	}
	return unstructured.SetNestedSlice(spec, containers, "podTemplate", "spec", "containers")
}

func (s *Store) SetMCPProfile(ctx context.Context, id, name string) error {
	if name == "" {
		return errors.New("removing an MCP profile is not supported")
	}
	if _, ok := s.mcpProfiles[name]; !ok {
		return fmt.Errorf("%w: %q", ErrMCPProfile, name)
	}
	obj, err := s.client.Get(ctx, id, metav1.GetOptions{})
	if err != nil {
		return err
	}
	current := FromSandbox(obj)
	if current.State != Stopped || current.StateSaved {
		return ErrMCPProfileState
	}
	spec, _, err := unstructured.NestedMap(obj.Object, "spec")
	if err != nil {
		return err
	}
	if err := s.applyMCPProfile(spec, name); err != nil {
		return err
	}
	annotations := obj.GetAnnotations()
	if annotations == nil {
		annotations = map[string]string{}
	}
	annotations[AnnMCPProfile] = name
	obj.SetAnnotations(annotations)
	obj.Object["spec"] = spec
	_, err = s.client.Update(ctx, obj, metav1.UpdateOptions{})
	return err
}
