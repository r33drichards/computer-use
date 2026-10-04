# Disk fork v2 — separate bounded protocol models

These are abstract separate models, not a composition proof, refinement proof,
CSI implementation proof, or proof that production forwarding is gated.
The backend staged slice remains unavailable. There is no memory clone or merge.

## Current independently executed evidence

The resumed backend lane independently ran all 23 focused configs. Supplied
tools were verified before each JVM: jar SHA256
c2fe4e56e43bde19f213b4a7e441d037297fda733e503579623e859b79348239;
Temurin archive SHA256
4086cc7cb2d9e7810141f255063caad10a8a018db5e6b47fa5394c506ab65bff.
toolchain.json records provenance. One worker, 512 MiB heap, 180s per config;
no symmetry or state constraint. LATEST.json selects only fresh executions of
the current runner and source/config hashes, never historical mixtures.
Each trace header records input/tool hashes, command, timeout and run ID.
results.jsonl records return code, completion, unchanged inputs and coverage.
COVERAGE.json contains fresh action counters, not production/branch coverage.
Prior LATEST/COVERAGE bytes are retained as .before-delivery; old logs remain.

9 correct configs exited 0 with exhaustive bounded state graphs:
- DrainDeadline: drain-deadline/drain-liveness (28 distinct states each).
- Resources: resources/resources-liveness (2,850 distinct each).
- IntentCleanup: intent-cleanup (6,372), intent-multi/intent-liveness (1,701 each),
  cleanup/cleanup-liveness (354 each).

10 unsafe configs exited 12 with intended invariant counterexamples: shared
disk, fresh fallback, stale commit, control reuse, stale resume, missing UID,
postcommit cleanup, legacy check/register, expired lease and lease snapshot.
Four reachability probes exited 12: lost-response recovery, stop→run,
billing→run, late cleanup. They violate deliberately false witness predicates;
they are not failed correct models or implementation tests.

Reproduce from repository root:
python3 spec/disk-fork/v2/check.py drain-deadline drain-liveness resources resources-liveness intent-cleanup intent-multi intent-liveness cleanup cleanup-liveness unsafe-shared-disk unsafe-fresh-fallback unsafe-stale-commit unsafe-control-reuse unsafe-stale-resume unsafe-no-uid unsafe-postcommit probe-lost-response probe-stop-run probe-billing-run probe-late-cleanup legacy-unsafe-check legacy-unsafe-lease legacy-unsafe-lease-snapshot
The runner changes confine state output to ignored worktree .states/ and fail
unless expected completion/counterexample text exists. No tools committed.
The supplied runtime paths must exist to reproduce.

## Meaning and limitations

DrainDeadline starts with work outstanding: cancellation is not completion.
Before shutdown, deadline releases the gate without touching a running/mounted
parent. After shutdown starts, timeout means protected blocked reconciliation,
never fabricated unmount or snapshot. Weak fairness assumes enabled deadline,
stop/unmount/abort steps progress, not that hung work finishes. This is not OS
shutdown code.

Resources models distinct snapshot/PVC/child identities, immutable contents,
cold restore, fresh controls, lost API responses, re-observation, commit fencing
and access publication. Guards for resource ownership/UID are assumed. It does
not implement CSI scheduling, attach/unmount, credentials, network enforcement,
or persisted database transactions.

IntentCleanup models effect-time epoch-fenced resume vs user/billing/delete
intent, stop→run/billing→run epochs, and late cleanup vs commit/generation/UID.
Liveness configs use weak fairness of resume/stop/delete/cleanup. A foreign UID
surviving is a safe refusal, not guaranteed garbage collection. Coverage/witness
probes establish bounded reachability, not unbounded correctness. These separate
state variables are NOT one integrated verified controller. Read each .cfg for
finite bounds, invariants and temporal properties.

DiskFork.tla is byte-identical to v1, used for legacy mutants. v1's known
liveness-races timeout remains a timeout, not success. Historical attempts
remain; narrow fresh runs do not authenticate lost old jar bytes or prove the
broad all-faults configs. Production barriers and CSI gates remain incomplete.
