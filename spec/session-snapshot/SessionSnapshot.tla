-------------------------- MODULE SessionSnapshot --------------------------
EXTENDS Naturals

(* One sleep/wake cycle. The checkpoint includes process memory but not the
   persistent volume. Current postCheckpoint: resume permits writes between
   checkpoint and suspension, including writes during graceful shutdown.
   Chrome rotates a file referenced by checkpointed memory; the database
   advances its log while the checkpoint retains the old writer position.
   The database corruption action is an explicit hypothesis, not a model of
   sled internals or proof of the observed corruption's historical cause. *)
CONSTANTS FreezeAfterCheckpoint, RotateChromeFile, AdvanceDatabase, MaxWrites,
          PairDiskSnapshot, AtomicPairCapture
VARIABLES phase, chromeFile, dbEpoch, memoryFile, memoryEpoch,
          snapshotFile, snapshotEpoch, writes, restoreAttempts, missingFile,
          databaseCorrupt, diskSnapshotFile, diskSnapshotEpoch, diskCaptured

vars == <<phase, chromeFile, dbEpoch, memoryFile, memoryEpoch,
          snapshotFile, snapshotEpoch, writes, restoreAttempts, missingFile,
          databaseCorrupt, diskSnapshotFile, diskSnapshotEpoch, diskCaptured>>

Init ==
    /\ phase = "running"
    /\ chromeFile = 0
    /\ dbEpoch = 0
    /\ memoryFile = 0
    /\ memoryEpoch = 0
    /\ snapshotFile = 0
    /\ snapshotEpoch = 0
    /\ writes = 0
    /\ restoreAttempts = 0
    /\ missingFile = FALSE
    /\ databaseCorrupt = FALSE
    /\ diskSnapshotFile = 0
    /\ diskSnapshotEpoch = 0
    /\ diskCaptured = FALSE

Checkpoint ==
    /\ phase = "running"
    /\ phase' = "checkpointed"
    /\ snapshotFile' = memoryFile
    /\ snapshotEpoch' = memoryEpoch
    /\ diskSnapshotFile' = IF PairDiskSnapshot /\ AtomicPairCapture THEN chromeFile ELSE diskSnapshotFile
    /\ diskSnapshotEpoch' = IF PairDiskSnapshot /\ AtomicPairCapture THEN dbEpoch ELSE diskSnapshotEpoch
    /\ diskCaptured' = (PairDiskSnapshot /\ AtomicPairCapture)
    /\ UNCHANGED <<chromeFile, dbEpoch, memoryFile, memoryEpoch, writes,
                    restoreAttempts, missingFile, databaseCorrupt>>

(* Separate CSI capture without a common pause can record a newer disk.
   AtomicPairCapture abstracts an orchestrator that pauses all writers,
   flushes filesystem buffers, captures both artifacts, and publishes the
   pair before resuming. It is a required contract, not a GKE API guarantee. *)
DiskCheckpoint ==
    /\ PairDiskSnapshot /\ ~AtomicPairCapture /\ ~diskCaptured
    /\ phase \in {"checkpointed", "draining"}
    /\ diskSnapshotFile' = chromeFile
    /\ diskSnapshotEpoch' = dbEpoch
    /\ diskCaptured' = TRUE
    /\ UNCHANGED <<phase, chromeFile, dbEpoch, memoryFile, memoryEpoch,
                    snapshotFile, snapshotEpoch, writes, restoreAttempts,
                    missingFile, databaseCorrupt>>

MayWrite ==
    /\ (phase = "running" \/
        (phase \in {"checkpointed", "draining"} /\ ~FreezeAfterCheckpoint))
    /\ writes < MaxWrites

(* Replace the old file and close it in the live process. Its checkpointed
   counterpart still holds the old reference. This is not disk corruption. *)
ChromeRotation ==
    /\ MayWrite /\ RotateChromeFile
    /\ chromeFile' = chromeFile + 1
    /\ memoryFile' = chromeFile'
    /\ writes' = writes + 1
    /\ UNCHANGED <<phase, dbEpoch, memoryEpoch, snapshotFile, snapshotEpoch,
                    restoreAttempts, missingFile, databaseCorrupt, diskSnapshotFile, diskSnapshotEpoch, diskCaptured>>

DatabaseAppend ==
    /\ MayWrite /\ AdvanceDatabase
    /\ dbEpoch' = dbEpoch + 1
    /\ memoryEpoch' = dbEpoch'
    /\ writes' = writes + 1
    /\ UNCHANGED <<phase, chromeFile, memoryFile, snapshotFile, snapshotEpoch,
                    restoreAttempts, missingFile, databaseCorrupt, diskSnapshotFile, diskSnapshotEpoch, diskCaptured>>

BeginShutdown ==
    /\ phase = "checkpointed"
    /\ phase' = "draining"
    /\ UNCHANGED <<chromeFile, dbEpoch, memoryFile, memoryEpoch, snapshotFile,
                    snapshotEpoch, writes, restoreAttempts, missingFile,
                    databaseCorrupt, diskSnapshotFile, diskSnapshotEpoch, diskCaptured>>

Suspend ==
    /\ phase = "draining"
    /\ (~PairDiskSnapshot \/ diskCaptured)
    /\ phase' = "suspended"
    /\ UNCHANGED <<chromeFile, dbEpoch, memoryFile, memoryEpoch, snapshotFile,
                    snapshotEpoch, writes, restoreAttempts, missingFile,
                    databaseCorrupt, diskSnapshotFile, diskSnapshotEpoch, diskCaptured>>

(* GKE tries the same checkpoint again after a failed restore. Bounded at
   two attempts so TLC enumerates a finite state space. *)
Restore ==
    /\ phase \in {"suspended", "restoreFailed"}
    /\ restoreAttempts < 2
    /\ restoreAttempts' = restoreAttempts + 1
    /\ memoryFile' = snapshotFile
    /\ memoryEpoch' = snapshotEpoch
    /\ chromeFile' = IF PairDiskSnapshot THEN diskSnapshotFile ELSE chromeFile
    /\ dbEpoch' = IF PairDiskSnapshot THEN diskSnapshotEpoch ELSE dbEpoch
    /\ missingFile' = (snapshotFile # chromeFile')
    /\ phase' = IF missingFile' THEN "restoreFailed" ELSE "restored"
    /\ UNCHANGED <<snapshotFile, snapshotEpoch, writes,
                    databaseCorrupt, diskSnapshotFile, diskSnapshotEpoch, diskCaptured>>

(* A stale writer may reuse a log position already advanced on disk. This
   represents the proposed corruption mechanism, not sled's implementation. *)
StaleDatabaseWrite ==
    /\ phase = "restored"
    /\ memoryEpoch # dbEpoch
    /\ databaseCorrupt' = TRUE
    /\ phase' = "databaseFailed"
    /\ UNCHANGED <<chromeFile, dbEpoch, memoryFile, memoryEpoch, snapshotFile,
                    snapshotEpoch, writes, restoreAttempts, missingFile,
                    diskSnapshotFile, diskSnapshotEpoch, diskCaptured>>

Next == Checkpoint \/ DiskCheckpoint \/ ChromeRotation \/ DatabaseAppend \/ BeginShutdown
        \/ Suspend \/ Restore \/ StaleDatabaseWrite
Spec == Init /\ [][Next]_vars

TypeOK ==
    /\ phase \in {"running", "checkpointed", "draining", "suspended",
                  "restoreFailed", "restored", "databaseFailed"}
    /\ chromeFile \in 0..MaxWrites /\ dbEpoch \in 0..MaxWrites
    /\ memoryFile \in 0..MaxWrites /\ memoryEpoch \in 0..MaxWrites
    /\ snapshotFile \in 0..MaxWrites /\ snapshotEpoch \in 0..MaxWrites
    /\ writes \in 0..MaxWrites /\ restoreAttempts \in 0..2
    /\ missingFile \in BOOLEAN /\ databaseCorrupt \in BOOLEAN
    /\ diskSnapshotFile \in 0..MaxWrites
    /\ diskSnapshotEpoch \in 0..MaxWrites
    /\ diskCaptured \in BOOLEAN

(* The requested consistency invariant: after attempting restore, memory
   must describe the persistent volume it is actually paired with. *)
RestoreUsesCompatibleDisk ==
    restoreAttempts > 0 =>
        /\ memoryFile = chromeFile
        /\ memoryEpoch = dbEpoch

NoMissingChromeFile == ~missingFile
NoDatabaseCorruption == ~databaseCorrupt
=============================================================================
