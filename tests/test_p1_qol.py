"""Preview controls regression tests: no Telegram, network, or import poisoning."""

import asyncio
import importlib.util
import logging
import os
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class DB:
    name = "LocalDB"

    def __init__(self, values=None):
        self.values = dict(values or {})

    def get_key(self, key):
        return self.values.get(key)

    def set_key(self, key, value):
        self.values[key] = value

    def del_key(self, key):
        self.values.pop(key, None)

    def ping(self):
        raise RuntimeError("password=DO_NOT_DISCLOSE")


class Event:
    def __init__(self, argument=""):
        self.pattern_match = mock.Mock()
        self.pattern_match.group.return_value = argument
        self.messages = []

    async def eor(self, text, **kwargs):
        self.messages.append(text)
        return self

    async def edit(self, text):
        self.messages.append(text)


@contextmanager
def isolated_modules(db=None, official_dir=None):
    """Restore all imports, including package attributes, when the test ends."""
    with mock.patch.dict(sys.modules):
        for name in tuple(sys.modules):
            if name == "pyUltroid" or name.startswith("pyUltroid.") or name == "plugins" or name.startswith("plugins."):
                del sys.modules[name]
        for name, relative in (("pyUltroid", "pyUltroid"), ("pyUltroid.security", "pyUltroid/security"), ("pyUltroid.startup", "pyUltroid/startup"), ("plugins", "plugins")):
            package = types.ModuleType(name)
            package.__path__ = [str(ROOT / relative)]
            sys.modules[name] = package
        decouple = types.ModuleType("decouple")
        decouple.config = lambda key, default=None: os.environ.get(key, default)
        sys.modules["decouple"] = decouple
        pkg = sys.modules["plugins"]
        pkg.udB = db or DB()
        pkg.LOGS = logging.getLogger("preview-test")
        pkg.HOSTED_ON = "Local"
        pkg.get_help = lambda name: name
        pkg.get_string = lambda name: name
        pkg.eor = lambda *args: None
        pkg.Redis = lambda key: False
        pkg.commands = {}

        def command(**kwargs):
            def decorate(func):
                pkg.commands[kwargs["pattern"]] = (func, kwargs)
                return func
            return decorate

        pkg.ultroid_cmd = command
        paths = load_module("pyUltroid.paths", "pyUltroid/paths.py")
        if official_dir is not None:
            paths.OFFICIAL_PLUGINS = official_dir
        load_module("pyUltroid.security.parsing", "pyUltroid/security/parsing.py")
        load_module("pyUltroid.security.profiles", "pyUltroid/security/profiles.py")
        load_module("pyUltroid.startup.settings_schema", "pyUltroid/startup/settings_schema.py")
        loader = types.ModuleType("pyUltroid.loader")
        loader.LOAD_REPORT = {"loaded": [], "failed": [], "skipped_missing_dep": []}
        sys.modules[loader.__name__] = loader
        version = types.ModuleType("pyUltroid.version")
        version.__version__ = "test"
        version.ultroid_version = "test"
        sys.modules[version.__name__] = version
        yield pkg, loader


class SettingsSchemaTests(unittest.TestCase):
    def test_loader_filters_remain_split_compatible(self):
        with isolated_modules():
            schema = sys.modules["pyUltroid.startup.settings_schema"]
            for key in ("EXCLUDE_OFFICIAL", "INCLUDE_ONLY", "EXCLUDE_ADDONS", "INCLUDE_ADDONS"):
                for raw in ("a b", "['a', 'b']"):
                    value, warning = schema.coerce_value(key, raw)
                    self.assertEqual(value.split(), ["a", "b"])
                    self.assertIsNone(warning)
            self.assertEqual(schema.coerce_value("SUDOS", "[1, 2]")[0], [1, 2])
            self.assertEqual(schema.coerce_value("PLUGIN_CHANNEL", "a b")[0], ["a", "b"])

    def test_security_bool_and_profiles(self):
        with isolated_modules():
            schema = sys.modules["pyUltroid.startup.settings_schema"]
            for key in ("ALLOW_UNTRUSTED_PLUGINS", "ALLOW_DANGEROUS_DEV_EXEC"):
                self.assertIs(schema.coerce_value(key, "false")[0], False)
                self.assertIs(schema.coerce_value(key, "enabled")[0], True)
            self.assertIn("PLUGIN_PROFILES", schema.KNOWN_KEYS)
            self.assertIn("PLUGIN_PROFILE_POLICY", schema.KNOWN_KEYS)
            with self.assertRaises(ValueError):
                schema.coerce_value("ADDONS_MODE", "any")
            with self.assertRaises(ValueError):
                schema.coerce_value("PLUGIN_PROFILES", "not-a-profile")


class PluginControlsTests(unittest.TestCase):
    def test_exact_inventory_owner_and_no_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            official = Path(directory)
            (official / "core.py").touch()
            (official / "_private.py").touch()
            (official / "spoof.py").symlink_to(ROOT / "plugins/core.py")
            with isolated_modules(official_dir=official) as (pkg, _):
                mod = load_module("plugins.pluginsctl", "plugins/pluginsctl.py")
                self.assertEqual(mod._official_names(), ["core"])
                self.assertTrue(all(meta["owner_only"] for _, meta in pkg.commands.values()))
                self.assertFalse(any(pattern.startswith("reload") for pattern in pkg.commands))
                for name in ("../core", "/tmp/core", "_private", "spoof", "unknown"):
                    for handler in (mod.enable_plugin, mod.disable_plugin):
                        asyncio.run(handler(Event(" " + name)))
                        self.assertEqual(pkg.udB.values, {})

    def test_filters_and_profile_feedback(self):
        db = DB({"INCLUDE_ONLY": "core", "EXCLUDE_OFFICIAL": "core database"})
        with isolated_modules(db) as (pkg, _):
            mod = load_module("plugins.pluginsctl", "plugins/pluginsctl.py")
            asyncio.run(mod.enable_plugin(Event(" database")))
            self.assertEqual(set(db.values["INCLUDE_ONLY"].split()), {"core", "database"})
            self.assertEqual(db.values["EXCLUDE_OFFICIAL"], "core")
            asyncio.run(mod.disable_plugin(Event(" core")))
            self.assertIn("core", db.values["INCLUDE_ONLY"].split())
            self.assertIn("core", db.values["EXCLUDE_OFFICIAL"].split())
            db.values = {"PLUGIN_PROFILES": "core", "PLUGIN_PROFILE_POLICY": "new-safe-v1"}
            event = Event(" devtools")
            asyncio.run(mod.enable_plugin(event))
            self.assertIn("profile", event.messages[-1].lower())
            self.assertNotIn("**Enabled**", event.messages[-1])
            db.values = {}
            with mock.patch.dict(os.environ, {"INCLUDE_ONLY": "core", "EXCLUDE_OFFICIAL": "database", "PLUGIN_PROFILES": "core"}):
                asyncio.run(mod.enable_plugin(Event(" database")))
                self.assertIn("database", db.values["INCLUDE_ONLY"].split())
                self.assertEqual(db.values["EXCLUDE_OFFICIAL"].split(), [])


class DoctorTests(unittest.TestCase):
    def test_report_is_read_only_counts_only_and_nonblocking(self):
        db = DB()
        with isolated_modules(db) as (pkg, loader):
            loader.LOAD_REPORT.update(loaded=[("Official", "core")], failed=[("Addons", "secret", "password=DO_NOT_DISCLOSE")], skipped_missing_dep=[("x", "y", "token=DO_NOT_DISCLOSE")])
            mod = load_module("plugins.doctor", "plugins/doctor.py")
            event = Event()
            original = dict(db.values)
            with mock.patch.object(mod.asyncio, "to_thread", new=mock.AsyncMock(side_effect=RuntimeError("DO_NOT_DISCLOSE"))) as threaded:
                asyncio.run(mod.doctor_cmd(event))
                threaded.assert_awaited_once()
            text = event.messages[-1]
            self.assertIn("BoudyOS", text)
            self.assertIn("loaded `1`", text)
            self.assertIn("failed `1`", text)
            self.assertNotIn("DO_NOT_DISCLOSE", text)
            self.assertEqual(db.values, original)
            self.assertTrue(all(meta["owner_only"] for _, meta in pkg.commands.values()))


class DatabaseTests(unittest.TestCase):
    def test_setdb_never_echoes_credentials_or_invalid_raw_value(self):
        with isolated_modules() as (pkg, _):
            load_module("plugins.database", "plugins/database.py")
            func, meta = next(value for pattern, value in pkg.commands.items() if pattern.startswith("setdb"))
            self.assertTrue(meta["owner_only"])
            for argument in ("BOT_TOKEN DO_NOT_DISCLOSE", "CUSTOM_TOKEN DO_NOT_DISCLOSE", "PLUGIN_PROFILES DO_NOT_DISCLOSE"):
                event = Event(argument)
                asyncio.run(func(event))
                self.assertNotIn("DO_NOT_DISCLOSE", " ".join(event.messages))
            self.assertEqual(pkg.udB.values["BOT_TOKEN"], "DO_NOT_DISCLOSE")


if __name__ == "__main__":
    unittest.main()
