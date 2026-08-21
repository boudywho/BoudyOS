import ast
import fnmatch
import importlib.util
import json
import re
import string
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_parse_bool():
    path = ROOT / "pyUltroid" / "security" / "parsing.py"
    spec = importlib.util.spec_from_file_location("security_parsing", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.parse_bool


parse_bool = load_parse_bool()
LOCALES = ROOT / "strings" / "strings"
MENU_KEYS = tuple(f"inline_{index}" for index in range(1, 10))
FAUX_SMALL_CAPS = set("ᴀʙᴄᴅᴇꜰғɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡʏᴢᴴ")
# These glyphs are product copy everywhere else, but intentional data in the
# font command's explicit ASCII-to-small-caps transformation table.
FAUX_SMALL_CAPS_ALLOWLIST = {ROOT / "plugins" / "fontgen.py"}


def placeholders(value):
    fields = []
    for _, field_name, _, _ in string.Formatter().parse(str(value)):
        if field_name is not None:
            fields.append(field_name)
    return fields


def dockerignore_excludes(relative_path, patterns):
    relative_path = relative_path.strip("/")
    excluded = False
    for raw_pattern in patterns:
        pattern = raw_pattern.strip()
        if not pattern or pattern.startswith("#"):
            continue
        negated = pattern.startswith("!")
        if negated:
            pattern = pattern[1:]
        pattern = pattern.lstrip("/")
        if pattern.endswith("/"):
            directory = pattern.rstrip("/")
            if "/" in directory:
                matched = relative_path.startswith(f"{directory}/")
            else:
                matched = directory in Path(relative_path).parts[:-1]
        elif "/" in pattern:
            matched = fnmatch.fnmatchcase(relative_path, pattern)
        else:
            matched = any(
                fnmatch.fnmatchcase(part, pattern)
                for part in Path(relative_path).parts
            )
        if matched:
            excluded = not negated
    return excluded


def load_branding_function():
    path = ROOT / "pyUltroid" / "startup" / "funcs.py"
    tree = ast.parse(path.read_text("utf-8"), filename=str(path))
    selected = [
        node
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and any(
            target.id.startswith(("BOUDYOS_BRAND_VERSION", "BOTFATHER_"))
            for target in (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
            if isinstance(target, ast.Name)
        )
    ]
    selected.extend(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name
        in {
            "_apply_boudyos_branding",
            "_latest_botfather_response",
            "_require_botfather_success",
        }
    )
    selected.extend(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_botfather_mutation_succeeded"
    )
    namespace = {
        "asyncio": SimpleNamespace(sleep=AsyncMock()),
        "LOGS": Mock(),
        "source_resource": lambda *parts: ROOT / "resources" / Path(*parts),
    }
    exec(compile(ast.Module(selected, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


class FakeDatabase:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.set_calls = []
        self.del_calls = []

    def get_key(self, key):
        return self.values.get(key)

    def set_key(self, key, value):
        self.values[key] = value
        self.set_calls.append((key, value))

    def del_key(self, key):
        self.values.pop(key, None)
        self.del_calls.append(key)


def branding_clients(*, fail_avatar=False, responses=None):
    notification = SimpleNamespace(edit=AsyncMock())
    assistant = SimpleNamespace(
        me=SimpleNamespace(
            username="existing_assistant_bot", photo=object(), bot=True
        ),
        send_message=AsyncMock(return_value=notification),
    )
    user = SimpleNamespace(
        me=SimpleNamespace(
            username="owner", first_name="Owner", bot=False
        ),
        send_message=AsyncMock(),
        send_file=AsyncMock(),
        get_messages=AsyncMock(),
    )
    replies = responses or [
        "Choose a bot to change its photo.",
        "Success! Profile photo updated.",
        "Done! The name was updated successfully.",
        "Done! The about section was updated successfully.",
        "Done! The description was updated successfully.",
    ]
    user.get_messages.side_effect = [
        [SimpleNamespace(text=text)] for text in replies
    ]
    if fail_avatar:
        user.send_file.side_effect = RuntimeError("upload failed")
    return assistant, user, notification


class LocaleQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalogs = {}
        for path in sorted(LOCALES.glob("*.yml")):
            with path.open(encoding="utf-8") as stream:
                cls.catalogs[path.name] = yaml.safe_load(stream)

    def test_all_locale_yaml_is_valid_mapping(self):
        self.assertGreater(len(self.catalogs), 1)
        for name, catalog in self.catalogs.items():
            with self.subTest(locale=name):
                self.assertIsInstance(catalog, dict)
                self.assertIn("name", catalog)
                self.assertIn("natively", catalog)
                self.assertIn("authors", catalog)

    def test_shared_menu_placeholders_match_english(self):
        english = self.catalogs["en.yml"]
        for name, catalog in self.catalogs.items():
            for key in MENU_KEYS:
                if key not in catalog:
                    continue
                with self.subTest(locale=name, key=key):
                    self.assertEqual(
                        placeholders(catalog[key]),
                        placeholders(english[key]),
                    )

    def test_dashboard_contract_in_every_locale(self):
        for name, catalog in self.catalogs.items():
            dashboard = catalog["inline_4"]
            with self.subTest(locale=name):
                self.assertIn("BoudyOS", dashboard)
                self.assertEqual(dashboard.count("{}"), 4)

    def test_all_locales_have_no_stale_legacy_branding_variants(self):
        forbidden_variants = (
            "TeamUltroid",
            "theUltroid",
            "UseUltroid",
            "@TeamUltroid",
            "@UseUltroid",
            "Teamultroid",
            "teamultroid",
            "TEAMULTROID",
            "@teamultroid",
            "@Teamultroid",
            "@TEAMULTROID",
            "Teamultroïde",
            "teamultroïde",
            "@teamultroïd",
            "@Teamullroid",
            "@teamullroid",
            "teamullroid",
            "@ટેમલટ્રોઇડ",
            "UtheUltroid",
            "utheultroid",
            "Theultroid",
            "theultroid",
            "TheUltroid",
            "THEULTROID",
            "@theultroid",
            "@Theultroid",
            "@theUltroid",
            "@TheUltroid",
            "Useultroid",
            "useultroid",
            "useUltroid",
            "@Useultroid",
            "@useultroid",
            "@USEULTROID",
            "@UseulTroid",
            "ulroid",
            "Ulroid",
            "ULROID",
            "@ulroid",
            "@Ulroid",
            "@ULROID",
            "teamulroid",
            "Teamulroid",
            "theulroid",
            "Theulroid",
            "useulroid",
            "Useulroid",
            "@teamulroid",
            "@Teamulroid",
            "@theulroid",
            "@Theulroid",
            "@useulroid",
            "@Useulroid",
            "t.me/theUltroid",
            "t.me/theultroid",
            "t.me/TheUltroid",
            "t.me/TeamUltroid",
            "t.me/teamultroid",
            "t.me/UseUltroid",
            "t.me/useultroid",
            "t.me/ulroid",
            "t.me/Ulroid",
            "ultroïde",
            "ultroïd",
            "ultroides",
            "TheUltroi",
        )
        for name, catalog in self.catalogs.items():
            for key in (
                "inline_1",
                "inline_2",
                "inline_3",
                "inline_6",
                "chats_5",
                "chats_6",
                "gdrive_4",
                "help_button",
            ):
                if key not in catalog:
                    continue
                for variant in forbidden_variants:
                    with self.subTest(locale=name, key=key, variant=variant):
                        self.assertNotIn(variant, catalog[key])


class ProductSurfaceTests(unittest.TestCase):
    def test_docker_installs_then_copies_local_source_to_compatibility_path(self):
        dockerfile = (ROOT / "Dockerfile").read_text("utf-8")
        installer = (ROOT / "installer.sh").read_text("utf-8")
        workdir = re.search(r'^WORKDIR\s+"?([^"\s]+)"?', dockerfile, re.MULTILINE)
        install_dir = re.search(r'^DIR="([^"]+)"', installer, re.MULTILINE)
        self.assertIsNotNone(workdir)
        self.assertIsNotNone(install_dir)
        self.assertEqual(workdir.group(1), install_dir.group(1))
        self.assertEqual(workdir.group(1), "/root/TeamUltroid")
        dependency_install = dockerfile.index("python3 -m pip install")
        source_copy = dockerfile.index("COPY . .")
        self.assertLess(dependency_install, source_copy)
        self.assertLess(workdir.start(), source_copy)
        self.assertLess(source_copy, dockerfile.index('CMD ["bash", "startup"]'))
        self.assertNotIn("bash installer.sh", dockerfile)
        self.assertNotIn("git clone", dockerfile)

    def test_docker_runtime_identity_never_fabricates_remote_main(self):
        dockerfile = (ROOT / "Dockerfile").read_text("utf-8")
        dockerignore = (ROOT / ".dockerignore").read_text("utf-8").splitlines()
        self.assertIn(".git", dockerignore)
        self.assertNotIn("git init", dockerfile)
        self.assertNotIn("git fetch", dockerfile)
        self.assertNotIn("git reset", dockerfile)
        self.assertIn("ARG BOUDYOS_SOURCE_COMMIT=unknown", dockerfile)
        self.assertIn("ARG BOUDYOS_SOURCE_DIRTY=1", dockerfile)
        self.assertIn("/opt/boudyos-release.json", dockerfile)

    def test_docker_context_keeps_required_source_assets_and_tests(self):
        patterns = (ROOT / ".dockerignore").read_text("utf-8").splitlines()
        for required in (
            "README.md",
            ".github/workflows/codeql-analysis.yml",
            "pyUltroid/__init__.py",
            "resources/extras/boudyos_avatar.jpg",
            "tests/test_product_quality.py",
        ):
            with self.subTest(required=required):
                self.assertFalse(dockerignore_excludes(required, patterns))
        for excluded in (
            ".git/config",
            ".env",
            "downloads/video.mp4",
            "venv/bin/python",
            "pyUltroid/__pycache__/module.pyc",
        ):
            with self.subTest(excluded=excluded):
                self.assertTrue(dockerignore_excludes(excluded, patterns))

    def test_app_manifest_requires_runtime_api_credentials(self):
        manifest = json.loads((ROOT / "app.json").read_text("utf-8"))
        for key in ("API_ID", "API_HASH"):
            with self.subTest(key=key):
                self.assertTrue(manifest["env"][key]["required"])
                self.assertIn("Your Telegram API", manifest["env"][key]["description"])

    def test_no_faux_small_caps_in_python_or_locale_sources(self):
        offenders = []
        paths = list(ROOT.rglob("*.py"))
        paths.extend(ROOT.rglob("*.yml"))
        paths.extend(ROOT.rglob("*.yaml"))
        for path in paths:
            if any(
                part in {".git", "venv", ".venv", "tests"} for part in path.parts
            ):
                continue
            if path in FAUX_SMALL_CAPS_ALLOWLIST:
                continue
            found = sorted(FAUX_SMALL_CAPS.intersection(path.read_text("utf-8")))
            if found:
                offenders.append(f"{path.relative_to(ROOT)}: {''.join(found)}")
        self.assertEqual(offenders, [])

    def test_small_caps_mapping_matches_ascii_letters_and_transforms_text(self):
        path = ROOT / "plugins" / "fontgen.py"
        tree = ast.parse(path.read_text("utf-8"), filename=str(path))
        selected = [
            node
            for node in tree.body
            if (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name)
                    and target.id in {"_default", "Fonts"}
                    for target in node.targets
                )
            )
            or (
                isinstance(node, ast.FunctionDef)
                and node.name == "gen_font"
            )
        ]
        namespace = {"string": string}
        exec(
            compile(ast.Module(selected, type_ignores=[]), str(path), "exec"),
            namespace,
        )
        mapping = namespace["Fonts"]["small caps"]
        self.assertEqual(len(mapping), len(string.ascii_letters))
        transformed = namespace["gen_font"]("abc BoudyOS", mapping)
        self.assertNotEqual(transformed, "abc BoudyOS")
        self.assertTrue(transformed.startswith("ᴀʙᴄ "))

    def test_dashboard_buttons_are_readable_and_stable(self):
        source = (ROOT / "plugins" / "_help.py").read_text("utf-8")
        for label in (
            "Plugins",
            "Add-ons",
            "Voice Chat",
            "Inline tools",
            "Settings",
            "System status",
            "Support",
            "Close",
        ):
            with self.subTest(label=label):
                self.assertIn(f'"{label}"', source)
        for callback_data in (
            "uh_Official_",
            "uh_Addons_",
            "uh_VCBot_",
            "ownr",
            "close",
        ):
            with self.subTest(callback_data=callback_data):
                self.assertIn(callback_data, source)

    def test_inline_media_defaults_to_bundled_avatar(self):
        path = ROOT / "plugins" / "__init__.py"
        tree = ast.parse(path.read_text("utf-8"), filename=str(path))
        inline_pic = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "inline_pic"
        )
        namespace = {
            "source_resource": lambda *parts: ROOT / "resources" / Path(*parts),
            "udB": FakeDatabase(),
        }
        exec(
            compile(ast.Module([inline_pic], type_ignores=[]), str(path), "exec"),
            namespace,
        )
        bundled_avatar = str(ROOT / "resources/extras/boudyos_avatar.jpg")
        self.assertEqual(namespace["inline_pic"](), bundled_avatar)

        namespace["udB"] = FakeDatabase(
            {"INLINE_PIC": "https://example.com/pic.jpg"}
        )
        self.assertEqual(
            namespace["inline_pic"](), "https://example.com/pic.jpg"
        )
        namespace["udB"] = FakeDatabase({"INLINE_PIC": False})
        self.assertIsNone(namespace["inline_pic"]())

        bot_source = (ROOT / "plugins" / "bot.py").read_text("utf-8")
        self.assertIn(
            'inline_pic() or str(source_resource("extras", "boudyos_avatar.jpg"))',
            bot_source,
        )

    def test_scoped_help_surfaces_have_no_stale_teamultroid_branding(self):
        for relative in (
            "plugins/_help.py",
            "plugins/_inline.py",
            "plugins/bot.py",
            "assistant/manager/_help.py",
            "pyUltroid/fns/helper.py",
            "assistant/inlinestuff.py",
            "pyUltroid/fns/tools.py",
            "assistant/callbackstuffs.py",
            "pyUltroid/__init__.py",
        ):
            with self.subTest(path=relative):
                source = (ROOT / relative).read_text("utf-8")
                user_facing_source = "\n".join(source.splitlines()[7:])
                self.assertNotIn("@TeamUltroid", user_facing_source)
                self.assertNotIn("t.me/TeamUltroid", user_facing_source)

        helper_source = (ROOT / "pyUltroid/fns/helper.py").read_text("utf-8")
        self.assertIn(
            'output += "\\nBoudyOS • https://github.com/boudywho/BoudyOS"',
            helper_source,
        )

        english = yaml.safe_load((LOCALES / "en.yml").read_text("utf-8"))
        for key in ("inline_6", "chats_5", "gdrive_4", "help_button"):
            with self.subTest(key=key):
                self.assertNotIn("TeamUltroid", english[key])
                self.assertNotIn("theUltroid", english[key])
                self.assertNotIn("UseUltroid", english[key])
        self.assertEqual(placeholders(english["help_button"]), ["i", "i"])
        self.assertIn("BoudyOS", english["chats_5"])
        self.assertIn("BoudyOS support", english["gdrive_4"])

        inlinestuff_source = (ROOT / "assistant/inlinestuff.py").read_text(
            "utf-8"
        )
        self.assertIn('"Search On Google": "go BoudyOS"', inlinestuff_source)
        self.assertIn(
            '"Piston Eval": "run javascript console.log(\'Hello BoudyOS\')"',
            inlinestuff_source,
        )
        self.assertIn('"Twitter User": "twitter telegram"', inlinestuff_source)
        self.assertNotIn("theultroid", inlinestuff_source)

        tools_source = (ROOT / "pyUltroid/fns/tools.py").read_text("utf-8")
        self.assertIn(
            'kwargs["title"] = kwargs.get("title", "BoudyOS")', tools_source
        )
        self.assertIn(
            'else "https://github.com/boudywho/BoudyOS"', tools_source
        )

        cb_source = (ROOT / "assistant/callbackstuffs.py").read_text("utf-8")
        self.assertNotIn("@ultroidplugins", cb_source)
        self.assertIn(
            "Only install plugins from trusted BoudyOS repositories", cb_source
        )

        init_source = (ROOT / "pyUltroid/__init__.py").read_text("utf-8")
        self.assertIn('print("pyUltroid - BoudyOS")', init_source)

    def test_manager_help_has_dashboard_navigation(self):
        source = (ROOT / "assistant" / "manager" / "_help.py").read_text(
            "utf-8"
        )
        self.assertIn('Button.inline("Dashboard", "open")', source)
        self.assertIn('Button.url("Add me to Group", url)', source)
        for callback_key in ("Admintools", "locks", "Utils", "Misc"):
            with self.subTest(callback_key=callback_key):
                self.assertIn(f'"{callback_key}"', source)

    def test_dual_mode_buttons_use_distinct_explicit_callbacks(self):
        source = (ROOT / "assistant" / "callbackstuffs.py").read_text("utf-8")
        self.assertIn('Button.inline("Dual Mode On", "dmon")', source)
        self.assertIn('Button.inline("Dual Mode Off", "dmoff")', source)
        self.assertIn('@callback("dmon", owner=True)', source)
        self.assertIn('@callback("dmoff", owner=True)', source)
        self.assertIn('@callback("dmof", owner=True)', source)

    def test_bundled_brand_assets_and_startup_fallback(self):
        for relative in (
            "resources/extras/boudyos_logo.png",
            "resources/extras/boudyos_avatar.jpg",
        ):
            path = ROOT / relative
            with self.subTest(path=relative):
                self.assertTrue(path.is_file())
                self.assertGreater(path.stat().st_size, 0)

        startup = (ROOT / "pyUltroid" / "startup" / "funcs.py").read_text("utf-8")
        self.assertGreaterEqual(startup.count("boudyos_avatar.jpg"), 3)
        self.assertNotIn("graph.org/file", startup)


class AssistantBrandingTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_photo_does_not_prevent_one_time_branding(self):
        branding = load_branding_function()
        database = FakeDatabase({branding["BOUDYOS_BRAND_VERSION_KEY"]: 0})
        assistant, user, notification = branding_clients()

        await branding["_apply_boudyos_branding"](assistant, database, user)

        commands = [call.args[1] for call in user.send_message.await_args_list]
        self.assertIn("/setuserpic", commands)
        self.assertIn("/setname", commands)
        self.assertIn("BoudyOS Assistant", commands)
        self.assertIn("/setabouttext", commands)
        self.assertIn("/setdescription", commands)
        self.assertNotIn("/newbot", commands)
        self.assertNotIn("/setusername", commands)
        user.send_file.assert_awaited_once_with(
            "botfather", str(ROOT / "resources/extras/boudyos_avatar.jpg")
        )
        notification.edit.assert_awaited_once()
        self.assertEqual(
            database.set_calls,
            [
                (
                    branding["BOUDYOS_BRAND_VERSION_KEY"],
                    branding["BOUDYOS_BRAND_VERSION"],
                )
            ],
        )
        self.assertEqual(user.get_messages.await_count, 5)

    async def test_brand_version_skips_completed_migration(self):
        branding = load_branding_function()
        version_key = branding["BOUDYOS_BRAND_VERSION_KEY"]
        database = FakeDatabase({version_key: branding["BOUDYOS_BRAND_VERSION"]})
        assistant, user, _ = branding_clients()

        await branding["_apply_boudyos_branding"](assistant, database, user)

        assistant.send_message.assert_not_awaited()
        user.send_message.assert_not_awaited()
        user.send_file.assert_not_awaited()
        self.assertEqual(database.set_calls, [])

    async def test_failed_branding_is_nonfatal_and_remains_retryable(self):
        branding = load_branding_function()
        database = FakeDatabase()
        assistant, user, notification = branding_clients(fail_avatar=True)

        await branding["_apply_boudyos_branding"](assistant, database, user)

        notification.edit.assert_not_awaited()
        self.assertEqual(database.set_calls, [])
        self.assertNotIn(branding["BOUDYOS_BRAND_VERSION_KEY"], database.values)

    async def test_user_mode_skips_branding_without_botfather_activity(self):
        branding = load_branding_function()
        database = FakeDatabase()
        user_client = SimpleNamespace(
            me=SimpleNamespace(
                username="owner", first_name="Owner", bot=False
            ),
            send_message=AsyncMock(),
            send_file=AsyncMock(),
            get_messages=AsyncMock(),
        )

        await branding["_apply_boudyos_branding"](
            user_client, database, user_client
        )

        user_client.send_message.assert_not_awaited()
        user_client.send_file.assert_not_awaited()
        user_client.get_messages.assert_not_awaited()
        branding["LOGS"].warning.assert_not_called()
        self.assertEqual(database.set_calls, [])

    async def test_bot_mode_skips_branding_without_botfather_activity(self):
        branding = load_branding_function()
        database = FakeDatabase()
        _, bot_client, _ = branding_clients()
        bot_client.me.bot = True

        await branding["_apply_boudyos_branding"](
            bot_client, database, bot_client
        )

        bot_client.send_message.assert_not_awaited()
        bot_client.send_file.assert_not_awaited()
        bot_client.get_messages.assert_not_awaited()
        branding["LOGS"].warning.assert_not_called()
        self.assertEqual(database.set_calls, [])

    async def test_botfather_rejection_keeps_branding_retryable(self):
        branding = load_branding_function()
        database = FakeDatabase()
        assistant, user, notification = branding_clients(
            responses=[
                "Choose a bot to change its photo.",
                "Sorry, the image is invalid. Please try again.",
            ]
        )

        await branding["_apply_boudyos_branding"](assistant, database, user)

        notification.edit.assert_not_awaited()
        self.assertEqual(database.set_calls, [])
        self.assertNotIn(branding["BOUDYOS_BRAND_VERSION_KEY"], database.values)
        commands = [call.args[1] for call in user.send_message.await_args_list]
        self.assertNotIn("/setname", commands)


class DualModeBehaviorTests(unittest.IsolatedAsyncioTestCase):
    def _load_handlers(self, initial_values):
        path = ROOT / "assistant" / "callbackstuffs.py"
        tree = ast.parse(path.read_text("utf-8"), filename=str(path))
        functions = [
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name
            in {"_set_dual_mode", "dual_mode_on", "dual_mode_off", "rhwhe"}
        ]
        database = FakeDatabase(initial_values)
        namespace = {
            "udB": database,
            "get_back_button": lambda callback_data: callback_data,
            "parse_bool": parse_bool,
            "callback": lambda *args, **kwargs: lambda fn: fn,
        }
        exec(
            compile(ast.Module(functions, type_ignores=[]), str(path), "exec"),
            namespace,
        )
        return namespace, database

    async def test_explicit_dual_mode_actions_are_idempotent(self):
        namespace, database = self._load_handlers({"DUAL_MODE": "True"})
        event = SimpleNamespace(edit=AsyncMock())

        await namespace["_set_dual_mode"](event, True)
        self.assertEqual(database.set_calls, [])
        self.assertEqual(database.del_calls, [])

        await namespace["_set_dual_mode"](event, False)
        await namespace["_set_dual_mode"](event, False)
        self.assertEqual(database.del_calls, ["DUAL_MODE"])

        await namespace["_set_dual_mode"](event, True)
        await namespace["_set_dual_mode"](event, True)
        self.assertEqual(database.set_calls, [("DUAL_MODE", "True")])

    async def test_dual_mode_initial_state_matrix_on_and_off(self):
        initial_states = [
            {"DUAL_MODE": "False"},
            {"DUAL_MODE": False},
            {"DUAL_MODE": "0"},
            {},
        ]
        for initial in initial_states:
            with self.subTest(initial=initial, action="on"):
                namespace, database = self._load_handlers(initial)
                event = SimpleNamespace(edit=AsyncMock())
                await namespace["dual_mode_on"](event)
                self.assertEqual(database.set_calls, [("DUAL_MODE", "True")])
                self.assertEqual(database.get_key("DUAL_MODE"), "True")
                event.edit.assert_awaited_once_with(
                    "Dual Mode : On", buttons="cbs_otvars"
                )
                await namespace["dual_mode_on"](event)
                self.assertEqual(database.set_calls, [("DUAL_MODE", "True")])

            with self.subTest(initial=initial, action="off"):
                namespace, database = self._load_handlers(initial)
                event = SimpleNamespace(edit=AsyncMock())
                await namespace["dual_mode_off"](event)
                if "DUAL_MODE" in initial:
                    self.assertEqual(database.del_calls, ["DUAL_MODE"])
                    self.assertIsNone(database.get_key("DUAL_MODE"))
                else:
                    self.assertEqual(database.del_calls, [])
                event.edit.assert_awaited_once_with(
                    "Dual Mode : Off", buttons="cbs_otvars"
                )
                await namespace["dual_mode_off"](event)
                if "DUAL_MODE" in initial:
                    self.assertEqual(database.del_calls, ["DUAL_MODE"])
                else:
                    self.assertEqual(database.del_calls, [])

    async def test_legacy_dmof_toggle_uses_parse_bool(self):
        for initial in (
            {"DUAL_MODE": "False"},
            {"DUAL_MODE": False},
            {"DUAL_MODE": "0"},
            {},
        ):
            with self.subTest(initial=initial):
                namespace, database = self._load_handlers(initial)
                event = SimpleNamespace(edit=AsyncMock())
                await namespace["rhwhe"](event)
                self.assertEqual(database.set_calls, [("DUAL_MODE", "True")])
                self.assertEqual(database.get_key("DUAL_MODE"), "True")
                event.edit.assert_awaited_once_with(
                    "Dual Mode : On", buttons="cbs_otvars"
                )

        namespace, database = self._load_handlers({"DUAL_MODE": "True"})
        event = SimpleNamespace(edit=AsyncMock())
        await namespace["rhwhe"](event)
        self.assertEqual(database.del_calls, ["DUAL_MODE"])
        self.assertIsNone(database.get_key("DUAL_MODE"))
        event.edit.assert_awaited_once_with(
            "Dual Mode : Off", buttons="cbs_otvars"
        )


class InlineAliveBehaviorTests(unittest.IsolatedAsyncioTestCase):
    async def test_inline_alive_uses_builder_photo_or_article_without_github_fallback(
        self,
    ):
        path = ROOT / "plugins" / "_inline.py"
        source = path.read_text("utf-8")
        self.assertNotIn("raw.githubusercontent.com", source)

        tree = ast.parse(source, filename=str(path))
        inline_alive_node = next(
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "inline_alive"
        )

        builder = SimpleNamespace(
            photo=AsyncMock(return_value="photo_result"),
            article=AsyncMock(return_value="article_result"),
        )
        event = SimpleNamespace(
            builder=builder,
            answer=AsyncMock(),
        )

        # 1. Configured local bundled path
        bundled_path = str(ROOT / "resources/extras/boudyos_avatar.jpg")
        namespace = {
            "inline_pic": lambda: bundled_path,
            "SUP_BUTTONS": [[]],
            "in_pattern": lambda *args, **kwargs: lambda fn: fn,
        }
        exec(
            compile(
                ast.Module([inline_alive_node], type_ignores=[]),
                str(path),
                "exec",
            ),
            namespace,
        )
        await namespace["inline_alive"](event)
        builder.photo.assert_awaited_once_with(
            file=bundled_path,
            text="**BoudyOS**",
            buttons=[[]],
            link_preview=False,
        )
        event.answer.assert_awaited_once_with(
            ["photo_result"],
            private=True,
            cache_time=300,
            switch_pm="BoudyOS",
            switch_pm_param="start",
        )

        # 2. Configured remote override
        builder.photo.reset_mock()
        event.answer.reset_mock()
        namespace["inline_pic"] = lambda: "https://example.com/override.jpg"
        await namespace["inline_alive"](event)
        builder.photo.assert_awaited_once_with(
            file="https://example.com/override.jpg",
            text="**BoudyOS**",
            buttons=[[]],
            link_preview=False,
        )
        event.answer.assert_awaited_once_with(
            ["photo_result"],
            private=True,
            cache_time=300,
            switch_pm="BoudyOS",
            switch_pm_param="start",
        )

        # 3. Explicitly disabled media
        builder.article.reset_mock()
        event.answer.reset_mock()
        namespace["inline_pic"] = lambda: None
        await namespace["inline_alive"](event)
        builder.article.assert_awaited_once_with(
            title="BoudyOS",
            description="Personal Telegram workspace",
            text="**BoudyOS**",
            buttons=[[]],
            link_preview=False,
        )
        event.answer.assert_awaited_once_with(
            ["article_result"],
            private=True,
            cache_time=300,
            switch_pm="BoudyOS",
            switch_pm_param="start",
        )


if __name__ == "__main__":
    unittest.main()
