# Disk-snapshot fork: staged, unavailable contract

## Delivered slice — not automatic pause functionality

Authenticated POST /api/sessions/{id}/fork and /v1/sessions/{id}/fork return 501
with code disk_fork_disabled after existing session authorization. Unauthenticated
requests return 401; denied/missing sources return 404. Authenticated GET
/api/fork-operations/{operation} and /v1/fork-operations/{operation} also return
501 without revealing operation IDs. There is no accepted submission, operation
HTTP resource, enable switch, CSI call, source pause, child creation or fallback.
Admin authorization never enables a fork; future enabled calls must be same-owner.
On the configured API_URL host, explicit whitelist entries require sessions:write
for POST and sessions:read for GET, and reject session-bound tokens on both.
APIHost rewrites /v1 to /api. The app host uses existing assertion authentication;
there is no new credential, exchange flow, scope or grant. Operation names are
opaque single path segments; while disabled they are never looked up.

The unwired internal/diskfork prototype stores durable gate, execution receipts
and key tombstones in one Sandbox annotation. Admission and gate installation
use the same resourceVersion CAS, with source UID/owner/size checks on every
retry. Tokens cannot be reused: ambiguous admission retry returns ErrReplay,
never permission to execute again. Restart reads the durable ledger. Receipts
never expire; only a trusted execution supervisor may ACK that actual work and
all descendants ended. HTTP disconnect, expired marks, cancellation and worker
death are not such ACKs. Pre-stop drain deadline releases admission without
stopping/resuming/copying/killing anything, retaining outstanding receipts.
This prototype fails closed at 256 receipts/16 operations; no safe GC exists.
Drained() is a ledger predicate, not physical quiescence certification.

The initial prototype was unwired. The subsequent limited consumer integration is described in disk-fork-coordination.md; fork initialization and pause remain unsupported. No finalizer,
operation reconciler, shared owner reservation/cap/billing transaction, executor
ACK channel, physical graceful termination/unmount/flush, CSI restore, child
commit/publication, cleanup or current-intent resume is implemented. No claim of
production atomic admission or end-to-end crash recovery is made. Annotation
writers require future RBAC/protocol enforcement. Current Create's replica-local
list/create cap is insufficient. Existing Sleep's PodSnapshot and fresh fallback
paths MUST NOT implement disk fork.

## Subsequent requirements — release blockers

1. Durable owner-scoped idempotency/operation resource/reservation with shared
   create/fork cap/billing checks, same-owner/same-size and conflict responses.
   Lost-response recovery uses deterministic object names and verified UIDs.
2. Atomic admission on ALL MCP/browser/exec/files/artifacts/upload/streams/VNC
   forwarding and every mutation/wake/resize/policy path. Executor positive ACK,
   not expiring marks. Pre-stop deadline cancels safely; post-stop unknown state
   retains protection and never claims an unmount.
3. Source protection vs latest user/billing/delete intent. Graceful terminate,
   flush, pod exit, volume detach/unmount and controller ACK before CSI snapshot.
   Hung or ambiguous shutdown stays blocked, never forced success.
4. Immutable ready CSI VolumeSnapshot of source PVC, restoreSize/class/owner/UID
   checks, and new independent restored PVC. Cold child only: no PodSnapshot,
   memory restore, source disk sharing, merge or fresh fallback.
5. Fresh URLs/control identities/capabilities and freshly enforced policy.
   Never copy host OAuth secrets, tokens, tickets or credentials into guests.
6. Inaccessible child until durable commit verifies ownership, binding/readiness,
   policy and latest deletion intent. Effect-time resourceVersion-fenced source
   resume against current user/billing/delete intent.
7. Snapshot/PVC/child cleanup with UID preconditions and commit/generation fence;
   late workers cannot delete a healthy committed child or replacement object.

## Live prerequisites and gates

No cloud writes or live fork enablement in this lane. Later tests require an
isolated disposable namespace, Sandbox controller with verified physical
shutdown/unmount semantics, persistent source PVC, CSI VolumeSnapshot v1 driver,
snapshot-controller and matching class, quota/RBAC, independent restore volume,
policy controller and execution supervisor, inspected cold-only guest blueprint,
and verified absence of host secrets. Independent review and passing CI before
merge; live CSI/Sandbox E2E before enablement.

The test/disk-fork/preflight.py script is a no-write prerequisite and disabled-API
probe on the API_URL host, NOT successful-fork E2E. Both runtime surfaces are
covered by fake-server tests; --base is not the Pomerium app host. Full E2E is blocked on implementation: race work
and intent updates while running parent writes a marker; copy at known quiescence;
verify marker in cold child, independent volume/URLs/policy and no memory/secrets;
verify no precommit access; mutate disks independently; inject crashes/lost
responses at every stage; test hung work and post-stop timeout; replace UIDs and
race late cleanup vs commit; verify latest-intent resume and leak-free owned
cleanup. Abstract TLC/fake-server tests alone never justify enablement.
