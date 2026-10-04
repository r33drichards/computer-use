# Disk-snapshot fork: pre-implementation TLA+ model

**Historical pre-implementation scope:** formal-spec files only. No backend, deployment, credentials, branch/commit, or cloud mutations. Worktree: /data/chrome/home/computer-use-fork-work, feat/disk-snapshot-fork at 46225c5b9c5b0581575aaa6e95b979c0d9efa574. CONTRIBUTING.md was read; no AGENTS.md was found in the worktree or its ancestors. The separate computer-use/default-desktop-keyring work must remain separate.

The user selected **automatic controlled pause of a running parent**, not a stopped-only release. Disk state is copied into an independent child PVC/session, cold-started with a fresh control identity. Pi conversation is copied separately; there is no merge.

## Model and protocol

DiskFork.tla uses one durable record to keep the atomicity assumptions visible. Replicas each admit at most one request; requests progress idle -> admitted -> executing -> done. Expired is STILL executing: a proxy lease is not proof that an upstream process/background job has stopped. Admitted work may begin executing after the gate; newly admitted work may not.

Two operation slots compete for a per-source exclusive gate. Two idempotency keys can select either slot. A durable key reservation prevents a second slot from accepting the same key; Replay returns the same operation without allocating a child. Pending operations count against an atomic owner reservation cap. Authentication/same-owner validation is an explicit precondition of Submit; the model has one authenticated owner, not an implementation of JWT/admin/scopes. MaxChildren is available child slots after charging the source and existing sessions; cross-source creates must use the SAME owner reservation mechanism.

Operation stages:

    absent -> pending -> draining -> stopping -> snapshotting -> ready
           -> provisioning -> starting -> succeeded
    active -> cleanup -> failed/cancelled
    succeeded + child deletion -> deleted

Gate competes atomically with request registration. Drain waits for BOTH admitted and actually executing work. Graceful stop precedes unmount. Snapshot becomes immutable at the quiescent data value; only then may the source gate/protection release. Release checks CURRENT user/billing/deletion intent rather than captured intent. Clone assigns a fresh disk/control identity and snapshot contents; Commit models disk bound, cold pod ready, policy installed, and external access publication. Child deletion before commit cancels it. Source deletion waits for its protection and physical quiescence. A fork already holding the gate may finish its accepted point-in-time copy after source deletion intent, without resuming the source; pending unstarted forks cancel. This behavior is a proposed API rule, not an inferred current backend behavior.

Fail may occur in each active stage. Durable state survives a worker crash, then Recover resumes reconciliation. Cleanup deletes only resources whose current UID matches the recorded operation-owned UID, never a healthy committed child. ReplaceUID simulates an out-of-band delete/recreate under the same child resource name; foreign UID 2 is left untouched. Leaked foreign objects require operator diagnosis, not unsafe cleanup. Source and child protections are distinct. Failed/cancelled operations leave no private source gate; cleanup/release restores the parent's desired running state only if current intent permits.

The data value counts completed source writes (one per replica), making a small finite content abstraction. Snapshot value never changes; initial child contents equal it. Post-commit child writes are omitted; independent physical disk IDs are the refinement requirement, not a proof of CSI implementation.

## Checked safety predicates

- TypeOK: bounded control/request domains and content count (not a complete Kubernetes schema).
- SnapshotSafe: every snapshot was taken with no executing/admitted work and no mounted parent disk.
- NoNewAdmission: no request registration linearizes after a gate is installed.
- IndependentDisks / FreshIdentity: child disks and control identities differ from the parent's and each other; child starts cold, not from PodSnapshot memory.
- CorrectContents: initial child content equals the immutable quiescent snapshot.
- CommitBeforeAccess: no child externally accessible before commit or after deletion intent.
- LatestIntentWins: no automatic resume event against current stop/billing/delete intent.
- Idempotent / SameOwnerAndCap: unique durable key reservation, owner precondition, reserved-child cap.
- Protection: a gated source stays protected/live; an initializing child is protected.
- CleanupSafe: cleanup never deletes a wrong-UID resource or healthy committed child.
- FailureSourceSafe: a terminal failed/cancelled fork does not retain its source gate.
- ExecutingMounted: supposedly completed unmount cannot coexist with executing work.

Some predicates are deliberately guaranteed by action construction (owner validation, ID allocation, resume guard, UID-delete guard). TLC checks protocol interactions under those choices; it does NOT prove the real backend supplies those choices. History flags record unsafe admission/resume/deletion events; snapshot safety is recorded at snapshot creation, not tested against a later resumed parent.

## Bounds, fairness, and actual results

All final claims below use ONLY the published-digest jar in toolchain.json, SHA256 c2fe4e56e43bde19f213b4a7e441d037297fda733e503579623e859b79348239. Runtime: TLC2 Version 2026.10.04.025638 (rev: 1813307), Temurin OpenJDK 17.0.13+11. One worker, -Xmx512m, -XX:+UseParallelGC; per-check deadline 180 s except the final one-replica/two-fork liveness check at 60 s. No symmetry reduction or state constraint was used; each successful run exhausted its configured state graph.

| Config | Bound | Result | Generated / distinct | Depth |
|---|---|---|---:|---:|
| atomic.cfg | 2 replicas, 2 forks, 2 keys, cap 2; no faults/intent update | exit 0, safety pass | 731,727 / 158,657 | 29 |
| cap-one.cfg | same, cap 1 | exit 0, safety pass | 204,327 / 55,529 | 29 |
| faults.cfg | 2 replicas, 1 fork; 1 intent update, 1 worker crash, nondeterministic failure/UID replacement | exit 0, safety pass | 192,203 / 45,807 | 24 |
| liveness.cfg | 1 replica, 1 fork; faults and 1 intent update | exit 0, safety + temporal pass | 36,642 / 10,425 | 21 |
| liveness-two-forks.cfg | 1 replica, 2 forks; no faults/intent update | exit 0, safety + temporal pass | 116,022 / 28,973 | 26 |
| liveness-races.cfg | 2 replicas, 2 forks; no faults/intent update | **timeout at 180 s, NOT a pass** | last progress 500,022 / 116,249; queue 13,356 | last progress 23 |
| unsafe-check.cfg | 2 replicas/2 forks, faulty check/register | exit 12: NoNewAdmission counterexample | 904 / 514 | 5 |
| unsafe-lease.cfg | 2 replicas/2 forks, expiry mistaken for quiescence | exit 12: ExecutingMounted counterexample | 36,418 / 12,847 | 8 |
| unsafe-lease-snapshot.cfg | same, omit earlier ExecutingMounted check to expose snapshot violation | exit 12: SnapshotSafe counterexample | 94,723 / 29,776 | 9 |

Logs: traces/*-verified.txt contain checker command, hash, state counts, full counterexamples and -coverage 1 output. traces/coverage.json extracts raw TLC action coverage counters (not percentages). traces/verified-results.json is the consolidated result index.

The full combination of 2 replicas + 2 forks + faults + intent updates is NOT exhaustively checked. Its initial historical run was interrupted by remote session restart; all-faults-races.cfg preserves that intended bound. This decomposition does not prove arbitrary population, repeated requests/crashes, two simultaneous failures, or more than one intent change. Do not increase MaxEpoch without making deletion intent absorbing and revisiting the temporal source-deletion property: the current bound permits one superseding intent, not stop/run/delete reversals.

FairSpec explicitly assumes weak fairness for worker recovery, each operation's reconciliation steps, execution/completion of each admitted request, user-intent application/resume, and source deletion. Crashes and intent changes are finitely bounded. Completion means each accepted operation eventually reaches succeeded/failed/cancelled/deleted, not necessarily success. SnapshotCleanup means committed operations eventually remove temporary snapshots. SourceDeletion is checked only in the one-operation lifecycle bound. No fairness on submission is assumed; a fork is not promised to happen unless submitted.

**Availability assumptions:** control plane/controller/CSI eventually answer; graceful shutdown and unmount eventually succeed; admitted upstream/background work eventually terminates; worker eventually recovers; finite new intent changes; physical provisioning/readiness eventually resolves or reports failure. An infinite background job, network partition, stuck detach, or unrecoverable CSI error can defeat liveness. A lease timeout must NEVER authorize a snapshot; timed-out forks fail/reconcile rather than silently copy a running filesystem. This conservative model can retain a cleanup gate until outstanding work actually ends. Safe early abort while the source remains mounted/running would require an additional modeled transition before implementation.

## Counterexamples and fixes

Verified stale-check trace (5 states): Init -> Begin(1) checks the ungated source -> Submit(1,1) -> Gate(1) -> Register(1) trusts the stale check and admits work after the gate. Fix: atomically register admitted work against the same durable source version/fence as gate acquisition, before any upstream forwarding. An in-memory mutex or check followed by registration is not sufficient across replicas.

Verified expiry trace (8 states): Init -> Begin -> Execute -> Expire -> Submit -> Gate -> Drain ignores expired work -> Unmount. The request is still executing. The 9-state variant continues to Snapshot, recording safe=FALSE. The unsafe model's Unmount represents falsely declaring termination/unmount based on lease evidence; the trace is precisely the invalid physical refinement. Fix: track actual execution independently of renewable proxy leases, drain/cancel it with reliable evidence, gracefully terminate the pod, and confirm its disk is unmounted before requesting a CSI snapshot. An expired annotation is only failure-detection evidence, never quiescence.

## Implementation refinement obligations (not backend changes)

1. **Linearization:** Begin/Gate must map to a fail-closed durable source CAS/fence. Every MCP/exec/browser request, upload, file transfer and mutating VNC/background path must register before dispatch. Existing sessions/activity.go Mark is a coarsened merge patch; idle Tracker retries writes. proxy/proxy.go upload currently looks up Running before Flight. They do not meet this obligation.
2. **Actual execution:** include work surviving request cancellation or backend crash. Close viewers/streams during drain. Drain cannot use only local call counts or expired replica marks. Cancellation needs acknowledged upstream termination or complete graceful pod exit.
3. **Multi-object writes:** the model's single record is NOT a Kubernetes multi-object transaction. An owner reservation ledger, durable idempotency record, source CAS barrier/finalizer, and operation state need explicit fencing, retry, recovery, and safe ordering. A newer user/billing/delete intent must linearize against resume, not a check-then-Patch race. Pending normal creates and forks must share cap/billing reservations across sources.
4. **Physical stop:** Suspended desired mode is not evidence of absent pod, successful Chromium shutdown, flushed filesystem or unmount/detach. Forced shutdown or ambiguous termination must fail the fork; never silently downgrade to crash consistency. Model Unmount must refine to verified physical evidence.
5. **Immutable copy:** discover the source PVC by captured Sandbox/PVC UID and controller metadata, not a guessed name. Wait for VolumeSnapshot readyToUse, validate restore size, create a new RWO PVC with snapshot dataSource and child ownership. WaitForFirstConsumer needs the guarded child pod to be scheduled; waiting for Bound while permanently suspended deadlocks. No source PVC reuse, PV binding fields or shared mount.
6. **Identity and policy:** render a fresh trusted blueprint with new ID/URLs, approved same size/images, same actual owner, independent SessionPolicy with copied effective restrictions (freeze policy version during capture). Never bulk-copy source PodSnapshot annotations, SandboxClaim ownership, restore hashes/node pins, runtime service tokens, tickets, URLs, arbitrary env/metadata, or control-plane secrets. No warm pool adoption.
7. **Commit and cleanup:** initialize in a protected inaccessible state; install policy and verify disk/cold readiness before access publication. Record every resource name AND UID before destructive reconciliation, use UID preconditions, handle partial Create success/lost responses, and never delete healthy committed children due to later cleanup errors. Source protection ends only after immutable snapshot readiness; child protection ends only on commit or completed cleanup. Source deletion must not cascade-delete in-progress snapshot/operation before restoration finishes.
8. **Idempotency:** owner/source UID/request-hash scope, deterministic operation names, duplicate requests return the same durable child; conflicting payload returns 409. Model keys never expire. Implemented retention/key GC and authorization revocation require additional reasoning and tests.
9. **Failures:** map every reported Kubernetes/CSI failure into durable stage/retry/cleanup state; restart does not forget gates/resources. Eventual failure classification, orphan auditing, disk/snapshot billing, and no manual deletion of unrelated resources are obligations.

## Interface proposal only

POST /v1/sessions/{id}/fork mirrors POST /api/sessions/{id}/fork. Optional JSON name and optional Idempotency-Key. Default controlled pause is automatic; no caller owner/size/storage class/snapshot ID/policy/image override. Return 202 + operation ID, source ID, preallocated child ID, status URL. Mirrored GET /sessions/{source}/forks/{operation} is owner-authorized even after source deletion. No stop/resume promise overrides a newer user/billing/deletion intent.

Require unbound sessions:write token and fresh actual-owner equality, including browser-authenticated admins; source-bound tokens cannot create an independent child. GET needs sessions:read. Preserve 404 for missing/other-owner source; 400 input, 403 scope/bound token, 409 conflicting key/cap/unsafe lifecycle, existing 402 billing refusal, 503 unavailable fork prerequisites. Pending children count toward cap and disk charges; recheck current billing permission for child start and parent resume. Same-owner/same-size only, no credential export endpoint.

Copy whole persistent /data PVC, including Chromium profile/logins/home/keyring files; do not copy memory. Cold child keyring may need manual unlock. Pi conversation copy is a separate authorized client operation. Intentionally copied on-disk secrets must be disclosed; API capabilities/tickets should be regenerated under the child identity. Source branch keyring changes are NOT part of this work.

## Deployment evidence and live prerequisites

Repo evidence at this worktree: infra/main/cluster.tf enables gce_persistent_disk_csi_driver_config; deploy/gke/session.yaml declares browserjs-zonal with pd.csi.storage.gke.io, pd-balanced, RWO-compatible zonal provisioning, WaitForFirstConsumer and Delete reclaim. deploy/gke/blueprint.yaml mounts the 5Gi data claim. Existing deploy/gke/snapshots.yaml is PodSnapshot only: it excludes PVC contents and groups restore by Sandbox hash. Existing backend RBAC does not supply CSI VolumeSnapshot/PVC management. This is configuration evidence, NOT current cluster discovery.

Unverified: snapshot.storage.k8s.io/v1 CRDs/controller, matching VolumeSnapshotClass/driver with Delete deletionPolicy, CSI IAM/quotas/zone availability, restore dataSource support, Sandbox admission allowing explicit restored PVC or claim-template dataSource, actual graceful stop/unmount evidence, UID/finalizer behavior, cleanup of cloud snapshots and disks, keyring/browser login cold restore, regenerated service capabilities, billing correctness. Require live snapshot -> independent PVC -> cold child -> concurrent independent writes -> independent deletes smoke tests, interrupted-operation recovery tests, cross-replica barrier/admission tests and least-privilege RBAC tests before enabling anything. Backend must not gain Secret or PV/VolumeSnapshotContent mutation permissions.

## Reproduce and provenance

See toolchain.json. Official jar URL: https://github.com/tlaplus/tlaplus/releases/download/v1.8.0/tla2tools.jar. GitHub release 25926686, asset 609012765, published digest c2fe4e56e43bde19f213b4a7e441d037297fda733e503579623e859b79348239, tag commit 1813307068bbc5759a441df820f3f548948d6b7a. Final download endpoint is recorded without its temporary signed query. Asset creation 2026-10-04T03:00:49Z, update 03:00:50Z; release publication/update 03:02:01Z. Reason for replacement/reupload is unknown.

Initial bytes from the same release URL were 4,500,434 bytes, hash b3e56ba18c65abd22e35755739963000f22e770279841d364699c31951ede70a, runtime version 2026.10.03.231403. No published digest/asset metadata was captured for that vanished build; original results are unauthenticated historical evidence ONLY. A remote restart removed /tmp and interrupted larger runs. Redownload was 4,500,445 bytes and failed original checksum; execution stopped until supervisor explicitly authorized the published-digest re-pin. Historical logs live in traces/historical-unverified/ and are never used for final claims. Same revision prefix is not byte equivalence.

Checked jar and JRE archive/extraction persist outside the repo in /data/chrome/home/.cache/disk-fork-tlc. JRE official pinned URL/checksum are recorded in toolchain.json; SHA256 4086cc7cb2d9e7810141f255063caad10a8a018db5e6b47fa5394c506ab65bff matched publisher checksum. Direct java originally failed because /lib64/ld-linux-x86-64.so.2 is absent in this Nix container; the harness explicitly invokes the installed Nix glibc loader. No system install, privilege change, security-policy workaround, or mismatched-jar execution occurred.

From this directory:

    python3 check.py atomic cap-one faults liveness
    DISK_FORK_TIMEOUT=60 python3 check.py unsafe-check unsafe-lease unsafe-lease-snapshot liveness-two-forks

The harness verifies BOTH archive hashes before EVERY JVM invocation. Default -workers 1, heap 512MiB, timeout180; optional DISK_FORK_TOOLS and DISK_FORK_LOADER identify installed tool paths, not bypass hashes. Deadline aborts are not passes. The two-replica temporal scenario can be reproduced separately with python3 check.py liveness-races, but its 180-second run did not finish; do not present it as checked. check.py records per-run commands and append-only summaries; negative variants intentionally return TLC exit12. All production paths are unchanged.


## Resumed independent delivery checks

The delivery lane independently reran current source/config hashes using the
published pinned tools: atomic, cap-one, faults, liveness and liveness-two-forks
all exited 0 with exhaustive bounded graphs. Fresh immutable logs are selected
by delivery-results.jsonl, each with source/config/runner/tool hash bindings.
Reproduce: python3 spec/disk-fork/delivery/check_v1.py atomic cap-one faults liveness liveness-two-forks
Current DiskFork.tla SHA256: 04257d5ba906c1b2ff2542634ee98fa50fad5f6dabdfa60117e27772594d3609.
The original runner and historical logs are unchanged; use delivery/check_v1.py
for worktree-confined states and unique logs, not v1/check.py which overwrites
historical paths. The 2-replica liveness-races timeout and broad all-faults
interrupted attempts were NOT rerun and remain non-passes. v2 independently
reran all three legacy admission/lease mutants against byte-identical DiskFork.
These results do not establish v2 model composition or production correctness.
Backend changes are an unavailable staged admission foundation, not a live fork.
