# Owner desktop disk checkpoints

The opt-in checkpoint entrypoint keeps the MCP web function name, bearer
digest and request allowlists. The desktop runtime starts fresh in a private
named Sandbox. No Sandbox tunnels, new ingress routes or host mounts; the
Modal SDK credentials used by the controller are not copied to the Sandbox.

A private Modal class serializes MCP requests and checkpoints. Its record
contains the active Sandbox ID and last disk image ID. It does not launch an
empty replacement if an earlier generation exists and has no checkpoint.
Idle checkpoint drains desktop processes, snapshots the root filesystem and
records the image before retiring the old Sandbox. It defers while the exec
service has running children. Initial rollout is disk-only; real exec after
RAM restore is not validated.

Disk images may contain browser or CLI credentials. Verify workspace and
image access before enabling the backend. Disk images expire after 30 days.
A forced host exit can lose writes since the last completed checkpoint.
Use private synthetic test fixtures, never production authentication, when
verifying the implementation.

For the private canary, set COMPUTER_USE_CHECKPOINT_TEST=1, the immutable
COMPUTER_USE_IMAGE, and COMPUTER_USE_AUTH_MODE=app-bearer, then run
checkpoint_app.py::verify with Modal CLI in the existing environment.
Canary must pass authenticated real exec on both generations and reject
anonymous MCP and direct exec. Keep the stateless app.py for rollback.
