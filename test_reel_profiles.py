"""Offline regression checks for account routing and unconfigured cut rollout."""
import datetime as dt
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from contextlib import ExitStack, redirect_stdout
from unittest.mock import Mock, patch

import reel_profiles as profiles
import reel_publisher as publisher
import reel_performance as performance

ROOT = Path(__file__).resolve().parent


class ProfileTests(unittest.TestCase):
    def test_legacy_selection_and_explicit_profiles(self):
        for env, key in [({}, "en"), ({"REEL_LANGUAGE": "ko"}, "ko"),
                         ({"REEL_LANGUAGE": "en"}, "en"),
                         *[({"REEL_ACCOUNT": key}, key) for key in profiles.PROFILES]]:
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True):
                expected = profiles.PROFILES[key]
                self.assertEqual(profiles.selected_profile(), expected)
                for filename in ("reel_publisher", "reel_performance"):
                    spec = importlib.util.spec_from_file_location("isolated_" + filename, ROOT / (filename + ".py"))
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    self.assertEqual((module.ACCOUNT, module.LANGUAGE, module.DATA.name, module.SECRET_NAME), expected)

    def test_unknown_or_conflicting_selection_fails_closed(self):
        for env in ({"REEL_ACCOUNT": "unknown"}, {"REEL_ACCOUNT": ""},
                    {"REEL_LANGUAGE": "cut"}, {"REEL_ACCOUNT": "cut", "REEL_LANGUAGE": "en"}):
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True):
                with self.assertRaises(RuntimeError):
                    profiles.selected_profile()

    def test_all_credentials_are_separate(self):
        values = {key: {"username": row[0], "user_id": str(i), "access_token": "TEST_ONLY_" + key}
                  for i, (key, row) in enumerate(profiles.PROFILES.items(), 1)}
        env = {row[3]: json.dumps({"accounts": {row[0]: values[key]}} if key == "ko" else values[key])
               for key, row in profiles.PROFILES.items()}
        with patch.dict(os.environ, env, clear=True):
            for key, (account, _, _, secret) in profiles.PROFILES.items():
                self.assertEqual(profiles.read_credentials(account, secret), values[key])

    def test_missing_cut_secret_never_falls_back_to_existing_accounts(self):
        with patch.dict(os.environ, {"IG_SECRETS_JSON": "{}", "IG_EN_SECRETS_JSON": "{}"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "secret is missing"):
                profiles.read_credentials("phyedu.cut", "IG_CUT_SECRETS_JSON")

    def test_malformed_or_wrong_cut_secret_is_sanitized(self):
        for raw in ("not-json", "null", "[]", '"TEST_ONLY"', "{}",
                    json.dumps({"accounts": {"phyedu.cut": {}}}),
                    json.dumps({"username": "phyedu_en", "user_id": "123", "access_token": "TEST_ONLY"}),
                    json.dumps({"username": "phyedu.cut", "user_id": "bad", "access_token": "TEST_ONLY"})):
            with self.subTest(raw_type=type(raw).__name__), patch.dict(os.environ, {"IG_CUT_SECRETS_JSON": raw}, clear=True):
                with self.assertRaises(RuntimeError) as error:
                    profiles.read_credentials("phyedu.cut", "IG_CUT_SECRETS_JSON")
                self.assertNotIn("TEST_ONLY", str(error.exception))

    def test_workflows_route_secrets_and_preserve_fallback(self):
        groups = []
        for key, (_, _, directory, secret) in profiles.PROFILES.items():
            text = (ROOT / ".github/workflows" / (directory + ".yml")).read_text(encoding="utf-8")
            self.assertIn("7,27,47 8-14 * * 1-5", text)
            self.assertIn("options: [check, plan, publish, reconcile]", text)
            self.assertIn("python reel_publisher.py --auto", text)
            self.assertIn("secrets." + secret, text)
            self.assertIn("REEL_ACCOUNT: cut" if key == "cut" else "REEL_LANGUAGE: " + key, text)
            for other in profiles.PROFILES.values():
                if other[3] != secret:
                    self.assertNotIn("secrets." + other[3], text)
            groups.append(next(line.strip() for line in text.splitlines() if "group:" in line))
        self.assertEqual(len(set(groups)), 3)
        text = (ROOT / ".github/workflows/reel-performance.yml").read_text(encoding="utf-8")
        self.assertIn("25 */3 * * *", text)
        self.assertIn("REEL_ACCOUNT: cut", text)
        self.assertIn("secrets.IG_CUT_SECRETS_JSON", text)
        self.assertLess(text.index("Capture English samples"), text.index("Capture cut samples"))


class CutTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.data = Path(self.stack.enter_context(tempfile.TemporaryDirectory(dir=ROOT)))
        self.stack.enter_context(patch.dict(os.environ, {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "owner/repo"}, clear=True))
        for module in (publisher, performance):
            for name, value in {"ACCOUNT": "phyedu.cut", "LANGUAGE": "ko", "DATA": self.data,
                                "QUEUE": self.data / "queue.json", "SECRET_NAME": "IG_CUT_SECRETS_JSON"}.items():
                self.stack.enter_context(patch.object(module, name, value))
        self.stack.enter_context(patch.object(publisher, "LOG", self.data / "UPLOAD.log"))
        self.stack.enter_context(patch.object(performance, "PERFORMANCE", self.data / "performance.json"))
        self.at = dt.datetime(2026, 11, 24, 17, tzinfo=publisher.KST)
        self.stack.enter_context(patch.object(publisher, "now", return_value=self.at))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        # Real cut queue header; scenarios start from an empty queue in a temp directory.
        self.q = dict(json.loads((ROOT / "shorts-cut/queue.json").read_text(encoding="utf-8")), queue=[], done=[])
        self.args = types.SimpleNamespace(plan=False, check=False, auto=True, slot=None, reconcile=False)
        self.c = {"username": "phyedu.cut", "user_id": "123", "access_token": "TEST_ONLY", "obtained_at": self.at.isoformat()}
        publisher.save_queue(self.q)

    def test_initial_empty_queue_loads_with_existing_policy(self):
        self.assertEqual(publisher.load_queue(), self.q)
        self.assertEqual(self.q["queue"], [])
        self.assertEqual(self.q["done"], [])
        self.assertFalse(self.q["paused"])

    def test_real_cut_queue_passes_exam_reading_policy(self):
        data = ROOT / "shorts-cut"
        with patch.object(publisher, "DATA", data), patch.object(publisher, "QUEUE", data / "queue.json"):
            q = publisher.load_queue()
        self.assertTrue(q["queue"])
        for item in q["queue"]:
            self.assertEqual(item["content_policy"]["mode"], "exam_reading")
            self.assertEqual(item["slot"], "A")

    def test_wrong_queue_account_rejected(self):
        for account in ("phyedu_net", "phyedu_en"):
            publisher.save_queue(dict(self.q, account=account))
            with self.assertRaisesRegex(RuntimeError, "account/timezone"):
                publisher.load_queue()

    def test_empty_unconfigured_publish_and_plan_have_no_side_effects(self):
        with patch.object(publisher, "API") as api, patch.object(publisher, "persist") as persist, \
             patch.object(publisher, "credentials") as credentials, patch.object(publisher, "refresh_if_due") as refresh:
            self.assertEqual(publisher.run(self.args), 0)
            self.args.plan = True
            self.assertEqual(publisher.run(self.args), 0)
            api.assert_not_called()
            persist.assert_not_called()
            credentials.assert_not_called()
            refresh.assert_not_called()
        self.assertEqual(publisher.load_queue(), self.q)

    def test_unconfigured_check_fails_without_network(self):
        self.args.check = True
        with patch.object(publisher, "API") as api:
            with self.assertRaisesRegex(RuntimeError, "secret is missing"):
                publisher.run(self.args)
            api.assert_not_called()

    def test_due_item_without_secret_fails_without_publication(self):
        self.q["queue"] = [{"slot": "A", "scheduled_at": self.at.isoformat()}]
        with patch.object(publisher, "load_queue", return_value=self.q), \
             patch.object(publisher, "media", return_value=(self.data / "test.mp4", "caption")), \
             patch.object(publisher, "API") as api, patch.object(publisher, "persist") as persist:
            with self.assertRaisesRegex(RuntimeError, "secret is missing"):
                publisher.run(self.args)
            api.assert_not_called()
            persist.assert_not_called()

    def test_live_cut_identity_requires_username_and_id(self):
        api = object.__new__(publisher.API)
        api.c = self.c
        for data, valid in [({"id": "123", "username": "phyedu.cut"}, True),
                            ({"id": "456", "user_id": "123", "username": "phyedu.cut"}, True),
                            ({"id": "123", "username": "phyedu_net"}, False),
                            ({"id": "456", "username": "phyedu.cut"}, False)]:
            with patch.object(api, "call", return_value=data):
                if valid:
                    api.verify()
                else:
                    with self.assertRaisesRegex(RuntimeError, "phyedu.cut"):
                        api.verify()

    def test_cut_refresh_updates_only_dedicated_secret(self):
        response = Mock(ok=True)
        response.json.return_value = {"access_token": "REFRESHED_TEST_ONLY", "expires_in": 3600}
        with patch.dict(os.environ, {"GH_TOKEN": "TEST_ONLY"}), \
             patch("requests.get", return_value=response) as get, \
             patch.object(publisher.subprocess, "run", return_value=Mock(returncode=0)) as run:
            updated = publisher.refresh_if_due(dict(self.c, obtained_at=(self.at-dt.timedelta(days=8)).isoformat()))
            self.assertEqual(updated["username"], "phyedu.cut")
            get.assert_called_once()
            self.assertEqual(run.call_args.args[0], ["gh", "secret", "set", "IG_CUT_SECRETS_JSON", "--repo", "owner/repo"])
            self.assertEqual(json.loads(run.call_args.kwargs["input"])["access_token"], "REFRESHED_TEST_ONLY")

    def test_cut_unpublished_intent_uses_shared_recovery_without_publish(self):
        row = {"id": "test-cut", "creation_id": "c1", "publish_requested_at": (self.at-dt.timedelta(minutes=15)).isoformat()}
        self.q["queue"] = [row]
        self.q["paused"] = True
        self.args.reconcile = True
        api = Mock()
        api.recent.return_value = []
        api.container_status.return_value = {"id": "c1", "status_code": "FINISHED"}
        with patch.object(publisher, "load_queue", return_value=self.q), \
             patch.object(publisher, "media", return_value=(self.data / "test.mp4", "caption")), \
             patch.object(publisher, "credentials", return_value=self.c), \
             patch.object(publisher, "API", return_value=api), patch.object(publisher, "persist"):
            self.assertEqual(publisher.run(self.args), 0)
        api.verify.assert_called_once()
        api.create.assert_not_called()
        api.publish.assert_not_called()
        self.assertNotIn("publish_requested_at", row)
        self.assertEqual(row["reconciliation_retries"], 1)
        self.assertFalse(self.q["paused"])

    def collect(self, *args):
        with patch("sys.argv", ["reel_performance.py", *args]):
            performance.main()

    def test_empty_unconfigured_performance_has_no_side_effects(self):
        with patch.object(performance, "credentials") as credentials, patch.object(performance, "API") as api, \
             patch.object(performance, "read_metrics") as read, patch.object(performance, "persist") as persist:
            self.collect()
            self.collect("--dry-run")
            credentials.assert_not_called()
            api.assert_not_called()
            read.assert_not_called()
            persist.assert_not_called()
        self.assertFalse(performance.PERFORMANCE.exists())

    def test_performance_rejects_cross_account_queue_and_report(self):
        with patch.object(performance, "read_metrics") as read:
            publisher.save_queue(dict(self.q, account="phyedu_en"))
            with self.assertRaisesRegex(RuntimeError, "performance queue"):
                self.collect()
            publisher.save_queue(self.q)
            performance.PERFORMANCE.write_text(json.dumps({"account": "phyedu_net", "samples": []}), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "performance file"):
                self.collect()
            read.assert_not_called()

    def due_history(self):
        now = dt.datetime.now(dt.timezone.utc)
        self.q["done"] = [{"id": str(window), "media_id": str(window),
                           "published_at": (now-dt.timedelta(hours=window+1)).isoformat(),
                           "content_policy": {"measurement_hours": [24, 72]}} for window in (24, 72)]
        publisher.save_queue(self.q)

    def test_due_performance_without_secret_fails_closed(self):
        self.due_history()
        with patch.object(performance, "read_metrics") as read, patch.object(performance, "persist") as persist:
            with self.assertRaisesRegex(RuntimeError, "secret is missing"):
                self.collect()
            read.assert_not_called()
            persist.assert_not_called()

    def test_performance_verifies_identity_before_reading_cut_metrics(self):
        self.due_history()
        with patch.dict(os.environ, {"IG_CUT_SECRETS_JSON": json.dumps(self.c)}), \
             patch.object(performance, "API") as api, \
             patch.object(performance, "read_metrics", return_value={"reach": 100}) as read, \
             patch.object(performance, "persist") as persist:
            api.return_value.verify.side_effect = RuntimeError("wrong identity")
            with self.assertRaisesRegex(RuntimeError, "wrong identity"):
                self.collect()
            read.assert_not_called()
            persist.assert_not_called()
            api.return_value.verify.side_effect = None
            self.collect()
            api.assert_called_with(self.c)
            self.assertEqual(read.call_count, 2)
            self.assertTrue(all(call.args[1] == "TEST_ONLY" for call in read.call_args_list))
            report = persist.call_args.args[0]
            self.assertEqual(report["account"], "phyedu.cut")
            self.assertEqual([row["window_hours"] for row in report["samples"]], [24, 72])


if __name__ == "__main__":
    unittest.main()
