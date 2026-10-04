# Limited disk-fork coordination increment

This increment consumes already-initialized, UID-bound durable fences in the
actual backend. It does NOT enable fork or initialize tracking for legacy
sessions. HTTP submissions/operation reads stay disabled (501); runtime
BeginDiskFork always returns execution-supervisor-quiescence unsupported.
Direct protocol Begin/Admit also reject an absent ledger. No snapshot, source
pause, source resume, clone, memory restore, sharing, merge or fresh fallback.

## Integrated boundary

Production Proxy receives the Store fence interface in cmd/server. Cached
awake/running lookups check existing fences before waking. Actual reverse-proxy
dispatch (MCP, event streams, VNC, artifacts/uploads and forwarded browser/file
routes) admits immediately before upstream dispatch; manual file-list/clipboard
and background browser-start RoundTrips use the same persisted admission helper.
Only already-tracked sources receive random unreused receipts. Completed HTTP
responses do NOT resolve receipts. Lost writes refuse dispatch. Capacity or
invalid/copied-UID ledgers fail closed. Legacy traffic is unchanged; this is NOT
atomic execution admission across untracked legacy sessions.

The Store's shared resourceVersion modification loop checks fences before its
change callback, covering wake/resume/resize/suspend/rename and metadata changes
using that loop. Explicit stop/resume, billing drain, sleep and deletion record
attempted intent with a monotonic epoch in the same CAS as refusal. Delete intent
is sticky while fenced. These attempts still return refusal: users must retry;
the audit is not an accepted action or billing authorization. No automatic
resume is performed. Sleep refuses before PodSnapshot triggering; deletion
refuses before cleanup and uses UID/resourceVersion preconditions on its final
source delete. EnsurePolicy and authenticated API policy mutations refuse an
already-active source fence before cross-resource effects.

Limitations: cross-resource policy/snapshot/claim effects are not one transaction
with source admission. A racing external controller can invalidate prechecks.
There is no initializer/activator/controller in production, so this increment
must NOT be used as a complete activation/pause protocol. Concurrent external
writers require a future operation/owner/protection/refinement protocol. Existing
legacy requests before tracking are not retroactively accounted for. Receipts
are bounded and have no safe GC. Neither receipt expiry nor RPC/log completion
means actual execution or descendants ended. Source protection finalizers,
physical graceful shutdown/unmount and CSI ownership cleanup are not implemented.

## Runtime dependency discovered

Guest images pin mcp-exec to 86a6aee684bae7db574473005c824f6602ef24ac.
Its README exposes exec, stream_logs, search_logs, kill and tasks methods, and
explicitly says execution ends when the original program ends even if background
children continue writing output. Process-group cancellation is not proof for
setsid/double-fork descendants. There is no atomic close-admission epoch plus
positive all-descendants-complete certificate. Therefore Begin remains blocked;
no invented endpoint is called and no host OAuth secret is placed in a guest.

## Next coherent provider/CSI increments (not reviewed implementation)

Investigate a pinned mcp-exec patch carried initially inside this fork worktree,
not edits to another repository: an unprivileged per-execution Linux subreaper
supervisor remains alive until waitpid establishes ECHILD for all descendants.
Admission must close atomically at a backend-authenticated operation/epoch and
cover all provider exec requests, not only this replica's HTTP calls. Proposed
mechanism needs review against detached/setsid/double-fork children, inherited
output FDs closing early, supervisor death, exec-provider restart, old orphan PID
namespace ambiguity, reparenting and signal races. Any uncertainty is UNKNOWN,
never drained; actual container-death proof may be needed. No privileged cgroup,
user-namespace or new capability assumptions are approved. Same-UID hostile guest
code may kill/spoof a provider; certificate/control authentication and isolation
from guest-writable state must be designed and adversarially tested, not assumed.
This proposal alone is not production proof. Browser/V8/VNC and graceful Chrome/
SecretService shutdown plus real volume detach/unmount remain separate obligations.

A durable operation resource must use a dedicated CRD or separate least-privilege
controller/namespace, NOT a broad namespace ConfigMap journal grant (sensitive
Dex/Pomerium configuration exists). Backend baseline intentionally lacks pod/PVC/
snapshot/ConfigMap/Secret rights. No RBAC changes here. Parent baseline identifies
browserjs-zonal CSI pd.csi.storage.gke.io/pd-balanced, WaitForFirstConsumer/Delete;
no configured VolumeSnapshotClass in non-vendor deploy manifests. Actual live
CRDs, snapshot-controller, matching class, restore/binding/unmount behavior and
independent volume identity remain unverified live prerequisites.

Subsequent operation increment must atomically reserve shared create/fork owner
cap and billing allowance, enforce same-owner/same-size and durable idempotency,
protect source/child against deletion, fence effect-time resume against latest
user/billing/deletion intent, reconcile response loss/restarts, and UID-fence
snapshot/PVC/child cleanup and late workers vs healthy committed children. CSI
increment must snapshot only after safe quiescence/flush/physical unmount, restore
an independent PVC and cold child with fresh URLs/controls/enforced policy and
no guest host-OAuth secrets, and keep it inaccessible until durable commit. No
memory clone, source disk sharing, merge or fresh fallback.

## Validation and shipping gate

Use delivery/validate_admission.py: serial narrow packages under the shared
0700-access coordination directory (existing02700 setgid preserved), owner0600
nofollow advisory lock and bounded wait; CPU1/GOMEMLIMIT384MiB. Do not run the
historical605-library warming helper on this small desktop. Full/race/backend
server suite is deferred to the existing public backend-tests GitHub workflow;
passing targeted tests is not full-suite success. Draft PR only, no merge,
feature enablement, cloud resources or deployment in this lane. Independent
review and relevant CI are required; live isolated CSI/Sandbox tests before
future enablement, including independent disk writes/deletion, detached execution,
hung drain, lost responses/crashes, UID replacement and late cleanup races.

The prior28 hash-bound TLC outcomes/logs/tools are preserved unchanged. Models
are separate bounded abstractions, not composition or production refinement proof.


## Explicit TOCTOU and trust tails for draft review

Existing open VNC/websocket/event-stream connections are NOT revoked or proven
quiet by installing a gate. Gate consumers block new dispatch only; bytes and
already-running browser/V8/detached processes may continue. No fork may start
from this limited component. Policy prechecks target a different CRD, and GKE
PodSnapshot prechecks/cleanup are not CAS-atomic with source gating. Source final
delete uses UID/resourceVersion preconditions but preceding claim/snapshot/policy
cleanup is not a complete transactional or UID-fenced fork cleanup protocol.
External actual PodUID/container death and unmount proof before CSI is essential;
none is implemented or live-verified here. Never trust a same-UID guest certificate
without a separately reviewed authentication/isolation design: forged or replayed
ACKs, wrong operation/epoch/UID, provider restart and old-orphan uncertainty must
fail closed. The subreaper direction above requires independent design review
before a provider patch, not just unit tests. Current receipts/intent are internal
coordination/audit data, not authenticated execution certificates or accepted
lifecycle requests. No broad ConfigMap/RBAC grant or host secret in a guest.

Admission consumers add fresh Sandbox reads to ordinary dispatch even though fork remains disabled; performance and cluster-unavailable behavior need review. No latency/throughput production claim is made.
