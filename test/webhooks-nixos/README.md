# Webhook pipeline in a NixOS nspawn k3s cluster

Run on an x86_64 Linux host:

```sh
sudo modprobe dummy overlay br_netfilter ip_tables iptable_nat nf_conntrack
nix build .#webhooks-k3s-driver --out-link result-webhooks-driver -L
mkdir -p result-webhooks
sudo systemd-run --wait --pipe --collect -p Delegate=yes -p TasksMax=infinity \
  "$(readlink -f result-webhooks-driver)/bin/nixos-test-driver" \
  -o "$PWD/result-webhooks"
```

The NixOS integration test boots a systemd-nspawn container containing a real
single-node k3s cluster. There is no QEMU, KVM, Docker daemon, or kind. k3s uses
containerd's native snapshotter and host-gw networking inside the NixOS container. The host must provide cgroup v2 and the networking kernel modules;
the workflow configures them on `ubuntu-24.04`. It builds the packaged NixOS
test driver with Nix and executes it as root in a delegated systemd unit.
Nix 2.35 build sandboxes do not expose the writable cgroup hierarchy k3s
requires; running the driver directly retains the same NixOS containers and
assertions without a VM.

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
Identity is provided by a seeded, hashed APIToken; Pomerium/Dex, Chromium/VNC,
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
