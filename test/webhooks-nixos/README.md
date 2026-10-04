# Webhook pipeline in a NixOS k3s VM

Run on an x86_64 Linux host with access to `/dev/kvm`:

```sh
nix build .#webhooks-k3s-driver --out-link result-webhooks-driver -L
mkdir -p result-webhooks
./result-webhooks-driver/bin/nixos-test-driver -o "$PWD/result-webhooks"
```

The NixOS integration test boots a QEMU/KVM VM containing a real single-node
k3s cluster with containerd's overlayfs snapshotter and host-gw networking.
The VM has its own kernel, 6 GiB RAM, two CPUs, and a 20 GiB writable disk.
The workflow uses KVM on `ubuntu-24.04`. This avoids the cgroup, read-only
kernel settings, and nested container runtime constraints encountered with
systemd-nspawn. The smaller container check remains available below.

k3s airgap images and all application images are preloaded from fixed Nix
inputs. The test does not download images after the cluster starts. The real
agent-sandbox v1.0.4 controller creates session pods; the real backend creates
the session through its authenticated API and stores webhook subscriptions in
SessionPolicy resources. The test deploys production CRDs, RBAC, Services,
NetworkPolicies, OPA Deployments, the Kopf operator, and Redis StatefulSet with
its retained PVC, AOF/always, authentication, and noeviction configuration.
Application binaries are packaged with Nix for offline execution rather than
using the release Dockerfiles. MCPJS and OPA retain their pinned versions.

The external browser/shell MCP tool is a stdio fixture recording execution.
The HTTPS receiver verifies HMAC, retains raw deliveries, and transactionally
deduplicates event effects. Its test-only public-looking address is local to
the container; CoreDNS resolves it and the collector trusts the generated TLS
certificate. Production destination validation and HTTP delivery are exercised.
Identity is provided by a seeded, hashed APIToken and an empty JWKS startup fixture; Pomerium/Dex, Chromium/VNC,
billing, and GKE infrastructure are outside this webhook integration test.

Assertions cover subscription API persistence and secret redaction, real CRD
watching and OPA reconciliation, full/partial signed batches, allowed/denied
attempts, Rego export filtering, lost acknowledgements, identical retry after
operator pod replacement, Redis PVC recovery, outages blocking tool execution,
and disabling subscriptions while draining accepted backlog.

The smaller sandboxed `webhooks-container` check needs these Nix daemon settings:

```ini
auto-allocate-uids = true
use-cgroups = true
extra-system-features = nixos-test uid-range
extra-experimental-features = nix-command flakes auto-allocate-uids cgroups
```

macOS can evaluate the check, but execution requires a Linux builder. CI uploads
the driver report, resource state, service logs, and build log. The smaller
`webhooks-container` check remains available for rapid checks without Kubernetes;
it supplies SessionPolicy resources from a file and tests the same delivery
failure scenarios against real MCPJS, OPA, and Redis.
