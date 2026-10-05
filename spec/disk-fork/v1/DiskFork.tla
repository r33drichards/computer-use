------------------------------ MODULE DiskFork ------------------------------
EXTENDS Naturals, Integers, FiniteSets, TLC
CONSTANTS Replicas, Ops, Keys, MaxChildren, MaxEpoch, Mode, Faults
VARIABLE s
vars == <<s>>
NoOp == 0
Terminal == {"succeeded", "failed", "cancelled", "deleted"}
Active == {"pending", "draining", "stopping", "snapshotting", "ready", "provisioning", "starting", "cleanup"}
OpInit == [stage |-> "absent", key |-> 0, epoch |-> 0,
           snap |-> -1, snapshot |-> FALSE, safe |-> TRUE,
           uid |-> 0, actual |-> 0, disk |-> 0, contents |-> -1,
           committed |-> FALSE, accessible |-> FALSE,
           deleting |-> FALSE, protected |-> FALSE, cold |-> FALSE,
           owner |-> "owner", control |-> 0]
Init == s = [live |-> TRUE, running |-> TRUE, mounted |-> TRUE,
             intent |-> "run", epoch |-> 0, data |-> 0,
             gate |-> 0, sourceProtected |-> FALSE,
             req |-> [r \in Replicas |-> "idle"],
             op |-> [i \in Ops |-> OpInit], replay |-> {},
             up |-> TRUE, crashes |-> 0,
             badAdmit |-> FALSE, badResume |-> FALSE,
             wrongDeleted |-> FALSE, healthyDestroyed |-> FALSE]
Executing == {r \in Replicas : s.req[r] \in {"executing", "expired"}}
Admitted == {r \in Replicas : s.req[r] = "admitted"}
Reservations == {i \in Ops : s.op[i].stage \notin {"absent", "failed", "cancelled", "deleted"}}
Quiet == Executing = {} /\ Admitted = {}
LeaseQuiet == {r \in Replicas : s.req[r] \in {"admitted", "executing"}} = {}
CanResume == s.live /\ s.intent = "run"

\* Submit is an atomic OWNER reservation. A non-owner has no Submit transition.
Submit(i,k) == /\ s.up /\ s.live /\ s.intent # "delete"
               /\ s.op[i].stage = "absent"
               /\ ~\E j \in Ops : s.op[j].key = k
               /\ Cardinality(Reservations) < MaxChildren
               /\ s' = [s EXCEPT !.op[i].stage = "pending", !.op[i].key = k]
Replay(k) == /\ \E i \in Ops : s.op[i].key = k
             /\ k \notin s.replay /\ s' = [s EXCEPT !.replay = @ \cup {k}]

\* Fixed admission registers before forwarding, atomically competing with Gate.
Begin(r) == /\ s.req[r] = "idle" /\ s.live /\ s.running /\ s.mounted
            /\ s.intent = "run" /\ s.gate = 0
            /\ s' = [s EXCEPT !.req[r] = IF Mode = "check" THEN "checked" ELSE "admitted"]
\* Intentional TOCTOU bug: registration trusts a previous check.
Register(r) == /\ Mode = "check" /\ s.req[r] = "checked"
               /\ s' = [s EXCEPT !.req[r] = "admitted",
                          !.badAdmit = @ \/ (s.gate # 0)]
Execute(r) == /\ s.req[r] = "admitted" /\ s.running /\ s.mounted
              /\ s' = [s EXCEPT !.req[r] = "executing"]
Expire(r) == /\ s.req[r] = "executing"
             /\ s' = [s EXCEPT !.req[r] = "expired"]
\* Long-lived/background work survives lease expiry until an actual completion.
Finish(r) == /\ s.req[r] \in {"executing", "expired"}
             /\ s' = [s EXCEPT !.req[r] = "done", !.data = @ + 1]

Gate(i) == /\ s.up /\ s.live /\ s.intent # "delete" /\ s.gate = 0
           /\ s.op[i].stage = "pending"
           /\ s' = [s EXCEPT !.gate = i, !.sourceProtected = TRUE,
                      !.op[i].stage = "draining", !.op[i].epoch = s.epoch]
Drain(i) == /\ s.up /\ s.gate = i /\ s.op[i].stage = "draining"
            /\ (IF Mode = "lease" THEN LeaseQuiet ELSE Quiet)
            /\ s' = [s EXCEPT !.running = FALSE, !.op[i].stage = "stopping"]
Unmount(i) == /\ s.up /\ s.gate = i /\ s.op[i].stage = "stopping"
              /\ s' = [s EXCEPT !.mounted = FALSE, !.op[i].stage = "snapshotting"]
Snapshot(i) == /\ s.up /\ s.gate = i /\ s.op[i].stage = "snapshotting"
               /\ ~s.mounted
               /\ s' = [s EXCEPT !.op[i].stage = "ready", !.op[i].snapshot = TRUE,
                          !.op[i].snap = s.data,
                          !.op[i].safe = (~s.mounted /\ Quiet)]
\* Snapshot is immutable: gate/finalizer can now release; latest intent wins.
Release(i) == /\ s.up /\ s.gate = i /\ s.op[i].stage = "ready"
              /\ s' = [s EXCEPT !.gate = 0, !.sourceProtected = FALSE,
                         !.running = CanResume, !.mounted = CanResume,
                         !.badResume = @ \/ (CanResume /\ s.intent # "run"),
                         !.op[i].stage = "provisioning"]
Clone(i) == /\ s.up /\ s.op[i].stage = "provisioning" /\ ~s.op[i].deleting
            /\ s' = [s EXCEPT !.op[i].stage = "starting", !.op[i].uid = 1,
                       !.op[i].actual = 1, !.op[i].disk = i + 1,
                       !.op[i].contents = s.op[i].snap, !.op[i].protected = TRUE,
                       !.op[i].cold = TRUE, !.op[i].control = i + 1]
Commit(i) == /\ s.up /\ s.op[i].stage = "starting" /\ ~s.op[i].deleting
             /\ s' = [s EXCEPT !.op[i].stage = "succeeded",
                        !.op[i].committed = TRUE, !.op[i].accessible = TRUE,
                        !.op[i].protected = FALSE]
PruneSnapshot(i) == /\ s.up /\ s.op[i].stage = "succeeded" /\ s.op[i].snapshot
                    /\ s' = [s EXCEPT !.op[i].snapshot = FALSE]

UserIntent(kind) == /\ s.live /\ s.epoch < MaxEpoch
                    /\ kind \in {"stop", "billing", "delete", "run"}
                    /\ s' = [s EXCEPT !.intent = kind, !.epoch = @ + 1]
ApplyIntent == /\ s.up /\ s.live /\ s.gate = 0 /\ Quiet
               /\ s.intent # "run" /\ (s.running \/ s.mounted)
               /\ s' = [s EXCEPT !.running = FALSE, !.mounted = FALSE]
UserResume == /\ s.up /\ s.live /\ s.gate = 0 /\ s.intent = "run"
              /\ ~s.running /\ s' = [s EXCEPT !.running = TRUE, !.mounted = TRUE]
DeleteSource == /\ s.up /\ s.live /\ s.intent = "delete" /\ s.gate = 0
                /\ ~s.sourceProtected /\ ~s.mounted /\ Quiet
                /\ s' = [s EXCEPT !.live = FALSE]
CancelPending(i) == /\ s.up /\ s.intent = "delete" /\ s.op[i].stage = "pending"
                     /\ s' = [s EXCEPT !.op[i].stage = "cleanup"]
Fail(i) == /\ s.up /\ Faults /\ s.op[i].stage \in Active \ {"cleanup"}
           /\ s' = [s EXCEPT !.op[i].stage = "cleanup"]
DeleteChildIntent(i) == /\ s.op[i].stage \in Active \cup {"succeeded"}
                        /\ ~s.op[i].deleting
                        /\ s' = [s EXCEPT !.op[i].deleting = TRUE, !.op[i].accessible = FALSE]
CancelChild(i) == /\ s.up /\ s.op[i].deleting
                  /\ s.op[i].stage \in Active \ {"cleanup"}
                  /\ s' = [s EXCEPT !.op[i].stage = "cleanup"]
\* Out-of-band delete/recreate at same name: UID 2 is foreign, never owned.
ReplaceUID(i) == /\ Faults /\ s.op[i].stage = "cleanup" /\ s.op[i].actual = 1
                 /\ s' = [s EXCEPT !.op[i].actual = 2]
Cleanup(i) == /\ s.up /\ s.op[i].stage = "cleanup"
              /\ (s.gate # i \/ Quiet)
              /\ LET owned == s.op[i].actual = s.op[i].uid /\ s.op[i].uid # 0
                      releasing == s.gate = i
                  IN s' = [s EXCEPT
                    !.op[i].actual = IF owned THEN 0 ELSE @,
                    !.op[i].disk = IF owned THEN 0 ELSE @,
                    !.op[i].snapshot = FALSE, !.op[i].protected = FALSE,
                    !.op[i].stage = IF s.intent = "delete" \/ s.op[i].deleting THEN "cancelled" ELSE "failed",
                    !.wrongDeleted = @ \/ (owned /\ s.op[i].actual # s.op[i].uid),
                    !.healthyDestroyed = @ \/ (owned /\ s.op[i].committed /\ ~s.op[i].deleting),
                    !.gate = IF releasing THEN 0 ELSE @,
                    !.sourceProtected = IF releasing THEN FALSE ELSE @,
                    !.running = IF releasing THEN CanResume ELSE @,
                    !.mounted = IF releasing THEN CanResume ELSE @,
                    !.badResume = @ \/ (releasing /\ CanResume /\ s.intent # "run")]
DeleteChild(i) == /\ s.up /\ s.op[i].stage = "succeeded" /\ s.op[i].deleting
                  /\ ~s.op[i].protected /\ s.op[i].actual = s.op[i].uid
                  /\ s' = [s EXCEPT !.op[i].stage = "deleted", !.op[i].actual = 0,
                             !.op[i].disk = 0, !.op[i].snapshot = FALSE]
Crash == /\ Faults /\ s.up /\ s.crashes = 0
         /\ s' = [s EXCEPT !.up = FALSE, !.crashes = 1]
Recover == /\ ~s.up /\ s' = [s EXCEPT !.up = TRUE]
OpStep(i) == Gate(i) \/ Drain(i) \/ Unmount(i) \/ Snapshot(i) \/ Release(i)
             \/ Clone(i) \/ Commit(i) \/ PruneSnapshot(i) \/ Cleanup(i)
             \/ CancelPending(i) \/ CancelChild(i) \/ DeleteChild(i)
Next == (\E r \in Replicas : Begin(r) \/ Register(r) \/ Execute(r) \/ Expire(r) \/ Finish(r))
        \/ (\E i \in Ops : OpStep(i) \/ Fail(i) \/ DeleteChildIntent(i) \/ ReplaceUID(i))
        \/ (\E i \in Ops, k \in Keys : Submit(i,k)) \/ (\E k \in Keys : Replay(k))
        \/ (\E kind \in {"stop", "billing", "delete", "run"} : UserIntent(kind))
        \/ ApplyIntent \/ UserResume \/ DeleteSource \/ Crash \/ Recover
Spec == Init /\ [][Next]_vars
FairSpec == Spec /\ WF_vars(Recover) /\ WF_vars(ApplyIntent)
            /\ WF_vars(UserResume) /\ WF_vars(DeleteSource)
            /\ \A r \in Replicas : WF_vars(Execute(r)) /\ WF_vars(Finish(r))
            /\ \A i \in Ops : WF_vars(OpStep(i))

TypeOK == /\ s.gate \in Ops \cup {0} /\ s.epoch \in 0..MaxEpoch
          /\ s.data \in 0..Cardinality(Replicas)
          /\ s.req \in [Replicas -> {"idle", "checked", "admitted", "executing", "expired", "done"}]
          /\ \A i \in Ops : s.op[i].stage \in Active \cup Terminal \cup {"absent"}
SnapshotSafe == \A i \in Ops : s.op[i].safe
NoNewAdmission == ~s.badAdmit
IndependentDisks == /\ \A i \in Ops : s.op[i].disk # 1
                    /\ \A i,j \in Ops : i # j /\ s.op[i].disk # 0 /\ s.op[j].disk # 0 => s.op[i].disk # s.op[j].disk
CorrectContents == \A i \in Ops : s.op[i].uid # 0 => s.op[i].contents = s.op[i].snap
FreshIdentity == \A i \in Ops : s.op[i].uid # 0 => s.op[i].cold /\ s.op[i].control = i+1 /\ s.op[i].control # 1
CommitBeforeAccess == \A i \in Ops : s.op[i].accessible => s.op[i].committed /\ s.op[i].stage = "succeeded" /\ ~s.op[i].deleting
LatestIntentWins == ~s.badResume
Idempotent == \A i,j \in Ops : i # j /\ s.op[i].key # 0 => s.op[i].key # s.op[j].key
SameOwnerAndCap == /\ Cardinality(Reservations) <= MaxChildren
                   /\ \A i \in Ops : s.op[i].owner = "owner"
Protection == /\ (s.gate # 0) = s.sourceProtected
              /\ s.sourceProtected => s.live
              /\ \A i \in Ops : s.op[i].stage = "starting" => s.op[i].protected
CleanupSafe == ~s.wrongDeleted /\ ~s.healthyDestroyed
\* A failed fork does not leave a private pause/gate behind. Later intents may stop it.
FailureSourceSafe == \A i \in Ops : s.op[i].stage \in {"failed", "cancelled"} => s.gate # i
ExecutingMounted == Executing # {} => s.mounted
Completion == \A i \in Ops : (s.op[i].stage \in Active) ~> (s.op[i].stage \in Terminal)
SourceDeletion == (s.intent = "delete") ~> ~s.live
SnapshotCleanup == \A i \in Ops : (s.op[i].stage = "succeeded") ~> ~s.op[i].snapshot
=============================================================================
