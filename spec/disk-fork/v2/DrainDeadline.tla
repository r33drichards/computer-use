--------------------------- MODULE DrainDeadline ---------------------------
EXTENDS Naturals, FiniteSets, TLC
VARIABLE s
vars == <<s>>
Init == s = [phase |-> "drain", actualWork |-> TRUE, running |-> TRUE,
             mounted |-> TRUE, gate |-> TRUE, deadline |-> FALSE,
             cancelRequested |-> FALSE, snapshotAudit |-> {}]
\* Cancellation request is NOT acknowledgement that upstream work ended.
RequestCancel == /\ s.phase = "drain" /\ ~s.cancelRequested
                 /\ s' = [s EXCEPT !.cancelRequested = TRUE]
CompleteActualWork == /\ s.actualWork /\ s' = [s EXCEPT !.actualWork = FALSE]
Deadline == /\ ~s.deadline /\ s' = [s EXCEPT !.deadline = TRUE]
BeginStop == /\ s.phase = "drain" /\ ~s.actualWork
             /\ s' = [s EXCEPT !.phase = "stopping", !.running = FALSE]
GracefulUnmount == /\ s.phase = "stopping" /\ ~s.actualWork
                   /\ s' = [s EXCEPT !.phase = "unmounted", !.mounted = FALSE]
TakeSnapshot == /\ s.phase = "unmounted" /\ ~s.mounted /\ ~s.actualWork
                /\ s' = [s EXCEPT !.phase = "snapshot",
                  !.snapshotAudit = @ \cup {[mounted |-> s.mounted, work |-> s.actualWork]}]
\* Before any shutdown, abort can release the gate WITHOUT resuming, killing,
\* or copying anything: parent continues exactly as it was, even if work hangs.
AbortBeforeStop == /\ s.phase = "drain" /\ s.deadline
                   /\ s' = [s EXCEPT !.phase = "failed", !.gate = FALSE]
\* Once shutdown started, timeout alone cannot certify a clean unmount.
\* Keep protection; report blocked reconciliation, never a successful fork.
TimeoutAfterStop == /\ s.phase \in {"stopping", "unmounted"} /\ s.deadline
                    /\ s' = [s EXCEPT !.phase = "blocked"]
Next == RequestCancel \/ CompleteActualWork \/ Deadline \/ BeginStop \/ GracefulUnmount
        \/ TakeSnapshot \/ AbortBeforeStop \/ TimeoutAfterStop
Spec == Init /\ [][Next]_vars
FairSpec == Spec /\ WF_vars(Deadline) /\ WF_vars(BeginStop) /\ WF_vars(GracefulUnmount)
            /\ WF_vars(TakeSnapshot) /\ WF_vars(AbortBeforeStop) /\ WF_vars(TimeoutAfterStop)
SnapshotSafe == \A e \in s.snapshotAudit : ~e.mounted /\ ~e.work
FailureSourceSafe == s.phase = "failed" => s.running /\ s.mounted /\ ~s.gate /\ s.snapshotAudit = {}
BlockedSafe == s.phase = "blocked" => s.gate /\ ~s.running /\ s.snapshotAudit = {}
NoFabricatedUnmount == ~s.mounted => ~s.actualWork
TerminationOrSafeBlock == (s.phase \notin {"failed", "blocked", "snapshot"}) ~> (s.phase \in {"failed", "blocked", "snapshot"})
HungDrainAborts == (s.phase = "drain" /\ s.actualWork) ~> (s.phase = "failed" \/ ~s.actualWork)
=============================================================================
