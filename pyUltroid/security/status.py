"""Sanitized dashboard status collection."""

import asyncio
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Mapping

from .updater import UpdateState


_ALLOWED_STATUS_KEYS = frozenset(
    (
        "state",
        "healthy",
        "checked_at",
        "backup_age_seconds",
        "release",
        "message",
    )
)
_UNSAFE_STATUS_VALUE = re.compile(
    r"https?://|traceback|(?:^|\s)/(?:etc|opt|root|home|var|tmp|run)/|"
    r"(?:token|password|secret|session)\s*[=:]|[0-9]{7,}",
    re.IGNORECASE,
)
_RELEASE_TAG = re.compile(r"^v?[0-9]+\.[0-9]+\.[0-9]+$")
_RELEASE_COMMIT = re.compile(r"^[0-9a-f]{40}$")


def status_dir() -> Path:
    """Resolve the read-only root truth directory at call time."""
    return Path(os.environ.get("BOUDYOS_STATUS_DIR", "runtime/status"))


def app_status_dir() -> Path:
    """Resolve the service-owned status output directory at call time."""
    return Path(os.environ.get("BOUDYOS_APP_STATUS_DIR", "runtime/app-status"))


def read_bounded_status(path: Path, max_bytes: int = 64 * 1024) -> Dict[str, Any]:
    try:
        if not path.is_file() or path.stat().st_size > max_bytes:
            return {}
        raw = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    clean: Dict[str, Any] = {}
    for key in _ALLOWED_STATUS_KEYS:
        value = raw.get(key)
        if isinstance(value, (bool, int, float)) or (
            isinstance(value, str)
            and len(value) <= 160
            and not _UNSAFE_STATUS_VALUE.search(value)
        ):
            clean[key] = value
    return clean


def write_update_status(state: UpdateState, path: Path = None) -> bool:
    if path is None:
        path = app_status_dir() / "update.json"
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError:
        return False
    payload = {
        "schema_version": 1,
        "state": state.state,
        "checked_at": int(time.time()),
        "message": (
            state.detail[:160]
            if not _UNSAFE_STATUS_VALUE.search(state.detail)
            else "details withheld"
        ),
    }
    try:
        prior = json.loads(path.read_text("utf-8"))
        if (
            _RELEASE_TAG.fullmatch(prior.get("tag", ""))
            and _RELEASE_COMMIT.fullmatch(prior.get("commit", ""))
        ):
            payload["tag"] = prior["tag"]
            payload["commit"] = prior["commit"]
    except (OSError, AttributeError, ValueError, json.JSONDecodeError):
        pass
    try:
        handle, temporary = tempfile.mkstemp(prefix=".update.", dir=path.parent)
    except OSError:
        return False
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o640)
        os.replace(temporary, path)
    except OSError:
        return False
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return True


def mark_ready(configured_path: str) -> None:
    """Write readiness only inside the dedicated /run/boudyos directory."""
    if not configured_path:
        return
    root = Path("/run/boudyos")
    target = Path(configured_path)
    try:
        resolved_parent = target.parent.resolve()
        resolved_parent.relative_to(root)
    except (OSError, ValueError):
        raise ValueError("readiness path must be under /run/boudyos")
    target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".ready.", dir=target.parent)
    try:
        with os.fdopen(handle, "w", encoding="ascii") as stream:
            json.dump(
                {
                    "schema_version": 1,
                    "pid": os.getpid(),
                    "timestamp": int(time.time()),
                },
                stream,
                sort_keys=True,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o640)
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


async def readiness_heartbeat(
    configured_path: str, interval: float = None
) -> None:
    """Refresh the process-correlated marker for the lifetime of the app."""
    if not configured_path:
        return
    if interval is None:
        try:
            interval = float(os.environ.get("BOUDYOS_READY_INTERVAL_SECONDS", "15"))
        except ValueError:
            interval = 15.0
    interval = max(5.0, min(interval, 60.0))
    while True:
        try:
            mark_ready(configured_path)
        except (OSError, ValueError):
            pass
        await asyncio.sleep(interval)


def dashboard_summary(
    *,
    version: str,
    started_at: float,
    official_count: int,
    addon_count: int,
    disabled_count: int,
    update: UpdateState,
    redis_healthy: bool,
    assistant_healthy: bool,
    state_dir: Path = None,
) -> str:
    if state_dir is None:
        state_dir = status_dir()
    uptime = max(0, int(time.time() - started_at))
    health = read_bounded_status(state_dir / "health.json")
    backup = read_bounded_status(state_dir / "backup.json")
    update_label = update.state
    backup_label = str(backup.get("state", "unknown"))
    health_label = str(health.get("state", "unknown"))
    return (
        f"\n\n**BoudyOS {version} status**\n"
        f"Uptime: `{uptime}s` · Official: `{official_count}` · Add-ons: `{addon_count}`\n"
        f"Disabled optional: `{disabled_count}` · Update: `{update_label}`\n"
        f"Redis: `{'healthy' if redis_healthy else 'unavailable'}` · "
        f"Assistant: `{'healthy' if assistant_healthy else 'unavailable'}`\n"
        f"Health: `{health_label}` · Backup: `{backup_label}`"
    )
