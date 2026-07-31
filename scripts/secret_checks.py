#!/usr/bin/env python3
"""Small offline secret-pattern gate for repository content."""

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache"}
PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bgh[opusr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\b[0-9]{7,12}:[A-Za-z0-9_-]{30,}\b"),
    re.compile(r"\b(?:redis|postgres(?:ql)?|mongodb(?:\+srv)?)://[^/\s:@]+:[^@\s]+@"),
)


def tracked_files():
    result = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard"],
        cwd=ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if result.returncode == 0:
        candidates = (ROOT / name for name in result.stdout.splitlines())
    else:
        # Release archives and Docker contexts intentionally contain no .git.
        # Scan the complete copied source tree instead of silently skipping the
        # gate or requiring fabricated repository metadata.
        candidates = ROOT.rglob("*")
    for path in candidates:
        if (
            path.is_file()
            and path != Path(__file__)
            and not SKIP_PARTS.intersection(path.relative_to(ROOT).parts)
        ):
            yield path


def main() -> int:
    offenders = []
    for path in tracked_files():
        try:
            text = path.read_text("utf-8")
        except (OSError, UnicodeError):
            continue
        if any(pattern.search(text) for pattern in PATTERNS):
            offenders.append(str(path.relative_to(ROOT)))
    if offenders:
        print("possible secrets: " + ", ".join(sorted(offenders)))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
