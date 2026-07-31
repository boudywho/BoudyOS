"""Verified installation for bundled trusted add-ons."""

import ast
import hashlib
import json
import os
import re
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Optional

from .paths import UnsafePathError, safe_basename


REGISTRY_SCHEMA = 1
DEFAULT_MAX_BYTES = 1024 * 1024
DEFAULT_TIMEOUT = 20.0
TRUSTED_SOURCE_HOSTS = frozenset(("raw.githubusercontent.com",))
_FULL_REVISION = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class AddonInstallError(RuntimeError):
    pass


@dataclass(frozen=True)
class TrustedAddon:
    name: str
    source_url: str
    revision: str
    sha256: str
    description: str
    capabilities: tuple


def _validate_source(url: str, revision: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise AddonInstallError("trusted add-on source must be credential-free HTTPS")
    if parsed.hostname not in TRUSTED_SOURCE_HOSTS or parsed.port not in (None, 443):
        raise AddonInstallError("trusted add-on source host is not allowed")
    if parsed.query or parsed.fragment:
        raise AddonInstallError("trusted add-on source must not use query or fragment")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 4 or any(part in (".", "..") for part in parts):
        raise AddonInstallError("trusted add-on source path is invalid")
    if revision not in parts:
        raise AddonInstallError("source URL does not contain its immutable revision")


def load_registry(path: Path) -> Dict[str, TrustedAddon]:
    try:
        payload = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AddonInstallError("trusted add-on registry is unreadable") from exc
    if payload.get("schema_version") != REGISTRY_SCHEMA:
        raise AddonInstallError("unsupported trusted add-on registry schema")
    entries: Dict[str, TrustedAddon] = {}
    plugins = payload.get("plugins")
    if not isinstance(plugins, list):
        raise AddonInstallError("trusted add-on registry plugins must be a list")
    for raw in plugins:
        if not isinstance(raw, dict):
            raise AddonInstallError("invalid trusted add-on entry")
        required = {
            "name",
            "source_url",
            "revision",
            "sha256",
            "description",
            "capabilities",
        }
        if set(raw) != required:
            raise AddonInstallError("trusted add-on entry has unexpected fields")
        name = safe_basename(str(raw["name"]), ".py")
        revision = str(raw["revision"])
        digest = str(raw["sha256"]).lower()
        if not _FULL_REVISION.fullmatch(revision):
            raise AddonInstallError("trusted add-on revision must be a full commit")
        if not _SHA256.fullmatch(digest):
            raise AddonInstallError("trusted add-on SHA-256 is invalid")
        _validate_source(str(raw["source_url"]), revision)
        capabilities = raw["capabilities"]
        if not isinstance(capabilities, list) or not all(
            isinstance(item, str) and item.strip() for item in capabilities
        ):
            raise AddonInstallError("trusted add-on capabilities must be strings")
        if name in entries:
            raise AddonInstallError("duplicate trusted add-on name")
        entries[name] = TrustedAddon(
            name,
            str(raw["source_url"]),
            revision,
            digest,
            str(raw["description"]),
            tuple(capabilities),
        )
    return entries


def download_https(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "BoudyOS/2.2 trusted-addon-installer"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            final = urllib.parse.urlsplit(response.geturl())
            original = urllib.parse.urlsplit(url)
            if final != original:
                raise AddonInstallError("add-on redirects are refused")
            length = response.headers.get("Content-Length")
            if length and int(length) > max_bytes:
                raise AddonInstallError("add-on exceeds download size limit")
            content = response.read(max_bytes + 1)
    except (OSError, ValueError) as exc:
        raise AddonInstallError("add-on download failed") from exc
    if len(content) > max_bytes:
        raise AddonInstallError("add-on exceeds download size limit")
    return content


def _validate_python(content: bytes, filename: str) -> None:
    if b"\x00" in content:
        raise AddonInstallError("add-on contains NUL bytes")
    try:
        source = content.decode("utf-8")
        ast.parse(source, filename=filename)
    except (UnicodeDecodeError, SyntaxError, ValueError, RecursionError) as exc:
        raise AddonInstallError("add-on is not valid UTF-8 Python") from exc


def atomic_install(
    content: bytes,
    name: str,
    addon_dir: Path,
    *,
    expected_sha256: Optional[str] = None,
) -> Path:
    """Validate in staging, preserve the prior file, then atomically replace."""
    safe_basename(name, ".py")
    if len(content) > DEFAULT_MAX_BYTES:
        raise AddonInstallError("add-on exceeds download size limit")
    digest = hashlib.sha256(content).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise AddonInstallError("add-on SHA-256 verification failed")
    _validate_python(content, name)
    addon_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination = addon_dir / name
    rollback_dir = addon_dir / ".rollback"
    stage_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".boudyos-addon-", dir=addon_dir, delete=False
        ) as stage:
            stage.write(content)
            stage.flush()
            os.fsync(stage.fileno())
            stage_name = stage.name
        os.chmod(stage_name, 0o600)
        if destination.exists():
            rollback_dir.mkdir(mode=0o700, exist_ok=True)
            stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            backup = rollback_dir / f"{destination.stem}-{stamp}.py"
            os.replace(destination, backup)
            try:
                os.replace(stage_name, destination)
            except Exception:
                os.replace(backup, destination)
                raise
        else:
            os.replace(stage_name, destination)
        return destination
    finally:
        if stage_name:
            try:
                os.unlink(stage_name)
            except FileNotFoundError:
                pass


def install_trusted(
    entry: TrustedAddon,
    addon_dir: Path,
    *,
    downloader: Callable[[str], bytes] = download_https,
    loader: Optional[Callable[[Path], None]] = None,
) -> Path:
    _validate_source(entry.source_url, entry.revision)
    content = downloader(entry.source_url)
    destination = addon_dir / entry.name
    prior = destination.read_bytes() if destination.exists() else None
    installed = atomic_install(
        content, entry.name, addon_dir, expected_sha256=entry.sha256
    )
    if loader is not None:
        try:
            loader(installed)
        except Exception as exc:
            if prior is None:
                installed.unlink(missing_ok=True)
            else:
                atomic_install(prior, entry.name, addon_dir)
            raise AddonInstallError(
                "add-on failed to load; the previous version was restored"
            ) from exc
    return installed


def install_legacy_untrusted(
    url: str,
    addon_dir: Path,
    *,
    downloader: Callable[[str], bytes] = download_https,
) -> Path:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise AddonInstallError("legacy add-on URL must be credential-free HTTPS")
    name = safe_basename(Path(parsed.path).name, ".py")
    return atomic_install(downloader(url), name, addon_dir)
