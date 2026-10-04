// Package github connects account-owned GitHub App authorizations to sessions.
package github

import (
	"context"
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/r33drichards/computer-use/backend/internal/sessions"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/client-go/dynamic"
)

var GVR = schema.GroupVersionResource{Group: "browserjs.dev", Version: "v1alpha1", Resource: "githubconnections"}
var ErrDisconnected = errors.New("GitHub connection unavailable; reconnect GitHub in account connections")

type connection struct {
	ID             string
	Login          string
	UserID         int64
	Access         string
	Refresh        string
	Expires        time.Time
	RefreshExpires time.Time
}

type Store struct {
	client dynamic.ResourceInterface
	box    cipher.AEAD
}

func NewStore(client dynamic.Interface, namespace string, key []byte) (*Store, error) {
	if len(key) != 32 {
		return nil, errors.New("GitHub encryption key must be 32 bytes")
	}
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, err
	}
	box, err := cipher.NewGCM(block)
	if err != nil {
		return nil, err
	}
	return &Store{client.Resource(GVR).Namespace(namespace), box}, nil
}
func randomID() (string, error) {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(b), nil
}
func (s *Store) seal(owner string, v any) (string, error) {
	raw, err := json.Marshal(v)
	if err != nil {
		return "", err
	}
	nonce := make([]byte, s.box.NonceSize())
	if _, err = rand.Read(nonce); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(s.box.Seal(nonce, nonce, raw, []byte(owner))), nil
}
func (s *Store) open(owner, encoded string, v any) error {
	raw, err := base64.RawURLEncoding.DecodeString(encoded)
	if err != nil || len(raw) < s.box.NonceSize() {
		return errors.New("invalid encrypted GitHub record")
	}
	plain, err := s.box.Open(nil, raw[:s.box.NonceSize()], raw[s.box.NonceSize():], []byte(owner))
	if err != nil {
		return errors.New("invalid encrypted GitHub record")
	}
	return json.Unmarshal(plain, v)
}
func recordName(owner string) string { return "gh-" + sessions.OwnerLabel(owner) }
func (s *Store) load(ctx context.Context, owner string) (*unstructured.Unstructured, connection, error) {
	obj, err := s.client.Get(ctx, recordName(owner), metav1.GetOptions{})
	if apierrors.IsNotFound(err) {
		return nil, connection{}, ErrDisconnected
	}
	if err != nil {
		return nil, connection{}, err
	}
	stored, _, _ := unstructured.NestedString(obj.Object, "spec", "owner")
	if stored != owner {
		return nil, connection{}, ErrDisconnected
	}
	encoded, _, _ := unstructured.NestedString(obj.Object, "spec", "encrypted")
	var c connection
	if err := s.open(owner, encoded, &c); err != nil {
		return nil, c, err
	}
	return obj, c, nil
}
func (s *Store) save(ctx context.Context, owner string, c connection, obj *unstructured.Unstructured) error {
	encrypted, err := s.seal(owner, c)
	if err != nil {
		return err
	}
	if obj == nil {
		obj = &unstructured.Unstructured{Object: map[string]any{"apiVersion": GVR.GroupVersion().String(), "kind": "GitHubConnection", "metadata": map[string]any{"name": recordName(owner)}, "spec": map[string]any{"owner": owner, "encrypted": encrypted}}}
		_, err = s.client.Create(ctx, obj, metav1.CreateOptions{})
		return err
	}
	_ = unstructured.SetNestedField(obj.Object, encrypted, "spec", "encrypted")
	unstructured.RemoveNestedField(obj.Object, "spec", "lockUntil")
	_, err = s.client.Update(ctx, obj, metav1.UpdateOptions{})
	return err
}
func (s *Store) connect(ctx context.Context, owner string, c connection) error {
	// Reconnect gets a new ID. Older sessions cannot inherit this authorization.
	id, err := randomID()
	if err != nil {
		return err
	}
	c.ID = id
	for range 5 {
		obj, _, err := s.load(ctx, owner)
		if errors.Is(err, ErrDisconnected) {
			obj = nil
		} else if err != nil {
			return err
		}
		err = s.save(ctx, owner, c, obj)
		if apierrors.IsConflict(err) || apierrors.IsAlreadyExists(err) {
			continue
		}
		return err
	}
	return fmt.Errorf("GitHub connection changed concurrently")
}
