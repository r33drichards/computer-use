"""Offline isolation and lifecycle contract checks: python3 -m unittest discover -s test/preview."""
import copy
import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("preview", ROOT / "hack/preview.py")
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)
IMAGES = {name: f"us-west1-docker.pkg.dev/browserjs-sessions/browserjs-previews/{name}@sha256:" + "a" * 64 for name in preview.IMAGES}


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.objects = preview.render("154", "b" * 40, IMAGES)

    def get(self, kind, name):
        return next(o for o in self.objects if o["kind"] == kind and o["metadata"]["name"] == name)

    def test_only_namespaced_resources_and_own_service_accounts(self):
        for obj in self.objects:
            self.assertNotIn(obj["kind"], {"CustomResourceDefinition", "ClusterRole", "ClusterRoleBinding", "StorageClass"})
            if obj["kind"] != "Namespace":
                self.assertEqual(obj["metadata"]["namespace"], "preview-pr-154")
            if obj["kind"] == "RoleBinding":
                self.assertTrue(all(s["namespace"] == "preview-pr-154" for s in obj["subjects"]))
        self.assertFalse(any(o["metadata"]["name"] in {"pomerium", "dex", "billing-operator"} for o in self.objects))

    def test_backend_has_no_billing_warm_pool_or_production_secrets(self):
        spec = self.get("Deployment", "backend")["spec"]["template"]["spec"]
        env = {e["name"]: e for e in spec["containers"][0]["env"]}
        self.assertEqual(env["BILLING"]["value"], "off")
        self.assertEqual(env["ALLOWED_EMAILS"]["value"], "*")
        self.assertEqual(env["ADMIN_EMAILS"]["value"], preview.admin_emails())
        self.assertNotEqual(env["ADMIN_EMAILS"]["value"], "*")
        self.assertEqual(env["SNAPSHOTS"]["value"], "false")
        self.assertEqual(env["MAX_SESSIONS_PER_USER"]["value"], "2")
        self.assertNotIn("WARM_POOL", env)
        self.assertNotIn("METRONOME_API_TOKEN", env)
        self.assertNotIn("STRIPE_API_KEY", env)
        self.assertIn("app-pr-154.preview.computeruse.site", env["PUBLIC_URL"]["value"])
        self.assertEqual(spec["volumes"], [{"name": "blueprint", "configMap": {"name": "session-blueprint"}}])

    def test_real_sessions_remain_gvisor_and_use_local_opa(self):
        import yaml
        blueprint = yaml.safe_load(self.get("ConfigMap", "session-blueprint")["data"]["blueprint.yaml"])
        pod = blueprint["podTemplate"]["spec"]
        self.assertEqual(pod["runtimeClassName"], "gvisor")
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertEqual(pod["serviceAccountName"], "session")
        for c in pod["containers"]:
            self.assertEqual(c["image"], IMAGES[c["name"]])
        self.assertIn("opa.preview-pr-154.svc", json.dumps(pod))
        self.assertNotIn("opa.browserjs-sessions.svc", json.dumps(pod))
        self.assertIn("policy-operator.preview-pr-154.svc", self.get("ConfigMap", "opa-config")["data"]["opa-config.yaml"])

    def test_cross_namespace_ingress_requires_production_pomerium(self):
        for name in ("backend", "site"):
            source = self.get("NetworkPolicy", name)["spec"]["ingress"][0]["from"][0]
            self.assertEqual(source["namespaceSelector"]["matchLabels"]["kubernetes.io/metadata.name"], "browserjs-sessions")
            self.assertEqual(source["podSelector"]["matchLabels"]["app"], "pomerium")

    def test_caps_sessions_and_disk(self):
        hard = self.get("ResourceQuota", "preview")["spec"]["hard"]
        self.assertEqual(hard["persistentvolumeclaims"], "2")
        self.assertEqual(hard["count/sandboxes.agents.x-k8s.io"], "2")
        self.assertEqual(hard["requests.storage"], "64Gi")

    def test_invalid_identifiers_and_production_images_are_refused(self):
        for pr in ("0", "-1", "154;echo bad", "../production", "000154"):
            with self.assertRaises(ValueError):
                preview.namespace(pr)
        bad = copy.deepcopy(IMAGES)
        bad["backend"] = bad["backend"].replace("browserjs-previews", "browserjs")
        with self.assertRaises(ValueError):
            preview.render("154", "b" * 40, bad)
        with self.assertRaises(ValueError):
            preview.render("154", "main", IMAGES)

    def test_routes_are_exact_authenticated_and_do_not_change_production(self):
        original = preview.documents("deploy/gke/pomerium-config.yaml")[0]
        merged = preview.merge_routes(original, ["154", "155"])
        self.assertEqual(merged["routes"][:len(original["routes"])], original["routes"])
        self.assertEqual(preview.merge_routes(merged, []), original)
        self.assertEqual(preview.merge_routes(merged, ["154", "155"]), merged)
        for route in merged["routes"][len(original["routes"]):]:
            self.assertNotIn("*", route["from"])
            if route["name"].endswith(("-app", "-site", "-mcp")) and not route["name"].endswith("-api-mcp"):
                self.assertEqual(route["policy"], preview.allowed_policy())
        self.assertEqual(len(preview.routes_for("154")), 8)

    def test_route_sync_accepts_progressing_production_at_exact_synced_revision(self):
        app = {"status": {"sync": {"revision": "a" * 40, "status": "Synced"}, "health": {"status": "Progressing"}, "operationState": {"phase": "Succeeded"}}}
        with patch.object(preview, "kubectl", return_value=json.dumps(app)):
            preview.wait_edge_sync("a" * 40)

    def test_route_sync_rejects_failed_operation_and_waits_for_exact_revision(self):
        app = {"status": {"sync": {"revision": "b" * 40, "status": "Synced"}, "operationState": {"phase": "Failed", "syncResult": {"revision": "a" * 40}}}}
        with patch.object(preview, "kubectl", return_value=json.dumps(app)):
            with self.assertRaises(RuntimeError):
                preview.wait_edge_sync("a" * 40)
        app["status"]["operationState"] = {"phase": "Succeeded"}
        with patch.object(preview, "kubectl", return_value=json.dumps(app)), patch.object(preview.time, "monotonic", side_effect=[0, 0, 601]), patch.object(preview.time, "sleep"):
            with self.assertRaises(TimeoutError):
                preview.wait_edge_sync("a" * 40)

    def test_gitops_changes_only_mounted_config_and_preserves_hash(self):
        import yaml
        config = preview.documents("deploy/gke/pomerium-config.yaml")[0]
        sts = {"kind": "StatefulSet", "metadata": {"name": "pomerium", "namespace": preview.PRODUCTION}, "spec": {"template": {"spec": {"volumes": [{"name": "config", "configMap": {"name": "pomerium-config-hash"}}]}}}}
        cm = {"kind": "ConfigMap", "metadata": {"name": "pomerium-config-hash", "namespace": preview.PRODUCTION}, "data": {"config.yaml": preview.dump(config)}}
        unrelated = {"kind": "Secret", "metadata": {"name": "unrelated"}, "data": {"key": "unchanged"}}
        docs = [sts, cm, unrelated]
        result = preview.merge_manifest_routes(docs, ["154"])
        self.assertEqual(result[0], sts)
        self.assertEqual(result[2], unrelated)
        self.assertEqual(result[1]["metadata"], cm["metadata"])
        self.assertEqual(yaml.safe_load(result[1]["data"]["config.yaml"]), preview.merge_routes(config, ["154"]))
        self.assertEqual(preview.merge_manifest_routes(result, ["154"]), result)
        self.assertEqual(preview.merge_manifest_routes(result, []), docs)
        self.assertEqual(docs[1], cm)

    def test_sync_follows_mounted_configmap_and_preserves_resource_version(self):
        original = preview.documents("deploy/gke/pomerium-config.yaml")[0]
        import yaml
        sts = {"spec": {"template": {"spec": {"volumes": [{"name": "config", "configMap": {"name": "pomerium-config-hash"}}]}}}}
        cm = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"resourceVersion": "123"}, "data": {"config.yaml": yaml.safe_dump(original)}}
        namespaces = {"items": [{"metadata": {"name": "preview-pr-154", "labels": {preview.LABEL: "154"}}}]}
        with patch.object(preview, "kubectl", side_effect=[json.dumps(sts), json.dumps(cm), json.dumps(namespaces), ""]) as kube:
            preview.sync_edge()
        self.assertIn("pomerium-config-hash", kube.call_args_list[1].args)
        saved = json.loads(kube.call_args_list[-1].kwargs["input"])
        self.assertEqual(saved["metadata"]["resourceVersion"], "123")
        self.assertEqual(len(yaml.safe_load(saved["data"]["config.yaml"])["routes"]), len(original["routes"]) + 8)


if __name__ == "__main__":
    unittest.main()
