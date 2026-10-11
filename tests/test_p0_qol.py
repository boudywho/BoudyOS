"""Setup/config regression checks without Telegram, boot, pip or network."""
import ast
import contextlib
import importlib.util
import io
import os
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load_file(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def config(**values):
    defaults = dict(API_ID=12345, API_HASH="a" * 32,
                    SESSION="session", BOT_TOKEN=None, REDIS_URI=None,
                    REDISHOST=None, REDISPORT=None, MONGO_URI=None, DATABASE_URL=None)
    defaults.update(values)
    return types.SimpleNamespace(**defaults)


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.cv = load_file("isolated_validate", "pyUltroid/startup/config_validate.py")
        self.env = mock.patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_custom_credentials_and_local_warning(self):
        errors, warnings = self.cv.collect_config_issues(config())
        self.assertEqual(errors, [])
        self.assertTrue(warnings)

    def test_credentials_rejected_without_echoing_secrets(self):
        for values in ({"API_ID": "private-secret"}, {"API_ID": -1},
                       {"API_HASH": "private-secret"},
                       {"API_ID": 6, "API_HASH": "eb06d4abfb49dc3eeb1aeb98ae0f581e"}):
            errors, _ = self.cv.collect_config_issues(config(**values))
            self.assertTrue(errors, values.keys())
            self.assertNotIn("private-secret", " ".join(errors))

    def test_remote_uri_validation_redacts_values(self):
        for func, good, bad in (
            (self.cv.validate_redis_uri, "host:6379", "host:private-secret"),
            (self.cv.validate_mongo_uri, "mongodb+srv://" + "u:p@cluster/db", "mongodb://" + "u:private-secret@"),
            (self.cv.validate_database_url, "postgres://" + "u:p@host:5432/db", "postgres://" + "u:private-secret@host:bad/db"),
        ):
            self.assertEqual(func(good), [])
            errors = func(bad)
            self.assertTrue(errors)
            self.assertNotIn("private-secret", " ".join(errors))
        for uri in ("redis://host:6379", "user:password@host:6379", "host:0", "host:65536"):
            self.assertTrue(self.cv.validate_redis_uri(uri))

    def test_auth_modes(self):
        self.assertTrue(self.cv.collect_config_issues(config(SESSION=None, BOT_TOKEN="token"))[0])
        with mock.patch.dict(os.environ, {"BOTMODE": "true"}):
            self.assertEqual(self.cv.collect_config_issues(config(SESSION=None, BOT_TOKEN="token"))[0], [])
            self.assertTrue(self.cv.collect_config_issues(config(SESSION=None))[0])

    def test_strict_is_optional_and_runtime_pip_always_off(self):
        for value, expected in (("false", False), ("0", False), ("true", True)):
            with mock.patch.dict(os.environ, {"ULTROID_STRICT_CONFIG": value, "ULTROID_AUTO_PIP": "1"}):
                self.assertEqual(bool(self.cv.collect_config_issues(config())[0]), expected)
                self.assertFalse(self.cv.auto_pip_enabled())

    def test_exit_on_errors(self):
        with self.assertRaises(SystemExit) as caught:
            self.cv.validate_config_or_exit(config(API_ID=None), mock.Mock())
        self.assertEqual(caught.exception.code, 1)


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.cli = load_file("isolated_setup", "pyUltroid/startup/setup_cli.py")

    def test_env_created_private_and_existing_paths_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / ".env"
            with mock.patch.object(self.cli, "ENV_PATH", target):
                self.cli._write_env({"API_HASH": "secret", "SESSION": "a#b '$"})
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
                original = target.read_bytes()
                with self.assertRaises(FileExistsError):
                    self.cli._write_env({"API_HASH": "other"})
                self.assertEqual(target.read_bytes(), original)
                link = Path(directory) / "link"
                link.symlink_to(target)
                with mock.patch.object(self.cli, "ENV_PATH", link):
                    with self.assertRaises(FileExistsError):
                        self.cli._write_env({"API_HASH": "other"})
                self.assertEqual(target.read_bytes(), original)

    def test_env_injection_rejected_before_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / ".env"
            with mock.patch.object(self.cli, "ENV_PATH", target):
                for values in ({"SESSION": "secret\nINJECT=1"}, {"BAD=KEY": "secret"}):
                    with self.assertRaises(ValueError):
                        self.cli._write_env(values)
                    self.assertFalse(target.exists())

    def test_noninteractive_setup_does_not_write_or_run_pip(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / ".env"
            with mock.patch.object(self.cli, "ENV_PATH", target), mock.patch.object(self.cli, "_is_interactive", return_value=False):
                self.assertEqual(self.cli.cmd_setup(), 0)
            self.assertFalse(target.exists())

    def test_profile_commands_use_existing_files_and_constraints(self):
        for version, constraint in (((3, 10), "py310.txt"), ((3, 13), "py313.txt")):
            for profile in self.cli.PROFILES:
                command = self.cli.install_command(profile, version=version)
                self.assertIn(str(ROOT / "constraints" / constraint), command)
                for i, arg in enumerate(command):
                    if arg in ("-r", "-c"):
                        self.assertTrue(Path(command[i + 1]).is_file(), command)
        with self.assertRaises(ValueError):
            self.cli.install_command("minimal", version=(3, 11))

    def test_doctor_redacts_invalid_config_without_boot(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-S", "-m", "pyUltroid", "doctor"], cwd=directory,
                env={"PYTHONPATH": str(ROOT), "API_ID": "private-secret",
                     "API_HASH": "private-secret", "REDIS_URI": "host:private-secret"},
                capture_output=True, text=True, timeout=15,
            )
            self.assertEqual(result.returncode, 1)
            self.assertNotIn("private-secret", result.stdout + result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_real_boot_still_requires_pinned_telethonpatch(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, "-S", "-m", "pyUltroid"],
                                    cwd=directory, env={"PYTHONPATH": str(ROOT)},
                                    capture_output=True, text=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("pinned Telethon-Patch", result.stderr)

    def test_cli_runs_before_boot_with_no_site_packages(self):
        with tempfile.TemporaryDirectory() as directory:
            for command, code in (("help", 0), ("--help", 0), ("setup", 0), ("doctor", 1)):
                result = subprocess.run([sys.executable, "-S", "-m", "pyUltroid", command],
                                        cwd=directory, env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ROOT)},
                                        text=True, capture_output=True, timeout=15)
                self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                self.assertNotIn("Traceback", result.stderr)
            self.assertFalse((Path(directory) / ".env").exists())


class StartupGuardTests(unittest.TestCase):
    def test_actual_call_sites_respect_false_db_values(self):
        # Execute the production if statements with side-effect boundaries replaced.
        # Removing a guard or treating the string 'false' as truthy breaks this test.
        security = types.ModuleType("pyUltroid")
        security.__path__ = [str(ROOT / "pyUltroid")]
        with mock.patch.dict(sys.modules, {"pyUltroid": security}):
            from pyUltroid.security.settings import setting_enabled
            from pyUltroid.security.parsing import parse_bool
        for filename, function, key in (("__init__.py", "autobot", "SKIP_AUTOBOT"),
                                        ("__main__.py", "autopilot", "SKIP_AUTOPILOT"),
                                        ("__main__.py", "customize", "SKIP_ASSISTANT_CUSTOMIZE")):
            tree = ast.parse((ROOT / "pyUltroid" / filename).read_text())
            guards = [node for node in ast.walk(tree) if isinstance(node, ast.If)
                      and any(isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                              and child.func.id == function for stmt in node.body for child in ast.walk(stmt))
                      and key in ast.unparse(node.test)]
            self.assertEqual(len(guards), 1, function)
            guard = ast.Module(body=[guards[0]], type_ignores=[])
            for value, runs in ((False, 1), ("false", 1), ("0", 1), (True, 0), ("true", 0)):
                calls = []
                db = types.SimpleNamespace(get_key=lambda name: value)
                client = types.SimpleNamespace(run_in_loop=lambda task: calls.append(task))
                namespace = dict(udB=db, Var=types.SimpleNamespace(**{key: True}),
                                 setting_enabled=setting_enabled, parse_bool=parse_bool,
                                 ultroid_bot=client, **{function: lambda: "task"})
                exec(compile(guard, filename, "exec"), namespace)
                self.assertEqual(len(calls), runs, (function, value))


if __name__ == "__main__":
    unittest.main()
