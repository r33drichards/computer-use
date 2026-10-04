# GitHub account connections

A user connects a GitHub App authorization at `/connections`. New sessions use
that connection by default; `POST /api/sessions` accepts `"github": false` to
opt out or `"github": true` to require a valid connection. Existing sessions are
not retrofitted. Reconnecting generates a new binding, so existing sessions do
not inherit the new authorization.

## Operator setup

Register a GitHub App with:

- Callback URL: `https://<app-host>/api/connections/github/callback`.
- Expiring user access tokens enabled.
- Repository Contents read/write for clone, fetch and push. Metadata access is
  implicit. Additional permissions such as Workflows require a separate choice
  if users need to update workflow files.
- Leave “Request user authorization during installation” off: account linking
  uses the separate OAuth flow with a browser-bound state and PKCE. No private
  app key or installation tokens are used by this feature.

The user authorizes the app and installs it on their personal account or
organization, choosing its repositories. Authorization alone does not grant
private repository access. Organization installation may require approval;
SAML organizations may require an active SAML session before reauthorizing.
The repository access is the intersection of the app's and the user's access.

Provision a Kubernetes Secret `github-app` in the backend namespace through the
normal secret management process, with keys:

| Key | Backend environment |
| --- | --- |
| `client-id` | `GITHUB_CLIENT_ID` |
| `client-secret` | `GITHUB_CLIENT_SECRET` |
| `app-slug` | `GITHUB_APP_SLUG` |
| `encryption-key` | `GITHUB_ENCRYPTION_KEY` |

`encryption-key` is an independently generated, base64-encoded 32-byte random
key, not the GitHub client secret or the API signing key. Retain it across
replicas and releases: losing or changing it makes existing connections
unreadable. Do not put these values in source control. The optional Secret refs
in `deploy/base/backend.yaml` keep the feature off when no Secret is present;
a partial configuration fails startup.

Deploy the `GitHubConnection` CRD, RBAC, broker Service and NetworkPolicies with
the backend and browser image changes. The backend's service account can manage
this CRD but gains no access to Kubernetes Secrets. Account token pairs are
AES-256-GCM encrypted with the account owner as authenticated data.

The broker listens on `GITHUB_BROKER_ADDR` (default `:8082`). Its internal origin
is `GITHUB_BROKER_URL` (default
`http://github-broker.<namespace>.svc.cluster.local:8082`). The dedicated Service
and NetworkPolicies allow session pods to reach only this port; do not expose
it through an ingress or Pomerium. It accepts only session-bound bearer
credentials, never Pomerium headers or account API tokens. Traffic uses the
isolated cluster network; an HTTPS broker origin can be configured when the
cluster supplies TLS termination.

## Session behavior

Connected sessions start cold, bypassing the warm pool, so the browser
container receives its session ID, random broker credential and broker origin
at creation. The session's Sandbox stores the credential hash and connection
binding; the browser pod template contains the bootstrap credential. Treat
Sandbox specs and pod snapshots as sensitive. Public session responses never
expose these fields. Opted-out sessions retain the normal warm-pool behavior.
The binding and bootstrap environment survive stop/start, resizing and snapshot
restore. The broker requires a running, non-draining session, verifies its
credential and owner, and checks its connection binding on every request.

The image contains `git-credential-computeruse`. The entrypoint configures it
for `https://github.com` when the session is connected. Git invokes it on
clone/fetch/push; the helper requests credentials from the backend and outputs
Git's credential protocol. It does not persist GitHub tokens, follow redirects,
use user-supplied HTTP proxies or answer for other Git hosts. Long-lived refresh
tokens never enter the session. Refresh rotation uses Kubernetes resource-version
updates and a temporary lock to coordinate multiple backend replicas. An
ambiguous refresh failure or a crash between GitHub rotation and persistence
may require reconnection.

The short-lived GitHub user access token does enter the session when Git asks
for it. Commands in that session can retrieve it and use all repositories the
connection permits until expiry/revocation. This is communicated in the create
form. Per-session repository narrowing is not implemented. Commit name/email,
SSH remotes, the `gh` CLI and GitHub website browser sign-in are separate from
this Git HTTPS authentication feature.

Disconnect deletes the local connection before revoking the GitHub app grant,
blocking fresh credential requests immediately. If GitHub revocation fails, the
UI reports it and directs the user to revoke the app in GitHub settings; an
already issued token may otherwise remain valid until its eight-hour expiry.
Authorization revoked directly on GitHub is enforced by GitHub; this version
does not consume GitHub authorization webhooks. The UI shows stored connection
identity and refresh-expiry status, not a live GitHub authorization check.

## Validation

Backend tests cover encrypted storage, OAuth state/PKCE/account binding,
origin checks, browser-only connection management, session credential and
owner checks, reconnect isolation, disconnect, concurrent refresh across
replicas, and cold provisioning with resume. Python tests exercise Git's actual
credential helper interface against a local broker and verify host filtering,
no persistence operations and redirect refusal. A real GitHub App is required
for a live private-repository clone/push test.
