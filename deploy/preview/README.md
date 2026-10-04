# PR environments

`hack/preview.py render` builds namespaced manifests from the trusted
backend, policy, OPA, site and GKE session definitions. It does not apply PR
manifests, CRDs, cluster roles, storage classes, Pomerium, Dex or production
secrets. All five workload images come from the preview build's commit.

Pomerium remains in `browserjs-sessions`, with exact routes to the preview's
Services and the production sign-in policy. It alone may reach the preview
backend and site from another namespace. The backend and policy operator's
Kubernetes rights remain namespaced. Session networking and gVisor are the
same as production, and OPA is local to the preview.

See [the setup and lifecycle guide](../../docs/preview-environments.md).
