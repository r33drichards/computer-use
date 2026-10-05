---------------------------- MODULE IntentCleanup ----------------------------
EXTENDS Naturals, FiniteSets, TLC
CONSTANTS Mode, MaxEpoch, CleanupEnabled
VARIABLE s
vars == <<s>>
Init == s = [live |-> TRUE, running |-> FALSE, intent |-> "run", epoch |-> 0,
             obs |-> [valid |-> FALSE, intent |-> "run", ver |-> 0], reads |-> {},
             resumeAudit |-> {}, exists |-> TRUE, actualUID |-> 1, ownedUID |-> 1,
             committed |-> FALSE, deleting |-> FALSE, generation |-> 0,
             task |-> [valid |-> FALSE, uid |-> 1, gen |-> 0], cleanupReads |-> {},
             cleanupAudit |-> {}]
UserRequest(kind) == /\ s.live /\ s.intent # "delete" /\ s.epoch < MaxEpoch
                     /\ kind \in {"run", "stop", "billing", "delete"}
                     /\ s' = [s EXCEPT !.intent = kind, !.epoch = @ + 1]
ReadResume == /\ s.live /\ ~s.running /\ ~s.obs.valid /\ s.epoch \notin s.reads
              /\ s' = [s EXCEPT !.obs = [valid |-> TRUE, intent |-> s.intent, ver |-> s.epoch],
                         !.reads = @ \cup {s.epoch}]
ResumeFence == s.obs.valid /\ s.obs.intent = "run" /\ (Mode = "stale-resume" \/ s.obs.ver = s.epoch)
\* Audit samples the ACTUAL resource at the effect, NOT a CanResume guard.
ResumeEffect == s' = [s EXCEPT !.running = TRUE, !.obs.valid = FALSE,
                    !.resumeAudit = @ \cup {[intent |-> s.intent, ver |-> s.epoch, readVer |-> s.obs.ver]}]
ResumeAfterFork == /\ s.live /\ ~s.running /\ s.obs.ver = 0 /\ ResumeFence /\ ResumeEffect
UserResume == /\ s.live /\ ~s.running /\ s.obs.ver > 0 /\ ResumeFence /\ ResumeEffect
DiscardResume == /\ s.obs.valid
                 /\ (s.obs.intent # "run" \/ (Mode # "stale-resume" /\ s.obs.ver # s.epoch))
                 /\ s' = [s EXCEPT !.obs.valid = FALSE]
ApplyStop == /\ s.live /\ s.running /\ s.intent # "run"
             /\ s' = [s EXCEPT !.running = FALSE]
DeleteSource == /\ s.live /\ s.intent = "delete" /\ ~s.running
                /\ s' = [s EXCEPT !.live = FALSE]
ReadCleanup == /\ CleanupEnabled /\ s.exists /\ ~s.task.valid /\ s.generation \notin s.cleanupReads
               /\ s' = [s EXCEPT !.task = [valid |-> TRUE, uid |-> s.ownedUID, gen |-> s.generation],
                          !.cleanupReads = @ \cup {s.generation}]
Commit == /\ CleanupEnabled /\ s.exists /\ s.actualUID = s.ownedUID /\ ~s.committed /\ ~s.deleting
          /\ s' = [s EXCEPT !.committed = TRUE, !.generation = @ + 1]
ReplaceUID == /\ CleanupEnabled /\ s.exists /\ s.actualUID = 1
              /\ s' = [s EXCEPT !.actualUID = 2]
ChildDeleteIntent == /\ CleanupEnabled /\ s.exists /\ ~s.deleting
                     /\ s' = [s EXCEPT !.deleting = TRUE, !.generation = @ + 1]
UIDFence == Mode = "no-uid" \/ s.actualUID = s.task.uid
CommitFence == Mode = "postcommit-cleanup" \/ ((~s.committed \/ s.deleting) /\ s.generation = s.task.gen)
\* Stale jobs really attempt cleanup after commit. Audits sample live identity
\* and commit/deletion state independently, whether deletion occurs or refuses.
CleanupEffect == LET allowed == UIDFence /\ CommitFence
                     event == [deleted |-> allowed, removedUID |-> s.actualUID,
                               expectedUID |-> s.ownedUID, committed |-> s.committed,
                               deleting |-> s.deleting, taskGen |-> s.task.gen,
                               actualGen |-> s.generation]
                 IN s' = [s EXCEPT !.exists = IF allowed THEN FALSE ELSE @,
                                   !.task.valid = FALSE, !.cleanupAudit = @ \cup {event}]
CleanupAttempt == /\ s.exists /\ s.task.valid /\ ~s.committed /\ CleanupEffect
LateCleanupAttempt == /\ s.exists /\ s.task.valid /\ s.committed /\ CleanupEffect
ResumeStep == ReadResume \/ ResumeAfterFork \/ UserResume \/ DiscardResume
CleanupStep == ReadCleanup \/ CleanupAttempt \/ LateCleanupAttempt
Next == (\E kind \in {"run", "stop", "billing", "delete"} : UserRequest(kind))
        \/ ResumeStep \/ ApplyStop \/ DeleteSource \/ CleanupStep \/ Commit
        \/ ReplaceUID \/ ChildDeleteIntent
Spec == Init /\ [][Next]_vars
FairSpec == Spec /\ WF_vars(ResumeStep) /\ WF_vars(ApplyStop)
            /\ WF_vars(DeleteSource) /\ WF_vars(CleanupStep)
TypeOK == s.epoch \in 0..MaxEpoch /\ s.generation \in 0..2 /\ s.actualUID \in {1,2}
LatestIntentWins == \A e \in s.resumeAudit : e.intent = "run"
UIDDeletionSafe == \A e \in s.cleanupAudit : e.deleted => e.removedUID = e.expectedUID
HealthyChildSafe == \A e \in s.cleanupAudit : e.deleted => (~e.committed \/ e.deleting)
NoResumeAfterDeletion == ~s.live => ~s.running
SourceDeletion == (s.intent = "delete") ~> ~s.live
OwnedChildDeletion == s.deleting ~> (~s.exists \/ s.actualUID # s.ownedUID)
=============================================================================
