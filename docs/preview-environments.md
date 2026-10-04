# Pull-request environments

Each opted-in pull request gets a real backend, app, docs site, policy
operator, OPA and isolated desktop sessions in `preview-pr-<number>` on the
existing GKE cluster. This is a test environment: its disks and API tokens
are deleted when the environment closes or expires.

For PR 154 the URLs are:

| Surface | URL |
| --- | --- |
| App | `https://app-pr-154.preview.computeruse.site` |
| Docs | `https://site-pr-154.preview.computeruse.site` |
| Sessions | `https://sessions-pr-154.preview.computeruse.site/<id>/mcp` |
| Token API | `https://api-pr-154.preview.computeruse.site` |

## Isolation and limits

The five workload images are built at the PR's exact head commit. Trusted
main templates determine RBAC, network policy, session runtime and resource
limits; changes to deployment manifests or CRDs in a PR are not applied.
Pomerium, Dex, the controllers, storage class and CRDs are shared. No
production signing keys, OAuth credentials, billing secrets or user storage
are copied into the preview namespace. Session PVCs use the existing
`browserjs-zonal` storage class, whose reclaim policy is Delete.

Pomerium adds exact routes for each preview, using the same email allow-list
as the production app. The docs preview also requires sign-in. VNC tickets,
one-time artifact upload tokens and API bearer tokens are checked as in
production. Exact MCP hosts retain Pomerium's OAuth discovery support.
Preview workloads receive only preview-host identity assertions; they do
not receive production-host assertions. Routes set `X-Robots-Tag: noindex,
nofollow`.

Each namespace permits at most two Sandboxes, two PVCs and 10 GiB of disk,
10 pods, 3 requested CPU cores and 6 GiB of requested memory. These are
namespace quotas, in addition to the per-container limits in the trusted
session blueprint. Each user may create two sessions. Idle sessions sleep
after five minutes. Warm pools and Pod Snapshots are disabled: waking is a
cold start using the retained disk. Only the small session size is exposed.
Billing, Stripe and Metronome are off. Compute and disk still incur GCP
costs; the browser image build is large and can take substantially longer
than an app-only build.

This is isolation for maintainer-owned preview code, not a hostile-code
sandbox for arbitrary fork PRs. PR builds receive no cloud identity, registry
credentials or deployment secrets. Publishing and deployment execute only
trusted main scripts, in separate jobs/runners. The publisher can write only
the preview registry. The separate deployer has GKE administrator access
because namespace/RBAC creation and the shared edge ConfigMap need it;
its main-only identity must never be granted to a PR job. Neither identity
can be used by a preview pod. Production image repositories are unchanged.

## One-time setup

1. Merge and apply the infrastructure PR through the existing **infra apply**
   workflow. `enable_previews = true` creates a separate preview registry,
   publisher and deployer identities, and wildcard DNS at
   `*.preview.computeruse.site`, pointing to the existing edge address.
2. Set these repository variables from the new OpenTofu outputs:
   - `PREVIEW_REGISTRY`: `preview_registry_url`
   - `PREVIEW_PUBLISH_SA`: `preview_publisher_service_account_email`
   - `PREVIEW_DEPLOY_SA`: `preview_deployer_service_account_email`
   - `PREVIEWS_ENABLED`: `true`, after the next step succeeds.
3. Run the production **deploy** workflow on main with its existing `deploy`
   confirmation. This adds `*.preview.computeruse.site` to the existing
   Pomerium certificate. Wait for the certificate to be Ready before
   enabling preview workflows. The DNS and certificate names are deliberately
   fixed to this repository's GKE deployment, as in `deploy/gke`.
4. Merge the automation PR. Label a same-repository, non-draft PR `preview`.
   The workflow builds and creates its environment. Fork PRs are refused.

The workflows need no new repository secrets. Existing GCP Workload
Identity Federation allows the two new identities only on `refs/heads/main`.
Never broaden that condition to `refs/pull/*`.

## Lifecycle

The **preview build** workflow runs when the `preview` label is added and
on subsequent commits, reopening, or making a labelled PR ready for review.
Its artifacts contain Docker images; the trusted **preview deploy** workflow
verifies the source repository, workflow, PR label and current head SHA
before publishing or applying anything. Stale and superseded runs do not
replace a newer preview. The app and docs URLs appear in a PR comment and
GitHub deployment record, naming the exact previewed commit.

Closing or merging the PR, removing `preview`, or converting it to a draft
removes its routes and namespace. An hourly sweep repeats that reconciliation
and removes environments seven days after their last deployment. This is a
hard expiry even for open PRs, to bound forgotten environments; push another
commit or remove/re-add the label to recreate one. Namespace deletion also
removes session resources and PVCs; the disk provisioner reclaims the disks.
Image versions expire after 14 days in the preview registry. Refreshing an
old environment requires a new build so its images will not expire in use.

Reconciliation edits the ConfigMap mounted by the current production
Pomerium StatefulSet and preserves all non-preview routes. It uses
resourceVersion to detect conflicting edits. Preview lifecycle jobs and
production deployment share the `deploy` concurrency group. Production
releases include live preview routes before rendering their kustomize
ConfigMap; the hourly sweep also restores routes after a historical release
rollback. A preview is unavailable briefly while Pomerium reloads a changed
ConfigMap (Kubernetes projection is eventually consistent).

## Verification and troubleshooting

Offline checks: `python3 -m unittest discover -s test/preview` with
`PyYAML==6.0.3`. Rendered manifests must contain only the preview Namespace
and its namespaced resources; all five images must be preview-registry
digests, session runtime must be gVisor, and OPA references must stay within
the preview namespace. Tests cover preserving production routes, idempotent
reconciliation, quotas and malformed input rejection.

After setup, use an opted-in PR to verify sign-in, session creation, live
VNC, policy evaluation, API token exchange and an MCP client connection.
Then close it and verify that its namespace, PVCs and preview routes are
removed. A render and CI test do not prove these live checks.

For an unhealthy preview, inspect its pods/events with `kubectl -n
preview-pr-154 get pods,events`. No nodes available for gVisor means a cold
session must wait for the existing session pool's autoscaler. Quota errors
mean that two session disks are already allocated: delete a session before
creating another. Route recovery: from trusted main code with the deployer
identity, run `python3 hack/preview.py sync-edge`. Do not print Secret data in
public Actions logs. Failed reconciliation leaves its workflow failed for
operator attention, and the hourly sweep retries it.
