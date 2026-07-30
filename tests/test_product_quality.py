import ast
import fnmatch
import json
import re
import string
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import yaml


ROOT = Path(__file__).resolve().parents[1]
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
    }
    exec(compile(ast.Module(selected, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


class FakeDatabase:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.set_calls = []

    def get_key(self, key):
        return self.values.get(key)

    def set_key(self, key, value):
        self.values[key] = value
        self.set_calls.append((key, value))


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

    def test_docker_runtime_git_tracks_boudyos_without_host_metadata(self):
        dockerfile = (ROOT / "Dockerfile").read_text("utf-8")
        dockerignore = (ROOT / ".dockerignore").read_text("utf-8").splitlines()
        self.assertIn(".git", dockerignore)
        self.assertIn("git init -b main", dockerfile)
        self.assertIn(
            "git remote add origin https://github.com/boudywho/BoudyOS.git",
            dockerfile,
        )
        self.assertIn("git fetch --depth=1 origin main", dockerfile)
        self.assertIn("git reset --mixed origin/main", dockerfile)
        self.assertIn("git branch --set-upstream-to=origin/main main", dockerfile)

    def test_docker_context_keeps_required_source_assets_and_tests(self):
        patterns = (ROOT / ".dockerignore").read_text("utf-8").splitlines()
        for required in (
            "README.md",
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
            "Settings",
            "Updates",
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
            "botfather", "resources/extras/boudyos_avatar.jpg"
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


if __name__ == "__main__":
    unittest.main()
