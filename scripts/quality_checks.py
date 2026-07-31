#!/usr/bin/env python3
"""Offline repository checks used by CI and release preflight."""

import ast
import json
import re
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache"}
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)(?:bot[_-]?token|api[_-]?hash|password)\s*=\s*['\"][^'\"]{12,}"),
)


def files(suffix):
    for path in ROOT.rglob("*" + suffix):
        if not SKIP_PARTS.intersection(path.parts):
            yield path


def main():
    errors = []
    for path in files(".py"):
        try:
            ast.parse(path.read_text("utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError) as exc:
            errors.append(f"{path.relative_to(ROOT)}: {exc}")
    for path in files(".json"):
        try:
            json.loads(path.read_text("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            errors.append(f"{path.relative_to(ROOT)}: {exc}")
    for suffix in (".yml", ".yaml"):
        for path in files(suffix):
            try:
                yaml.safe_load(path.read_text("utf-8"))
            except (yaml.YAMLError, UnicodeDecodeError) as exc:
                errors.append(f"{path.relative_to(ROOT)}: {exc}")
    for path in ROOT.rglob("*"):
        if (
            not path.is_file()
            or SKIP_PARTS.intersection(path.parts)
            or path.suffix in {".png", ".jpg", ".jpeg", ".gif", ".pyc"}
        ):
            continue
        try:
            text = path.read_text("utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                errors.append(
                    f"{path.relative_to(ROOT)}: possible committed secret"
                )
    runtime_python = [
        path
        for directory in ("pyUltroid", "plugins", "assistant")
        for path in (ROOT / directory).rglob("*.py")
    ]
    for path in runtime_python:
        text = path.read_text("utf-8")
        if re.search(r"\beval\s*\(", text):
            errors.append(f"{path.relative_to(ROOT)}: generic eval is forbidden")
        if re.search(r"shell\s*=\s*True", text):
            errors.append(f"{path.relative_to(ROOT)}: shell=True is forbidden")
        tree = ast.parse(text, filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "exec"
                and (
                    path.relative_to(ROOT).as_posix() != "plugins/devtools.py"
                    or "ALLOW_DANGEROUS_DEV_EXEC" not in text
                )
            ):
                errors.append(
                    f"{path.relative_to(ROOT)}: generic runtime exec is forbidden"
                )
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "extractall"
            ):
                errors.append(
                    f"{path.relative_to(ROOT)}: extractall is forbidden"
                )
        if "load_addons(" in text and path.name != "utils.py":
            if not any(
                marker in text
                for marker in (
                    "setting_enabled",
                    "_trusted_local_addons",
                    "ALLOW_UNTRUSTED_PLUGINS",
                )
            ):
                errors.append(
                    f"{path.relative_to(ROOT)}: immediate add-on load lacks trust gate"
                )
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
