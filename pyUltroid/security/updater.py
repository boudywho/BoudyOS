"""Release-aware, non-mutating in-app update policy."""

import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Optional, Sequence, Tuple

from .subprocess import ProcessResult, run_exec


APPROVED_ORIGIN = "https://github.com/boudywho/BoudyOS.git"
APPROVED_BRANCH = "main"
APPROVED_HELPERS = frozenset(
    ("/usr/local/sbin/boudyos-deploy", "/usr/libexec/boudyos-deploy")
)
_TAG = re.compile(r"^v?([0-9]+)\.([0-9]+)\.([0-9]+)$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class UpdateState:
    state: str
    current_revision: str = ""
    available_revision: str = ""
    branch: str = ""
    dirty: bool = False
    detail: str = ""

    @property
    def update_available(self) -> bool:
        return self.state == "available"


Runner = Callable[..., Awaitable[ProcessResult]]


def is_approved_ref(reference: str) -> bool:
    return reference == APPROVED_BRANCH or bool(_TAG.fullmatch(reference))


def sanitize_git_url(url: str) -> str:
    return APPROVED_ORIGIN if url == APPROVED_ORIGIN else "<unapproved origin>"


def _version(reference: str) -> Optional[Tuple[int, int, int]]:
    match = _TAG.fullmatch(reference)
    return tuple(map(int, match.groups())) if match else None


def _target_release(
    target_tag: Optional[str],
    target_commit: Optional[str],
    status_path: Optional[Path] = None,
) -> Tuple[str, str]:
    tag = target_tag or os.environ.get("BOUDYOS_RELEASE_TAG", "")
    commit = target_commit or os.environ.get("BOUDYOS_RELEASE_COMMIT", "")
    if not tag and not commit:
        if status_path is None:
            status_path = Path(
                os.environ.get("BOUDYOS_STATUS_DIR", "runtime/status")
            ) / "update.json"
        try:
            if status_path.stat().st_size > 16 * 1024:
                raise ValueError
            value = json.loads(status_path.read_text("utf-8"))
            if value.get("schema_version") != 1:
                raise ValueError
            tag = value.get("tag", "")
            commit = value.get("commit", "")
        except (OSError, AttributeError, ValueError, json.JSONDecodeError):
            tag = commit = ""
    if not _TAG.fullmatch(tag) or not _COMMIT.fullmatch(commit):
        raise ValueError("approved release tag and full commit are not configured")
    return tag, commit


def _release_metadata(path: Optional[Path] = None) -> dict:
    if path is None:
        path = Path(
            os.environ.get("BOUDYOS_RELEASE_METADATA", ".boudyos-release.json")
        )
    try:
        if path.stat().st_size > 16 * 1024:
            return {}
        value = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(value, dict):
        return {}
    commit = value.get("commit")
    tag = value.get("tag")
    origin = value.get("origin")
    image_metadata = origin == APPROVED_ORIGIN and value.get("dirty") is False
    root_metadata = (
        "origin" not in value
        and "dirty" not in value
        and isinstance(value.get("checked_at"), str)
    )
    if (
        value.get("schema_version") != 1
        or not isinstance(commit, str)
        or not _COMMIT.fullmatch(commit)
        or not isinstance(tag, str)
        or not _TAG.fullmatch(tag)
        or not (image_metadata or root_metadata)
    ):
        return {}
    return {"commit": commit, "tag": tag, "origin": APPROVED_ORIGIN}


def release_identity(metadata_path: Optional[Path] = None) -> Tuple[str, str]:
    """Return a validated release label and fixed-origin source link."""
    metadata = _release_metadata(metadata_path)
    if not metadata:
        return "main", APPROVED_ORIGIN.removesuffix(".git")
    tag = metadata["tag"]
    commit = metadata["commit"]
    return (
        f"{tag} ({commit[:12]})",
        APPROVED_ORIGIN.removesuffix(".git") + "/tree/" + commit,
    )


async def _git(
    runner: Runner, repository: Path, args: Sequence[str], timeout: float = 30
) -> ProcessResult:
    return await runner(
        ["git", "-C", str(repository), *args],
        timeout=timeout,
        output_limit=512_000,
    )


async def check_for_update(
    repository: Path = Path("."),
    *,
    fetch: bool = True,
    runner: Runner = run_exec,
    target_tag: Optional[str] = None,
    target_commit: Optional[str] = None,
    metadata_path: Optional[Path] = None,
    target_status_path: Optional[Path] = None,
) -> UpdateState:
    """Compare the active release with the root-configured tag+commit.

    Source checkouts verify the exact fetched tag and ancestry. Managed runtimes
    always use configured root-written release metadata, even if an unexpected
    .git path appears; the privileged helper repeats full verification.
    """
    try:
        tag, approved_commit = _target_release(
            target_tag, target_commit, target_status_path
        )
    except ValueError as exc:
        return UpdateState("blocked", detail=str(exc))

    repository = repository.resolve()
    git_dir = repository / ".git"
    if metadata_path is None:
        metadata_path = Path(
            os.environ.get("BOUDYOS_RELEASE_METADATA", ".boudyos-release.json")
        )
    metadata_present = metadata_path.exists()
    metadata = _release_metadata(metadata_path)
    if metadata_present or not git_dir.exists():
        if not metadata:
            return UpdateState(
                "blocked", detail="immutable active release metadata is unavailable"
            )
        current = metadata["commit"]
        current_tag = metadata["tag"]
        if _version(tag) < _version(current_tag):
            return UpdateState(
                "blocked",
                current_revision=current,
                available_revision=approved_commit,
                branch="HEAD",
                detail="configured release would be a downgrade",
            )
        state = "current" if current == approved_commit else "available"
        return UpdateState(
            state,
            current,
            approved_commit,
            "HEAD",
            False,
            (
                "approved pinned release is queued through the root verifier"
                if state == "available"
                else "BoudyOS is at the configured release"
            ),
        )

    origin = await _git(runner, repository, ["remote", "get-url", "origin"])
    if not origin.ok or origin.stdout != APPROVED_ORIGIN:
        return UpdateState(
            "blocked", detail="origin is not the approved BoudyOS repository"
        )
    branch_result = await _git(
        runner, repository, ["rev-parse", "--abbrev-ref", "HEAD"]
    )
    branch = branch_result.stdout
    if not branch_result.ok or branch not in (APPROVED_BRANCH, "HEAD"):
        return UpdateState("blocked", branch=branch, detail="ref is not approved")
    status = await _git(
        runner, repository, ["status", "--porcelain", "--untracked-files=normal"]
    )
    if not status.ok:
        return UpdateState("error", branch=branch, detail="unable to inspect worktree")
    dirty = bool(status.stdout)
    current = await _git(runner, repository, ["rev-parse", "HEAD"])
    if not current.ok or not _COMMIT.fullmatch(current.stdout):
        return UpdateState("error", branch=branch, dirty=dirty, detail="unable to read revision")

    if fetch:
        fetched = await _git(
            runner,
            repository,
            [
                "fetch",
                "--quiet",
                "--force",
                "--no-tags",
                "origin",
                f"+refs/tags/{tag}:refs/tags/{tag}",
            ],
            timeout=60,
        )
        if not fetched.ok:
            return UpdateState(
                "error",
                current.stdout,
                approved_commit,
                branch,
                dirty,
                "BoudyOS release check failed",
            )
    peeled = await _git(runner, repository, ["rev-parse", f"refs/tags/{tag}^{{commit}}"])
    if not peeled.ok or peeled.stdout != approved_commit:
        return UpdateState(
            "blocked",
            current.stdout,
            approved_commit,
            branch,
            dirty,
            "configured tag does not match its pinned commit",
        )
    if current.stdout != approved_commit:
        ancestor = await _git(
            runner,
            repository,
            ["merge-base", "--is-ancestor", current.stdout, approved_commit],
        )
        if not ancestor.ok:
            return UpdateState(
                "blocked",
                current.stdout,
                approved_commit,
                branch,
                dirty,
                "configured release is a downgrade or unrelated history",
            )
    state = "available" if current.stdout != approved_commit else "current"
    detail = (
        "approved pinned release is available through the privileged request helper"
        if state == "available"
        else "BoudyOS is at the configured release"
    )
    if dirty:
        detail += "; local changes prevent deployment"
    return UpdateState(
        state, current.stdout, approved_commit, branch, dirty, detail
    )


def validate_helper(path: str) -> Path:
    if path not in APPROVED_HELPERS:
        raise ValueError("deployment helper path is not approved")
    helper = Path(path)
    info = helper.stat()
    if not helper.is_file() or not os.access(helper, os.X_OK):
        raise ValueError("deployment helper is not executable")
    if info.st_uid != 0 or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise ValueError("deployment helper ownership or mode is unsafe")
    return helper


async def request_deployment(
    helper_path: str,
    *,
    runner: Runner = run_exec,
) -> ProcessResult:
    helper = validate_helper(helper_path)
    return await runner(
        ["sudo", "-n", str(helper), "request", "--non-interactive"],
        timeout=15,
        output_limit=128_000,
    )


def format_update_report(state: UpdateState) -> str:
    if state.state == "blocked":
        return f"BoudyOS update check blocked: {state.detail}."
    if state.state == "error":
        return f"BoudyOS update check failed: {state.detail}."
    current = state.current_revision[:12] or "unknown"
    available = state.available_revision[:12] or "unknown"
    label = "available" if state.update_available else "current"
    dirty = " Local changes detected; no deployment will run." if state.dirty else ""
    return (
        f"BoudyOS update state: {label}. Current `{current}`, configured "
        f"release `{available}`.{dirty}"
    )


def format_changelog_report(state: UpdateState) -> Tuple[str, Optional[str]]:
    """Provide a gitless-safe update report and validated compare/release link."""
    report = format_update_report(state)
    current = state.current_revision
    available = state.available_revision
    base = APPROVED_ORIGIN.removesuffix(".git")
    if _COMMIT.fullmatch(current) and _COMMIT.fullmatch(available):
        if current != available:
            return report, f"{base}/compare/{current}...{available}"
        return report, f"{base}/commit/{current}"
    return report, f"{base}/releases"
