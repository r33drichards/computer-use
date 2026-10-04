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

## Historical provider sketch — SUPERSEDED, not an implementation plan

The unprivileged subreaper-authority sketch below is SUPERSEDED by the selected protected reference design at the end. It is retained only as rejected historical context. Do not implement it as authority.

Previously proposed: investigate a pinned mcp-exec patch carried initially inside this fork worktree,
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
Dex/Pomerium configuration exists). Pre-main6ebb baseline intentionally lacked pod/PVC/
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


## P2 corrections and remaining boundary (2026-10-04)

ColdStart now refuses an installed, malformed or copied-UID fence before any
snapshot cleanup. It rechecks source UID/fence before each selected deletion,
and binds suspend, wait and final wake to the original source UID. PodSnapshot
deletes carry the **listed snapshot UID and resourceVersion**; a replacement
at that name conflicts rather than being deleted. A contradictory nonempty
origin-pod is not overridden by a matching name-hash label. These existing GKE
fields provide legacy name provenance, NOT source-incarnation/PVC ownership.
The source check and snapshot delete are still separate resources: a fence can
land after the last check, and earlier cleanup can precede a later CAS refusal.
No transaction, physical barrier or complete fork-cleanup claim follows.

Protocol CAS reads/retries (including completion and deadline abort) now require
an existing initialized ledger. Inspect also refuses missing protocol state;
legacy Fence/Intent inspection intentionally remains tolerant without writing
an initializer. Erasing an annotation destroys evidence, never certifies that
its executions ended. It must not synthesize empty receipts/tombstones or allow
a dispatch that had already observed tracked state. A first legacy lookup after
external erasure still cannot distinguish never-tracked from lost state: future
protected durable operation authority must solve that; this slice cannot enable
forking. Refused-intent audit is NOT latest ACCEPTED user/billing intent. The256
unresolved receipt cap has no safe GC. Forwarding discards permit identity and
is not PodUID-bound; upgraded streams and other post-check effects remain tails.

## Proposed protected authority: independent design review required

This is an approved DIRECTION for refinement, not approved provider code,
implemented attestation, live permissions, or replacement of the full fork goal.
No provider/controller implementation until fresh independent contract approval.
Runtime Begin remains ErrQuiescenceUnsupported and public APIs remain disabled.

### Authority placement and bootstrap

* Keep hostile guest UID1000, dropALL and allowPrivilegeEscalation=false unchanged.
  A guest-managed subreaper is useful telemetry only. Same-UID guest code can
  SIGKILL/spoof a service, inspect its environment/files/FDs, ptrace/inject where
  allowed, or change loader/module inputs. PR_SET_DUMPABLE=0 alone is rejected.
* Put the trusted admission broker and operation controller in a SEPARATE
  control-plane workload, never in a user V8 realm/module authority or guest
  container PID/mount namespace. Private V8/module authority and typed tool
  dispatch must be trusted service code outside the arbitrary guest execution
  environment; do not expose signer/control globals or guest-writable modules.
  Current guest services do not satisfy this redesign merely by adding an ACK.
* Bootstrap broker/node-attestor identities before untrusted code using a
  separately authenticated control-plane workload identity and operator-managed
  trust anchor. No key in guest PVC, environment, inherited FD, endpoint URL,
  shared filesystem, core dump or guest-accessible metadata identity. The broker
  must not fork an untrusted child containing key memory; an audited runtime
  launches clean guest processes with public opaque permit IDs only. The private
  control transport is network/namespace isolated and mutually authenticated,
  outside guest mounts/FD inheritance; public tool requests cannot impersonate it.
* Bind authenticated messages to operation/request hash, owner, sourceUID,
  PodUID, current container ID/incarnation, node/runtime identity, admission epoch,
  nonce/challenge and all issued permit IDs. Reject wrong UID/CID, replay, old
  epoch and unrequested assertions. Persist identity/epoch before dispatch and
  compare responses with the durable operation, not client-supplied fields.
  Abnormal service death/restart or unaccounted/orphan work yields UNKNOWN;
  restart does not issue a fresh empty successful drain certificate.

### Actual mechanisms required, and what remains unavailable

1. Broker CLOSE must linearize with every JS/browser/exec/file/network/VNC
   admission and every already-issued service-lifetime permit. Existing streams,
   Chrome timers, V8 callbacks, queued work and detached descendants are included.
   Graceful cancel/drain and positive actual service completion must be observable
   by trusted supervision, not a guest-origin log event. A deadline can abort the
   fork before shutdown; it cannot erase receipts. Forced termination is not an
   execution-success ACK and must retain aborted/unknown outcomes.
2. Audit OCI deployment/runtime configuration: distinct container PID namespaces,
   no hostPID/shared process namespace, no privileged guest, host-runtime socket,
   writable host cgroup or namespace-escape capability. Account for descendant
   PID namespaces and all containers/services that may write the PVC. Linux PID
   namespace-init death kills its remaining namespace descendants only under
   these containment assumptions; original exec-parent exit does not do so.
3. A trusted node/runtime observer must obtain fresh kubelet/CRI container state
   for the EXACT recorded PodUID/container incarnation, challenge-bound to this
   stop epoch, and corroborate actual runtime task/PID-namespace teardown under
   the audited containment. ContainerStatus.EXITED alone is insufficient where
   deployment could leave another writer or namespace. API404, PodNotReady,
   deletion/forceDelete, stale status, process groups/proc scans, HTTP/log done
   and lease expiry are rejected certificates. Node partition gives UNKNOWN.
   Current GKE/backend APIs have not been shown to expose this fresh trusted
   evidence; do not invent an attestation endpoint or treat a fake as proof.
4. Fence the Sandbox/controller's restart/new-Pod paths, adoption and ALL other
   read-write mount paths before stop. RWO permits multiple same-node Pods: it is
   NOT a single-writer lock. Admission/reconciliation must reject new writer Pods
   and source PVC reuse while an operation owns the epoch; privileged external
   writers are an explicit excluded trust assumption, not silently safe.
5. Trusted kubelet/CSI node lifecycle must establish flush and NodeUnpublishVolume
   /NodeUnstageVolume completion and absence of writer mounts in the actual node
   mount namespace, correlated with operation epoch and PVCUID/PVUID/volumeHandle.
   If detach is required, reconcile VolumeAttachment identity/generation and
   controller/PD fencing of the old attachment before admitting any new writer.
   A deleted VolumeAttachment or idempotent RPC response alone is not fresh
   unmount/fencing evidence. A node observer with mount/CRI access is strong node
   authority; a read-only socket bind does NOT reduce a CRI Unix socket's power.
   Prefer an audited platform-provided observer; deploying a bespoke privileged
   node agent requires separate security review, not this document's approval.
6. Only after these evidence obligations may the vetted CSI class snapshot the
   consistent whole PVC and restore a newly-owned independent PVC/cold child.
   Ambiguous create/restore responses must be reconciled by operation ownership,
   UID and immutable spec, never create a fresh fallback/shared PVC. If the
   actual managed platform cannot prove any required observation/fencing, remain
   UNSUPPORTED; forceDelete/finalizers cannot convert UNKNOWN into quiescence.

### Minimal proposed privileges (no manifests/grants in this increment)

* Backend: retain current role; authenticated owner-scoped submit/read of a new
  namespaced DiskForkOperation CRD only after API approval. No CM journal or
  guest service-account credential. Admission validates immutable owner/source
  UID/request hash and protected status; guest traffic cannot mutate the ledger.
* Dedicated namespace controller: get/list/watch operations; patch their status
  and its own finalizers; get/list/watch relevant Sandboxes and UID/RV-conditional
  lifecycle updates; get/list/watch/create/delete UID-owned child Pods/PVCs and
  VolumeSnapshots, plus narrowly scoped restore policy resources if needed.
  No generic Secrets/ConfigMaps/exec/log privileges. Any future broker identity
  delivery is separate control namespace, not a source guest secret grant.
* A separately scoped cluster observer may get/watch the relevant PVs,
  VolumeAttachments, vetted VolumeSnapshotClass and node identities. It does not
  gain writes to unrelated volumes/classes/nodes. Kubernetes RBAC alone cannot
  constrain every ownership predicate: immutable CRD admission and controller
  checks must enforce those predicates. No blanket node/proxy permission as a
  substitute for a typed trusted attestation interface.
* Preventing arbitrary same-node writer Pods requires an independently reviewed
  admission/controller integration for PVC ownership/restart fencing. This and
  strong CRI/mount observer privileges remain unavailable/unauthorized here.
  Pre-main6ebb backendRole lacked CM/Secret/PVC/pod/snapshot rights. Selected main adds source PVC expansion and capacity lease rights; no fork observer/CM/Secret grant or live application is made here.

### Durable invariants and smallest next slices

The operation CRD must hold owner-scoped idempotency tombstones, immutable
sourceUID/epoch/request digest and reservations shared with create/fork caps,
billing/quota. Reserve before pause; retry/lost response cannot double-charge or
allocate two children. User stop/delete and current ACCEPTED billing/user desired
intent need their own authoritative version, not the refused-intent audit above.
Controller recovery must compare the latest accepted intent at effect time; never
resume a source superseded by delete, stop, account loss or newer accepted action.

Record source/Pod/container and PVC/PV/attachment identities and owned snapshot,
restore PVC and child UIDs. Child remains inaccessible until durable commit;
identity, URLs, policies and capabilities are fresh and host OAuth/control secrets
never cloned into guest data. Cleanup deletes only resources still owned by this
operation at observed UIDs/generations, distinguishes pre/post-commit, and must
not delete a committed accessible child on lost response/restart. Child writes
and deletes must not affect source PVC, and source deletion must not invalidate
child data. Parent/source intent and reservations reconcile after every restart.

Next smallest slices, each gated by independent approval: (a) schema/invariants
and deterministic durable-operation reconciliation without physical effects;
(b) protected broker/typed provider contracts and falsifiable containment/epoch
refinement tests, still disabled; (c) separately approved controller/node/storage
observation on an isolated test platform; (d) end-to-end owned CSI independent
restore/access/cleanup after actual proof. No step removes the full fork goal.

Falsification matrix: guest SIGKILL/ptrace/ENV/FD/LD/module spoofing; broker crash
before/after admission and ACK, detached/setsid/double-fork and orphan/restart;
replayed nonce/epoch or stale PodUID/CID; node offline plus forceDelete and stale
CRI/status; unknown mount/orphan attachment or concurrent same-node RW Pod;
old/new source/snapshot/PVC UID name reuse; ambiguous snapshot/create/restore/
commit/cleanup responses; accepted stop/delete/billing changes racing resume;
controller death at every durable transition; independent child write/delete.
Each uncertain case must refuse snapshot/access/resume or reconcile safely, not
substitute parent-done, lease expiry or a manufactured signing certificate.

Inventory assumption only: browserjs-zonal pd.csi.storage.gke.io/pd-balanced,
WaitForFirstConsumer/Delete, RWO5Gi. No vetted snapshot class or live CSI restore,
node/runtime/storage certificate or isolation/fencing test has been established.
Formal28 historical outcomes are separate bounded abstractions, not refinement
or production proof of this proposed authority or current P2 code.


## Selected concrete reference mechanism after main55ba20b integration

Selection is SOURCE DESIGN ONLY: no implementation, deployment, trust grant or
GKE eligibility. It supersedes the historical subreaper-authority proposal.
The concrete source audit is REFERENCE-SOURCES-main55ba20b.json: immutable public
commits, full-file SHA256 and extracted interface/implementation evidence.
Older MECHANISM-SOURCE-20261005.json is explicitly historical comparison, NOT
selected versions. These are API/source observations, not deployment certification.

Selected custom-built isolated reference node: kind0.33.0, Kubernetes1.37.1,
containerd2.4.1/runc1.5.2, CSI1.11.0 interfaces, external-snapshotter8.6.0 and
csi-driver-host-path1.18.0. Full commits in the audit artifact pin this selection;
we do NOT assert an off-the-shelf kind node image contains this combination.
A future operator builds/reviews the image, records kernel/OCI/cgroup2 settings
and image digest, and verifies version/security compatibility before tests.
Host-path CreateSnapshot is explicitly a tar-directory fixture in audited source:
it tests idempotency and independent restore DATA only. It is NOT a PD snapshot,
block flush guarantee, cross-node fencing or production whole-PVC consistency.

### New protected components and concrete interfaces they must implement

None of the following new source components exists yet. Proposed locations in
THIS fork, after independent approval: backend/internal/forkcontrol (authority,
CRD clients/controller/protocol), images/fork-guard (root node adapter/CRI+CSI
frontdoors), and a protected tools gateway independent of guest-writable modules.
These paths are responsibilities, not existing API names or deployed guarantees.

1. **Authority**: a distinct control-namespace service owns a namespaced
   SourceControl and DiskForkOperation CRD. SourceControl is the single durable
   CAS record for accepted desired intent sequence, owner billing revision,
   immutable sourceUID, admission epoch, broker incarnation, issued permit IDs,
   writer-Pod/container inventory and pending effect receipts. Operation stores
   owner/request-hash idempotency, shared create/fork reservation and all child/
   storage UIDs. Separate actors serialize each source and the owner's capacity/
   billing reservations; no broad ConfigMap journal. All user/billing/delete
   changes enter this authority before they are accepted for physical action.
2. **Tools gateway**: JS/V8 module authority, browser control and file/network/
   exec/VNC admission stay outside the hostile exec guest. Private modules/control
   are not guest-writable. Arbitrary exec runs only in separate guest containers,
   not the trusted browser/V8 gateway namespace. Every async task, timer, stream
   and upgrade has a durable permit/lifetime; HTTP closure does not release it.
   Existing pinned mcp-exec parent-done contract cannot supply this API; it needs
   an independently reviewed gateway/shim patch in this fork, not a renamed ACK.
3. **Node guard**: a NEW authenticated CRI frontdoor between kubelet and the
   raw containerd socket. The raw socket is runtime-administrator authority even
   if mounted read-only. Only the operator-controlled root guard can open it.
   Frontdoor gRPC method dispatch must enforce identities AND method allowlists;
   no generic proxy/dial/exec input. Kubelet gets its own authenticated channel;
   controller gets only RegisterWriter/InstallGate/StopBound/ObserveBound methods.
   Guest cannot connect. RunPodSandbox, CreateContainer, StartContainer, ExecSync,
   Exec/Attach and equivalent direct paths for protected sources are checked at
   effect time against the installed sourceUID/epoch/intent and permit inventory.
   Exact CRI paths come from audited runtime/v1/api.proto, not invented kubelet
   certificates. Uncontrolled alternate runtime endpoints make fork unsupported.
4. **CSI frontdoor**: a NEW guarded driver socket registered instead of the raw
   source driver endpoint. It intercepts NodePublish/Unpublish/Unstage and
   ControllerPublish/Unpublish/Expand/CreateSnapshot for protected handles; validates
   identities, source/PVC/PV bindings and current effect ticket before dispatch.
   It records exact trusted request/response plus mount inventory. Caller never
   supplies arbitrary host paths: paths are bound to trusted kubelet publish
   records, PodUID and PV/volumeHandle. No open gRPC passthrough to guest.
   Existing CSI RPCs do not themselves implement this admission or evidence log.

### Private bootstrap, wire authentication and restart algorithm

Operator installs a control CA/public trust anchor and scoped workload identities
in the separate control namespace/node-root mount, before any guest code. Signing
keys are in private root/controller memory/secret mounts NEVER projected into
source PVC, guest env, inherited FDs, shared proc/mount namespace or endpoint URLs.
A node guard does not fork a guest with signer memory: containerd/runc is a
separate launch boundary. Private Unix sockets are root0600/SO_PEERCRED checked;
network links use mTLS with exact controller/node UID identities and server name.
A method/owner/node allowlist rejects a valid certificate for the wrong role.
Guest network policy and mounts exclude these endpoints; that isolation needs
adversarial deployment tests, not trust in a port number or dumpable flag.

Every custom request carries operationUID, sourceUID, epoch, acceptedIntentSeq,
nodeUID, brokerBootID, nonce, expected PodUID/containerID/createdAt and volume
identity set. Canonical protobuf bytes/signature and mTLS identity bind these
fields; receiver rejects unknown fields affecting meaning, wrong role/owner,
replayed nonce, old incarnation and mismatched durable request digest. Nonces and
results are journalled before ACK; lost response replays the SAME result, not a
second action. Keys rotate only with durable incarnation/epoch rollover.

On broker/guard restart: default CLOSED, mark previously active scopes UNKNOWN,
read the durable inventory, reconcile actual runtime/mount incarnations, reject
old response nonces, and reinstall deny gates on ALL nodes before permitting
new admission. A process memory cache or fresh empty ledger cannot reopen it.
Partition or missing journal/observer denies effects. No lease expiry proves
execution completion. Root observer writes observation records; controller signs
an eligibility decision only after validating all records, never guest telemetry.

### Concrete stop and storage evidence, not abstract termination oracles

Audited CRI StopContainer is idempotent and forces kill after timeout; current
containerd stop code sends SIGKILL to its task and waits. That alone is NOT a
successful graceful drain. Audited runc Signal comments tie descendant SIGKILL
to own PID namespace/init semantics; this does NOT transfer automatically to
GKE runsc/gVisor. Reference guest must have private PID namespace, no hostPID,
shared namespace, privileged escape or writable ancestor cgroup/runtime socket.
Guard binds CRI ContainerStatus metadata, sandboxID, containerID/createdAt to
registered PodUID, root-owned cgroup inode/generation and namespace identity.
Status is cross-checked with containerd task wait/state and root namespace/cgroup
observations; proc scans/status alone are rejected. Kernel cgroup2 ownership and
no migration/alternate launch paths are REQUIRED; not an inference from EXITED.

For a future per-exec shim, root-owned sub-cgroups and atomic pre-exec placement
(e.g. audited clone3 CLONE_INTO_CGROUP/runtime integration) track descendants;
only a CLOSED scope with no further launch capability and verified empty kernel
scope can release its permit. Guest subreaper reports remain telemetry. This
runtime integration is missing and must be audited before code approval. All
long-lived writer service scopes must also drain/close; per-exec emptiness is
insufficient while Chrome/V8/VNC or file/network service permits remain issued.
Abnormal death/SIGKILL/restart yields aborted/UNKNOWN work, not successful ACK.
If graceful service completion cannot be independently established, abort fork.

The authority first CAS-closes admission, then gets installed-gate receipts from
all controlled nodes and driver frontdoors. API admission denies new/adopted Pods
using the protected PVC, but CRI and CSI frontdoors ALSO check at effect time to
cover already-admitted kubelet restarts and NodePublish. RWO same-node other Pods
are writers, not excluded by the access mode. Inventory must include all of them;
a foreign/uncontrolled writer aborts, never silently kills somebody else's Pod.

After actual drain/stop, root observer correlates kubelet-requested successful
NodeUnpublish/NodeUnstage with the actual target/staging mount namespaces and
open writer scope inventory, PVCUID/PVUID/volumeHandle and node/attachment epoch.
Root-owned source filesystem syncfs before unpublish, successful driver semantics
and absence of live holder namespaces/FDs are separate evidence obligations.
The directory fixture does not prove block-device flush. If storage requires
ControllerUnpublish/detach, bind VolumeAttachment UID/generation and fresh driver
backend fencing receipt to the SAME handle/epoch. API deletion of that object is
not proof. Node partition/forceDelete cannot make a missing receipt successful.
No snapshot after uncertain mounts, old writer, stale CID or unobserved stop.

### Accepted intent and cross-resource effects

Root effect application is serialized with acceptance by the authority/guard
actor, not merely a precheck followed by IO. Each effect ticket is durable and
one-shot, with expected acceptedIntentSeq/billing revision; issuing a ticket does
NOT let it survive a newer accepted stop/delete. A new intent invalidates permits
at guards and settles/cancels in-flight conflicting effects before its accepted
ACK; if an effect outcome/guard is unreachable, record Pending/UNKNOWN, not an
accepted action plus a stale resume. This acceptance semantics must be explicitly
approved for API/billing integration; current refused-intent audit and current
billing webhook queue do not already implement it. Global owner billing changes
must install deny barriers on affected sources before authoritative acceptance;
if product semantics cannot support that ordering, resume stays unsupported.
No claim of an atomic Kubernetes/Stripe/PD transaction is made.

Every shared reservation/idempotency and latest accepted desired action is checked
in this authority, not guest fields. Snapshot creation, independent restore PVC,
child policy/identity and durable access commit reconcile lost responses using
immutable request/owner/UID digests. Cleanup is pre/post-commit aware, uses observed
UID/generation preconditions and cannot delete a committed child after restart.
Source delete/new accepted intent supersedes resume; child write/delete and source
removal independence must be demonstrated, never assume name-owner equivalence.

### Minimum authority and production transition decisions

Existing baseline claims above are historical: selected main adds PVC expansion
and capacity-lease source/RBAC work, preserved in this source-only merge. It is
NOT live-applied here and supplies no fork observer/CRI/CSI/Secret/CM authority.
New controller needs only named operation/SourceControl CRUD/status/finalizers,
UID-conditional relevant Sandbox/Pod/PVC/VolumeSnapshot lifecycle and read-only
PV/VolumeAttachment/class/node inventory. Observer root-runtime/mount rights are
explicitly STRONG node administrator trust, isolated from backend and guest;
not 'least privilege' by a readonly socket mount. No broad CM/Secret/node-proxy
journal grant. Admission/ownership enforcement must constrain RBAC's broad verbs.

Production GKE/gVisor remains MANDATORY, UNSUPPORTED until: (1) select and pin
actual GKE/runsc/PD CSI versions and audited runtime/CSI interfaces; (2) obtain
operator decisions for a managed node observer or separately audited root guard
and exclusive frontdoors/all restart/mount paths; (3) prove runsc sandbox/sentry/
gofer teardown and writer handle closure, not runc assumptions; (4) vet a real PD
VolumeSnapshotClass and flush/unpublish/detach/fencing semantics under partition;
(5) review bootstrap/CRDs/accepted-intent/billing and all-path integration; (6) run
isolated node-offline/forced-delete/replay/guest-spoof/crash/restart/same-node writer
and independent restore/write/delete/cleanup tests against actual versions.
If managed GKE cannot expose required authority, select an operator-approved
supported node/control architecture; do not manufacture a certificate or abandon
production goal in favour of tar-copy reference results. No component/privilege
implementation or physical enablement is authorized by this source selection.

Integration note: main disk growth now refuses an installed fence before PVC access, patches the observed PVC UID/RV and binds final source CAS to original UID. This does not make the source check/PVC effect atomic. Main capacity lease, tool-event recording and webhook policy work are retained, not treated as execution completion or fork reservation proof.

Selected wire/identity details for the NEW implementation: Go TLS1.3 mutual TLS
plus crypto/ed25519 response signing; crypto/rand32-byte challenges, never a guest
seed. URI SAN role identities spiffe://fork-control/controller/<controlUID> and
spiffe://fork-control/node/<nodeUID> are exact allowlist entries, not wildcard
trusted clients. Operator offline control CA provisions server/node certificates
and node signing-key/public-key bindings before guest launch. Root node key files
live in node-private /var/lib/fork-guard with root0600/no guest mount; broker keys
are private control-namespace mounts, service-account automount disabled for guest.
No generic backend Secret read is required; any automated issuer is a separately
reviewed replacement, not implicitly Kubernetes' kubelet-client signer.
Signature input is domain 'disk-fork-observation-v1' plus method/direction and
length-delimited deterministic protobuf payload, rejecting unknown fields, over
all identity/epoch/nonce/intent/volume fields. Trusted receiver durably records
nonce-use/result before ACK; replay may retrieve identical prior result, never
execute a second effect. Rebuilt nodeUID/key/brokerBootID invalidates old sessions.
Actual custom protocol/issuer/proxy source is not yet written or reviewed; these
selected details are falsifiable implementation requirements, not existing APIs.
