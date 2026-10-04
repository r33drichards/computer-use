import copy
import datetime as dt
import importlib.util
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hack"))
import preview
import preview_lifecycle as lifecycle
import preview_publish as publish

SHA = "b" * 40
REPO = "r33drichards/computer-use"


def request(**changes):
    value = {"number": 154, "state": "open", "draft": False, "labels": [{"name": "preview"}],
             "head": {"sha": SHA, "repo": {"full_name": REPO}}}
    value.update(changes)
    return value


def ns(expires="2026-10-10T00:00:00+00:00"):
    return {"metadata": {"name": "preview-pr-154", "labels": {preview.LABEL: "154", preview.MANAGED: preview.MANAGER},
                         "annotations": {preview.EXPIRES: expires, preview.SHA: SHA}}}


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"GITHUB_REPOSITORY": REPO})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_only_current_same_repo_labelled_open_non_draft_prs_are_eligible(self):
        self.assertTrue(lifecycle.eligible(request(), SHA))
        variants = [request(state="closed"), request(draft=True), request(labels=[]),
                    request(head={"sha": SHA, "repo": None}),
                    request(head={"sha": SHA, "repo": {"full_name": "someone/fork"}})]
        for pr in variants:
            self.assertFalse(lifecycle.eligible(pr, SHA))
        self.assertFalse(lifecycle.eligible(request(), "c" * 40))

    def test_deployment_source_must_be_the_expected_successful_workflow_and_head(self):
        run = {"path": ".github/workflows/preview-build.yml", "event": "pull_request", "conclusion": "success",
               "head_repository": {"full_name": REPO}, "head_sha": SHA, "pull_requests": [{"number": 154}]}
        with patch.object(lifecycle, "github", side_effect=[run, request()]):
            self.assertEqual(lifecycle.resolve_run(123), {"pr": "154", "sha": SHA})
        for changes in ({"path": ".github/workflows/other.yml"}, {"event": "workflow_dispatch"},
                        {"conclusion": "failure"}, {"head_repository": {"full_name": "someone/fork"}}, {"pull_requests": []}):
            changed = {**run, **changes}
            with patch.object(lifecycle, "github", return_value=changed):
                self.assertIsNone(lifecycle.resolve_run(123))
        with patch.object(lifecycle, "github", side_effect=[run, request(head={"sha": "c" * 40, "repo": {"full_name": REPO}})]):
            self.assertIsNone(lifecycle.resolve_run(123))

    def test_cleanup_keeps_active_previews_and_removes_closed_or_expired_ones(self):
        now = dt.datetime(2026, 10, 3, tzinfo=dt.timezone.utc)
        for pr, current, expected in ((request(), ns(), False), (request(state="closed"), ns(), True),
                                      (request(), ns("2026-10-02T00:00:00+00:00"), True)):
            with patch.object(lifecycle, "get_namespace", return_value=current), patch.object(lifecycle, "get_pr", return_value=pr), \
                    patch.object(lifecycle, "remove") as remove, patch.object(preview, "sync_edge"), patch.object(lifecycle, "gc_image_tags"):
                lifecycle.cleanup("154", now)
                self.assertEqual(remove.called, expected)

    def test_api_failure_does_not_delete_an_environment(self):
        with patch.object(lifecycle, "get_namespace", return_value=ns()), \
                patch.object(lifecycle, "get_pr", side_effect=subprocess.CalledProcessError(1, "gh")), \
                patch.object(lifecycle, "remove") as remove:
            with self.assertRaises(subprocess.CalledProcessError):
                lifecycle.cleanup("154")
            remove.assert_not_called()

    def test_wrong_ownership_refuses_namespace_mutation(self):
        wrong = ns()
        wrong["metadata"]["labels"][preview.MANAGED] = "production"
        with patch.object(preview, "kubectl", return_value=json.dumps(wrong)):
            with self.assertRaises(ValueError):
                lifecycle.get_namespace("154")

    def test_existing_signing_keys_survive_deploy_updates(self):
        with patch.object(preview, "kubectl", return_value='{"kind":"Secret"}') as kube:
            lifecycle.ensure_secret("154", "api-tokens", ["signing-key"])
            self.assertEqual(kube.call_count, 1)
        with patch.object(preview, "kubectl", side_effect=["", ""]) as kube:
            lifecycle.ensure_secret("154", "api-tokens", ["signing-key"])
            obj = json.loads(kube.call_args.kwargs["input"])
            self.assertEqual(obj["metadata"]["namespace"], "preview-pr-154")
            self.assertEqual(set(obj["stringData"]), {"signing-key"})
            self.assertGreater(len(obj["stringData"]["signing-key"]), 32)
            self.assertEqual(kube.call_args.args[0], "create")

    def test_stale_deploy_never_touches_the_cluster(self):
        with patch.object(lifecycle, "get_pr", return_value=request(state="closed")), patch.object(preview, "kubectl") as kube:
            lifecycle.deploy("154", SHA, {})
            kube.assert_not_called()

    def test_old_certificate_ready_condition_cannot_activate_a_preview(self):
        images = {name: f"{publish.REGISTRY}/{name}@sha256:" + "a" * 64 for name in preview.IMAGES}
        certificate = {"metadata": {"generation": 2}, "spec": {"dnsNames": ["*." + preview.DOMAIN]},
                       "status": {"conditions": [{"type": "Ready", "status": "True", "observedGeneration": 1}]}}
        with patch.object(lifecycle, "get_pr", return_value=request()), \
                patch.object(lifecycle, "get_namespace", return_value=None), \
                patch.object(preview, "kubectl", return_value=json.dumps(certificate)) as kube, \
                patch.object(lifecycle, "github") as github:
            with self.assertRaises(ValueError):
                lifecycle.deploy("154", SHA, images)
            self.assertEqual(kube.call_count, 1)
            github.assert_not_called()

    def test_publisher_cannot_target_production_or_shell_injected_names(self):
        self.assertEqual(publish.target_image("backend", "154", SHA, publish.REGISTRY), publish.REGISTRY + "/backend:pr-154-" + SHA)
        for name, number, sha, registry in (("backend", "154", SHA, publish.REGISTRY.replace("-previews", "")),
                                             ("backend;pwd", "154", SHA, publish.REGISTRY),
                                             ("backend", "154;pwd", SHA, publish.REGISTRY),
                                             ("backend", "154", "main", publish.REGISTRY)):
            with self.assertRaises(ValueError):
                publish.target_image(name, number, sha, registry)

    def test_registry_cleanup_keeps_all_live_preview_tags(self):
        active_tag = "pr-154-" + SHA
        removed_tag = "pr-155-" + SHA
        entries = [{"name": "packages/backend/tags/" + tag} for tag in (active_tag, removed_tag, "main")]
        with patch.object(preview, "live_previews", return_value=["154"]), \
                patch.object(lifecycle, "cloud_command", side_effect=[json.dumps(entries), ""] * len(preview.IMAGES)) as cloud:
            lifecycle.gc_image_tags()
        deletions = [call for call in cloud.call_args_list if "delete" in call.args]
        self.assertEqual(len(deletions), len(preview.IMAGES))
        self.assertTrue(all(removed_tag in call.args for call in deletions))
        self.assertTrue(all(active_tag not in call.args for call in deletions))

    def test_quota_and_network_policy_are_applied_before_deployments(self):
        images = {name: f"{publish.REGISTRY}/{name}@sha256:" + "a" * 64 for name in preview.IMAGES}
        kinds = [obj["kind"] for obj in preview.render("154", SHA, images)]
        self.assertLess(kinds.index("ResourceQuota"), kinds.index("Deployment"))
        self.assertLess(kinds.index("NetworkPolicy"), kinds.index("Deployment"))


if __name__ == "__main__":
    unittest.main()
