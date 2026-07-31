import importlib.util
import json
import sys
import tempfile
import time
import unittest
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_package_module(package_name, name):
    if package_name not in sys.modules:
        package_spec = importlib.util.spec_from_file_location(
            package_name,
            ROOT / "pyUltroid" / "security" / "__init__.py",
            submodule_search_locations=[str(ROOT / "pyUltroid" / "security")],
        )
        package = importlib.util.module_from_spec(package_spec)
        sys.modules[package_name] = package
        package_spec.loader.exec_module(package)
    full_name = package_name + "." + name
    spec = importlib.util.spec_from_file_location(
        full_name, ROOT / "pyUltroid" / "security" / (name + ".py")
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


profiles = load_package_module("test_profile_security", "profiles")
load_package_module("test_status_security", "subprocess")
updater = load_package_module("test_status_security", "updater")
status = load_package_module("test_status_security", "status")


class ProfileTests(unittest.TestCase):
    def test_existing_default_preserves_all_and_new_default_is_safe(self):
        old = profiles.resolve_profiles(None, existing_install=True)
        self.assertTrue(old.legacy_all)
        new = profiles.resolve_profiles(None, existing_install=False)
        self.assertEqual(new.names, ("core", "media"))
        self.assertNotIn("devtools", new.include)

    def test_developer_requires_explicit_profile(self):
        selected = profiles.resolve_profiles("core,developer", existing_install=False)
        self.assertIn("devtools", selected.include)
        with self.assertRaises(ValueError):
            profiles.resolve_profiles("core,unknown", existing_install=False)

    def test_official_inventory_is_exact_and_assistant_games_is_separate(self):
        actual = {
            path.stem
            for path in (ROOT / "plugins").glob("*.py")
            if path.name != "__init__.py"
        }
        assigned = {}
        for profile, names in profiles.PROFILE_PLUGINS.items():
            for name in names:
                assigned.setdefault(name, []).append(profile)
        self.assertEqual(set(assigned), actual)
        self.assertTrue(all(len(values) == 1 for values in assigned.values()))
        self.assertNotIn("games", assigned)
        self.assertEqual(
            profiles.ASSISTANT_PROFILE_PLUGINS, {"games": "experimental"}
        )

    def test_unset_profile_uses_explicit_policy_not_init_deploy(self):
        legacy = profiles.resolve_profiles(None, policy_marker=None)
        self.assertTrue(legacy.legacy_all)
        new = profiles.resolve_profiles(
            None, policy_marker=profiles.PROFILE_POLICY_NEW
        )
        self.assertEqual(new.names, ("core", "media"))
        loader = (ROOT / "pyUltroid/startup/loader.py").read_text("utf-8")
        self.assertNotIn('get_key("INIT_DEPLOY")', loader)


class StatusTests(unittest.TestCase):
    def test_status_files_are_bounded_and_allowlisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "health.json"
            path.write_text(
                json.dumps(
                    {
                        "state": "healthy",
                        "remote_url": "https://secret@example.test",
                        "exception": "private traceback",
                        "message": "ok",
                    }
                ),
                "utf-8",
            )
            clean = status.read_bounded_status(path)
            self.assertEqual(clean, {"state": "healthy", "message": "ok"})

    def test_dashboard_has_no_raw_sensitive_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = status.dashboard_summary(
                version="2.2.0",
                started_at=time.time() - 10,
                official_count=20,
                addon_count=2,
                disabled_count=5,
                update=updater.UpdateState("current", "abc", "abc", "main"),
                redis_healthy=True,
                assistant_healthy=True,
                state_dir=Path(tmp),
            )
            self.assertIn("BoudyOS 2.2.0", summary)
            self.assertNotIn(str(tmp), summary)

    def test_status_dir_is_resolved_at_call_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.environ.get("BOUDYOS_APP_STATUS_DIR")
            os.environ["BOUDYOS_APP_STATUS_DIR"] = tmp
            try:
                status.write_update_status(updater.UpdateState("current"))
                self.assertTrue((Path(tmp) / "update.json").is_file())
            finally:
                if old is None:
                    os.environ.pop("BOUDYOS_APP_STATUS_DIR", None)
                else:
                    os.environ["BOUDYOS_APP_STATUS_DIR"] = old

    def test_root_truth_and_app_status_paths_are_separate_at_call_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            truth = root / "truth"
            app = root / "app"
            old_truth = os.environ.get("BOUDYOS_STATUS_DIR")
            old_app = os.environ.get("BOUDYOS_APP_STATUS_DIR")
            os.environ["BOUDYOS_STATUS_DIR"] = str(truth)
            os.environ["BOUDYOS_APP_STATUS_DIR"] = str(app)
            try:
                status.write_update_status(updater.UpdateState("current"))
                self.assertEqual(status.status_dir(), truth)
                self.assertTrue((app / "update.json").is_file())
                self.assertFalse((truth / "update.json").exists())
            finally:
                if old_truth is None:
                    os.environ.pop("BOUDYOS_STATUS_DIR", None)
                else:
                    os.environ["BOUDYOS_STATUS_DIR"] = old_truth
                if old_app is None:
                    os.environ.pop("BOUDYOS_APP_STATUS_DIR", None)
                else:
                    os.environ["BOUDYOS_APP_STATUS_DIR"] = old_app

    def test_bot_update_preserves_root_pinned_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "update.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "state": "available",
                        "tag": "v2.2.0",
                        "commit": "a" * 40,
                    }
                ),
                "utf-8",
            )
            status.write_update_status(
                updater.UpdateState("current", detail="safe"), path
            )
            value = json.loads(path.read_text("utf-8"))
            self.assertEqual(value["tag"], "v2.2.0")
            self.assertEqual(value["commit"], "a" * 40)

    def test_log_off_does_not_guard_readiness(self):
        source = (ROOT / "pyUltroid/__main__.py").read_text("utf-8")
        notification = source.index('if not udB.get_key("LOG_OFF")')
        marker = source.index("mark_ready(ready_path)")
        self.assertGreater(marker, notification)
        guarded_block = source[notification:marker]
        self.assertIn("ultroid_bot.run_in_loop(ready())", guarded_block)
        self.assertIn("Operational readiness is unconditional", guarded_block)
