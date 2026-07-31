import asyncio
import io
import importlib.util
import json
import os
import sys
import tarfile
import tempfile
import unittest
import zipfile
import errno
import shlex
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_security_module(name):
    path = ROOT / "pyUltroid" / "security" / (name + ".py")
    spec = importlib.util.spec_from_file_location("boudyos_" + name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


expressions = load_security_module("expressions")
parsing = load_security_module("parsing")
paths = load_security_module("paths")
processes = load_security_module("subprocess")
ExpressionError = expressions.ExpressionError
evaluate_arithmetic = expressions.evaluate_arithmetic
parse_bool = parsing.parse_bool
parse_night_time = parsing.parse_night_time
safe_data_value = parsing.safe_data_value
UnsafePathError = paths.UnsafePathError
extract_archive = paths.extract_archive
resolve_under = paths.resolve_under
safe_basename = paths.safe_basename
cli_path = paths.cli_path
run_exec = processes.run_exec
run_shell_compat = processes.run_shell_compat


class ParsingTests(unittest.TestCase):
    def test_json_and_legacy_literals_are_data(self):
        self.assertEqual(safe_data_value('{"safe": true}'), {"safe": True})
        self.assertEqual(safe_data_value("('legacy', 2)"), ("legacy", 2))
        payload = "__import__('pathlib').Path('/tmp/pwned').touch()"
        self.assertEqual(safe_data_value(payload), payload)

    def test_night_time_is_strict_and_fails_safe(self):
        self.assertEqual(parse_night_time("[23, 59, 7, 0]"), (23, 59, 7, 0))
        for value in (
            "[24, 0, 7, 0]",
            "[0, 60, 7, 0]",
            "[0, 0, 7]",
            "[True, 0, 7, 0]",
            "__import__('os').system('false')",
        ):
            with self.subTest(value=value):
                self.assertEqual(parse_night_time(value), (0, 0, 7, 0))

    def test_opt_in_boolean_fails_closed(self):
        for value in (True, 1, "yes", "TRUE", "enabled"):
            self.assertTrue(parse_bool(value))
        for value in (False, 0, 2, None, "", "maybe", object()):
            self.assertFalse(parse_bool(value))


class ArithmeticTests(unittest.TestCase):
    def test_documented_arithmetic(self):
        self.assertEqual(evaluate_arithmetic("(2 + 3) * 4 - 5 // 2"), 18)
        self.assertAlmostEqual(evaluate_arithmetic("10 / 4"), 2.5)
        self.assertEqual(evaluate_arithmetic("-2 ** 3"), -8)

    def test_rejects_code_and_resource_abuse(self):
        rejected = (
            "__import__('os').system('id')",
            "(1).__class__",
            "[x for x in range(4)]",
            "open('/etc/passwd')",
            "9 ** 99999",
            "1" * 300,
            "'" + ("x" * 20) + "'",
        )
        for expression in rejected:
            with self.subTest(expression=expression):
                with self.assertRaises(ExpressionError):
                    evaluate_arithmetic(expression)


class ProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_argv_preserves_shell_metacharacters(self):
        value = "space ' quote ; $(not-a-command) —"
        result = await run_exec(
            [sys.executable, "-c", "import sys; print(sys.argv[1])", value],
            timeout=5,
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.stdout, value)

    async def test_timeout_and_output_are_bounded(self):
        result = await run_exec(
            [sys.executable, "-c", "print('x' * 10000)"],
            timeout=5,
            output_limit=32,
        )
        self.assertEqual(len(result.stdout), 32)
        self.assertTrue(result.stdout_truncated)
        timed = await run_exec(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            timeout=0.05,
        )
        self.assertTrue(timed.timed_out)
        self.assertFalse(timed.ok)

    async def test_progress_callback_runs_while_process_is_active(self):
        calls = []
        result = await run_exec(
            [sys.executable, "-c", "import time; time.sleep(0.15)"],
            timeout=2,
            progress_callback=lambda: calls.append(True),
            progress_interval=0.03,
        )
        self.assertTrue(result.ok)
        self.assertGreaterEqual(len(calls), 2)

    async def test_legacy_shell_timeout_kills_descendants(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "descendant-ran"
            child = (
                "import time; from pathlib import Path; "
                f"time.sleep(.3); Path({str(marker)!r}).write_text('bad')"
            )
            parent = (
                "import subprocess,sys,time; "
                f"subprocess.Popen([sys.executable,'-c',{child!r}]); "
                "time.sleep(5)"
            )
            command = (
                shlex.quote(sys.executable) + " -c " + shlex.quote(parent)
            )
            result = await run_shell_compat(command, timeout=0.05)
            self.assertTrue(result.timed_out)
            await asyncio.sleep(0.5)
            self.assertFalse(marker.exists())


class PathTests(unittest.TestCase):
    def test_paths_and_basenames_stay_in_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(resolve_under(tmp, "safe/name"), Path(tmp) / "safe/name")
            for value in ("../escape", "/absolute"):
                with self.assertRaises(UnsafePathError):
                    resolve_under(tmp, value)
        for name in ("../bad.py", "/bad.py", "-option.py", ".."):
            with self.assertRaises(UnsafePathError):
                safe_basename(name, ".py")
        self.assertEqual(cli_path("-leading name;quote'"), "./-leading name;quote'")

    def test_runtime_code_symlink_is_not_a_writable_media_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime"
            immutable = root / "release" / "plugins"
            runtime.mkdir()
            immutable.mkdir(parents=True)
            (immutable / "bot.py").write_text("official = True\n", "utf-8")
            (runtime / "plugins").symlink_to(immutable)
            with self.assertRaises(UnsafePathError):
                resolve_under(runtime, "plugins/bot.py")

    def test_rejects_archive_traversal_without_partial_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "unsafe.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("good.txt", "good")
                zipped.writestr("../escape.txt", "bad")
            with self.assertRaises(UnsafePathError):
                extract_archive(archive, "unpack", workspace=root)
            self.assertFalse((root / "unpack").exists())
            self.assertFalse((root.parent / "escape.txt").exists())

    def test_rejects_tar_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "unsafe.tar"
            with tarfile.open(archive, "w") as tar:
                entry = tarfile.TarInfo("link")
                entry.type = tarfile.SYMTYPE
                entry.linkname = "/etc/passwd"
                tar.addfile(entry)
            with self.assertRaises(UnsafePathError):
                extract_archive(archive, "unpack", workspace=root)

    def test_safe_move_falls_back_across_filesystems(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            destination = root / "other" / "destination"
            source.write_text("payload", "utf-8")
            real_replace = os.replace
            calls = 0

            def replace(old, new):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise OSError(errno.EXDEV, "cross-device")
                return real_replace(old, new)

            with mock.patch.object(paths.os, "replace", side_effect=replace):
                paths.safe_move(source, destination)
            self.assertFalse(source.exists())
            self.assertEqual(destination.read_text("utf-8"), "payload")

    def test_private_workspaces_are_unique_and_always_cleaned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with paths.private_workspace(root, ".command-") as first:
                with paths.private_workspace(root, ".command-") as second:
                    self.assertNotEqual(first, second)
                    self.assertEqual(first.stat().st_mode & 0o777, 0o700)
                    first_path, second_path = first, second
            self.assertFalse(first_path.exists())
            self.assertFalse(second_path.exists())

    def test_zip_option_order_and_curl_file_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "-leading @file"
            source.write_text("payload", "utf-8")
            argv = paths.zip_command(source.name, "-archive.zip", "secret")
            self.assertEqual(argv[:4], ["zip", "-r", "--password", "secret"])
            self.assertEqual(argv[4], "./-archive.zip")
            self.assertEqual(argv[5], "--")
            self.assertEqual(argv[6], "./-leading @file")
            reference = paths.curl_file_reference(source)
            self.assertEqual(reference, "@" + str(source.resolve()))
