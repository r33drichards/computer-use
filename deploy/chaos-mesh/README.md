# Chaos Mesh on production GKE

Target: `browserjs` in `browserjs-sessions`, `us-west1-a`. The vendored
upstream Helm chart is version 2.8.4; `SHA256SUMS` locks its contents.
Installation guide: <https://chaos-mesh.org/docs/production-installation-using-helm/>.

Kubernetes components belong in `deploy/`, following this repository's
existing split from OpenTofu's GCP infrastructure. Helm manages this release;
the workflow applies the chart's CRDs explicitly because Helm does not
upgrade CRDs. No experiments, schedules or namespace opt-ins are included.

The controller, dashboard and DNS server run only on the `system` node pool.
The privileged daemon runs on system nodes and all nodes labeled
`sandbox.gke.io/runtime=gvisor`, tolerating the session pool's NoSchedule taint.
It uses the default host container runtime, not the gVisor RuntimeClass, and
requires host access and the containerd socket. This includes existing and
future session pools carrying that label. It adds a 100m CPU / 256Mi memory
reservation per node; account for that overhead when sizing session capacity.
Daemon placement does not establish gVisor fault compatibility: process,
filesystem, time and network injection require separate validation against
the sandbox runtime. No fault support is claimed until tested.
Namespace filtering requires
`chaos-mesh.org/inject=enabled` before a namespace can receive experiments.
Do not treat that annotation as an authorization boundary: cluster RBAC still
controls who can create experiments and change namespace annotations.

The dashboard requires credentials, uses an internal ClusterIP Service, and
persists SQLite data on an 8 GiB `standard-rwo` volume. No public route is created.

## Deploy

Following `docs/gke-deployment.md`, review and merge these files to `main`, then:

```sh
gh workflow run chaos-mesh.yml --ref main -f confirm=deploy
```

The workflow uses the existing WIF provider and deployer service account,
the `production` environment, and the same concurrency lock as app deployments.
It checks the chart checksum, applies CRDs, installs/upgrades the Helm release,
and waits up to ten minutes for readiness. PRs lint and render without GCP access.
Helm rolls back a failed upgrade (or removes a failed initial release); CRDs
and persistent data are not rolled back by `--atomic`.

## Access and rollback

With production kubeconfig credentials:

```sh
kubectl -n chaos-mesh port-forward svc/chaos-dashboard 2333:2333
helm -n chaos-mesh history chaos-mesh
helm -n chaos-mesh rollback chaos-mesh <revision> --wait --timeout 10m
```

Open <http://localhost:2333> and authenticate with a Kubernetes token whose
RBAC permits only the intended experiment namespaces. No new user tokens or
cluster-admin user grants are created here. Rollback is temporary: commit the
corresponding configuration so the next deployment preserves it.

Before any experiments, separately review the target namespace, selectors,
duration and recovery plan. Installation does not start experiments.

## Validation

Chart 2.8.4 lints and renders locally. GCP API inspection confirmed the target
is running GKE 1.36.4 with COS_CONTAINERD system and session pools.
Live Kubernetes admission, storage provisioning and readiness remain unverified
until the workflow runs; local kubectl lacks the GKE authentication plugin.
