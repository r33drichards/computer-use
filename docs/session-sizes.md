# Session sizes and storage

Production has one 4-vCPU/16-GB N2D session node in us-west1-c. Its minimum and maximum are one node, so the warm-pool DaemonSet is always available. The conservative usable session capacity is 3213m CPU and 12097Mi memory.

| Compute tier | Pod CPU request | Pod memory request | Desktop limits | MCP limits | Fits alone on the node |
|---|---:|---:|---|---|---:|
| Small | 1 CPU | 2.5 GiB | 1.5 CPU / 2 GiB | 0.5 CPU / 1 GiB | 3 |
| Medium | 1.5 CPU | 5.5 GiB | 2 CPU / 5 GiB | 0.5 CPU / 1 GiB | 2 |
| Large | 3 CPU | 11 GiB | 3 CPU / 10 GiB | 0.5 CPU / 1 GiB | 1 |

One small and one medium can share the node. A large session needs the node's session capacity to itself. A requested size that cannot fit returns `409 no_capacity`. Suspended sessions keep their disks and count toward the three total session slots, but release compute until they wake.

Only small sessions are kept warm. The DaemonSet calculates spare capacity from both the three-slot budget and claimed sessions' actual CPU/memory requests. Two running small sessions leave one warm spare. Medium and large starts or wakes reserve their requested resources through the `session-capacity` Lease; warm spares yield those resources before admission. The Lease expires if the backend dies. Release workflows explicitly apply `deploy/gke/session-capacity.yaml` before enabling the handshake, because Argo CD excludes Leases by default. Releasing a claim replenishes a clean warm spare after its disk disappears. No user's files are handed to another claimant.

## Independent HDD capacity

All compute tiers default to **32 GiB HDD** (`pd-standard`, `browserjs-session-hdd`). `POST /api/sessions` accepts `diskGB` independently of `size`; for example `{"size":"medium","diskGB":64}`. `PATCH /api/sessions/{id}` accepts `{"diskGB":128}` to expand an existing disk. A disk cannot be shrunk, and resizing compute does not change storage. Filesystem expansion can finish on the next mount for suspended sessions.

The normal maximum is **128 GiB**. OpenFeature evaluates `session-disk-max-gb` using the account's stable owner hash as its targeting key. `deploy/gke/feature-flags.json` is mounted as a ConfigMap; evaluations read updates without restarting the backend:

```json
{
  "session-disk-max-gb": {
    "default": 128,
    "accounts": {"ACCOUNT_OWNER_HASH": 256}
  }
}
```

Get the hash from the Account's `spec.ownerHash` or the Sandbox's `browserjs.dev/owner` label. Do not use the client-provided account identity: evaluation always targets the authenticated session owner. Missing/invalid configuration falls back to 128. Overrides must be between 32 and 1536 GiB. The namespace has a separate shared HDD budget of 1536Gi and a three-Sandbox ceiling, so an account override does not grant more cluster-wide capacity. `GET /api/sizes` returns the calling account's `storage` limits for the UI.

The session node boot disk also uses HDD. Pomerium and Redis remain on their current balanced disks. Existing sessions keep their current disk type and capacity. HDD defaults apply to new sessions; legacy disks are not migrated.

## Changing compute size

`PATCH /api/sessions/{id}` with `{"size":"large"}` changes CPU/memory. A running session keeps its current size until its next start; the response includes `pendingSize`. Suspended sessions get the new size immediately. The next start is fresh from disk, and a saved memory snapshot is dropped because its pod spec differs. Files and disk capacity are preserved. Large sessions may have to wait until other running sessions release compute.
