#!/usr/bin/env python3
"""Trusted main-only preview deployment, reporting and garbage collection."""
import argparse
import base64
import datetime as dt
import json
import os
import re
import secrets
import subprocess
from pathlib import Path

import preview
from preview_publish import command as cloud_command


# gh supplies authentication; neither API responses nor artifacts become code.
def github(endpoint, body=None):
    command = ["gh", "api", endpoint]
    if body is not None:
        command += ["--method", "POST", "--input", "-"]
    completed = subprocess.run(command, input=None if body is None else json.dumps(body), text=True, capture_output=True, check=True)
    return json.loads(completed.stdout) if completed.stdout.strip() else None


def repo():
    value = os.environ["GITHUB_REPOSITORY"]
    if value != "r33drichards/computer-use":
        raise ValueError("This preview deployment targets r33drichards/computer-use only")
    return value


def get_pr(number):
    return github(f"repos/{repo()}/pulls/{preview.pr_number(number)}")


def eligible(pr, sha=None):
    return (pr["state"] == "open" and not pr["draft"]
            and pr["head"]["repo"] is not None
            and pr["head"]["repo"]["full_name"] == repo()
            and any(label["name"] == "preview" for label in pr["labels"])
            and (sha is None or pr["head"]["sha"] == sha))


def resolve_run(run_id):
    run = github(f"repos/{repo()}/actions/runs/{preview.pr_number(run_id)}")
    if (run["path"] != ".github/workflows/preview-build.yml" or run["event"] != "pull_request"
            or run["conclusion"] != "success" or run["head_repository"]["full_name"] != repo()):
        return None
    candidates = run["pull_requests"]
    if len(candidates) != 1:
        return None
    pr = get_pr(candidates[0]["number"])
    if not eligible(pr, run["head_sha"]):
        return None
    return {"pr": preview.pr_number(pr["number"]), "sha": run["head_sha"]}


def outputs(values):
    with open(os.environ["GITHUB_OUTPUT"], "a") as file:
        for key, value in values.items():
            file.write(f"{key}={value}\n")


def get_namespace(pr):
    raw = preview.kubectl("get", "namespace", preview.namespace(pr), "--ignore-not-found", "-o", "json")
    if not raw.strip():
        return None
    obj = json.loads(raw)
    metadata = obj["metadata"]
    if (metadata["name"] != preview.namespace(pr)
            or metadata.get("labels", {}).get(preview.MANAGED) != preview.MANAGER
            or metadata.get("labels", {}).get(preview.LABEL) != preview.pr_number(pr)):
        raise ValueError("Refusing to touch a namespace not owned by PR previews")
    return obj


def ensure_secret(pr, name, keys):
    ns = preview.namespace(pr)
    # Existing keys survive updates. Never copy secrets from production.
    raw = preview.kubectl("-n", ns, "get", "secret", name, "--ignore-not-found", "-o", "json")
    if raw.strip():
        return
    obj = {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": name, "namespace": ns}, "type": "Opaque",
           "stringData": {key: base64.b64encode(secrets.token_bytes(32)).decode() for key in keys}}
    # create, not apply: a competing creator must not overwrite existing keys.
    preview.kubectl("create", "-f", "-", input=json.dumps(obj))


def deployment_status(pr, deployment_id, state, description):
    body = {"state": state, "description": description, "auto_inactive": state == "success"}
    if state == "success":
        body["environment_url"] = preview.urls(pr)["app"]
    github(f"repos/{repo()}/deployments/{deployment_id}/statuses", body)


def deploy(pr, sha, images):
    # Recheck after waiting for the production deployment lock, immediately
    # before cluster mutations. A closed/unlabelled or superseded PR is skipped.
    if not eligible(get_pr(pr), sha):
        print("Preview skipped: PR is no longer eligible at this commit.")
        return
    objects = preview.render(pr, sha, images)
    current = get_namespace(pr)
    if current and "deletionTimestamp" in current["metadata"]:
        raise ValueError("Previous preview namespace is still terminating; retry after its resources are deleted")
    certificate = json.loads(preview.kubectl("-n", preview.PRODUCTION, "get", "certificate", "pomerium-tls", "-o", "json"))
    if (f"*.{preview.DOMAIN}" not in certificate["spec"]["dnsNames"]
            or not any(c["type"] == "Ready" and c["status"] == "True" and c.get("observedGeneration") == certificate["metadata"]["generation"] for c in certificate.get("status", {}).get("conditions", []))):
        raise ValueError("Preview wildcard certificate is not Ready; follow docs/preview-environments.md")
    record = github(f"repos/{repo()}/deployments", {"ref": sha, "environment": preview.namespace(pr), "auto_merge": False,
                    "required_contexts": [], "transient_environment": True, "production_environment": False,
                    "description": f"Real-session preview for PR #{pr}"})
    deployment_id = record["id"]
    deployment_status(pr, deployment_id, "in_progress", "Starting isolated preview workloads")
    try:
        preview.kubectl("apply", "-f", "-", input=json.dumps(objects[0]))
        ensure_secret(pr, "api-tokens", ["signing-key"])
        ensure_secret(pr, "policy-tokens", ["bundle-token", "opa-token", "operator-api-token"])
        preview.kubectl("apply", "-f", "-", input=json.dumps({"apiVersion": "v1", "kind": "List", "items": objects[1:]}))
        # Establish routes before checking backend readiness: its JWKS fetch
        # uses the shared production edge. Projection is eventually consistent.
        preview.sync_edge()
        for name in ("policy-operator", "opa", "backend", "site"):
            preview.kubectl("-n", preview.namespace(pr), "rollout", "status", f"deployment/{name}", "--timeout=600s")
        # A PR may have closed during the rollout. Do not publish a stale URL.
        if not eligible(get_pr(pr), sha):
            deployment_status(pr, deployment_id, "inactive", "PR changed while preview was starting")
            if not eligible(get_pr(pr)):
                remove(pr)
            return
        deployment_status(pr, deployment_id, "success", f"Ready at commit {sha[:12]}")
        expires = objects[0]["metadata"]["annotations"][preview.EXPIRES]
        links = preview.urls(pr)
        text = (f"<!-- computeruse-pr-preview -->\nPreview for commit `{sha}` is ready.\n\n"
                f"[Open app]({links['app']}) · [Open docs]({links['site']})\n\n"
                f"Real desktop sessions; billing off. Test data and disks expire at {expires}, "
                "or when this PR closes, loses its `preview` label, or becomes a draft.")
        comment(pr, text)
        print(f"App: {links['app']}\nDocs: {links['site']}\nCommit: {sha}")
    except Exception:
        deployment_status(pr, deployment_id, "failure", "Preview failed; inspect the preview deploy Actions run")
        raise


def comment(pr, body):
    # Paginate so an older preview comment is updated instead of duplicated.
    page = 1
    while True:
        comments = github(f"repos/{repo()}/issues/{preview.pr_number(pr)}/comments?per_page=100&page={page}")
        for item in comments:
            if item["user"]["login"] == "github-actions[bot]" and item["body"].startswith("<!-- computeruse-pr-preview -->"):
                command = ["gh", "api", f"repos/{repo()}/issues/comments/{item['id']}", "--method", "PATCH", "--input", "-"]
                subprocess.run(command, input=json.dumps({"body": body}), text=True, check=True, capture_output=True)
                return
        if len(comments) < 100:
            break
        page += 1
    github(f"repos/{repo()}/issues/{preview.pr_number(pr)}/comments", {"body": body})


def remove(pr):
    current = get_namespace(pr)
    if not current:
        return False
    if "deletionTimestamp" not in current["metadata"]:
        preview.kubectl("delete", "namespace", preview.namespace(pr), "--wait=false")
    # Namespace is now terminating and omitted from live_previews. Remove
    # its routes now, without waiting for slow session disk finalizers.
    preview.sync_edge()
    # Deactivate all records for this one preview environment.
    records = github(f"repos/{repo()}/deployments?environment={preview.namespace(pr)}&per_page=100")
    for record in records:
        deployment_status(pr, record["id"], "inactive", "Preview removed; namespace and session disks are being deleted")
    comment(pr, "<!-- computeruse-pr-preview -->\nPreview removed. Its namespace and session disks are being deleted. "
            "To recreate an open PR's preview, add the `preview` label and push a commit (or remove/re-add the label).")
    print(f"Removed {preview.namespace(pr)}")
    return True


def gc_image_tags():
    # Keep every tag of a live preview (including previous rollout images).
    # Tagged versions cannot be swept while a session still needs them.
    # Publishing/deployment and cleanup share the workflow-level deploy lock.
    active = set(preview.live_previews())
    for name in preview.IMAGES:
        flags = ["--project=browserjs-sessions", "--location=us-west1", "--repository=browserjs-previews", f"--package={name}"]
        tags = json.loads(cloud_command("gcloud", "artifacts", "tags", "list", *flags, "--format=json"))
        for tag in tags:
            value = tag["name"].rsplit("/", 1)[-1]
            match = re.fullmatch(r"pr-([1-9][0-9]{0,9})-[0-9a-f]{40}", value)
            if match and match[1] not in active:
                cloud_command("gcloud", "artifacts", "tags", "delete", value, *flags, "--quiet")


def cleanup(pr=None, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    numbers = [preview.pr_number(pr)] if pr is not None else preview.live_previews(include_terminating=True)
    for number in numbers:
        current = get_namespace(number)
        if not current:
            continue
        # API failures propagate: inability to read a PR is not authorization
        # to delete its environment.
        request = get_pr(number)
        expires = dt.datetime.fromisoformat(current["metadata"]["annotations"][preview.EXPIRES])
        if not eligible(request) or expires <= now:
            remove(number)
    preview.sync_edge()
    gc_image_tags()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    resolver = sub.add_parser("resolve-run")
    resolver.add_argument("--run-id", required=True)
    guard = sub.add_parser("guard")
    guard.add_argument("--pr", required=True)
    guard.add_argument("--sha", required=True)
    apply = sub.add_parser("deploy")
    apply.add_argument("--pr", required=True)
    apply.add_argument("--sha", required=True)
    apply.add_argument("--images-dir", required=True, type=Path)
    clean = sub.add_parser("cleanup")
    clean.add_argument("--pr")
    args = parser.parse_args()
    if args.command == "resolve-run":
        result = resolve_run(args.run_id)
        outputs({"eligible": "true" if result else "false", **(result or {})})
    elif args.command == "guard":
        if not eligible(get_pr(args.pr), args.sha):
            raise ValueError("PR is closed, forked, draft, unlabelled or at a different SHA")
    elif args.command == "deploy":
        images = {}
        for name in preview.IMAGES:
            published = json.loads((args.images_dir / f"{name}.json").read_text())
            if published["sha"] != args.sha or published["pr"] != preview.pr_number(args.pr) or published["name"] != name:
                raise ValueError("Published image metadata does not match this deployment")
            images[name] = published["image"]
        deploy(args.pr, args.sha, images)
    else:
        cleanup(args.pr)


if __name__ == "__main__":
    main()
