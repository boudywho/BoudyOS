import json
import os
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ops/boudyos-rename-service"


class ServiceRenameTests(unittest.TestCase):
    def make_fixture(self, root, health_success=True):
        unit_dir = root / "systemd"
        dropin = unit_dir / "ultroid.service.d"
        bin_dir = root / "bin"
        unit_dir.mkdir()
        dropin.mkdir()
        bin_dir.mkdir()
        unit = unit_dir / "ultroid.service"
        unit.write_text(
            "[Unit]\nRequires=ultroid-redis.service\n"
            "[Service]\nUser=ultroid\nGroup=ultroid\n"
            "Environment=PRIVATE_TOKEN=fixture-secret\n",
            "utf-8",
        )
        override = dropin / "boudyos.conf"
        override.write_text(
            "[Service]\nUser=ultroid\nGroup=ultroid\n"
            "WorkingDirectory=/var/lib/boudyos/current/work\n"
            "EnvironmentFile=/etc/boudyos/runtime.env\n"
            "Environment=PYTHONPATH=/var/lib/boudyos/current/source\n"
            "ExecStart=\n"
            "ExecStart=/var/lib/boudyos/current/source/.venv/bin/python -s "
            "/var/lib/boudyos/current/source/ops/boudyos-python-launcher\n",
            "utf-8",
        )
        unit.chmod(0o640)
        override.chmod(0o600)
        configs = []
        for name, prefix in (
            ("deploy.conf", "BOUDYOS_SERVICE="),
            ("backup.conf", "QUIESCE_SERVICE="),
            ("health.conf", "SERVICE="),
        ):
            path = root / name
            path.write_text(
                prefix + "ultroid.service\nSECRET=do-not-print-this\n", "utf-8"
            )
            path.chmod(0o640)
            configs.append(path)

        state = root / "systemctl-state"
        state.mkdir()
        (state / "active").write_text("ultroid.service\n", "ascii")
        (state / "pid").write_text("101\n", "ascii")
        (state / "legacy-enabled").write_text("enabled\n", "ascii")
        ready = root / "ready"
        ready.write_text(
            json.dumps(
                {"schema_version": 1, "pid": 101, "timestamp": int(time.time())}
            ),
            "ascii",
        )
        fake = bin_dir / "systemctl"
        fake.write_text(
            """#!/usr/bin/env bash
set -eu
command="$1"; shift
service="${!#:-}"
case "$command" in
  is-active)
    [[ "$(cat "$FAKE_STATE/active")" == "$service" ]]
    ;;
  show)
    service="$1"
    if [[ "$(cat "$FAKE_STATE/active")" == "$service" ]]; then
      cat "$FAKE_STATE/pid"
    else
      echo 0
    fi
    ;;
  stop)
    : >"$FAKE_STATE/active"; echo 0 >"$FAKE_STATE/pid"
    ;;
  start)
    echo "$service" >"$FAKE_STATE/active"
    if [[ "$service" == "boudyos.service" ]]; then pid=202; else pid=303; fi
    echo "$pid" >"$FAKE_STATE/pid"
    python3 - "$BOUDYOS_READY_FILE" "$pid" <<'PY'
import json, sys, time
with open(sys.argv[1], "w", encoding="ascii") as stream:
    json.dump({"schema_version": 1, "pid": int(sys.argv[2]),
               "timestamp": int(time.time())}, stream)
PY
    ;;
  is-enabled)
    if [[ "$service" == "ultroid.service" ]]; then
      cat "$FAKE_STATE/legacy-enabled"
    elif [[ -f "$FAKE_STATE/target-enabled" ]]; then
      cat "$FAKE_STATE/target-enabled"
    else
      echo disabled; exit 1
    fi
    ;;
  enable)
    [[ "$service" != "boudyos.service" ]] || echo enabled >"$FAKE_STATE/target-enabled"
    [[ "$service" != "ultroid.service" ]] || echo enabled >"$FAKE_STATE/legacy-enabled"
    ;;
  disable)
    [[ "$service" != "boudyos.service" ]] || echo disabled >"$FAKE_STATE/target-enabled"
    [[ "$service" != "ultroid.service" ]] || echo disabled >"$FAKE_STATE/legacy-enabled"
    ;;
  daemon-reload) ;;
  *) exit 2 ;;
esac
""",
            "utf-8",
        )
        fake.chmod(0o755)
        health = root / "health-helper"
        if health_success:
            health.write_text(
                "#!/usr/bin/env bash\nset -e\n"
                "[[ \"$PYTHONPATH\" == \"$EXPECTED_HEALTH_PYTHONPATH\" ]]\n"
                "if [[ \"$(cat \"$FAKE_STATE/active\")\" == boudyos.service ]]; then\n"
                "  grep -Fxq SERVICE=boudyos.service \"$BOUDYOS_HEALTH_CONFIG\"\n"
                "fi\n",
                "utf-8",
            )
        else:
            health.write_text(
                "#!/usr/bin/env bash\nset -e\n"
                "[[ \"$PYTHONPATH\" == \"$EXPECTED_HEALTH_PYTHONPATH\" ]]\n"
                "if [[ \"$(cat \"$FAKE_STATE/active\")\" == boudyos.service ]]; then\n"
                "  grep -Fxq SERVICE=boudyos.service \"$BOUDYOS_HEALTH_CONFIG\"\n"
                "  grep -Fxq BOUDYOS_SERVICE=ultroid.service \"$LIVE_DEPLOY\"\n"
                "  grep -Fxq QUIESCE_SERVICE=ultroid.service \"$LIVE_BACKUP\"\n"
                "  grep -Fxq SERVICE=ultroid.service \"$LIVE_HEALTH\"\n"
                "  exit 1\n"
                "fi\n",
                "utf-8",
            )
        health.chmod(0o755)
        health_pythonpath = root / "health-pythonpath"
        inherited_pythonpath = root / "inherited-pythonpath"
        env = {
            **os.environ,
            "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
            "FAKE_STATE": str(state),
            "BOUDYOS_RENAME_TEST_MODE": "1",
            "BOUDYOS_RENAME_LIB": "1",
            "BOUDYOS_RENAME_UNIT_DIR": str(unit_dir),
            "BOUDYOS_DEPLOY_CONFIG": str(configs[0]),
            "BOUDYOS_BACKUP_CONFIG": str(configs[1]),
            "BOUDYOS_HEALTH_CONFIG": str(configs[2]),
            "BOUDYOS_HEALTH_PYTHONPATH": str(health_pythonpath),
            "BOUDYOS_READY_FILE": str(ready),
            "BOUDYOS_HEALTH_HELPER": str(health),
            "PYTHONPATH": str(inherited_pythonpath),
            "EXPECTED_HEALTH_PYTHONPATH": os.pathsep.join(
                (str(health_pythonpath), str(inherited_pythonpath))
            ),
            "LIVE_DEPLOY": str(configs[0]),
            "LIVE_BACKUP": str(configs[1]),
            "LIVE_HEALTH": str(configs[2]),
            "BOUDYOS_RENAME_RECORD": str(root / "rename-record"),
            "BOUDYOS_RENAME_LOCK": str(root / "rename.lock"),
            "BOUDYOS_RENAME_READY_ATTEMPTS": "2",
            "BOUDYOS_RENAME_READY_INTERVAL": "0",
        }
        return unit_dir, configs, state, env

    def run_rename(self, env, action="rename"):
        return subprocess.run(
            [
                "bash", "-c",
                'source "$SCRIPT" "$RUN_ACTION"; require_root() { :; }; main',
            ],
            env={**env, "SCRIPT": str(SCRIPT), "RUN_ACTION": action},
            text=True, capture_output=True,
            timeout=10, check=False
        )

    def test_success_preserves_legacy_runtime_contract_and_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            unit_dir, configs, state, env = self.make_fixture(root)
            result = self.run_rename(env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((unit_dir / "ultroid.service").exists())
            target = unit_dir / "boudyos.service"
            self.assertTrue(target.is_file())
            combined = target.read_text("utf-8") + (
                unit_dir / "boudyos.service.d/boudyos.conf"
            ).read_text("utf-8")
            self.assertIn("User=ultroid", combined)
            self.assertIn("Group=ultroid", combined)
            self.assertIn("Requires=ultroid-redis.service", combined)
            self.assertNotIn("boudyos-redis.service", combined)
            for config in configs:
                self.assertIn("boudyos.service", config.read_text("utf-8"))
                self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o640)
            self.assertEqual((state / "active").read_text().strip(), "boudyos.service")
            self.assertEqual((state / "target-enabled").read_text().strip(), "enabled")
            self.assertNotIn("fixture-secret", result.stdout + result.stderr)
            self.assertNotIn("do-not-print-this", result.stdout + result.stderr)

    def test_plan_validates_without_mutating_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            unit_dir, configs, _state, env = self.make_fixture(root)
            watched = [
                unit_dir / "ultroid.service",
                unit_dir / "ultroid.service.d/boudyos.conf",
                *configs,
            ]
            before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in watched}
            result = self.run_rename(env, "plan")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("plan:", result.stdout)
            self.assertFalse((unit_dir / "boudyos.service").exists())
            self.assertFalse((root / "rename-record").exists())
            for path, expected in before.items():
                self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), expected)
            self.assertNotIn("do-not-print-this", result.stdout + result.stderr)

    def test_second_run_is_a_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            unit_dir, configs, state, env = self.make_fixture(root)
            first = self.run_rename(env)
            self.assertEqual(first.returncode, 0, first.stderr)
            before = {
                path: (path.read_bytes(), path.stat().st_mtime_ns)
                for path in [unit_dir / "boudyos.service", *configs]
            }
            second = self.run_rename(env)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("already migrated", second.stdout)
            for path, value in before.items():
                self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), value)

    def test_health_failure_rolls_back_exact_files_and_running_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            unit_dir, configs, state, env = self.make_fixture(
                root, health_success=False
            )
            original_unit = (unit_dir / "ultroid.service").read_bytes()
            original_dropin = (
                unit_dir / "ultroid.service.d/boudyos.conf"
            ).read_bytes()
            original_configs = [(p.read_bytes(), stat.S_IMODE(p.stat().st_mode)) for p in configs]
            result = self.run_rename(env)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((unit_dir / "boudyos.service").exists())
            self.assertEqual((unit_dir / "ultroid.service").read_bytes(), original_unit)
            self.assertEqual(
                (unit_dir / "ultroid.service.d/boudyos.conf").read_bytes(),
                original_dropin,
            )
            for path, expected in zip(configs, original_configs):
                self.assertEqual(
                    (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)), expected
                )
            self.assertEqual((state / "active").read_text().strip(), "ultroid.service")
            self.assertEqual((state / "pid").read_text().strip(), "303")
            self.assertIn("restored and verified", result.stderr)
            self.assertNotIn("do-not-print-this", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
