------------------------------ MODULE Resources ------------------------------
EXTENDS Naturals, FiniteSets, TLC
CONSTANT Mode
VARIABLE s
vars == <<s>>
Kinds == {"snapshot", "pvc", "child"}
Empty == [uid |-> 0, owner |-> 0, source |-> 0, mount |-> 0, disk |-> 0,
          contents |-> -1, control |-> 0, ready |-> FALSE, cold |-> FALSE, access |-> FALSE]
Init == s = [phase |-> "snapshot", obj |-> [k \in Kinds |-> Empty],
             seen |-> [k \in Kinds |-> 0], creates |-> [k \in Kinds |-> 0],
             lost |-> {}, up |-> TRUE, crashes |-> 0, commits |-> {}, deletes |-> {}]
CreateSnapshot(lost) == /\ s.up /\ s.phase = "snapshot" /\ s.obj["snapshot"].uid = 0
 /\ s' = [s EXCEPT !.obj["snapshot"] = [Empty EXCEPT !.uid = 1, !.owner = 1, !.contents = 7, !.ready = TRUE],
                   !.creates["snapshot"] = @ + 1,
                   !.seen["snapshot"] = IF lost THEN 0 ELSE 1,
                   !.lost = IF lost THEN @ \cup {"snapshot"} ELSE @]
SnapshotResponse == CreateSnapshot(FALSE)
LoseSnapshotResponse == CreateSnapshot(TRUE)
ReconcileSnapshot == /\ s.up /\ s.phase = "snapshot"
 /\ s.obj["snapshot"].uid # 0 /\ s.obj["snapshot"].owner = 1
 /\ s' = [s EXCEPT !.seen["snapshot"] = s.obj["snapshot"].uid, !.phase = "pvc"]
CreatePVC(lost) == /\ s.up /\ s.phase = "pvc" /\ s.obj["pvc"].uid = 0
 /\ s.obj["snapshot"].uid = s.seen["snapshot"] /\ s.obj["snapshot"].owner = 1
 /\ s' = [s EXCEPT !.obj["pvc"] = [Empty EXCEPT !.uid = 1, !.owner = 1],
                   !.creates["pvc"] = @ + 1, !.seen["pvc"] = IF lost THEN 0 ELSE 1,
                   !.lost = IF lost THEN @ \cup {"pvc"} ELSE @]
PVCResponse == CreatePVC(FALSE)
LosePVCResponse == CreatePVC(TRUE)
\* Asynchronous CSI consumption can race snapshot replacement. It samples
\* ACTUAL backing snapshot, not the operation's desired ledger UID/value.
BindPVC == /\ s.up /\ s.phase = "pvc" /\ s.obj["pvc"].owner = 1 /\ ~s.obj["pvc"].ready
 /\ s.obj["snapshot"].uid # 0
 /\ s' = [s EXCEPT !.obj["pvc"].ready = TRUE,
                   !.obj["pvc"].source = IF Mode = "fresh-fallback" THEN 0 ELSE s.obj["snapshot"].uid,
                   !.obj["pvc"].contents = IF Mode = "fresh-fallback" THEN 0 ELSE s.obj["snapshot"].contents,
                   !.obj["pvc"].disk = IF Mode = "shared-disk" THEN 10 ELSE 20]
ReconcilePVC == /\ s.up /\ s.phase = "pvc" /\ s.obj["pvc"].uid # 0 /\ s.obj["pvc"].owner = 1
 /\ (s.seen["pvc"] = 0 \/ s.obj["pvc"].ready)
 /\ (~s.obj["pvc"].ready \/ s.obj["pvc"].source = s.seen["snapshot"] \/ Mode = "fresh-fallback")
 /\ s' = [s EXCEPT !.seen["pvc"] = s.obj["pvc"].uid,
                   !.phase = IF s.obj["pvc"].ready THEN "child" ELSE @]
CreateChild(lost) == /\ s.up /\ s.phase = "child" /\ s.obj["child"].uid = 0
 /\ s.obj["pvc"].uid = s.seen["pvc"] /\ s.obj["pvc"].owner = 1
 /\ s' = [s EXCEPT !.obj["child"] = [Empty EXCEPT !.uid = 1, !.owner = 1, !.cold = TRUE, !.control = 20],
                   !.creates["child"] = @ + 1, !.seen["child"] = IF lost THEN 0 ELSE 1,
                   !.lost = IF lost THEN @ \cup {"child"} ELSE @]
ChildResponse == CreateChild(FALSE)
LoseChildResponse == CreateChild(TRUE)
ReadyChild == /\ s.up /\ s.phase = "child" /\ s.obj["child"].owner = 1 /\ ~s.obj["child"].ready
 /\ s.obj["pvc"].uid # 0
 /\ s' = [s EXCEPT !.obj["child"].ready = TRUE, !.obj["child"].mount = s.obj["pvc"].uid]
ReconcileChild == /\ s.up /\ s.phase = "child" /\ s.obj["child"].uid # 0 /\ s.obj["child"].owner = 1
 /\ (s.seen["child"] = 0 \/ s.obj["child"].ready)
 /\ s' = [s EXCEPT !.seen["child"] = s.obj["child"].uid,
                   !.phase = IF s.obj["child"].ready THEN "commit" ELSE @]
IdentityFence == /\ s.obj["child"].uid = s.seen["child"] /\ s.obj["child"].owner = 1
                 /\ s.obj["pvc"].uid = s.seen["pvc"] /\ s.obj["pvc"].owner = 1
                 /\ s.obj["child"].mount = s.seen["pvc"]
                 /\ (s.obj["pvc"].source = s.seen["snapshot"] \/ Mode = "fresh-fallback")
Commit == /\ s.up /\ s.phase = "commit"
 /\ (Mode = "stale-commit" \/ IdentityFence)
 \* Audit samples CURRENT objects at publication, independently of the fence.
 /\ LET event == [childUID |-> s.obj["child"].uid, childSeen |-> s.seen["child"],
                  pvcUID |-> s.obj["pvc"].uid, pvcSeen |-> s.seen["pvc"],
                  mountedUID |-> s.obj["child"].mount, sourceUID |-> s.obj["pvc"].source,
                  snapshotSeen |-> s.seen["snapshot"], disk |-> s.obj["pvc"].disk,
                  contents |-> s.obj["pvc"].contents, control |-> s.obj["child"].control,
                  cold |-> s.obj["child"].cold, owner |-> s.obj["child"].owner]
    IN s' = [s EXCEPT !.phase = "committed", !.commits = @ \cup {event}, !.obj["child"].access = TRUE]
Replace(k) == /\ s.phase \notin {"committed", "failed"} /\ s.obj[k].uid = 1
 /\ s' = [s EXCEPT !.obj[k] = [Empty EXCEPT !.uid = 2, !.contents = 9, !.disk = 30, !.control = 90, !.ready = TRUE]]
ReplaceSnapshot == Replace("snapshot")
ReplacePVC == Replace("pvc")
ReplaceChild == Replace("child")
Mismatch == /\ s.phase \notin {"cleanup", "committed", "failed"}
 /\ ( (\E k \in Kinds : s.obj[k].uid # 0 /\ s.obj[k].owner # 1)
      \/ (s.obj["pvc"].ready /\ s.obj["pvc"].source # s.seen["snapshot"] /\ Mode # "fresh-fallback")
      \/ (s.obj["child"].ready /\ s.obj["child"].mount # s.seen["pvc"]) )
DetectMismatch == /\ s.up /\ Mismatch /\ s' = [s EXCEPT !.phase = "cleanup"]
Cancel == /\ s.up /\ s.phase \notin {"cleanup", "committed", "failed"}
          /\ s' = [s EXCEPT !.phase = "cleanup"]
CleanupReconcile(k) == /\ s.up /\ s.phase = "cleanup" /\ s.obj[k].owner = 1 /\ s.seen[k] = 0
 /\ s' = [s EXCEPT !.seen[k] = s.obj[k].uid]
CleanupDelete(k) == /\ s.up /\ s.phase = "cleanup" /\ s.obj[k].owner = 1
 /\ s.obj[k].uid = s.seen[k] /\ s.obj[k].uid # 0
 /\ s' = [s EXCEPT !.deletes = @ \cup {[kind |-> k, actual |-> s.obj[k].uid, ledger |-> s.seen[k]]}, !.obj[k] = Empty]
CleanupDone == /\ s.up /\ s.phase = "cleanup" /\ \A k \in Kinds : s.obj[k].owner # 1
 /\ s' = [s EXCEPT !.phase = "failed"]
Crash == /\ s.up /\ s.crashes = 0 /\ s' = [s EXCEPT !.up = FALSE, !.crashes = 1]
Recover == /\ ~s.up /\ s' = [s EXCEPT !.up = TRUE]
Step == SnapshotResponse \/ LoseSnapshotResponse \/ ReconcileSnapshot
        \/ PVCResponse \/ LosePVCResponse \/ BindPVC \/ ReconcilePVC
        \/ ChildResponse \/ LoseChildResponse \/ ReadyChild \/ ReconcileChild \/ Commit
        \/ DetectMismatch \/ CleanupDone \/ (\E k \in Kinds : CleanupReconcile(k) \/ CleanupDelete(k))
Next == Step \/ Cancel \/ Crash \/ Recover \/ ReplaceSnapshot \/ ReplacePVC \/ ReplaceChild
Spec == Init /\ [][Next]_vars
FairSpec == Spec /\ WF_vars(Recover) /\ WF_vars(Step)
TypeOK == s.phase \in {"snapshot", "pvc", "child", "commit", "cleanup", "committed", "failed"}
          /\ \A k \in Kinds : s.obj[k].uid \in {0,1,2} /\ s.seen[k] \in {0,1,2}
IdempotentCreate == \A k \in Kinds : s.creates[k] <= 1
CommitOwnedFenced == \A e \in s.commits : e.owner = 1 /\ e.childUID = e.childSeen /\ e.pvcUID = e.pvcSeen /\ e.mountedUID = e.pvcSeen
IndependentDisk == \A e \in s.commits : e.disk # 10
CorrectContents == \A e \in s.commits : e.contents = 7 /\ e.sourceUID = e.snapshotSeen
FreshControl == \A e \in s.commits : e.cold /\ e.control # 10
CommitBeforeAccess == s.obj["child"].access => s.phase = "committed"
CleanupUIDSafe == \A e \in s.deletes : e.actual = e.ledger
Completion == (s.phase \notin {"committed", "failed"}) ~> (s.phase \in {"committed", "failed"})
=============================================================================
