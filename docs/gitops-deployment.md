# Production releases with Argo CD

Merging a reviewed pull request to `main` builds the affected images. The
`production release` workflow requires successful image publication and all
checks of that pull request's tested head. It commits rendered workload manifests
and immutable image digests to the `production` branch. Argo CD watches
`production/` on that branch and reconciles it automatically.

Argo CD owns workload reconciliation. Argo Rollouts owns backend blue-green and
site canary promotion. The backend canary requires the `release-canary` Secret;
a missing credential fails the release. The release workflow runs a canary
through the public edge before and after the update, and waits for the exact
Argo CD Git revision to become Synced and Healthy.

A failed release is restored by a **new Git commit** containing the previous
production manifests. Argo CD then reconciles that rollback, and the public
canary runs again. A Kubernetes-only rollback would be overwritten by automatic
sync. Rollback refuses to overwrite a different release that changed the branch.
The `production-stable` branch records only releases that passed; subsequent
image builds compare against this baseline so skipped or failed releases cannot
leave images behind. An older build never supersedes a newer `main` commit.

The single MCP image includes skills and follows this same release. Cluster-scoped
bootstrap infrastructure (CRDs, cluster RBAC, namespaces, StorageClasses and
snapshot storage configuration) remains under the infrastructure/bootstrap
procedure. Argo CD's project is restricted to `browserjs-sessions`.

## Failure emails

Google Cloud Monitoring sends failures to the configured
`deployment_alert_email` (currently `rwendt1337@gmail.com`). The production
release workflow writes a structured failure log before rollback. An observer
CronJob in `argocd` also checks the Application every minute, covering failed
syncs and degraded health outside CI. Its ServiceAccount can only read the one
Application. Alerts include the revision and a link to the release workflow.
Notifications are limited to one per five minutes per revision.

GitHub Actions failed-workflow emails are also enabled at the same address,
covering failures before a workflow can authenticate to Google Cloud. Argo CD
failures are reported by Cloud Monitoring even when no GitHub workflow is active.

The alert channel, policy and deployer log-writing role are defined in
`infra/main/deployment-alerts.tf`. `hack/gitops/configure-alerts.py --email ADDRESS`
configures the channel and policy idempotently when bootstrapping. The current
channel, policy and log-writing permission are recorded in infrastructure state.

## Configuration

Repository variable `ARGOCD_ENABLED=true` enables the GitOps release workflow
and prevents the old full-deploy and standalone site workflows from applying
production manifests. `CANARY=on` and secret `CANARY_API_TOKEN` are required.
The same canary token is stored as Secret `release-canary`, key `token`, in
`browserjs-sessions`. Use an admin-owned API token with `sessions:read`,
`sessions:write`, `sessions:connect`, `policies:read` and `policies:write`.
Rotate it before its expiry; no credential is stored in Git or printed in logs.

The controller installation is pinned to Argo CD v3.5.3's release commit in
`deploy/argocd/kustomization.yaml`. `application.yaml` defines its restricted
project and production Application. `alerts.yaml` defines the failure observer.
Argo CD's UI is a private ClusterIP service. Use an authenticated cluster context
and `kubectl -n argocd port-forward service/argocd-server 8080:443` to access it.
Bootstrap credentials are in the cluster's `argocd-initial-admin-secret`.

## Bootstrap and recovery

Install the controller and its settings, create the required canary Secret,
then seed `production/` with the current live image references and reviewed
workload manifests. Seed both `production` and `production-stable` before enabling
the Application. Verify Synced/Healthy and the public canary before enabling
`ARGOCD_ENABLED`. The baseline must match the running images; mutable `main`
image tags are never a release input.

For emergency recovery, commit known-good manifests to `production`, or use
`hack/gitops/rollback.sh FAILED_REVISION PREVIOUS_REVISION` from a checkout with
GitHub push access and an authenticated cluster context. Confirm Synced/Healthy
and run `test/canary.py` with `CANARY_API_TOKEN` set. To return to the old manual
workflow, first disable Argo CD auto-sync and self-heal, then disable
`ARGOCD_ENABLED`; never let both deployment systems write production together.

Canaries detect the exercised browser/session/policy paths and rollout failures.
They do not reverse data changes or prove every application behavior. Keep schema
and data changes compatible with the preceding release.

Run `test/gitops/integration.sh` with cluster and GitHub access to exercise
a failed sync and forward Git rollback in the isolated `gitops-smoke` namespace.
It never changes the production Application.
