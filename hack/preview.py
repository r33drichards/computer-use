#!/usr/bin/env python3
"""Trusted PR namespace rendering and Pomerium route reconciliation.

Requires PyYAML 6.0.3. Never import, execute or apply files supplied by a PR.
"""
import argparse
import copy
import datetime as dt
import json
import os
import tempfile
import time
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PRODUCTION = "browserjs-sessions"
DOMAIN = "preview.computeruse.site"
LABEL = "computeruse.site/preview-pr"
MANAGED = "computeruse.site/managed-by"
MANAGER = "pr-previews"
SHA = "computeruse.site/preview-sha"
EXPIRES = "computeruse.site/preview-expires"
IMAGES = ("backend", "site", "browser", "mcp-js", "policy-operator")


def pr_number(value):
    value = str(value)
    if not re.fullmatch(r"[1-9][0-9]{0,9}", value):
        raise ValueError("PR must be a positive integer")
    return value


def namespace(pr):
    return "preview-pr-" + pr_number(pr)


def urls(pr):
    pr = pr_number(pr)
    return {name: f"https://{name}-pr-{pr}.{DOMAIN}" for name in ("app", "site", "sessions", "api")}


def documents(path):
    return [d for d in yaml.safe_load_all((ROOT / path).read_text()) if d]


def dump(value):
    return yaml.safe_dump(value, sort_keys=False)


def kubectl(*args, input=None):
    result = subprocess.run(["kubectl", *args], input=input, text=True, check=True, capture_output=True)
    return result.stdout


def allowed_policy():
    routes = documents("deploy/gke/pomerium-config.yaml")[0]["routes"]
    return copy.deepcopy(next(r["policy"] for r in routes if r["name"] == "app"))


def allowed_emails():
    # Keep one authoritative allow-list: production Pomerium's app policy.
    return [rule["email"]["is"] for policy in allowed_policy() for rule in policy["allow"]["or"]]


def routes_for(pr):
    ns, hosts = namespace(pr), urls(pr)
    backend = f"http://backend.{ns}.svc"
    common = {"preserve_host_header": True, "set_response_headers": {"X-Robots-Tag": "noindex, nofollow"}}
    def route(name, host, **options):
        return {"name": f"preview-{pr}-{name}", "from": hosts[host], "to": backend, **common, **options}
    return [
        route("upload", "sessions", regex=r"^/s-[a-z0-9]+/api/artifact-uploads/[0-9a-f]+$", allow_public_unauthenticated_access=True, timeout="5m"),
        route("vnc", "sessions", regex=r"^/s-[a-z0-9]+/vnc$", allow_public_unauthenticated_access=True, allow_websockets=True),
        route("mcp", "sessions", regex=r"^/s-[a-z0-9]+/mcp(/.*)?$", policy=allowed_policy(), pass_identity_headers=True, mcp={"server": {"max_request_bytes": 1048576}}),
        route("app", "app", policy=allowed_policy(), pass_identity_headers=True, timeout="5m"),
        route("api", "api", prefix="/v1/", allow_public_unauthenticated_access=True),
        route("token", "api", path="/oauth/token", allow_public_unauthenticated_access=True),
        route("api-mcp", "api", regex=r"^/s-[a-z0-9]+/mcp(/.*)?$", allow_public_unauthenticated_access=True, timeout="0s", idle_timeout="0s"),
        {"name": f"preview-{pr}-site", "from": hosts["site"], "to": f"http://site.{ns}.svc", "policy": allowed_policy(), "pass_identity_headers": False, "set_response_headers": {"X-Robots-Tag": "noindex, nofollow"}},
    ]


def validate_images(images):
    if set(images) != set(IMAGES):
        raise ValueError("Provide exactly the five preview image digests")
    for name, image in images.items():
        # This repository is separate from the production image registry.
        expected = f"us-west1-docker.pkg.dev/browserjs-sessions/browserjs-previews/{name}@sha256:"
        if not image.startswith(expected) or not re.fullmatch(r"[0-9a-f]{64}", image[len(expected):]):
            raise ValueError(f"Invalid preview image for {name}")


def render(pr, sha, images, now=None):
    pr, ns, hosts = pr_number(pr), namespace(pr), urls(pr)
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Expected a full commit SHA")
    validate_images(images)
    now = now or dt.datetime.now(dt.timezone.utc)
    expires = (now + dt.timedelta(days=7)).isoformat()
    result = [{"apiVersion": "v1", "kind": "Namespace", "metadata": {
        "name": ns, "labels": {LABEL: pr, MANAGED: MANAGER}, "annotations": {SHA: sha, EXPIRES: expires},
    }}]
    sources = ("deploy/base/backend.yaml", "deploy/base/networkpolicy.yaml", "deploy/base/policy-operator.yaml", "deploy/base/opa.yaml", "deploy/gke/site.yaml", "deploy/gke/session.yaml")
    for source in sources:
        for obj in documents(source):
            if obj["kind"].startswith("Cluster") or obj["kind"] == "StorageClass" or obj["metadata"]["name"] == "billing-operator":
                continue
            obj["metadata"]["namespace"] = ns
            if obj["kind"] == "RoleBinding":
                for subject in obj["subjects"]:
                    subject["namespace"] = ns
            if obj["kind"] == "Role" and obj["metadata"]["name"] == "backend":
                obj["rules"] = [r for r in obj["rules"] if not set(r["resources"]) & {"accounts", "sandboxclaims", "apitokens/status"}]
                # API token use updates its last-used status.
                obj["rules"].append({"apiGroups": ["browserjs.dev"], "resources": ["apitokens/status"], "verbs": ["patch"]})
            if obj["kind"] == "Deployment":
                spec = obj["spec"]["template"]["spec"]
                for container in spec["containers"]:
                    name = container["name"]
                    if name in images:
                        container["image"] = images[name]
                    if name == "backend":
                        keep = {"NAMESPACE", "PUBLIC_URL", "SESSION_URL_TEMPLATE", "POMERIUM_JWKS_URL", "ADMIN_EMAILS", "POLICY_OPERATOR_URL", "OPERATOR_API_TOKEN", "API_URL", "ALLOWED_EMAILS", "API_SIGNING_KEY"}
                        container["env"] = [e for e in container["env"] if e["name"] in keep]
                        changes = {"PUBLIC_URL": hosts["app"], "SESSION_URL_TEMPLATE": hosts["sessions"] + "/{id}", "POMERIUM_JWKS_URL": "https://app.computeruse.site/.well-known/pomerium/jwks.json", "ADMIN_EMAILS": ",".join(allowed_emails()), "ALLOWED_EMAILS": ",".join(allowed_emails()), "API_URL": hosts["api"], "POLICY_OPERATOR_URL": f"http://policy-operator.{ns}.svc:8080"}
                        for env in container["env"]:
                            if env["name"] in changes:
                                env["value"] = changes[env["name"]]
                        container["env"] += [{"name": k, "value": v} for k, v in {"BILLING": "off", "SNAPSHOTS": "false", "IDLE_AFTER": "5m", "READY_TIMEOUT": "5m", "MAX_SESSIONS_PER_USER": "2"}.items()]
                        # No billing catalogue, billing IDs, or optional production config.
                        spec["volumes"] = [{"name": "blueprint", "configMap": {"name": "session-blueprint"}}]
                    if name == "policy-operator":
                        container["command"] = [arg.replace("--namespace=browserjs-sessions", f"--namespace={ns}") for arg in container["command"]]
                        container["env"].append({"name": "POLICY_NAMESPACE", "value": ns})
                    if name == "opa":
                        obj["spec"]["replicas"] = 1
            if obj["kind"] == "NetworkPolicy" and obj["metadata"]["name"] in {"backend", "site"}:
                # A namespace selector AND a pod selector: no peer preview can
                # impersonate Pomerium by assigning itself the same app label.
                obj["spec"]["ingress"] = [{"from": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": PRODUCTION}}, "podSelector": {"matchLabels": {"app": "pomerium"}}}], "ports": [{"port": 8080, "protocol": "TCP"}]}]
            result.append(obj)
    blueprint = documents("deploy/gke/blueprint.yaml")[0]
    for container in blueprint["podTemplate"]["spec"]["containers"]:
        container["image"] = images[container["name"]]
        for env in container.get("env", []):
            if "value" in env:
                env["value"] = env["value"].replace("opa.browserjs-sessions.svc", f"opa.{ns}.svc")
    config = {"blueprint.yaml": dump(blueprint)}
    result.append({"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "session-blueprint", "namespace": ns}, "data": config})
    opa_config = (ROOT / "docs/contracts/policy/opa-config.yaml").read_text().replace("policy-operator.browserjs-sessions.svc", f"policy-operator.{ns}.svc")
    result.append({"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "opa-config", "namespace": ns}, "data": {"opa-config.yaml": opa_config, "system-authz.rego": (ROOT / "docs/contracts/policy/system-authz.rego").read_text()}})
    result += [
        {"apiVersion": "v1", "kind": "ResourceQuota", "metadata": {"name": "preview", "namespace": ns}, "spec": {"hard": {"pods": "10", "persistentvolumeclaims": "2", "requests.storage": "64Gi", "requests.cpu": "3", "requests.memory": "6Gi", "count/sandboxes.agents.x-k8s.io": "2", "services.loadbalancers": "0", "services.nodeports": "0"}}},
        {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy", "metadata": {"name": "default-deny", "namespace": ns}, "spec": {"podSelector": {}, "policyTypes": ["Ingress"], "ingress": []}},
    ]
    # Quotas and ingress isolation must exist before any PR image starts.
    priority = {"Namespace": 0, "ResourceQuota": 1, "NetworkPolicy": 2, "ConfigMap": 3, "ServiceAccount": 4, "Role": 4, "RoleBinding": 5, "Deployment": 7}
    return sorted(result, key=lambda obj: priority.get(obj["kind"], 6))


def live_previews(include_terminating=False):
    items = json.loads(kubectl("get", "namespaces", "-l", f"{MANAGED}={MANAGER}", "-o", "json"))["items"]
    previews = []
    for obj in items:
        pr = pr_number(obj["metadata"]["labels"][LABEL])
        if obj["metadata"]["name"] != namespace(pr):
            raise ValueError("Preview label on an unexpected namespace")
        if include_terminating or "deletionTimestamp" not in obj["metadata"]:
            previews.append(pr)
    return sorted(previews, key=int)


def merge_routes(config, previews):
    config = copy.deepcopy(config)
    config["routes"] = [r for r in config.get("routes", []) if not r.get("name", "").startswith("preview-")]
    for pr in previews:
        config["routes"].extend(routes_for(pr))
    return config


def merge_manifest_routes(docs, prs):
    """Change only the desired mounted Pomerium config; keep its hash and refs."""
    changed = copy.deepcopy(docs)
    sts = next(d for d in changed if d["kind"] == "StatefulSet" and d["metadata"]["name"] == "pomerium" and d["metadata"].get("namespace") == PRODUCTION)
    cm_name = next(v["configMap"]["name"] for v in sts["spec"]["template"]["spec"]["volumes"] if v["name"] == "config")
    cm = next(d for d in changed if d["kind"] == "ConfigMap" and d["metadata"]["name"] == cm_name and d["metadata"].get("namespace") == PRODUCTION)
    config = yaml.safe_load(cm["data"]["config.yaml"])
    merged = merge_routes(config, prs)
    if merged != config:
        cm["data"]["config.yaml"] = dump(merged)
    return changed


def reconcile_manifest_file(path):
    docs = list(yaml.safe_load_all(path.read_text()))
    changed = merge_manifest_routes(docs, live_previews())
    if changed != docs:
        path.write_text(yaml.safe_dump_all(changed, sort_keys=False))
        return True
    return False


def wait_edge_sync(revision, timeout=600):
    # A route-only commit needs an exact successful sync. Unrelated production
    # rollout health is gated by the release workflow, not preview deployment.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app = json.loads(kubectl("-n", "argocd", "get", "application", "computer-use-production", "-o", "json"))
        status = app.get("status", {})
        sync = status.get("sync", {})
        operation = status.get("operationState", {})
        phase = operation.get("phase")
        if operation.get("syncResult", {}).get("revision") == revision and phase in {"Failed", "Error"}:
            raise RuntimeError("Argo CD preview route sync failed")
        if (sync.get("revision") == revision and sync.get("status") == "Synced"
                and not app.get("operation") and phase not in {"Running", "Terminating"}):
            return
        time.sleep(5)
    raise TimeoutError("Argo CD did not sync the preview routes before the deadline")


def sync_gitops_edge():
    # The normal push is a compare-and-swap: refuse to overwrite another writer.
    # Trusted lifecycle and production releases also share a workflow lock.
    def git(*args):
        return subprocess.check_output(["git", *args], text=True).strip()
    git("fetch", "--quiet", "origin", "production")
    with tempfile.TemporaryDirectory(prefix="preview-edge-") as directory:
        tree = str(Path(directory) / "tree")
        git("worktree", "add", "--quiet", "--detach", tree, "FETCH_HEAD")
        try:
            if not reconcile_manifest_file(Path(tree) / "production/manifests.yaml"):
                return
            git("-C", tree, "config", "user.name", "github-actions[bot]")
            git("-C", tree, "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
            git("-C", tree, "add", "production/manifests.yaml")
            git("-C", tree, "commit", "-m", "Reconcile live PR preview routes")
            git("-C", tree, "push", "origin", "HEAD:refs/heads/production")
            revision = git("-C", tree, "rev-parse", "HEAD")
        finally:
            git("worktree", "remove", "--force", tree)
    kubectl("-n", "argocd", "annotate", "application", "computer-use-production", "argocd.argoproj.io/refresh=hard", "--overwrite")
    wait_edge_sync(revision)


def sync_edge():
    if os.environ.get("ARGOCD_ENABLED") == "true":
        return sync_gitops_edge()
    # Legacy manual deployments use the actual mounted ConfigMap.
    sts = json.loads(kubectl("-n", PRODUCTION, "get", "statefulset", "pomerium", "-o", "json"))
    cm_name = next(v["configMap"]["name"] for v in sts["spec"]["template"]["spec"]["volumes"] if v["name"] == "config")
    cm = json.loads(kubectl("-n", PRODUCTION, "get", "configmap", cm_name, "-o", "json"))
    config = yaml.safe_load(cm["data"]["config.yaml"])
    changed = merge_routes(config, live_previews())
    if config == changed:
        return
    cm["data"]["config.yaml"] = dump(changed)
    kubectl("replace", "-f", "-", input=json.dumps(cm))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    renderer = sub.add_parser("render")
    renderer.add_argument("--pr", required=True)
    renderer.add_argument("--sha", required=True)
    renderer.add_argument("--images", type=Path, required=True)
    sub.add_parser("sync-edge")
    manifests = sub.add_parser("reconcile-manifests")
    manifests.add_argument("--file", type=Path, required=True)
    prepare = sub.add_parser("prepare-edge")
    prepare.add_argument("--file", type=Path, default=ROOT / "deploy/gke/pomerium-config.yaml")
    args = parser.parse_args()
    if args.command == "render":
        print(yaml.safe_dump_all(render(args.pr, args.sha, json.loads(args.images.read_text())), sort_keys=False))
    elif args.command == "sync-edge":
        sync_edge()
    elif args.command == "reconcile-manifests":
        reconcile_manifest_file(args.file)
    else:
        args.file.write_text(dump(merge_routes(yaml.safe_load(args.file.read_text()), live_previews())))


if __name__ == "__main__":
    main()
