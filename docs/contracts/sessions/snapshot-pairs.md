# Matching memory and disk snapshots

Paired capture is opt-in with `SNAPSHOTS=true` and
`SNAPSHOT_DISK_CLASS=computeruse-session`. An empty disk class retains the
legacy memory-only path. `SnapshotOptions.DiskClass` passes this setting to
the session store. The production overlay does not enable this setting.

## Capture contract

One writable persistent volume belongs to a session. Its pod is the only
writer; external writable mounts are outside this contract.

1. Conditionally reserve the Sandbox with `browserjs.dev/checkpoint-started`.
   The API reports the session as stopping and provides no routable pod IP.
   A second capture or explicit resume cannot take over this operation.
2. Require the `session-paired-sleep` policy to use `postCheckpoint: stop`.
   Require the legacy `session-sleep` policy to exclude pods labelled
   `browserjs.dev/paired-snapshots=true`, then label the target pod accordingly.
3. Trigger the memory checkpoint. Wait for its ready condition and for the
   same pod UID to reach Succeeded with all containers terminated. A changed
   pod UID makes capture fail; graceful deletion is not used to establish
   the disk checkpoint boundary.
4. Create a CSI `VolumeSnapshot` of the current claim. Check that the same
   completed pod remains stopped while waiting for `readyToUse`. A CSI error
   or timeout abandons the pair.
5. Only after both artifacts are ready, annotate the memory snapshot with
   `browserjs.dev/disk-snapshot` and `browserjs.dev/source-claim`. Record the
   memory snapshot, source claim, and compatible node pool on the Sandbox,
   then suspend it. Clear the capture fence after the operation completes.

This implements the model's atomic capture contract by forbidding writes
between the two physical captures. It does not rely on the independent
snapshots being simultaneous.

On failure, incomplete memory checkpoints are deleted so GKE cannot select
them implicitly. A failed capture still permits disk-only sleep. A changed
final sleep condition removes the stopped pod and starts cold from the
working disk. An expired capture fence is recovered on session access after
the configured capture timeout plus one minute. A committed suspension or
explicit user stop remains suspended during that recovery.

## Restore and disk preservation

A waking session keeps a memory checkpoint only when the corresponding disk
snapshot is also ready. Older memory-only snapshots are pruned before paired
sessions start cold. Explicit Resume follows the same preparation as Wake.

Wait for the old suspended pod to disappear. Create a fresh PVC from the
saved disk snapshot, owned by the Sandbox. Its name includes the checkpoint
and Sandbox generation so a later restore attempt does not overwrite an
older branch. Conditional-write retries may reuse the same unserved claim;
its owner and data source must match before it is accepted.

Replace claim templates with an explicit `data` volume referencing the
clone. Preserve capacity in `browserjs.dev/disk-gb`; expansion targets
`browserjs.dev/data-claim`, not an archived source claim. All original and
failed-restore claims remain owned by the Sandbox. They are not deleted or
overwritten during capture, restore, or cold fallback.

Before returning a serving session, verify all actual pod containers are
ready, its `data` volume selects the intended claim, and its current pod IP
exists. Stale Sandbox readiness cannot route requests to the old pod. Once
this check succeeds, consume the memory/disk checkpoint and clear its
Sandbox annotations. Later pod recreation starts cold against the working
clone rather than restoring stale memory over application writes.

If initial restore fails, ColdStart suspends the failed pod and deletes the
memory checkpoint. It records a durable cold-restore intent and retains the
disk snapshot until a fresh cold clone serves. User Stop during an uncompleted
restore records the same intent; explicit Resume prepares the cold clone.
Failed clones and the original source remain available for inspection.
Preservation does not merge their newer writes into the saved disk.

Orphan disk snapshots from interrupted capture are pruned by session label.
Retired PVCs remain until the session is deleted, when Kubernetes owner
references garbage-collect them. This deliberately retains more history
than the model requires after handoff; repeated sleep/wake cycles therefore
increase provisioned disk storage and cost. Automatic retired-claim deletion
is not implemented.

## Deployment and validation

The namespaced GKE overlay includes the paired policy and required RBAC.
The disk class is cluster-scoped and must be applied separately:

```sh
kubectl apply -f deploy/gke/volume-snapshot-class.yaml
```

After deploying the backend and namespaced policies, enable the disk class
setting in the backend deployment through the repository's deployment
configuration. Do not enable it before these prerequisites exist, or disable
it while paired sessions still hold checkpoints. The driver is the GKE
Persistent Disk CSI driver. VolumeSnapshot CRDs and its controller must be
installed and the current storage class must support CSI snapshots.

The unit tests cover capture ordering, replacement/refusal/failure cases,
explicit resume, source preservation, clone binding, cancellation, stale
readiness, checkpoint consumption, cold-clone fallback, user stop, expansion, and
abandoned-operation recovery. The TLA+ checks cover matching captures and
source-disk preservation; they do not model GKE internals.

Before production enablement, run a disposable GKE session through capture,
clone provisioning, gVisor memory restore, failed startup, and node/pod
replacement. Server-side dry runs validate schemas and RBAC manifest shapes
but do not verify these runtime interactions. In particular, GKE's internal
container/runtime retries before the backend observes readiness are outside
the unit-test and TLA+ state machines; verify their behavior against the CSI
clone. The opt-in setting remains unset pending that validation.

Sources:
- [GKE PVC mutation risks and stop mitigation](https://docs.cloud.google.com/kubernetes-engine/docs/troubleshooting/pod-snapshots#post-checkpoint_mutation_risks_with_pvcs)
- [GKE snapshot contents](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/pod-snapshots)
- [CSI snapshot and restore](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/persistent-volumes/backup-pd-volume-snapshots)
