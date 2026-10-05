# Session checkpoint and persistent-disk consistency

`SessionSnapshot.tla` models one session's sleep/wake cycle and the failure
seen in `package manager` (`s-hmezprnlnr`) on October 4, 2026 (Pacific time).
This is a bounded safety model, not a production failure injection.

## Evidence and hypothesis

The pod repeatedly failed to restore with:

```
vfs.CompleteRestore() failed
failed to walk "Default/Local Storage/leveldb/000004.log"
in mount "browser:/data/chrome": no such file or directory
```

After removing the runtime checkpoint and starting from the existing disk,
mcp-js failed opening its sled database:

```
duplicate segment LSN 16252928 detected at both 524288 and 9437184,
one should have been zeroed out during recovery
```

The missing file and database panic were observed. The exact file-deletion
timing and the cause of the database corruption were not established.
The model demonstrates how the configured ordering permits a memory/disk
mismatch; it does not reconstruct the historical execution or implement
sled's recovery algorithm. `StaleDatabaseWrite` explicitly assumes that an
older writer position can corrupt a newer log. Its counterexample establishes
the consequence of that assumption, not that sled necessarily does this.

## Mapping to the implementation

| Model action/state | Implementation or meaning |
|---|---|
| `Checkpoint` | `Store.Sleep` takes a whole-pod snapshot in `backend/internal/sessions/snapshots.go`. |
| `checkpointed` | `deploy/gke/snapshots.yaml` sets `postCheckpoint: resume`. Processes can run again. |
| `ChromeRotation` | A live process replaces a profile file and releases its old reference. Checkpointed memory still references the old file. File identity abstracts pathname availability. |
| `DatabaseAppend` | Disk log generation and the live writer position advance together. The saved writer position does not advance. |
| `BeginShutdown`, `draining` | After the snapshot is ready, Sleep suspends the Sandbox. Graceful shutdown can also write to disk. |
| `Suspend` | The pod stops; its persistent volume remains. |
| `Restore` | Older memory is paired with the current volume. GKE can retry the same checkpoint; attempts are bounded at two. |
| `StaleDatabaseWrite` | Hypothesized write with a restored stale log position. |

Both mutation actions can happen before the checkpoint, after it resumes,
or during shutdown. `MaxWrites = 2` bounds the explored generations. There
is one file identity and one database log generation, rather than complete
Chrome or database implementations. No unrelated disk writes, disk snapshots,
node failures, clean database recovery, or concurrent recovery workers are
modelled.

## Invariants and counterexamples

`RestoreUsesCompatibleDisk` requires that, after a restore attempt, the
restored file reference and writer generation match the current disk.
`NoMissingChromeFile` checks the observed restore failure separately.
`NoDatabaseCorruption` checks the hypothesized database failure separately.
`TypeOK` checks the model's state domains in every configuration.

| Configuration | Result |
|---|---|
| `current.cfg` | `RestoreUsesCompatibleDisk` violated, trace of 6 states. |
| `missing-file.cfg` | `NoMissingChromeFile` violated, trace of 6 states. |
| `database-hypothesis.cfg` | `NoDatabaseCorruption` violated, trace of 7 states. |
| `quiesced.cfg` | All invariants hold; 30 distinct reachable states. |

The shortest missing-file trace is:

```
running
  -> checkpoint memory referencing file 0
  -> rotate disk to file 1; live memory follows, checkpoint does not
  -> begin shutdown
  -> suspend
  -> restore checkpoint referencing file 0 against disk file 1: failure
```

The database trace substitutes a database append for file rotation, restores
successfully (the Chrome file exists), then takes the hypothesized stale
write action. Filtered TLC output is checked in under `traces/`.

`quiesced.cfg` forbids **every modelled persistent-disk write between checkpoint
and restore**, including shutdown writes. It still explores writes before
checkpointing. This is a candidate ordering requirement, not an implemented
fix: pausing only while the checkpoint is captured is insufficient if the
processes then resume or flush during shutdown. An atomic matching disk
snapshot or abandoning memory restore would need their own model actions.

Terminal states intentionally have no next action; deadlock checking is
disabled. These checks establish safety for the bounded model only, with no
fairness, eventual-readiness, or automatic-fallback claims.

## Reproduce

From the repository root:

```sh
spec/session-snapshot/check.sh
```

The script uses `tlc` if available, otherwise runs it with
`nix shell nixpkgs#tlaplus`. `TLC=/absolute/path/to/tlc` selects a checker.
It requires exactly the expected invariant violation and TLC exit code 12
for each failing configuration, and successful exhaustive checking for
`quiesced`. Unexpected failures make the script fail. It refreshes the saved
traces and removes temporary checker state. The checked-in traces were
produced with TLC 2.19.

To inspect one violation directly:

```sh
cd spec/session-snapshot
nix shell nixpkgs#tlaplus -c tlc -config missing-file.cfg SessionSnapshot.tla
```

That command intentionally exits nonzero when the invariant is violated.

## Paired memory and disk capture

`paired.cfg` enables a disk snapshot captured under the same pause as memory.
Restore installs the captured disk state before restoring memory. Live writes
are allowed again after capture, including shutdown writes: they change the
working disk, not the saved pair. All three safety invariants hold across
66 reachable states.

`uncoordinated-pair.cfg` captures disk in a separate action while writers may
run. TLC finds a seven-state consistency violation: memory capture, disk
mutation, disk capture, shutdown, suspend, restore. Merely creating both
snapshot resources is insufficient.

The atomic action specifies a required production contract. GKE's Pod
snapshot API does not supply an atomic PVC snapshot. Its documented
`postCheckpoint: stop` can establish the no-write interval for a subsequent
CSI capture, provided no controller restarts the pod and pending filesystem
writes are settled. A production coordinator must fence wakes and controller
recreation throughout this interval.

Sources:
- [GKE snapshot contents](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/pod-snapshots)
- [Post-checkpoint mutation risks](https://docs.cloud.google.com/kubernetes-engine/docs/troubleshooting/pod-snapshots#post-checkpoint_mutation_risks_with_pvcs)
- [CSI Persistent Disk snapshot and restore](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/persistent-volumes/backup-pd-volume-snapshots)

The production implementation must also publish pair IDs only after both
artifacts are ready, recover interrupted operations durably, provision the
restored volume before memory restore, preserve the original working disk
until successful handoff, and handle every restore retry using the same
saved disk generation. These requirements are not yet implemented by this
model or by the current backend.


## Preserving the working disk

`workingFile` and `workingEpoch` track the original source disk independently
of the disk installed for restore. `NoWorkingDiskLoss` requires that the sum
of its generations still accounts for every pre-restore mutation. The paired
configuration retains this source disk even when restoring an older branch.
`destructive-pair.cfg` deliberately replaces the source too: TLC violates
`NoWorkingDiskLoss` in six states after a post-checkpoint mutation.

This checks preservation of the abstract source disk, not availability of
newer writes in the resumed application. Those writes remain on the retained
source and require a separate reconciliation or recovery procedure. No
writes between failed restore attempts are modelled; retries install the
saved disk again. Production would need to preserve each attempt's mutated
branch as well. Neither actual data bytes nor successful handoff and eventual
backup deletion are modelled.

The runner now uses standard `grep` and `awk`, and saves only invariant
results, counterexample states, and state counts. It omits local paths,
host details, timestamps, and random seeds. The path-filtered
`.github/workflows/session-snapshot-model.yml` runs the regression checks and
requires the normalized traces to match the checked-in files.
