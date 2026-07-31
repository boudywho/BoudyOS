import importlib.util
import importlib.machinery
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("boudyos_ops", ROOT / "ops/boudyos_ops.py")
ops = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ops)
sys.modules["boudyos_ops"] = ops
HEALTH_LOADER = importlib.machinery.SourceFileLoader(
    "boudyos_health", str(ROOT / "ops/boudyos-health")
)
HEALTH_SPEC = importlib.util.spec_from_loader("boudyos_health", HEALTH_LOADER)
health = importlib.util.module_from_spec(HEALTH_SPEC)
HEALTH_LOADER.exec_module(health)


def make_managed_release(release_root, tag, marker):
    stage = release_root.parent / ("source-" + marker)
    (stage / "resources" / "static").mkdir(parents=True)
    for name in ("pyUltroid", "plugins", "assistant", "strings", "startup"):
        (stage / name).mkdir()
    (stage / "pyUltroid" / "__init__.py").write_text("", "utf-8")
    (stage / "pyUltroid" / "paths.py").write_text(
        (ROOT / "pyUltroid/paths.py").read_text("utf-8"), "utf-8"
    )
    (stage / "plugins" / "__init__.py").write_text("", "utf-8")
    (stage / "plugins" / "official.py").write_text("VALUE = 'official'\n", "utf-8")
    (stage / "ops" / "systemd").mkdir(parents=True)
    (stage / "ops" / "systemd" / "ultroid-boudyos.conf.example").write_text(
        (ROOT / "ops/systemd/ultroid-boudyos.conf.example").read_text("utf-8"),
        "utf-8",
    )
    (stage / "marker").write_text(marker, "utf-8")
    subprocess.run(["git", "init", "-q", str(stage)], check=True)
    subprocess.run(
        ["git", "-C", str(stage), "remote", "add", "origin",
         "https://github.com/boudywho/BoudyOS.git"],
        check=True,
    )
    subprocess.run(["git", "-C", str(stage), "add", "."], check=True)
    subprocess.run(
        [
            "git", "-C", str(stage), "-c", "user.name=BoudyOS Tests",
            "-c", "user.email=tests@invalid", "commit", "-qm", marker,
        ],
        check=True,
    )
    subprocess.run(["git", "-C", str(stage), "tag", tag], check=True)
    commit = subprocess.check_output(
        ["git", "-C", str(stage), "rev-parse", "HEAD"], text=True
    ).strip()
    release_root.mkdir(parents=True, exist_ok=True)
    release_root.chmod(0o750)
    release = release_root / commit
    stage.rename(release)
    for directory, names, files in os.walk(release):
        path = Path(directory)
        path.chmod(path.stat().st_mode & 0o7770)
        for name in names + files:
            child = path / name
            if not child.is_symlink():
                child.chmod(child.stat().st_mode & 0o7770)
    return release, commit


def make_managed_runtime(workspace_root, commit):
    workspace_root.mkdir(mode=0o750, parents=True, exist_ok=True)
    workspace_root.chmod(0o750)
    runtime = workspace_root / commit
    runtime.mkdir(mode=0o750)
    release = workspace_root.parent / "releases" / commit
    release.mkdir(mode=0o750, parents=True, exist_ok=True)
    (runtime / "source").symlink_to(release)
    work = runtime / "work"
    work.mkdir(mode=0o700)
    for name in ("addons", "downloads", "sessions", "db", "logs", "temp", "vcbot"):
        (work / name).mkdir(mode=0o700)
    resources = work / "resources"
    resources.mkdir(mode=0o700)
    for name in ("auth", "auths", "downloads"):
        (resources / name).mkdir(mode=0o700)
    return runtime


def make_legacy_ops_configs(root, legacy, service="ultroid.service"):
    backup = root / "backup.conf"
    paths = root / "backup-paths-ultroid"
    health_config = root / "health.conf"
    backup.write_text(
        "BACKUP_MODE=legacy\n"
        f"LEGACY_SOURCE={legacy}\n"
        f"QUIESCE_SERVICE={service}\n"
        f"ALLOWLIST_FILE={paths}\n",
        "utf-8",
    )
    paths.write_text(f"{legacy}\n", "utf-8")
    health_config.write_text(
        "LAYOUT_MODE=legacy\n"
        f"LEGACY_SOURCE={legacy}\n"
        f"SERVICE={service}\n",
        "utf-8",
    )
    for path in (backup, paths, health_config):
        path.chmod(0o600)
    return backup, paths, health_config


class BackupPolicyTests(unittest.TestCase):
    def test_manifest_is_exact_for_content_size_mode_and_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").write_text("safe", "utf-8")
            manifest = ops.build_manifest(root, {"release": "2.2.0"})
            self.assertEqual(ops.verify_manifest(root, manifest), [])
            (root / "config").write_text("fail", "utf-8")
            self.assertTrue(
                any(
                    "checksum mismatch" in error
                    for error in ops.verify_manifest(root, manifest)
                )
            )
            (root / "extra").write_text("unexpected", "utf-8")
            self.assertTrue(
                any(
                    "unexpected file" in error
                    for error in ops.verify_manifest(root, manifest)
                )
            )
            (root / "extra").unlink()
            os.chmod(root / "config", 0o600)
            self.assertTrue(
                any(
                    "mode mismatch" in error
                    for error in ops.verify_manifest(root, manifest)
                )
            )
            manifest["files"][0]["path"] = "../escape"
            self.assertIn("unsafe manifest path", ops.verify_manifest(root, manifest))

    def test_manifest_rejects_size_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = root / "payload"
            payload.write_bytes(b"original")
            manifest = ops.build_manifest(root, {})
            payload.write_bytes(b"longer payload")
            self.assertTrue(
                any(
                    error == "size mismatch: payload"
                    for error in ops.verify_manifest(root, manifest)
                )
            )

    def test_backup_source_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target"
            target.write_text("state", "utf-8")
            link = root / "link"
            link.symlink_to(target)
            destination = root / "backup"
            destination.mkdir()
            with self.assertRaises(ValueError):
                ops.copy_regular_source(link, destination)

    def test_active_runtime_resolution_accepts_only_commit_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspaces = root / "workspaces"
            runtime = workspaces / ("a" * 40)
            make_managed_runtime(workspaces, "a" * 40)
            current = root / "current"
            current.symlink_to(runtime)
            self.assertEqual(
                ops.resolve_active_runtime(current, workspaces), runtime
            )
            current.unlink()
            arbitrary = root / "arbitrary"
            arbitrary.mkdir()
            current.symlink_to(arbitrary)
            with self.assertRaises(ValueError):
                ops.resolve_active_runtime(current, workspaces)
            current.unlink()
            current.symlink_to(workspaces)
            with self.assertRaises(ValueError):
                ops.resolve_active_runtime(current, workspaces)

    def test_managed_runtime_backup_copies_only_work_and_rejects_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            commit = "b" * 40
            release = root / "releases" / commit
            runtime = root / "workspaces" / commit
            destination = root / "backup"
            (release / "plugins").mkdir(parents=True)
            (release / "resources" / "extras").mkdir(parents=True)
            (release / "plugins" / "bot.py").write_text("official", "utf-8")
            runtime = make_managed_runtime(root / "workspaces", commit)
            (runtime / "work" / "resources" / "downloads" / "media").write_text(
                "mutable", "utf-8"
            )
            (runtime / "work" / "resources" / "downloads" / "media").chmod(0o600)
            copied = ops.copy_managed_runtime_state(
                runtime, destination, root / "workspaces", release
            )
            self.assertFalse((copied / "plugins").exists())
            self.assertEqual(
                (
                    copied / "work" / "resources" / "downloads" / "media"
                ).read_text("utf-8"),
                "mutable",
            )
            (runtime / "work" / "operator-link").symlink_to(root)
            with self.assertRaises(ValueError):
                ops.copy_managed_runtime_state(
                    runtime, root / "backup2", root / "workspaces", release
                )

    def test_legacy_backup_copies_active_mutable_state_not_code_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "opt" / "ultroid"
            legacy.mkdir(parents=True)
            (legacy / "account.session").write_text("session", "utf-8")
            (legacy / "database.json").write_text("{}", "utf-8")
            (legacy / ".venv").mkdir()
            (legacy / ".venv" / "python").symlink_to("/usr/bin/python3")
            destination = root / "backup"
            destination.mkdir()
            ops.copy_legacy_runtime_state(legacy, destination)
            copied = destination / legacy.relative_to("/")
            self.assertEqual(
                (copied / "account.session").read_text("utf-8"), "session"
            )
            self.assertFalse((copied / ".venv").exists())
            (legacy / "database.json").unlink()
            (legacy / "database.json").symlink_to(root)
            with self.assertRaises(ValueError):
                ops.copy_legacy_runtime_state(legacy, root / "backup2")

    def test_example_backs_up_only_the_active_runtime_link(self):
        allowlist = (ROOT / "ops/config/backup-paths.example").read_text("utf-8")
        backup = (ROOT / "ops/boudyos-backup").read_text("utf-8")
        self.assertIn("/var/lib/boudyos/current", allowlist)
        self.assertNotIn("/var/lib/boudyos/runtime", allowlist)
        self.assertNotIn("/var/lib/boudyos/workspaces\n", allowlist)
        self.assertIn("resolve-active-runtime", backup)
        self.assertIn('--managed-workspace-root "$RUNTIME_ROOT"', backup)
        self.assertIn('active_source_seen=0', backup)
        self.assertIn('active_source_seen=1', backup)

    def test_manifest_rejects_links_and_special_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target"
            target.write_text("value", "utf-8")
            link = root / "link"
            link.symlink_to(target)
            with self.assertRaises(ValueError):
                ops.build_manifest(root, {})
            link.unlink()
            fifo = root / "fifo"
            os.mkfifo(fifo)
            with self.assertRaises(ValueError):
                ops.build_manifest(root, {})

    def test_hmac_authenticates_ciphertext_and_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "backup.age"
            archive.write_bytes(b"encrypted bytes")
            key = root / "key"
            wrong = root / "wrong"
            key.write_bytes(b"k" * 32)
            wrong.write_bytes(b"w" * 32)
            key.chmod(0o600)
            wrong.chmod(0o600)
            signature = root / "backup.age.hmac"
            ops.write_hmac(archive, key, signature)
            self.assertTrue(ops.verify_hmac(archive, key, signature))
            self.assertFalse(ops.verify_hmac(archive, wrong, signature))
            archive.write_bytes(b"tampered ciphertext")
            self.assertFalse(ops.verify_hmac(archive, key, signature))
            archive.write_bytes(b"encrypted bytes")
            signature.write_text("0" * 64 + "\n", "ascii")
            self.assertFalse(ops.verify_hmac(archive, key, signature))

    def test_safe_tar_extract_rejects_traversal_and_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            traversal = root / "traversal.tar"
            with tarfile.open(traversal, "w") as archive:
                item = tarfile.TarInfo("../escape")
                item.size = 0
                archive.addfile(item)
            with self.assertRaises(ValueError):
                ops.safe_extract_tar(traversal, root / "out")
            links = root / "links.tar"
            with tarfile.open(links, "w") as archive:
                item = tarfile.TarInfo("link")
                item.type = tarfile.SYMTYPE
                item.linkname = "/etc/passwd"
                archive.addfile(item)
            with self.assertRaises(ValueError):
                ops.safe_extract_tar(links, root / "links")

    def test_safe_tar_extract_and_exact_manifest_succeed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            payload = source / "payload"
            payload.write_text("restorable", "utf-8")
            payload.chmod(0o640)
            manifest = ops.build_manifest(source, {"product": "BoudyOS"})
            (source / "manifest.json").write_text(
                json.dumps(manifest), "utf-8"
            )
            archive = root / "backup.tar"
            with tarfile.open(archive, "w") as tar:
                tar.add(source, arcname=".")
            destination = root / "restored"
            ops.safe_extract_tar(archive, destination)
            restored_manifest = json.loads(
                (destination / "manifest.json").read_text("utf-8")
            )
            self.assertEqual(
                ops.verify_manifest(destination, restored_manifest), []
            )
            self.assertEqual(
                (destination / "payload").stat().st_mode & 0o777, 0o640
            )

    def test_rotation_keeps_daily_weekly_monthly_buckets(self):
        now = datetime(2026, 7, 30, tzinfo=timezone.utc)
        paths = []
        for days in range(0, 100):
            stamp = now - timedelta(days=days)
            paths.append(Path("boudyos-" + stamp.strftime("%Y%m%dT%H%M%SZ") + ".tar.age"))
        kept = ops.rotation_keep(paths, now=now)
        self.assertLessEqual(len(kept), 14)
        self.assertEqual(len(kept), 14)


class HealthPolicyTests(unittest.TestCase):
    @unittest.skipUnless(
        os.geteuid() == 0 and shutil.which("runuser"),
        "requires root and runuser to exercise a distinct runtime account",
    )
    def test_runtime_account_can_write_work_but_not_workspace_selectors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.chmod(0o755)
            nobody_uid = int(
                subprocess.check_output(["id", "-u", "nobody"], text=True).strip()
            )
            nobody_gid = int(
                subprocess.check_output(["id", "-g", "nobody"], text=True).strip()
            )
            source = root / "source"
            (source / "plugins").mkdir(parents=True)
            workspace_root = root / "workspaces"
            workspace_root.mkdir(mode=0o750)
            try:
                os.chown(workspace_root, 0, nobody_gid)
            except OSError as exc:
                self.skipTest(f"cannot chown to distinct runtime group: {exc}")
            runtime = workspace_root / ("a" * 40)
            runtime.mkdir(mode=0o750)
            os.chown(runtime, 0, nobody_gid)
            work = runtime / "work"
            work.mkdir(mode=0o700)
            os.chown(work, nobody_uid, nobody_gid)

            writable = subprocess.run(
                ["runuser", "-u", "nobody", "--", "touch", str(work / "output")],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(writable.returncode, 0, writable.stderr)
            replace = subprocess.run(
                [
                    "runuser", "-u", "nobody", "--", "ln", "-s",
                    str(source / "plugins"), str(runtime / "plugins"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(replace.returncode, 0)
            self.assertFalse((runtime / "plugins").exists())

    def test_runtime_preparation_rejects_symlink_mutable_state(self):
        script = ROOT / "ops/boudyos-deploy"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            prior = root / "prior"
            destination = root / "runtime"
            (source / "resources" / "extras").mkdir(parents=True)
            (source / "pyUltroid").mkdir()
            prior.mkdir()
            (prior / "addons").symlink_to(source / "pyUltroid")
            user = subprocess.check_output(["id", "-un"], text=True).strip()
            group = subprocess.check_output(["id", "-gn"], text=True).strip()
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    'source "$SCRIPT"; prepare_runtime "$SOURCE" "$DESTINATION" '
                    '"$PRIOR" "$SOURCE"',
                ],
                env={
                    "PATH": os.pathsep.join(
                        (str(Path(sys.executable).parent), "/usr/bin", "/bin")
                    ),
                    "SCRIPT": str(script),
                    "SOURCE": str(source),
                    "PRIOR": str(prior),
                    "DESTINATION": str(destination),
                    "BOUDYOS_DEPLOY_LIB": "1",
                    "BOUDYOS_STATUS_DIR": str(root / "status"),
                    "BOUDYOS_DEPLOY_LOCK": str(root / "deploy.lock"),
                    "BOUDYOS_APP_STATUS_DIR": str(root / "app-status"),
                    "BOUDYOS_RUNTIME_USER": user,
                    "BOUDYOS_RUNTIME_GROUP": group,
                },
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("mutable state source", result.stderr)

    def test_root_status_directory_is_not_group_writable(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir(mode=0o750)
            path = state / "status"
            group = subprocess.check_output(["id", "-gn"], text=True).strip()
            health.ensure_root_status_directory(path, group)
            self.assertEqual(path.stat().st_mode & 0o777, 0o750)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o750)
            if os.geteuid() == 0:
                self.assertEqual(path.stat().st_uid, 0)

    def test_status_setup_does_not_mutate_read_only_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            status = state / "status"
            state.mkdir(mode=0o755)
            status.mkdir(mode=0o700)
            state.chmod(0o555)
            before = state.stat()
            group = subprocess.check_output(["id", "-gn"], text=True).strip()
            health.ensure_root_status_directory(status, group)
            after = state.stat()
            self.assertEqual(stat.S_IMODE(after.st_mode), 0o555)
            self.assertEqual((after.st_uid, after.st_gid), (before.st_uid, before.st_gid))
            self.assertEqual(stat.S_IMODE(status.stat().st_mode), 0o750)

    def test_status_setup_rejects_insecure_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            status = state / "status"
            state.mkdir()
            state.chmod(0o775)
            status.mkdir()
            group = subprocess.check_output(["id", "-gn"], text=True).strip()
            with self.assertRaises(PermissionError):
                health.ensure_root_status_directory(status, group)

    def test_readiness_requires_fresh_timestamp_and_matching_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "ready"
            marker.write_text(
                json.dumps(
                    {"schema_version": 1, "pid": 42, "timestamp": 1_000}
                ),
                "ascii",
            )
            self.assertTrue(
                health.readiness_fresh(marker, 42, 45, now=1_030)
            )
            self.assertFalse(
                health.readiness_fresh(marker, 42, 45, now=1_100)
            )
            self.assertFalse(
                health.readiness_fresh(marker, 99, 45, now=1_030)
            )

    def test_alert_delivery_reports_success_and_failure(self):
        with mock.patch.object(
            health.urllib.request, "urlopen"
        ) as opened:
            opened.return_value.__enter__.return_value.read.return_value = (
                b'{"ok": true}'
            )
            self.assertTrue(
                health.send_alert(
                    {"TELEGRAM_BOT_TOKEN": "x", "TELEGRAM_CHAT_ID": "y"},
                    "fixed alert",
                )
            )
            opened.return_value.__enter__.return_value.read.return_value = (
                b'{"ok": false}'
            )
            self.assertFalse(
                health.send_alert(
                    {"TELEGRAM_BOT_TOKEN": "x", "TELEGRAM_CHAT_ID": "y"},
                    "fixed alert",
                )
            )
            opened.side_effect = OSError("unavailable")
            self.assertFalse(
                health.send_alert(
                    {"TELEGRAM_BOT_TOKEN": "x", "TELEGRAM_CHAT_ID": "y"},
                    "fixed alert",
                )
            )

    def test_backup_and_update_freshness_uses_recorded_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "status.json"
            with mock.patch.object(health.time, "time", return_value=1_000):
                path.write_text(
                    json.dumps({"schema_version": 1, "checked_at": 980}),
                    "utf-8",
                )
                self.assertTrue(health.file_fresh(path, 45))
                path.chmod(0o660)
                self.assertFalse(health.file_fresh(path, 45))
                path.chmod(0o640)
                path.write_text(
                    json.dumps({"schema_version": 1, "checked_at": 900}),
                    "utf-8",
                )
                self.assertFalse(health.file_fresh(path, 45))
                os.utime(path, (1_000, 1_000))
                self.assertFalse(health.file_fresh(path, 45))

    def test_sanitization_removes_secrets_urls_and_tracebacks(self):
        clean = ops.sanitize_health_status(
            {
                "schema_version": 1,
                "state": "degraded",
                "service_active": False,
                "alerts": ["redis failed"],
                "telegram_token": "secret",
                "remote_url": "https://user:pass@example.test",
                "traceback": "/private/path",
            }
        )
        self.assertEqual(
            clean,
            {
                "schema_version": 1,
                "state": "degraded",
                "service_active": False,
                "alerts": ["redis failed"],
            },
        )

    def test_deploy_dry_run_check_and_preflight_need_no_root_or_network(self):
        script = ROOT / "ops/boudyos-deploy"
        for command in ("check", "preflight", "request", "status"):
            result = subprocess.run(
                [str(script), command],
                env={"PATH": "/usr/bin:/bin", "BOUDYOS_DRY_RUN": "1"},
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )
            with self.subTest(command=command):
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('"dry_run":true', result.stdout)

    def test_request_is_fast_atomic_and_requires_real_commit(self):
        script = ROOT / "ops/boudyos-deploy"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = root / "deploy.request"
            status = root / "status"
            env = {
                "PATH": "/usr/bin:/bin",
                "SCRIPT": str(script),
                "BOUDYOS_DEPLOY_LIB": "1",
                "BOUDYOS_DEPLOY_REQUEST": str(request),
                "BOUDYOS_STATUS_DIR": str(status),
                "BOUDYOS_RELEASE_TAG": "v2.2.0",
                "BOUDYOS_RELEASE_COMMIT": "a" * 40,
                "BOUDYOS_RUNTIME_USER": subprocess.check_output(
                    ["id", "-un"], text=True
                ).strip(),
                "BOUDYOS_RUNTIME_GROUP": subprocess.check_output(
                    ["id", "-gn"], text=True
                ).strip(),
            }
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    'source "$SCRIPT"; load_release_config; queue_release_request',
                ],
                env=env,
                text=True,
                capture_output=True,
                timeout=3,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertRegex(request.read_text("ascii"), r"^v2\.2\.0 a{40} \d+\n$")
            env["BOUDYOS_RELEASE_COMMIT"] = "0" * 40
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    'source "$SCRIPT"; load_release_config; queue_release_request',
                ],
                env=env,
                text=True,
                capture_output=True,
                timeout=3,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)

    def test_real_actions_reject_insecure_deploy_config(self):
        script = ROOT / "ops/boudyos-deploy"
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "deploy.conf"
            config.write_text(
                "BOUDYOS_RELEASE_TAG=v2.2.0\n"
                "BOUDYOS_RELEASE_COMMIT=" + "a" * 40 + "\n",
                "utf-8",
            )
            if os.geteuid() == 0:
                config.chmod(0o662)
            else:
                config.chmod(0o600)
            result = subprocess.run(
                [str(script), "request", "--non-interactive"],
                env={
                    "PATH": "/usr/bin:/bin",
                    "BOUDYOS_DEPLOY_CONFIG": str(config),
                },
                text=True,
                capture_output=True,
                timeout=3,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Deployment config", result.stderr)

    def test_existing_release_is_quarantined_not_reused(self):
        script = ROOT / "ops/boudyos-deploy"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = os.environ.copy()
            env.update(
                {
                    "SCRIPT": str(script),
                    "BOUDYOS_DEPLOY_LIB": "1",
                    "BOUDYOS_RELEASE_ROOT": str(root / "releases"),
                    "BOUDYOS_RUNTIME_ROOT": str(root / "workspaces"),
                }
            )
            command = r'''
set -e
source "$SCRIPT"
RELEASE_COMMIT=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
mkdir -p "$RELEASE_ROOT/final" "$RUNTIME_ROOT/final" "$RELEASE_ROOT/staged" "$RUNTIME_ROOT/staged"
printf old >"$RELEASE_ROOT/final/value"
printf new >"$RELEASE_ROOT/staged/value"
promote_staged_release "$RELEASE_ROOT/staged" "$RUNTIME_ROOT/staged" "$RELEASE_ROOT/final" "$RUNTIME_ROOT/final"
test "$(cat "$RELEASE_ROOT/final/value")" = new
test "$(find "$RELEASE_ROOT" -maxdepth 1 -type d -name '.quarantine-*' | wc -l)" = 1
'''
            result = subprocess.run(
                ["bash", "-c", command],
                env=env,
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_verified_release_is_group_readable_but_immutable(self):
        script = ROOT / "ops/boudyos-deploy"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = root / "release"
            executable = release / "bin/tool"
            executable.parent.mkdir(parents=True)
            (release / "module.py").write_text("value = 1\n", "utf-8")
            executable.write_text("#!/bin/sh\nexit 0\n", "utf-8")
            executable.chmod(0o700)
            user = subprocess.check_output(["id", "-un"], text=True).strip()
            group = subprocess.check_output(["id", "-gn"], text=True).strip()
            env = os.environ.copy()
            env.update(
                {
                    "SCRIPT": str(script),
                    "BOUDYOS_DEPLOY_LIB": "1",
                    "BOUDYOS_RELEASE_OWNER": user,
                    "BOUDYOS_RUNTIME_GROUP": group,
                    "RELEASE": str(release),
                }
            )
            command = r'''
set -e
source "$SCRIPT"
secure_release "$RELEASE"
test "$(stat -c %a "$RELEASE")" = 750
test "$(stat -c %a "$RELEASE/module.py")" = 640
test "$(stat -c %a "$RELEASE/bin/tool")" = 750
test "$(stat -c %G "$RELEASE")" = "$BOUDYOS_RUNTIME_GROUP"
'''
            result = subprocess.run(
                ["bash", "-c", command],
                env=env,
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_active_release_uses_immutable_source_and_isolated_writable_work(self):
        script = ROOT / "ops/boudyos-deploy"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            releases = root / "releases"
            workspaces = root / "workspaces"
            source, commit = make_managed_release(releases, "v2.2.0", "active")
            workspaces.mkdir(mode=0o750)
            runtime = workspaces / commit
            current = root / "current"
            runtime_current = root / "runtime-current"
            current.symlink_to(source)
            runtime_current.symlink_to(runtime)
            env = os.environ.copy()
            env.update(
                {
                    "SCRIPT": str(script),
                    "BOUDYOS_DEPLOY_LIB": "1",
                    "BOUDYOS_RUNTIME_LINK": str(runtime_current),
                    "BOUDYOS_RELEASE_ROOT": str(releases),
                    "BOUDYOS_RUNTIME_ROOT": str(workspaces),
                    "BOUDYOS_STATUS_DIR": str(root / "status"),
                    "BOUDYOS_APP_STATUS_DIR": str(root / "app-status"),
                    "BOUDYOS_RUNTIME_USER": subprocess.check_output(
                        ["id", "-un"], text=True
                    ).strip(),
                    "BOUDYOS_RUNTIME_GROUP": subprocess.check_output(
                        ["id", "-gn"], text=True
                    ).strip(),
                    "RELEASE_COMMIT_VALUE": commit,
                    "SOURCE": str(source),
                    "RUNTIME": str(runtime),
                }
            )
            command = r'''
set -e
source "$SCRIPT"
RELEASE_TAG=v2.2.0
RELEASE_COMMIT="$RELEASE_COMMIT_VALUE"
prepare_runtime "$SOURCE" "$RUNTIME" "" "$SOURCE"
write_release_metadata
active_release_verified
test "$(find "$RUNTIME" -mindepth 1 -maxdepth 1 -printf '%f\n' | sort)" = $'source\nwork'
test "$(readlink "$RUNTIME/source")" = "$SOURCE"
test ! -e "$RUNTIME/pyUltroid"
test ! -e "$RUNTIME/work/pyUltroid"
test -d "$RUNTIME/work/resources/downloads"
(
    cd "$RUNTIME/work"
    PYTHONPATH="$SOURCE" python3 -s - "$SOURCE" <<'PY'
import sys
from pathlib import Path
source = Path(sys.argv[1]).resolve()
working = Path.cwd().resolve()
sys.path[:] = [str(source)] + [
    entry for entry in sys.path
    if entry and Path(entry).resolve() not in {source, working}
]
from pyUltroid.paths import OFFICIAL_PLUGINS, SOURCE_ROOT

assert SOURCE_ROOT == source
assert sorted(path.name for path in OFFICIAL_PLUGINS.glob("*.py")) == [
    "__init__.py", "official.py"
]
Path("resources/downloads/media.bin").write_bytes(b"writable")
assert Path("resources/downloads/media.bin").read_bytes() == b"writable"
PY
)
ln -s "$SOURCE/plugins" "$RUNTIME/work/plugins"
if active_release_verified; then
    exit 1
fi
'''
            result = subprocess.run(
                ["bash", "-c", command],
                env=env,
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_activation_rejects_workspace_tampering_before_service_start(self):
        script = ROOT / "ops/boudyos-deploy"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            releases = root / "releases"
            workspaces = root / "workspaces"
            old_source, old_commit = make_managed_release(
                releases, "v2.1.0", "old"
            )
            new_source, new_commit = make_managed_release(
                releases, "v2.2.0", "new"
            )
            old_runtime = make_managed_runtime(workspaces, old_commit)
            new_runtime = make_managed_runtime(workspaces, new_commit)
            current = root / "current"
            runtime = root / "runtime-current"
            current.symlink_to(old_source)
            runtime.symlink_to(old_runtime)
            env = os.environ.copy()
            env.update(
                {
                    "SCRIPT": str(script),
                    "BOUDYOS_DEPLOY_LIB": "1",
                    "BOUDYOS_RELEASE_ROOT": str(releases),
                    "BOUDYOS_RUNTIME_ROOT": str(workspaces),
                    "BOUDYOS_RUNTIME_LINK": str(runtime),
                    "BOUDYOS_PREVIOUS_FILE": str(root / "previous"),
                    "BOUDYOS_STATUS_DIR": str(root / "status"),
                    "BOUDYOS_RELEASE_METADATA": str(root / "release.json"),
                    "BOUDYOS_READY_FILE": str(root / "ready"),
                    "BOUDYOS_RUNTIME_USER": subprocess.check_output(
                        ["id", "-un"], text=True
                    ).strip(),
                    "BOUDYOS_RUNTIME_GROUP": subprocess.check_output(
                        ["id", "-gn"], text=True
                    ).strip(),
                    "OLD_SOURCE": str(old_source),
                    "OLD_RUNTIME": str(old_runtime),
                    "NEW_SOURCE": str(new_source),
                    "NEW_RUNTIME": str(new_runtime),
                    "OLD_COMMIT": old_commit,
                    "NEW_COMMIT": new_commit,
                }
            )
            command = r'''
source "$SCRIPT"
RELEASE_TAG=v2.2.0
RELEASE_COMMIT="$NEW_COMMIT"
starts=0
tampered=0
active=1
mock_pid=100
systemctl() {
    if [[ "$1" == stop && "$tampered" == 0 ]]; then
        ln -s "$NEW_SOURCE/plugins" "$NEW_RUNTIME/work/plugins"
        tampered=1
        active=0
        mock_pid=0
        return 0
    fi
    if [[ "$1" == stop ]]; then active=0; mock_pid=0; return 0; fi
    if [[ "$1" == is-active ]]; then
        if [[ "$active" == 1 ]]; then echo active; return 0; fi
        echo inactive; return 1
    fi
    if [[ "$1" == show ]]; then printf '%s\n' "$mock_pid"; return 0; fi
    if [[ "$1" == start ]]; then
        starts=$((starts + 1))
        active=1
        mock_pid=$((200 + starts))
        return 0
    fi
    return 0
}
wait_ready() { return 0; }
set +e
activate_release "$NEW_SOURCE" "$NEW_RUNTIME"
result=$?
set -e
test "$result" = 1
test "$(readlink -f "$RUNTIME_LINK")" = "$OLD_RUNTIME"
test "$(readlink -f "$RUNTIME_LINK/source")" = "$OLD_SOURCE"
test "$starts" = 1
grep -q '"state":"rolled_back"' "$STATUS_FILE"
'''
            result = subprocess.run(
                ["bash", "-c", command],
                env=env,
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_verified_automatic_rollback_republishes_previous_identity(self):
        script = ROOT / "ops/boudyos-deploy"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            releases = root / "releases"
            workspaces = root / "workspaces"
            old_source, old_commit = make_managed_release(
                releases, "v2.1.0", "old"
            )
            new_source, new_commit = make_managed_release(
                releases, "v2.2.0", "new"
            )
            old_runtime = make_managed_runtime(workspaces, old_commit)
            new_runtime = make_managed_runtime(workspaces, new_commit)
            current = root / "current"
            runtime_current = root / "runtime-current"
            current.symlink_to(old_source)
            runtime_current.symlink_to(old_runtime)
            user = subprocess.check_output(["id", "-un"], text=True).strip()
            group = subprocess.check_output(["id", "-gn"], text=True).strip()
            env = os.environ.copy()
            env.update(
                {
                    "SCRIPT": str(script),
                    "BOUDYOS_DEPLOY_LIB": "1",
                    "BOUDYOS_RELEASE_ROOT": str(releases),
                    "BOUDYOS_RUNTIME_ROOT": str(workspaces),
                    "BOUDYOS_RUNTIME_LINK": str(runtime_current),
                    "BOUDYOS_PREVIOUS_FILE": str(root / "previous"),
                    "BOUDYOS_STATUS_DIR": str(root / "status"),
                    "BOUDYOS_RELEASE_METADATA": str(root / "release.json"),
                    "BOUDYOS_READY_FILE": str(root / "ready"),
                    "BOUDYOS_RUNTIME_USER": user,
                    "BOUDYOS_RUNTIME_GROUP": group,
                    "OLD_SOURCE": str(old_source),
                    "OLD_RUNTIME": str(old_runtime),
                    "NEW_SOURCE": str(new_source),
                    "NEW_RUNTIME": str(new_runtime),
                    "OLD_COMMIT": old_commit,
                    "NEW_COMMIT": new_commit,
                }
            )
            command = r'''
set -e
source "$SCRIPT"
RELEASE_TAG=v2.2.0
RELEASE_COMMIT="$NEW_COMMIT"
starts=0
active=1
mock_pid=100
systemctl() {
    if [[ "$1" == stop ]]; then active=0; mock_pid=0; return 0; fi
    if [[ "$1" == is-active ]]; then
        if [[ "$active" == 1 ]]; then echo active; return 0; fi
        echo inactive; return 1
    fi
    if [[ "$1" == show ]]; then printf '%s\n' "$mock_pid"; return 0; fi
    if [[ "$1" == start ]]; then
        starts=$((starts + 1))
        if [[ "$starts" -gt 1 ]]; then active=1; mock_pid=202; return 0; fi
        [[ "$starts" -gt 1 ]]
        return
    fi
    return 0
}
wait_ready() { return 0; }
set +e
activate_release "$NEW_SOURCE" "$NEW_RUNTIME"
result=$?
set -e
test "$result" = 1
test "$(readlink -f "$RUNTIME_LINK")" = "$OLD_RUNTIME"
test "$(readlink -f "$RUNTIME_LINK/source")" = "$OLD_SOURCE"
python3 - "$RELEASE_METADATA" "$UPDATE_STATUS_FILE" "$OLD_COMMIT" \
    "$NEW_COMMIT" <<'PY'
import json, sys
release = json.load(open(sys.argv[1], encoding="utf-8"))
update = json.load(open(sys.argv[2], encoding="utf-8"))
assert release["tag"] == "v2.1.0"
assert release["commit"] == sys.argv[3]
assert isinstance(release["checked_at"], str)
assert update["state"] == "available"
assert update["tag"] == "v2.2.0"
assert update["commit"] == sys.argv[4]
PY
'''
            result = subprocess.run(
                ["bash", "-c", command],
                env=env,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_manual_rollback_publishes_exact_identity_and_newer_available(self):
        script = ROOT / "ops/boudyos-deploy"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            releases = root / "releases"
            workspaces = root / "workspaces"
            old_source, old_commit = make_managed_release(
                releases, "v2.1.0", "old"
            )
            new_source, new_commit = make_managed_release(
                releases, "v2.2.0", "new"
            )
            old_runtime = make_managed_runtime(workspaces, old_commit)
            new_runtime = make_managed_runtime(workspaces, new_commit)
            current = root / "current"
            runtime_current = root / "runtime-current"
            current.symlink_to(new_source)
            runtime_current.symlink_to(new_runtime)
            previous = root / "previous"
            previous.write_text(
                f"{old_source}\n{old_runtime}\n", "utf-8"
            )
            previous.chmod(0o600)
            user = subprocess.check_output(["id", "-un"], text=True).strip()
            group = subprocess.check_output(["id", "-gn"], text=True).strip()
            env = os.environ.copy()
            env.update(
                {
                    "SCRIPT": str(script),
                    "BOUDYOS_DEPLOY_LIB": "1",
                    "BOUDYOS_RELEASE_ROOT": str(releases),
                    "BOUDYOS_RUNTIME_ROOT": str(workspaces),
                    "BOUDYOS_RUNTIME_LINK": str(runtime_current),
                    "BOUDYOS_PREVIOUS_FILE": str(previous),
                    "BOUDYOS_STATUS_DIR": str(root / "status"),
                    "BOUDYOS_DEPLOY_LOCK": str(root / "deploy.lock"),
                    "BOUDYOS_READY_FILE": str(root / "ready"),
                    "BOUDYOS_RUNTIME_USER": user,
                    "BOUDYOS_RUNTIME_GROUP": group,
                    "BOUDYOS_RELEASE_TAG": "v2.2.0",
                    "BOUDYOS_RELEASE_COMMIT": new_commit,
                    "OLD_SOURCE": str(old_source),
                    "OLD_RUNTIME": str(old_runtime),
                    "OLD_COMMIT": old_commit,
                    "NEW_COMMIT": new_commit,
                }
            )
            command = r'''
set -e
source "$SCRIPT"
active=1
mock_pid=100
systemctl() {
    if [[ "$1" == stop ]]; then active=0; mock_pid=0; return 0; fi
    if [[ "$1" == is-active ]]; then
        if [[ "$active" == 1 ]]; then echo active; return 0; fi
        echo inactive; return 1
    fi
    if [[ "$1" == show ]]; then printf '%s\n' "$mock_pid"; return 0; fi
    if [[ "$1" == start ]]; then active=1; mock_pid=200; return 0; fi
    return 0
}
wait_ready() { return 0; }
rollback_release
test "$(readlink -f "$RUNTIME_LINK")" = "$OLD_RUNTIME"
test "$(readlink -f "$RUNTIME_LINK/source")" = "$OLD_SOURCE"
python3 - "$RELEASE_METADATA" "$UPDATE_STATUS_FILE" "$STATUS_FILE" \
    "$OLD_COMMIT" "$NEW_COMMIT" <<'PY'
import json, os, stat, sys
release = json.load(open(sys.argv[1], encoding="utf-8"))
update = json.load(open(sys.argv[2], encoding="utf-8"))
deploy = json.load(open(sys.argv[3], encoding="utf-8"))
assert release["tag"] == "v2.1.0"
assert release["commit"] == sys.argv[4]
assert set(release) == {"schema_version", "tag", "commit", "checked_at"}
assert update["state"] == "available"
assert update["tag"] == "v2.2.0"
assert update["commit"] == sys.argv[5]
assert deploy["state"] == "rolled_back"
assert deploy["tag"] == "v2.1.0"
assert stat.S_IMODE(os.stat(sys.argv[1]).st_mode) == 0o640
PY
'''
            result = subprocess.run(
                ["bash", "-c", command],
                env=env,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_manual_rollback_rejects_tampered_workspace_before_stop(self):
        script = ROOT / "ops/boudyos-deploy"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            releases = root / "releases"
            workspaces = root / "workspaces"
            old_source, old_commit = make_managed_release(
                releases, "v2.1.0", "old"
            )
            new_source, new_commit = make_managed_release(
                releases, "v2.2.0", "new"
            )
            old_runtime = make_managed_runtime(workspaces, old_commit)
            new_runtime = make_managed_runtime(workspaces, new_commit)
            (old_runtime / "work" / "plugins").symlink_to(
                old_source / "plugins"
            )
            current = root / "current"
            runtime_current = root / "runtime-current"
            current.symlink_to(new_source)
            runtime_current.symlink_to(new_runtime)
            previous = root / "previous"
            previous.write_text(f"{old_source}\n{old_runtime}\n", "utf-8")
            previous.chmod(0o600)
            user = subprocess.check_output(["id", "-un"], text=True).strip()
            group = subprocess.check_output(["id", "-gn"], text=True).strip()
            command = r'''
source "$SCRIPT"
stops=0
systemctl() {
    if [[ "$1" == stop ]]; then
        stops=$((stops + 1))
    fi
    return 0
}
set +e
rollback_release
result=$?
set -e
test "$result" = 1
test "$stops" = 0
test "$(readlink -f "$RUNTIME_LINK")" = "$NEW_RUNTIME"
test "$(readlink -f "$RUNTIME_LINK/source")" = "$NEW_SOURCE"
'''
            result = subprocess.run(
                ["bash", "-c", command],
                env={
                    **os.environ,
                    "SCRIPT": str(script),
                    "BOUDYOS_DEPLOY_LIB": "1",
                    "BOUDYOS_RELEASE_ROOT": str(releases),
                    "BOUDYOS_RUNTIME_ROOT": str(workspaces),
                    "BOUDYOS_RUNTIME_LINK": str(runtime_current),
                    "BOUDYOS_PREVIOUS_FILE": str(previous),
                    "BOUDYOS_STATUS_DIR": str(root / "status"),
                    "BOUDYOS_DEPLOY_LOCK": str(root / "deploy.lock"),
                    "BOUDYOS_RUNTIME_USER": user,
                    "BOUDYOS_RUNTIME_GROUP": group,
                    "BOUDYOS_RELEASE_TAG": "v2.2.0",
                    "BOUDYOS_RELEASE_COMMIT": new_commit,
                    "NEW_SOURCE": str(new_source),
                    "NEW_RUNTIME": str(new_runtime),
                },
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_atomic_selector_never_exposes_mixed_source_and_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspaces = root / "workspaces"
            releases = root / "releases"
            commits = ("a" * 40, "b" * 40)
            for commit in commits:
                release = releases / commit
                release.mkdir(parents=True)
                (release / "identity").write_text(commit, "ascii")
                runtime = make_managed_runtime(workspaces, commit)
                (runtime / "work" / "identity").write_text(commit, "ascii")
            current = root / "current"
            current.symlink_to(workspaces / commits[0])
            for index in range(500):
                commit = commits[index % 2]
                temporary = root / "current.new"
                temporary.symlink_to(workspaces / commit)
                os.replace(temporary, current)
                source_identity = (current / "source" / "identity").read_text(
                    "ascii"
                )
                work_identity = (current / "work" / "identity").read_text(
                    "ascii"
                )
                self.assertEqual(source_identity, work_identity)

    def test_health_rejects_workspace_source_commit_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            releases = root / "releases"
            workspaces = root / "workspaces"
            first, first_commit = make_managed_release(
                releases, "v2.1.0", "first"
            )
            second, second_commit = make_managed_release(
                releases, "v2.2.0", "second"
            )
            runtime = make_managed_runtime(workspaces, first_commit)
            current = root / "current"
            current.symlink_to(runtime)
            uid = os.geteuid()
            gid = os.getegid()
            self.assertTrue(
                health.runtime_code_links_valid(
                    current, releases, workspaces, uid, gid
                )
            )
            (runtime / "source").unlink()
            (runtime / "source").symlink_to(second)
            self.assertFalse(
                health.runtime_code_links_valid(
                    current, releases, workspaces, uid, gid
                )
            )
            self.assertNotEqual(first, second)
            self.assertNotEqual(first_commit, second_commit)

    def test_stop_failure_does_not_switch_or_publish_identity(self):
        script = ROOT / "ops/boudyos-deploy"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            releases = root / "releases"
            workspaces = root / "workspaces"
            old_source, old_commit = make_managed_release(
                releases, "v2.1.0", "old-stop"
            )
            new_source, new_commit = make_managed_release(
                releases, "v2.2.0", "new-stop"
            )
            old_runtime = make_managed_runtime(workspaces, old_commit)
            new_runtime = make_managed_runtime(workspaces, new_commit)
            current = root / "current"
            current.symlink_to(old_runtime)
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    r'''
source "$SCRIPT"
RELEASE_TAG=v2.2.0
RELEASE_COMMIT="$NEW_COMMIT"
starts=0
systemctl() {
    if [[ "$1" == show ]]; then echo 100; return 0; fi
    if [[ "$1" == stop ]]; then return 1; fi
    if [[ "$1" == start ]]; then starts=$((starts + 1)); fi
    return 0
}
if activate_release "$NEW_SOURCE" "$NEW_RUNTIME"; then
    result=0
else
    result=$?
fi
test "$result" = 1
test "$starts" = 0
test "$(readlink -f "$RUNTIME_LINK")" = "$OLD_RUNTIME"
test ! -e "$RELEASE_METADATA"
grep -q '"state":"activation_failed"' "$STATUS_FILE"
''',
                ],
                env={
                    **os.environ,
                    "SCRIPT": str(script),
                    "BOUDYOS_DEPLOY_LIB": "1",
                    "BOUDYOS_RELEASE_ROOT": str(releases),
                    "BOUDYOS_RUNTIME_ROOT": str(workspaces),
                    "BOUDYOS_RUNTIME_LINK": str(current),
                    "BOUDYOS_STATUS_DIR": str(root / "status"),
                    "BOUDYOS_RELEASE_METADATA": str(root / "release.json"),
                    "BOUDYOS_READY_FILE": str(root / "ready"),
                    "BOUDYOS_RUNTIME_USER": subprocess.check_output(
                        ["id", "-un"], text=True
                    ).strip(),
                    "BOUDYOS_RUNTIME_GROUP": subprocess.check_output(
                        ["id", "-gn"], text=True
                    ).strip(),
                    "NEW_SOURCE": str(new_source),
                    "NEW_RUNTIME": str(new_runtime),
                    "NEW_COMMIT": new_commit,
                    "OLD_RUNTIME": str(old_runtime),
                },
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_readiness_rejects_unchanged_pid_and_stale_marker(self):
        script = ROOT / "ops/boudyos-deploy"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "ready"
            marker.write_text(
                json.dumps(
                    {"schema_version": 1, "pid": 42, "timestamp": 2_000}
                ),
                "ascii",
            )
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    r'''
source "$SCRIPT"
systemctl() { [[ "$1" == show ]] && echo 42; }
if ready_is_fresh 1900 42; then exit 1; fi
if ready_is_fresh 2001 0; then exit 1; fi
''',
                ],
                env={
                    **os.environ,
                    "SCRIPT": str(script),
                    "BOUDYOS_DEPLOY_LIB": "1",
                    "BOUDYOS_READY_FILE": str(marker),
                    "BOUDYOS_READY_MAX_AGE_SECONDS": "9999999999",
                },
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_deploy_and_migration_share_one_contention_lock(self):
        deploy = ROOT / "ops/boudyos-deploy"
        migration = ROOT / "ops/boudyos-migrate-ultroid"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lock = root / "transition.lock"
            holder = subprocess.Popen(
                [
                    "bash",
                    "-c",
                    'exec 8>"$LOCK"; flock 8; echo locked; read -r _',
                ],
                env={**os.environ, "LOCK": str(lock)},
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                self.assertEqual(holder.stdout.readline().strip(), "locked")
                for script, command, library_key in (
                    (deploy, "rollback_release", "BOUDYOS_DEPLOY_LIB"),
                    (migration, "rollback", "BOUDYOS_MIGRATION_LIB"),
                ):
                    result = subprocess.run(
                        ["bash", "-c", f'source "$SCRIPT"; {command}'],
                        env={
                            **os.environ,
                            "SCRIPT": str(script),
                            library_key: "1",
                            "BOUDYOS_DEPLOY_LOCK": str(lock),
                            "BOUDYOS_RELEASE_TAG": "v2.2.0",
                            "BOUDYOS_RELEASE_COMMIT": "a" * 40,
                        },
                        text=True,
                        capture_output=True,
                        timeout=5,
                        check=False,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("transition is active", result.stderr)
            finally:
                holder.communicate("\n", timeout=5)

    def test_legacy_rollback_restores_backup_to_running_legacy_state(self):
        script = ROOT / "ops/boudyos-migrate-ultroid"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy"
            legacy.mkdir()
            (legacy / "account.session").write_text("session", "utf-8")
            legacy_env = root / "ultroid.env"
            legacy_env.write_text("API_ID=example\n", "utf-8")
            backup, backup_paths, health_config = make_legacy_ops_configs(
                root, legacy
            )
            current = root / "obsolete-current"
            runtime_current = root / "current"
            dropin_dir = root / "ultroid.service.d"
            status = root / "status"
            user = subprocess.check_output(["id", "-un"], text=True).strip()
            group = subprocess.check_output(["id", "-gn"], text=True).strip()
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    r'''
set -e
source "$SCRIPT"
active=0
mock_pid=0
systemctl() {
    if [[ "$1" == stop ]]; then active=0; mock_pid=0; return 0; fi
    if [[ "$1" == is-active ]]; then
        if [[ "$active" == 1 ]]; then echo active; return 0; fi
        echo inactive; return 1
    fi
    if [[ "$1" == show ]]; then echo "$mock_pid"; return 0; fi
    if [[ "$1" == start ]]; then active=1; mock_pid=200; return 0; fi
    return 0
}
wait_ready() { [[ "$active" == 1 && "$mock_pid" == 200 ]]; }
prepare
mkdir -p "$MANAGED_RUNTIME" "$DROPIN_DIR"
ln -s "$LEGACY_SOURCE" "$OBSOLETE_SOURCE_LINK"
ln -s "$MANAGED_RUNTIME" "$RUNTIME_LINK"
printf 'managed drop-in\n' >"$DROPIN"
printf 'BACKUP_MODE=managed\n' >"$BACKUP_CONFIG"
printf '/var/lib/boudyos/current\n' >"$BACKUP_PATHS"
printf 'LAYOUT_MODE=managed\n' >"$HEALTH_CONFIG"
active=1
mock_pid=100
rollback
test ! -e "$OBSOLETE_SOURCE_LINK"
test ! -e "$RUNTIME_LINK"
test ! -e "$DROPIN"
grep -q '^BACKUP_MODE=legacy$' "$BACKUP_CONFIG"
grep -Fxq "$LEGACY_SOURCE" "$BACKUP_PATHS"
grep -q '^LAYOUT_MODE=legacy$' "$HEALTH_CONFIG"
python3 - "$BACKUP_STATUS" <<'PY'
import json, sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
assert value["state"] == "required"
assert value["mode"] == "legacy"
assert "/" not in json.dumps(value)
PY
''',
                ],
                env={
                    **os.environ,
                    "SCRIPT": str(script),
                    "BOUDYOS_MIGRATION_LIB": "1",
                    "BOUDYOS_LEGACY_USER": user,
                    "BOUDYOS_LEGACY_GROUP": group,
                    "BOUDYOS_LEGACY_SOURCE": str(legacy),
                    "BOUDYOS_LEGACY_ENV": str(legacy_env),
                    "BOUDYOS_NEW_ENV": str(root / "runtime.env"),
                    "BOUDYOS_RUNTIME_ROOT": str(root / "workspaces"),
                    "BOUDYOS_SNAPSHOT_ROOT": str(root / "snapshots"),
                    "BOUDYOS_MIGRATION_RECORD": str(root / "migration.json"),
                    "BOUDYOS_OBSOLETE_CURRENT_LINK": str(current),
                    "BOUDYOS_RUNTIME_LINK": str(runtime_current),
                    "BOUDYOS_BACKUP_CONFIG": str(backup),
                    "BOUDYOS_BACKUP_PATHS": str(backup_paths),
                    "BOUDYOS_HEALTH_CONFIG": str(health_config),
                    "BOUDYOS_DROPIN_DIR": str(dropin_dir),
                    "BOUDYOS_STATUS_DIR": str(status),
                    "BOUDYOS_DEPLOY_LOCK": str(root / "deploy.lock"),
                    "BOUDYOS_READY_FILE": str(root / "ready"),
                    "MANAGED_RUNTIME": str(root / "managed-runtime"),
                },
                text=True,
                capture_output=True,
                timeout=15,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_every_readwrite_path_is_provisioned_before_execstart(self):
        tmpfiles = ROOT / "ops/tmpfiles.d/boudyos.conf"
        provisioned = {
            line.split()[1]
            for line in tmpfiles.read_text("utf-8").splitlines()
            if line.startswith("d ")
        }
        units = sorted((ROOT / "ops/systemd").glob("*"))
        for unit in units:
            text = unit.read_text("utf-8")
            unit_provisioned = set(provisioned)
            for line in text.splitlines():
                if line.startswith("StateDirectory="):
                    for value in line.split("=", 1)[1].split():
                        unit_provisioned.add("/var/lib/" + value)
                if line.startswith("RuntimeDirectory="):
                    for value in line.split("=", 1)[1].split():
                        unit_provisioned.add("/run/" + value)
            if "ExecStart=" in text and unit.name != "boudyos-paths.service":
                self.assertIn(
                    "Requires=boudyos-paths.service", text, unit.name
                )
                self.assertIn(
                    "After=", text, unit.name
                )
                self.assertIn("boudyos-paths.service", text, unit.name)
            for line in text.splitlines():
                if not line.startswith("ReadWritePaths="):
                    continue
                for configured in line.split("=", 1)[1].split():
                    safely_optional = configured.startswith("-")
                    path = configured.removeprefix("-")
                    if safely_optional:
                        self.assertEqual(path, "/var/lib/boudyos/current/work")
                        self.assertIn(
                            "WorkingDirectory=/var/lib/boudyos/current/work", text
                        )
                    else:
                        self.assertIn(path, unit_provisioned, (unit.name, path))
        paths_unit = (
            ROOT / "ops/systemd/boudyos-paths.service"
        ).read_text("utf-8")
        self.assertLess(
            paths_unit.index("ExecStart=/usr/bin/systemd-tmpfiles"),
            paths_unit.index("RemainAfterExit=yes"),
        )
        for account_unit in (
            "boudyos.service.example", "ultroid-boudyos.conf.example"
        ):
            text = (ROOT / "ops/systemd" / account_unit).read_text("utf-8")
            self.assertIn("RuntimeDirectory=boudyos", text)
            self.assertIn("StateDirectory=boudyos/app-status", text)

    def test_legacy_layout_migration_plan_is_exact(self):
        result = subprocess.run(
            [str(ROOT / "ops/boudyos-migrate-ultroid"), "plan"],
            text=True,
            capture_output=True,
            timeout=3,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for value in (
            "legacy_user=ultroid",
            "legacy_service=ultroid.service",
            "legacy_source=/opt/ultroid",
            "legacy_env=/etc/ultroid/ultroid.env",
        ):
            self.assertIn(value, result.stdout)

    def test_legacy_migration_contract_stages_snapshots_and_rolls_back(self):
        source = (ROOT / "ops/boudyos-migrate-ultroid").read_text("utf-8")
        documentation = (ROOT / "MIGRATION.md").read_text("utf-8")
        self.assertIn('cp -a --no-dereference -- "$LEGACY_SOURCE"', source)
        self.assertIn("os.chmod(temporary, 0o600)", source)
        self.assertIn("boudyos-deploy stage", documentation)
        self.assertIn("boudyos-migrate-ultroid rollback", documentation)
        self.assertIn("original ultroid.service was restored", source)

    def test_python310_launcher_excludes_writable_working_directory(self):
        launcher = ROOT / "ops/boudyos-python-launcher"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            work = root / "work"
            (source / "ops").mkdir(parents=True)
            (source / "pyUltroid").mkdir()
            (work / "pyUltroid").mkdir(parents=True)
            shutil.copy2(launcher, source / "ops/boudyos-python-launcher")
            result_path = root / "result.txt"
            (source / "pyUltroid/__main__.py").write_text(
                "import os, sys\n"
                "from pathlib import Path\n"
                "work = Path(os.environ['TEST_WORK']).resolve()\n"
                "paths = {Path(p).resolve() for p in sys.path if p}\n"
                "Path(os.environ['TEST_RESULT']).write_text("
                "'source' if work not in paths else 'unsafe', encoding='ascii')\n",
                "utf-8",
            )
            (work / "pyUltroid/__main__.py").write_text(
                "raise SystemExit('writable package executed')\n", "utf-8"
            )
            result = subprocess.run(
                [sys.executable, "-s", str(source / "ops/boudyos-python-launcher")],
                cwd=work,
                env={
                    **os.environ,
                    "TEST_WORK": str(work),
                    "TEST_RESULT": str(result_path),
                    "PYTHONPATH": str(work),
                },
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result_path.read_text("ascii"), "source")

    def test_legacy_restart_stability_does_not_require_managed_heartbeat(self):
        script = ROOT / "ops/boudyos-migrate-ultroid"
        with tempfile.TemporaryDirectory() as tmp:
            ready = Path(tmp) / "ready"
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    r'''
source "$SCRIPT"
systemctl() {
    if [[ "$1" == show ]]; then echo 222; return 0; fi
    if [[ "$1" == is-active ]]; then return 0; fi
    return 0
}
sleep() { :; }
wait_legacy_stable 111
test ! -e "$BOUDYOS_READY_FILE"
''',
                ],
                env={
                    **os.environ,
                    "SCRIPT": str(script),
                    "BOUDYOS_MIGRATION_LIB": "1",
                    "BOUDYOS_READY_FILE": str(ready),
                    "BOUDYOS_LEGACY_STABILITY_SECONDS": "2",
                    "BOUDYOS_LEGACY_STABILITY_ATTEMPTS": "3",
                },
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_legacy_restart_stability_rejects_pid_flapping(self):
        script = ROOT / "ops/boudyos-migrate-ultroid"
        with tempfile.TemporaryDirectory() as tmp:
            counter = Path(tmp) / "counter"
            counter.write_text("0", "ascii")
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    r'''
source "$SCRIPT"
systemctl() {
    if [[ "$1" == show ]]; then
        n=$(cat "$COUNTER"); n=$((n + 1)); printf '%s' "$n" > "$COUNTER"
        if (( n % 2 )); then echo 222; else echo 333; fi
        return 0
    fi
    if [[ "$1" == is-active ]]; then return 0; fi
    return 0
}
sleep() { :; }
if wait_legacy_stable 111; then exit 9; fi
''',
                ],
                env={
                    **os.environ,
                    "SCRIPT": str(script),
                    "COUNTER": str(counter),
                    "BOUDYOS_MIGRATION_LIB": "1",
                    "BOUDYOS_LEGACY_STABILITY_SECONDS": "2",
                    "BOUDYOS_LEGACY_STABILITY_ATTEMPTS": "4",
                },
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_managed_readiness_still_requires_heartbeat(self):
        script = ROOT / "ops/boudyos-migrate-ultroid"
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    r'''
source "$SCRIPT"
systemctl() {
    if [[ "$1" == show ]]; then echo 222; return 0; fi
    if [[ "$1" == is-active ]]; then return 0; fi
    return 0
}
sleep() { :; }
if wait_ready 1 111; then exit 9; fi
''',
                ],
                env={
                    **os.environ,
                    "SCRIPT": str(script),
                    "BOUDYOS_MIGRATION_LIB": "1",
                    "BOUDYOS_READY_FILE": str(Path(tmp) / "missing-ready"),
                },
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_legacy_migration_prepare_preserves_exact_state_and_snapshot(self):
        script = ROOT / "ops/boudyos-migrate-ultroid"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "opt-ultroid"
            legacy.mkdir()
            (legacy / "account.session").write_text("session", "utf-8")
            (legacy / "database.json").write_text('{"value": 1}', "utf-8")
            legacy_env = root / "ultroid.env"
            legacy_env.write_text("API_ID=example\n", "utf-8")
            backup, backup_paths, health_config = make_legacy_ops_configs(
                root, legacy
            )
            user = subprocess.check_output(["id", "-un"], text=True).strip()
            group = subprocess.check_output(["id", "-gn"], text=True).strip()
            env = os.environ.copy()
            env.update(
                {
                    "SCRIPT": str(script),
                    "BOUDYOS_MIGRATION_LIB": "1",
                    "BOUDYOS_LEGACY_USER": user,
                    "BOUDYOS_LEGACY_GROUP": group,
                    "BOUDYOS_LEGACY_SOURCE": str(legacy),
                    "BOUDYOS_LEGACY_ENV": str(legacy_env),
                    "BOUDYOS_NEW_ENV": str(root / "etc-boudyos/runtime.env"),
                    "BOUDYOS_RUNTIME_ROOT": str(root / "workspaces"),
                    "BOUDYOS_SNAPSHOT_ROOT": str(root / "snapshots"),
                    "BOUDYOS_MIGRATION_RECORD": str(root / "migration.record"),
                    "BOUDYOS_RUNTIME_LINK": str(root / "runtime-current"),
                    "BOUDYOS_DROPIN_DIR": str(root / "ultroid.service.d"),
                    "BOUDYOS_BACKUP_CONFIG": str(backup),
                    "BOUDYOS_BACKUP_PATHS": str(backup_paths),
                    "BOUDYOS_HEALTH_CONFIG": str(health_config),
                    "BOUDYOS_DEPLOY_LOCK": str(root / "deploy.lock"),
                    "BOUDYOS_READY_FILE": str(root / "ready"),
                }
            )
            command = r'''
set -e
source "$SCRIPT"
systemctl() { [[ "$1" == is-active ]] && return 1; return 0; }
prepare
snapshot="$(python3 - "$RECORD" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["snapshot"])
PY
)"
test "$(cat "$snapshot/source/account.session")" = session
test "$(cat "$snapshot/source/database.json")" = '{"value": 1}'
test "$(cat "$snapshot/ultroid.env")" = API_ID=example
seed="$(python3 - "$RECORD" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["seed"])
PY
)"
test "$(cat "$seed/work/account.session")" = session
test ! -e "$seed/pyUltroid"
test "$(stat -c %a "$RECORD")" = 600
before_count=$(find "$SNAPSHOT_ROOT" -mindepth 1 -maxdepth 1 -type d | wc -l)
systemctl() {
    if [[ "$1" == is-active ]]; then return 0; fi
    if [[ "$1" == show ]]; then echo 222; return 0; fi
    return 0
}
prepare
after_count=$(find "$SNAPSHOT_ROOT" -mindepth 1 -maxdepth 1 -type d | wc -l)
test "$before_count" = "$after_count"
'''
            result = subprocess.run(
                ["bash", "-c", command],
                env=env,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_legacy_prepare_stage_activate_uses_exact_staged_template(self):
        migration = ROOT / "ops/boudyos-migrate-ultroid"
        deploy = ROOT / "ops/boudyos-deploy"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy"
            legacy.mkdir()
            (legacy / "account.session").write_text("session", "utf-8")
            legacy_env = root / "ultroid.env"
            legacy_env.write_text("API_ID=example\n", "utf-8")
            backup, backup_paths, health_config = make_legacy_ops_configs(
                root, legacy
            )
            releases = root / "releases"
            workspaces = root / "workspaces"
            current = root / "current"
            runtime_current = root / "runtime-current"
            status = root / "status"
            staged_state = status / "staged-release.json"
            deploy_config = root / "deploy.conf"
            dropin_dir = root / "ultroid.service.d"
            user = subprocess.check_output(["id", "-un"], text=True).strip()
            group = subprocess.check_output(["id", "-gn"], text=True).strip()
            common = os.environ.copy()
            common.update(
                {
                    "BOUDYOS_MIGRATION_LIB": "1",
                    "BOUDYOS_LEGACY_USER": user,
                    "BOUDYOS_LEGACY_GROUP": group,
                    "BOUDYOS_LEGACY_SOURCE": str(legacy),
                    "BOUDYOS_LEGACY_ENV": str(legacy_env),
                    "BOUDYOS_NEW_ENV": str(root / "etc-boudyos/runtime.env"),
                    "BOUDYOS_RELEASE_ROOT": str(releases),
                    "BOUDYOS_RUNTIME_ROOT": str(workspaces),
                    "BOUDYOS_SNAPSHOT_ROOT": str(root / "snapshots"),
                    "BOUDYOS_MIGRATION_RECORD": str(root / "migration.record"),
                    "BOUDYOS_OBSOLETE_CURRENT_LINK": str(current),
                    "BOUDYOS_RUNTIME_LINK": str(runtime_current),
                    "BOUDYOS_BACKUP_CONFIG": str(backup),
                    "BOUDYOS_BACKUP_PATHS": str(backup_paths),
                    "BOUDYOS_HEALTH_CONFIG": str(health_config),
                    "BOUDYOS_DEPLOY_LOCK": str(root / "deploy.lock"),
                    "BOUDYOS_READY_FILE": str(root / "ready"),
                    "BOUDYOS_DEPLOY_CONFIG": str(deploy_config),
                    "BOUDYOS_DROPIN_DIR": str(dropin_dir),
                    "BOUDYOS_STATUS_DIR": str(status),
                    "BOUDYOS_APP_STATUS_DIR": str(root / "app-status"),
                    "BOUDYOS_STAGED_METADATA": str(staged_state),
                }
            )
            prepared = subprocess.run(
                [
                    "bash", "-c",
                    'source "$SCRIPT"; '
                    'systemctl() { [[ "$1" != is-active ]]; }; prepare',
                ],
                env={**common, "SCRIPT": str(migration)},
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(prepared.returncode, 0, prepared.stderr)

            release, commit = make_managed_release(
                releases, "v2.2.0", "staged"
            )
            runtime = workspaces / commit
            staged = subprocess.run(
                [
                    "bash", "-c",
                    'set -e; source "$SCRIPT"; RELEASE_TAG=v2.2.0; '
                    'RELEASE_COMMIT="$COMMIT"; '
                    'prepare_runtime "$SOURCE" "$RUNTIME" "" "$SOURCE"; '
                    'write_staged_release_metadata "$SOURCE" "$RUNTIME"',
                ],
                env={
                    **common,
                    "SCRIPT": str(deploy),
                    "SOURCE": str(release),
                    "RUNTIME": str(runtime),
                    "COMMIT": commit,
                    "BOUDYOS_DEPLOY_LIB": "1",
                    "BOUDYOS_RUNTIME_USER": user,
                    "BOUDYOS_RUNTIME_GROUP": group,
                },
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(staged.returncode, 0, staged.stderr)
            deploy_config.write_text(
                "BOUDYOS_RELEASE_TAG=v2.2.0\n"
                f"BOUDYOS_RELEASE_COMMIT={commit}\n"
                f"BOUDYOS_RELEASE_ROOT={releases}\n"
                f"BOUDYOS_RUNTIME_ROOT={workspaces}\n",
                "utf-8",
            )
            deploy_config.chmod(0o600)
            managed_paths = root / "backup-paths"
            managed_paths.write_text(f"{runtime_current}\n", "utf-8")
            backup.write_text(
                "BACKUP_MODE=managed\n"
                f"ALLOWLIST_FILE={managed_paths}\n"
                f"BOUDYOS_RUNTIME_ROOT={workspaces}\n"
                f"BOUDYOS_RUNTIME_LINK={runtime_current}\n"
                "QUIESCE_SERVICE=ultroid.service\n",
                "utf-8",
            )
            health_config.write_text(
                "LAYOUT_MODE=managed\n"
                "SERVICE=ultroid.service\n"
                f"RELEASE_ROOT={releases}\n"
                f"WORKSPACE_ROOT={workspaces}\n"
                f"RUNTIME_LINK={runtime_current}\n",
                "utf-8",
            )

            activated = subprocess.run(
                [
                    "bash", "-c",
                    'set -e; source "$SCRIPT"; '
                    'active=1; mock_pid=100; '
                    'systemctl() { '
                    'if [[ "$1" == stop ]]; then active=0; mock_pid=0; return 0; fi; '
                    'if [[ "$1" == is-active ]]; then '
                    'if [[ "$active" == 1 ]]; then echo active; return 0; fi; '
                    'echo inactive; return 1; fi; '
                    'if [[ "$1" == show ]]; then echo "$mock_pid"; return 0; fi; '
                    'if [[ "$1" == start ]]; then active=1; mock_pid=200; return 0; fi; '
                    'return 0; }; wait_ready() { return 0; }; '
                    'activate',
                ],
                env={**common, "SCRIPT": str(migration)},
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(activated.returncode, 0, activated.stderr)
            self.assertFalse(current.exists())
            self.assertEqual(runtime_current.resolve(), runtime)
            self.assertEqual((runtime_current / "source").resolve(), release)
            self.assertEqual(
                (dropin_dir / "boudyos.conf").read_text("utf-8"),
                (release / "ops/systemd/ultroid-boudyos.conf.example").read_text(
                    "utf-8"
                ),
            )
            state = json.loads(staged_state.read_text("utf-8"))
            self.assertEqual(state["release_path"], str(release))
            self.assertEqual(state["runtime_path"], str(runtime))
            self.assertEqual(state["commit"], commit)
            self.assertEqual(stat.S_IMODE(staged_state.stat().st_mode), 0o640)

    def test_legacy_activation_rejects_linked_staged_state(self):
        migration = ROOT / "ops/boudyos-migrate-ultroid"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_state = root / "real.json"
            real_state.write_text("{}", "utf-8")
            linked_state = root / "staged.json"
            linked_state.symlink_to(real_state)
            releases = root / "releases"
            workspaces = root / "workspaces"
            releases.mkdir()
            workspaces.mkdir()
            result = subprocess.run(
                [
                    "bash", "-c",
                    'source "$SCRIPT"; load_staged_release "$RELEASES" '
                    '"$WORKSPACES" v2.2.0 "$COMMIT"',
                ],
                env={
                    **os.environ,
                    "SCRIPT": str(migration),
                    "BOUDYOS_MIGRATION_LIB": "1",
                    "BOUDYOS_STAGED_METADATA": str(linked_state),
                    "RELEASES": str(releases),
                    "WORKSPACES": str(workspaces),
                    "COMMIT": "a" * 40,
                },
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ownership or format is unsafe", result.stderr)
