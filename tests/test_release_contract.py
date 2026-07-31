import ast
import json
import re
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


class ReleaseContractTests(unittest.TestCase):
    def test_product_and_upstream_versions_are_distinct(self):
        namespace = {}
        exec((ROOT / "pyUltroid/version.py").read_text("utf-8"), namespace)
        self.assertEqual(namespace["BOUDYOS_VERSION"], "2.2.2")
        self.assertEqual(namespace["ultroid_version"], "2.2.2")
        self.assertEqual(namespace["__version__"], "2026.04.03")

    def test_python310_service_uses_immutable_safe_path_launcher(self):
        launcher = ROOT / "ops/boudyos-python-launcher"
        self.assertTrue(launcher.is_file())
        source = launcher.read_text("utf-8")
        self.assertIn('runpy.run_module("pyUltroid"', source)
        self.assertIn("working = Path.cwd().resolve", source)
        for name in (
            "ops/systemd/boudyos.service.example",
            "ops/systemd/ultroid-boudyos.conf.example",
        ):
            unit = (ROOT / name).read_text("utf-8")
            self.assertNotIn(" -P ", unit)
            self.assertIn("-s /var/lib/boudyos/current/source/ops/boudyos-python-launcher", unit)
            self.assertIn("PYTHONDONTWRITEBYTECODE=1", unit)

    def test_runtime_has_no_generic_eval_or_shell_true(self):
        offenders = []
        for directory in ("pyUltroid", "plugins", "assistant"):
            for path in (ROOT / directory).rglob("*.py"):
                source = path.read_text("utf-8")
                tree = ast.parse(source, filename=str(path))
                for node in ast.walk(tree):
                    if (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id == "eval"
                    ):
                        offenders.append(str(path.relative_to(ROOT)))
                    if isinstance(node, ast.Call):
                        for keyword in node.keywords:
                            if (
                                keyword.arg == "shell"
                                and isinstance(keyword.value, ast.Constant)
                                and keyword.value.value is True
                            ):
                                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_telegram_updaters_do_not_mutate_or_install(self):
        source = "\n".join(
            (ROOT / path).read_text("utf-8")
            for path in ("plugins/bot.py", "assistant/callbackstuffs.py")
        )
        for forbidden in (
            "pip3",
            "git pull",
            "reset(\"--hard",
            "TeamUltroid/Ultroid/tree",
            "HEROKU_API@",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn("check_for_update", source)
        self.assertIn("request_deployment", source)

    def test_docker_uses_profile_dependencies_and_boudyos_origin(self):
        dockerfile = (ROOT / "Dockerfile").read_text("utf-8")
        self.assertIn("python:3.13-slim", dockerfile)
        self.assertIn("requirements/media.txt", dockerfile)
        self.assertNotIn("optional-requirements.txt", dockerfile)
        self.assertIn("org.opencontainers.image.revision", dockerfile)
        self.assertIn("/opt/boudyos-release.json", dockerfile)
        self.assertNotIn("git reset", dockerfile)

    def test_telethon_patch_is_full_commit_and_import_is_fail_fast(self):
        commit = "369fa3266c8a9c9aefb4a6c5608e8d44c09c7087"
        requirements = (ROOT / "requirements.txt").read_text("utf-8")
        self.assertIn(
            "git+https://github.com/New-dev0/Telethon-Patch.git@" + commit,
            requirements,
        )
        for name in ("py310.txt", "py313.txt"):
            self.assertIn(
                "Telethon-Patch.git@" + commit,
                (ROOT / "constraints" / name).read_text("utf-8"),
            )
        package = (ROOT / "pyUltroid/__init__.py").read_text("utf-8")
        self.assertNotIn("standard Telethon behavior", package)
        self.assertIn("requires the pinned Telethon-Patch", package)

    def test_every_core_media_direct_requirement_has_both_python_pins(self):
        direct = set()
        for path in (ROOT / "requirements.txt", ROOT / "requirements/media.txt"):
            for line in path.read_text("utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith(("#", "-r")):
                    continue
                direct.add(re.split(r"\s*@\s*|[<>=!~]", line, maxsplit=1)[0].lower())
        for constraint_name in ("py310.txt", "py313.txt"):
            constrained = set()
            for line in (ROOT / "constraints" / constraint_name).read_text(
                "utf-8"
            ).splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                constrained.add(
                    re.split(r"\s*@\s*|[<>=!~]", line, maxsplit=1)[0].lower()
                )
            self.assertEqual(direct - constrained, set(), constraint_name)

    def test_maintained_pdf_dependency_and_modern_api(self):
        media = (ROOT / "requirements/media.txt").read_text("utf-8")
        pdf_tools = (ROOT / "plugins/pdftools.py").read_text("utf-8")
        self.assertIn("pypdf>=", media)
        self.assertNotIn("PyPDF2", media + pdf_tools)
        for obsolete in (
            "PdfFileReader",
            "PdfFileWriter",
            "PdfFileMerger",
            "numPages",
            "getPage(",
            "extractText(",
        ):
            self.assertNotIn(obsolete, pdf_tools)
        self.assertIn("send_file(event.chat_id, ok,", pdf_tools)
        self.assertNotIn("os.remove(ok_)", pdf_tools)

    def test_ci_audits_installed_environment_and_checks_clean_imports(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text("utf-8")
        self.assertIn("python -m pip_audit --local", workflow)
        self.assertNotRegex(workflow, r"pip_audit[^\n]*\s-c\s")
        self.assertIn("bs4, htmlwebshot, telethonpatch", workflow)
        self.assertIn("hiredis, psycopg2, pymongo, redis", workflow)
        self.assertIn("find ops -type f -perm -0100", workflow)
        self.assertIn('bash -n "${shell_scripts[@]}"', workflow)
        self.assertIn('shellcheck "${shell_scripts[@]}"', workflow)
        self.assertNotIn("find . -type f -perm", workflow)
        self.assertIn("scripts/secret_checks.py", workflow)

    def test_default_profile_installs_every_documented_database_driver(self):
        database = (ROOT / "requirements/database.txt").read_text("utf-8")
        media = (ROOT / "requirements/media.txt").read_text("utf-8")
        startup = (ROOT / "pyUltroid/startup/_database.py").read_text("utf-8")
        self.assertIn("-r database.txt", media)
        for requirement, imported in (
            ("redis", "from redis import Redis"),
            ("hiredis", None),
            ("pymongo", "from pymongo import MongoClient"),
            ("dnspython", None),
            ("psycopg2-binary", "import psycopg2"),
        ):
            self.assertRegex(database, rf"(?m)^{re.escape(requirement)}[<>=]")
            if imported:
                self.assertIn(imported, startup)
        self.assertNotIn("pymongo[srv]", database)
        for optional in (
            "google-api-python-client",
            "heroku3",
            "instagrapi",
            "twikit",
        ):
            self.assertNotIn(optional, database + media)
        for constraint in ("py310.txt", "py313.txt"):
            pins = (ROOT / "constraints" / constraint).read_text("utf-8")
            for package in (
                "redis",
                "hiredis",
                "pymongo",
                "dnspython",
                "psycopg2-binary",
            ):
                self.assertRegex(pins, rf"(?m)^{re.escape(package)}==")

    def test_gitless_callbacks_and_alive_never_initialize_a_repository(self):
        callbacks = "\n".join(
            (ROOT / path).read_text("utf-8")
            for path in ("assistant/callbackstuffs.py", "plugins/_inline.py")
        )
        alive = (ROOT / "plugins/bot.py").read_text("utf-8")
        self.assertNotIn("Repo.init", callbacks)
        self.assertNotIn("Repo()", callbacks + alive)
        self.assertIn("format_changelog_report", callbacks)
        self.assertIn("release_identity", alive)

    def test_root_truth_is_read_only_to_service_and_app_status_is_separate(self):
        deploy = (ROOT / "ops/boudyos-deploy").read_text("utf-8")
        backup = (ROOT / "ops/boudyos-backup").read_text("utf-8")
        unit = (ROOT / "ops/systemd/boudyos.service.example").read_text("utf-8")
        docs = (ROOT / "docs/operations.md").read_text("utf-8")
        self.assertIn('STATUS_OWNER="root"', deploy)
        self.assertIn('install -d -o "$STATUS_OWNER" -g "$STATUS_GROUP" -m 0750', deploy)
        self.assertIn('chown "root:$STATUS_GROUP"', backup)
        self.assertNotIn('chown "$RUNTIME_USER:$RUNTIME_GROUP" "$STATUS_DIR"', deploy)
        self.assertIn(
            "ReadOnlyPaths=/opt/boudyos/releases /var/lib/boudyos/current "
            "/var/lib/boudyos/workspaces /var/lib/boudyos/status",
            unit,
        )
        self.assertIn(
            "ReadWritePaths=/run/boudyos "
            "-/var/lib/boudyos/current/work /var/lib/boudyos/app-status",
            unit,
        )
        self.assertIn("BOUDYOS_APP_STATUS_DIR=/var/lib/boudyos/app-status", unit)
        self.assertIn("StateDirectory=boudyos/app-status", unit)
        self.assertIn("root-owned", docs)
        self.assertIn("app-status", docs)

    def test_shared_status_files_do_not_record_origins_or_paths(self):
        deploy = (ROOT / "ops/boudyos-deploy").read_text("utf-8")
        migration = (ROOT / "ops/boudyos-migrate-ultroid").read_text("utf-8")
        release_writes = [
            line for line in (deploy + "\n" + migration).splitlines()
            if 'schema_version":1' in line and 'checked_at' in line
        ]
        self.assertGreaterEqual(len(release_writes), 2)
        self.assertTrue(all('"origin"' not in line for line in release_writes))

    def test_thumbnail_persists_before_upload_and_database_update(self):
        source = (ROOT / "plugins/converter.py").read_text("utf-8")
        persist = source.index("atomic_copy_file(dl, destination)")
        upload = source.index("nn = uf(str(destination))")
        database = source.index('udB.set_key("CUSTOM_THUMBNAIL", nn)')
        self.assertLess(persist, upload)
        self.assertLess(upload, database)
        self.assertNotIn("download_https", source)

    def test_unzip_uses_private_finally_cleaned_workspace(self):
        source = (ROOT / "plugins/ziptools.py").read_text("utf-8")
        self.assertIn('private_workspace(Path.cwd(), ".boudyos-unzip-")', source)
        self.assertNotIn('shutil.rmtree("unzip"', source)

    def test_native_eval_is_owner_opt_in_and_uses_private_workspace(self):
        source = (ROOT / "plugins/devtools.py").read_text("utf-8")
        native = source[source.index('@ultroid_cmd(pattern="cpp"'):]
        self.assertIn("ALLOW_DANGEROUS_DEV_EXEC", native)
        self.assertIn("sender_id != owner_id", native)
        self.assertIn('private_workspace(Path.cwd(), ".boudyos-cpp-")', native)

    def test_workflows_are_read_only_and_actions_are_sha_pinned(self):
        workflows = list((ROOT / ".github/workflows").glob("*.y*ml"))
        self.assertGreaterEqual(len(workflows), 2)
        for path in workflows:
            text = path.read_text("utf-8")
            with self.subTest(path=path.name):
                self.assertNotIn("git-auto-commit", text)
                self.assertNotIn("gist.githubusercontent.com", text)
                self.assertNotRegex(text, r"(?m)^\s+[a-z-]+:\s*write\s*$")
                for reference in re.findall(r"uses:\s*[^@\s]+@([^\s]+)", text):
                    self.assertRegex(reference, r"^[0-9a-f]{40}$")
                self.assertEqual(yaml.safe_load(text)["permissions"]["contents"], "read")

    def test_trusted_registry_schema_is_bundled(self):
        registry = json.loads(
            (ROOT / "resources/security/trusted-addons.json").read_text("utf-8")
        )
        self.assertEqual(registry["schema_version"], 1)
        self.assertIsInstance(registry["plugins"], list)
