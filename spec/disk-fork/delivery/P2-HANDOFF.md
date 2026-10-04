# P2 corrections: limited draft, full fork still unavailable

PR171 initial foundation at6ebb5cd remains historical evidence, not this revision's pass.

* ColdStart checks installed/malformed/copied-UID fence before any prune; rechecks original source UID/fence before selected deletes, binds suspend/wait/wake to original UID. Snapshot deletes use listed UID/RV; contradictory origin-pod is not overridden by name hash. Cross-resource check-to-delete race and legacy name-only source provenance are NOT solved.
* Every barrier mutation read/CAS retry requires an initialized ledger; protocol Inspect refuses loss. Legacy Fence/Intent inspection stays tolerant. No recreated receipt/tombstone ledger or forward after observed tracked-state loss. Never-tracked vs externally erased before first legacy read still needs protected durable authority.
* Deterministic all-mutator removal-between-reads/conflict regressions; snapshot-enabled installed/malformed/copied gates; source replacement before delete/at CAS/after delete and snapshot UID replacement; failed+timeout Waker fallback through embedded policy Gated; actual proxy no-dispatch regression.
* Contract now specifies separately trusted outside-guest broker/controller, private bootstrap, namespace/OCI/CRI identity and real CSI/PD writer-fencing obligations, least-privilege operation CRD, UNKNOWN/replay/orphan handling and hostile falsification matrix. Approved direction ONLY, fresh independent design approval before provider/controller code. No new grants, signing mocks, host secrets or physical implementation.

Validation (CPU1/GOMEMLIMIT384MiB/p1, shared actual EXEC flock, bounded test timeout30s):
-03c0812e-4c2d-4db8-92ad-5536a5aa67f2 completed0: full diskfork/sessions/proxy tests, API/auth DiskFork tests. P2-VALIDATION.json holds unchanged source hashes.
-126bcbbc-530c-42b2-addc-f0ce783fcb27 completed0: vet five packages; race ForkFence|LedgerRemoval core/sessions/proxy; go mod tidy. P2-CHECKS.json holds unchanged source hashes; no go.mod/go.sum changes.
- Earlier owned b782e344-1a89-483a-88a6-a0b91a0af089 was cancelled with supervisor approval and confirmed cancelled: test reactor reentered Fake.Invokes mutex. Test-only correction uses Tracker.Get, without weakening race/precondition checks. No shared PID/lock/cache deletion.

Prior28 formal outcomes/reports untouched, separate bounded models NOT production proof. Prior6ebb public CI success does not cover this revision. Current full public CI remains pending until parent settles the dependency barrier; no merge/feature acceptance.

Begin remains ErrQuiescenceUnsupported; APIs501, no initializer/pause/enablement. All-route physical quiescence, accepted user/billing/delete intent authority, reservations/caps/quota/idempotency, independent CSI restore/access-commit/UID cleanup/live evidence remain mandatory future work.
