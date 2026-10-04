#!/usr/bin/env bash
# Opt-in: a real Argo CD rejection and forward Git rollback in an isolated
# namespace. Requires cluster access, gh/git push access, Python and PyYAML.
set -euo pipefail
cd "$(dirname "$0")/../.."
branch="codex/gitops-smoke-$(date +%s)"
export ARGOCD_APP=computer-use-release-test GITOPS_BRANCH="$branch"
work="$(mktemp -d)"
# Refuse to touch a namespace left by someone else's test.
if kubectl get namespace gitops-smoke >/dev/null 2>&1; then
  echo 'gitops-smoke already exists; refusing to reuse it' >&2
  exit 1
fi
cleanup() {
  kubectl -n argocd delete application "$ARGOCD_APP" --ignore-not-found >/dev/null || true
  kubectl -n argocd delete appproject gitops-smoke --ignore-not-found >/dev/null || true
  kubectl delete namespace gitops-smoke --ignore-not-found --wait=false >/dev/null || true
  git push origin --delete "$branch" >/dev/null 2>&1 || true
  git worktree remove --force "$work/tree" 2>/dev/null || true
  rm -rf "$work"
}
trap cleanup EXIT
git worktree add --quiet --detach "$work/tree" origin/main
mkdir -p "$work/tree/production"
cat > "$work/tree/production/manifests.yaml" <<'YAML'
apiVersion: v1
kind: ConfigMap
metadata:
  name: release-smoke
  namespace: gitops-smoke
data:
  result: healthy
YAML
git -C "$work/tree" add production
git -C "$work/tree" commit -m 'GitOps test: healthy desired state'
good="$(git -C "$work/tree" rev-parse HEAD)"
git -C "$work/tree" push origin "HEAD:refs/heads/$branch"
python3 - "$branch" > "$work/application.yaml" <<'PY'
import sys, yaml
project, app = list(yaml.safe_load_all(open('deploy/argocd/application.yaml')))
project['metadata']['name'] = 'gitops-smoke'
project['spec']['destinations'][0]['namespace'] = 'gitops-smoke'
app['metadata']['name'] = 'computer-use-release-test'
app['spec']['project'] = 'gitops-smoke'
app['spec']['destination']['namespace'] = 'gitops-smoke'
app['spec']['source']['targetRevision'] = sys.argv[1]
print(yaml.safe_dump_all([project, app], sort_keys=False))
PY
kubectl create namespace gitops-smoke
kubectl apply -f "$work/application.yaml"
python3 hack/gitops/wait.py "$good" 180
sed 's/result: healthy/result: [invalid, configmap, value]/' "$work/tree/production/manifests.yaml" > "$work/bad.yaml"
mv "$work/bad.yaml" "$work/tree/production/manifests.yaml"
git -C "$work/tree" add production
git -C "$work/tree" commit -m 'GitOps test: intentionally invalid desired state'
bad="$(git -C "$work/tree" rev-parse HEAD)"
git -C "$work/tree" push origin "HEAD:refs/heads/$branch"
kubectl -n argocd annotate application "$ARGOCD_APP" argocd.argoproj.io/refresh=hard --overwrite
if python3 hack/gitops/wait.py "$bad" 180; then
  echo 'Invalid release was accepted' >&2
  exit 1
fi
# Restore with exactly the same script used by production CI.
hack/gitops/rollback.sh "$bad" "$good"
[ "$(kubectl -n gitops-smoke get configmap release-smoke -o jsonpath='{.data.result}')" = healthy ]
echo 'GitOps integration: invalid release rejected; forward Git rollback synced healthy.'
