## Scope: draft, limited fence consumers — disk fork remains unavailable

Integrates consumption of already-initialized UID-bound source fences into backend proxy dispatch and lifecycle CAS. This is NOT a functioning automatic-pause/CSI fork, all-route atomic legacy admission, or quiescence proof. POST fork and operation GET stay501; runtime Begin/initialization/pause unsupported. Legacy traffic is not retroactively tracked.

- Persist unresolved receipt before tracked-source reverse proxy/manual browser/files dispatch; never ACK on HTTP completion/expired marks/log-done.
- Consume gates in source CAS mutations; journal refused attempted user/billing/delete intent; sticky delete while fenced. Guard before snapshot/cleanup; final source delete uses UID/resourceVersion preconditions.
- Preserve owner authorization, APIHost existing read/write scopes and unbound-token checks. No new credential flow, guest host-OAuth secret, RBAC/cloud/deploy/enable switch.
- Tests exercise real fake-backend dispatch incl app files/valid-ticket VNC, lifecycle refusals, missing provider, CAS/restart/lost response and wrong UID.

## Validation

Recovered and independently checked all20 source hashes from the latest completed prior validator; lock free/no validator still running. Final locked CPU1/GOMEMLIMIT384MiB targeted run aeb87f15-12c7-4a6e-8ef8-6e27ec8d7e34: core and full sessions tests, focused proxy ForkFence/API DiskFork/auth DiskFork all passed,21 source/module hashes unchanged (ADMISSION-VALIDATION.json). Focused vet of these five packages and core race tests passed in3763f821-4850-4be4-bf2e-a9a5dd510a4f (ADMISSION-FOCUSED-CHECKS.json). go mod tidy passed; only existing json-patch dependency promoted indirect→direct at same version.

**Local full backend/server/race suite NOT checked.** Existing public backend-tests workflow must run supported ubuntu runner and independent review is required before merge. Historical desktop interrupted/ENOSPC validators are not passes. No605-library warming in this finalization.

Formal handoff preserves28 source/config/runner/tool-hash-bound TLC expectations:5 v1 correct,9 v2 correct,10 unsafe mutants and4 reachability probes. Separate bounded models, not composition/refinement/production proof; older broad/liveness-races interrupted/timeout attempts remain non-passes. No tool/generated binary or credential committed.

## Known blockers and next reviewed contract

Existing VNC/streams/processes are not revoked by new-dispatch fencing. Policy different-CRD checks and GKE snapshot/claim cleanup prechecks are not source-CAS transactions; indirect cleanup is not a complete UID-safe fork-cleanup protocol. Additional live-source reads affect performance/availability.

Pinned mcp-exec86a6aee... explicitly ends execution at parent exit while detached descendants can continue. No atomic provider close-admission+epoch/positive descendant certificate. Process group, parent/log-done, expiry or proc scan alone cannot prove drain. Same-UID hostile guest can kill/spoof provider; forged/replayed ACK/epoch/restart/orphan uncertainty must fail closed. Unprivileged subreaper direction needs independent design review before a pinned patch in this same worktree, not assumed proof. External actual PodUID/container-death and real unmount proof is essential before CSI.

Next increments require durable least-privilege CRD/separate controller (no broad ConfigMap journal grant), shared create/fork cap+billing+same-owner transaction, all V8/browser/VNC admission, graceful Chrome/SecretService shutdown, fenced latest-intent resume, independently restored CSI PVC+cold child with fresh identity/policy/no host secrets, inaccessible-until-commit and UID-safe snapshot/PVC/child cleanup. Live CSI class/controller/restore+independent-write/delete E2E remains unverified. Docs include explicit contract/refinement/adversarial test and live plan.

**Draft only. No merge, enablement, deployment or live cluster resources in this lane.**
