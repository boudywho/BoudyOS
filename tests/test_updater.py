import importlib.util
import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_package_module(name):
    package_name = "test_update_security"
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


subprocess_module = load_package_module("subprocess")
updater = load_package_module("updater")


class FakeGit:
    def __init__(
        self,
        *,
        origin=None,
        branch="HEAD",
        dirty="",
        current="a" * 40,
        remote="b" * 40,
        ancestor=True,
    ):
        self.origin = origin or updater.APPROVED_ORIGIN
        self.branch = branch
        self.dirty = dirty
        self.current = current
        self.remote = remote
        self.ancestor = ancestor
        self.calls = []

    async def __call__(self, argv, **kwargs):
        self.calls.append(tuple(argv))
        command = tuple(argv[3:])
        values = {
            ("remote", "get-url", "origin"): self.origin,
            ("rev-parse", "--abbrev-ref", "HEAD"): self.branch,
            ("status", "--porcelain", "--untracked-files=normal"): self.dirty,
            ("rev-parse", "HEAD"): self.current,
            ("rev-parse", "refs/tags/v2.2.0^{commit}"): self.remote,
        }
        returncode = 0
        if command == ("merge-base", "--is-ancestor", self.current, self.remote):
            returncode = 0 if self.ancestor else 1
        return subprocess_module.ProcessResult(
            tuple(argv), returncode, values.get(command, ""), ""
        )


class UpdatePolicyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._environment = mock.patch.dict(os.environ)
        self._environment.start()
        os.environ.pop("BOUDYOS_RELEASE_METADATA", None)
        self._repository_tmp = tempfile.TemporaryDirectory()
        self.repository = Path(self._repository_tmp.name)
        (self.repository / ".git").mkdir()

    async def asyncTearDown(self):
        self._repository_tmp.cleanup()
        self._environment.stop()

    async def test_check_reports_without_mutating_checkout(self):
        fake = FakeGit()
        state = await updater.check_for_update(
            self.repository,
            runner=fake,
            target_tag="v2.2.0",
            target_commit="b" * 40,
        )
        self.assertTrue(state.update_available)
        flattened = " ".join(" ".join(call) for call in fake.calls)
        for forbidden in (" reset ", " checkout ", " pull ", " pip3 ", " push "):
            self.assertNotIn(forbidden, " " + flattened + " ")

    async def test_unapproved_origin_branch_and_dirty_tree_fail_safe(self):
        state = await updater.check_for_update(
            self.repository,
            runner=FakeGit(origin="https://github.com/TeamUltroid/Ultroid.git"),
            target_tag="v2.2.0",
            target_commit="b" * 40,
        )
        self.assertEqual(state.state, "blocked")
        self.assertNotIn("TeamUltroid", updater.format_update_report(state))
        state = await updater.check_for_update(
            self.repository,
            runner=FakeGit(branch="feature"),
            target_tag="v2.2.0",
            target_commit="b" * 40,
        )
        self.assertEqual(state.state, "blocked")
        state = await updater.check_for_update(
            self.repository,
            runner=FakeGit(dirty=" M plugins/bot.py"),
            target_tag="v2.2.0",
            target_commit="b" * 40,
        )
        self.assertTrue(state.update_available)
        self.assertTrue(state.dirty)

    async def test_detached_tag_must_match_pin_and_forward_history(self):
        mismatch = FakeGit(remote="c" * 40)
        state = await updater.check_for_update(
            self.repository,
            runner=mismatch,
            target_tag="v2.2.0",
            target_commit="b" * 40,
        )
        self.assertEqual(state.state, "blocked")
        unrelated = FakeGit(ancestor=False)
        state = await updater.check_for_update(
            self.repository,
            runner=unrelated,
            target_tag="v2.2.0",
            target_commit="b" * 40,
        )
        self.assertEqual(state.state, "blocked")

    async def test_runtime_metadata_is_tag_aware_and_rejects_downgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata = Path(tmp) / "release.json"
            metadata.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "origin": updater.APPROVED_ORIGIN,
                        "tag": "v2.1.2",
                        "commit": "a" * 40,
                        "dirty": False,
                    }
                ),
                "utf-8",
            )
            state = await updater.check_for_update(
                Path(tmp),
                target_tag="v2.2.0",
                target_commit="b" * 40,
                metadata_path=metadata,
            )
            self.assertTrue(state.update_available)
            state = await updater.check_for_update(
                Path(tmp),
                target_tag="v2.0.0",
                target_commit="b" * 40,
                metadata_path=metadata,
            )
            self.assertEqual(state.state, "blocked")

    async def test_runtime_metadata_path_wins_over_unexpected_git_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            metadata = root / "release.json"
            metadata.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "tag": "v2.1.0",
                        "commit": "a" * 40,
                        "checked_at": "2026-07-30T00:00:00Z",
                    }
                ),
                "utf-8",
            )
            fake = FakeGit()
            state = await updater.check_for_update(
                root,
                runner=fake,
                target_tag="v2.2.0",
                target_commit="b" * 40,
                metadata_path=metadata,
            )
            self.assertTrue(state.update_available)
            self.assertEqual(fake.calls, [])

    async def test_rollback_metadata_makes_configured_newer_release_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata = Path(tmp) / "release.json"
            metadata.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "tag": "v2.1.0",
                        "commit": "a" * 40,
                        "checked_at": "2026-07-30T00:00:00Z",
                    }
                ),
                "utf-8",
            )
            state = await updater.check_for_update(
                Path(tmp),
                target_tag="v2.2.0",
                target_commit="b" * 40,
                metadata_path=metadata,
            )
            self.assertEqual(state.state, "available")
            self.assertEqual(state.current_revision, "a" * 40)
            self.assertEqual(state.available_revision, "b" * 40)

    def test_release_identity_uses_only_validated_metadata_and_safe_origin(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata = Path(tmp) / "release.json"
            metadata.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "tag": "v2.2.0",
                        "commit": "a" * 40,
                        "checked_at": "2026-07-30T00:00:00Z",
                    }
                ),
                "utf-8",
            )
            label, link = updater.release_identity(metadata)
            self.assertEqual(label, "v2.2.0 (aaaaaaaaaaaa)")
            self.assertEqual(
                link,
                "https://github.com/boudywho/BoudyOS/tree/" + "a" * 40,
            )

    async def test_root_status_supplies_configured_target_without_env_exposure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_status = root / "update.json"
            target_status.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "state": "available",
                        "tag": "v2.2.0",
                        "commit": "b" * 40,
                    }
                ),
                "utf-8",
            )
            metadata = root / "release.json"
            metadata.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "origin": updater.APPROVED_ORIGIN,
                        "tag": "v2.1.0",
                        "commit": "a" * 40,
                        "dirty": False,
                    }
                ),
                "utf-8",
            )
            state = await updater.check_for_update(
                root,
                metadata_path=metadata,
                target_status_path=target_status,
            )
            self.assertTrue(state.update_available)
            self.assertEqual(state.available_revision, "b" * 40)

    async def test_request_uses_only_short_allowlisted_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            helper = Path(tmp) / "helper"
            helper.write_text("#!/bin/sh\nexit 0\n", "utf-8")
            helper.chmod(0o755)
            old = updater.APPROVED_HELPERS
            updater.APPROVED_HELPERS = frozenset((str(helper),))
            fake = FakeGit()
            try:
                await updater.request_deployment(str(helper), runner=fake)
            finally:
                updater.APPROVED_HELPERS = old
            self.assertEqual(
                fake.calls[-1][:4],
                ("sudo", "-n", str(helper), "request"),
            )

    def test_only_main_or_release_tags_are_approved(self):
        for reference in ("main", "2.2.0", "v2.2.0"):
            self.assertTrue(updater.is_approved_ref(reference))
        for reference in ("dev", "../main", "v2.2", "2.2.0;id"):
            self.assertFalse(updater.is_approved_ref(reference))

    def test_helper_allowlist_rejects_arbitrary_programs(self):
        with self.assertRaises(ValueError):
            updater.validate_helper("/bin/sh")
