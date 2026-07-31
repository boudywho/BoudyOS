import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_package_module(name):
    package_name = "test_boudyos_security"
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
    path = ROOT / "pyUltroid" / "security" / (name + ".py")
    spec = importlib.util.spec_from_file_location(full_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


addons = load_package_module("addons")


class TrustedAddonTests(unittest.TestCase):
    def test_immediate_untrusted_code_commands_are_owner_only_and_opt_in(self):
        core = (ROOT / "plugins/core.py").read_text("utf-8")
        helper = (ROOT / "pyUltroid/fns/helper.py").read_text("utf-8")
        self.assertIn('@ultroid_cmd(pattern="install", owner_only=True)', core)
        self.assertIn('pattern=r"load( (.*)|$)"', core)
        self.assertIn("owner_only=True", core)
        self.assertIn("ALLOW_UNTRUSTED_PLUGINS", core)
        self.assertIn("event_is_owner", helper)
        self.assertIn("ALLOW_UNTRUSTED_PLUGINS", helper)

    def entry(self, content=b"VALUE = 1\n"):
        revision = "a" * 40
        return {
            "name": "safe-addon.py",
            "source_url": (
                "https://raw.githubusercontent.com/example/project/"
                + revision
                + "/safe-addon.py"
            ),
            "revision": revision,
            "sha256": hashlib.sha256(content).hexdigest(),
            "description": "Test add-on",
            "capabilities": ["messages:read"],
        }

    def write_registry(self, root, entry):
        path = root / "registry.json"
        path.write_text(
            json.dumps({"schema_version": 1, "plugins": [entry]}), "utf-8"
        )
        return path

    def test_registry_requires_immutable_https_and_exact_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            valid = self.entry()
            entries = addons.load_registry(self.write_registry(root, valid))
            self.assertIn("safe-addon.py", entries)
            for update in (
                {"source_url": "http://raw.githubusercontent.com/x/y/" + "a" * 40 + "/x.py"},
                {"revision": "main"},
                {"sha256": "bad"},
                {"name": "../escape.py"},
            ):
                bad = dict(valid)
                bad.update(update)
                with self.subTest(update=update):
                    with self.assertRaises(Exception):
                        addons.load_registry(self.write_registry(root, bad))

    def test_hash_or_syntax_failure_leaves_prior_plugin_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            destination = root / "safe-addon.py"
            destination.write_bytes(b"OLD = True\n")
            entry = addons.TrustedAddon(**self.entry())
            with self.assertRaises(addons.AddonInstallError):
                addons.install_trusted(entry, root, downloader=lambda _: b"wrong")
            self.assertEqual(destination.read_bytes(), b"OLD = True\n")
            broken = b"def broken(:\n"
            broken_entry = addons.TrustedAddon(**self.entry(broken))
            with self.assertRaises(addons.AddonInstallError):
                addons.install_trusted(
                    broken_entry, root, downloader=lambda _: broken
                )
            self.assertEqual(destination.read_bytes(), b"OLD = True\n")

    def test_verified_replace_preserves_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = b"OLD = True\n"
            new = b"NEW = True\n"
            (root / "safe-addon.py").write_bytes(old)
            entry = addons.TrustedAddon(**self.entry(new))
            installed = addons.install_trusted(
                entry, root, downloader=lambda _: new
            )
            self.assertEqual(installed.read_bytes(), new)
            backups = list((root / ".rollback").glob("safe-addon-*.py"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), old)

    def test_load_failure_restores_prior_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = b"OLD = True\n"
            new = b"NEW = True\n"
            destination = root / "safe-addon.py"
            destination.write_bytes(old)
            entry = addons.TrustedAddon(**self.entry(new))
            with self.assertRaises(addons.AddonInstallError):
                addons.install_trusted(
                    entry,
                    root,
                    downloader=lambda _: new,
                    loader=lambda _: (_ for _ in ()).throw(RuntimeError("boom")),
                )
            self.assertEqual(destination.read_bytes(), old)

    def test_legacy_installer_still_rejects_unsafe_url_and_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            for url in (
                "http://example.com/addon.py",
                "https://user:pass@example.com/addon.py",
                "https://example.com/-option.py",
                "https://example.com/addon.txt",
            ):
                with self.subTest(url=url):
                    with self.assertRaises(Exception):
                        addons.install_legacy_untrusted(
                            url, Path(tmp), downloader=lambda _: b"X = 1\n"
                        )
