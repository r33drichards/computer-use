# E37 webhook precheck + reference wire contract (draft only)

Initialc9 CI is historical after this patch. Explicit scoped mutation registrations now cover PUT/DELETE webhook, PUT/DELETE policy and PUT management after ownership/token scope authorization and before installed-fence precheck. GET is unaffected. This is NOT an atomic Sandbox/SessionPolicy effect-time barrier.

Actual app/API-host six-case regressions cover gate/malformed/copied UID, repeated PUT/DELETE refusals, zero operator-validation HTTP and policy patches, GET/read/owner/scope/status and signing-secret preservation after unfenced retry. Existing full suite also exercises patch-conflict/latest-secret retry and operator failure behavior.

Current full validator daaf6f8c-64fd-40b4-bf5b-bd7857e4dd46 completed0: tidy, vet ./..., race ./... CPU1/memory384MiB/p1 under actual bounded shared lock.458 top-level passes/816 including subtests/20 tested packages;184 backend bindings unchanged inclgo.sum. Fresh E37 artifacts; old183/281/3 and TLA28 reports retained as historical, not current proof.

Contract adopts concrete OwnerControl/SourceControl/operation fields, root-private durable SQLite WAL and effect states, typed canonical signed envelope, nonces/incarnations, private Exec/Attach/PortForward capability preparation and later redemption, external enrollment/atomic containment, owner-wide pending-vs-accepted barriers, crash/partition/late cleanup/access serialization and positive SnapshotEligible conjunction. These are PREIMPLEMENTATION approval obligations, not implemented certificates or live privileges. New component absence alone is not design rejection; enforceable contract requires fresh review.

No provider/controller/gateway/observer implementation, new secrets/privileges or enablement. Begin unsupported/APIs disabled. Full GKE/gVisor/PD remains mandatory UNSUPPORTED pending actual protected interfaces/versions/driver/fencing/independent restore proof. Current public CI and independent review remain gates; no merge/deploy authorization.
