#!/usr/bin/env python3
"""Pure policy helpers shared by BoudyOS operational scripts."""

import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import stat
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence


SECRET_KEY = re.compile(
    r"(token|secret|password|passwd|session|api[_-]?hash|credential|identity|url)",
    re.IGNORECASE,
)
MANIFEST_METADATA = frozenset(("manifest.json", "manifest.hmac"))
ALLOWED_HEALTH_KEYS = frozenset(
    (
        "schema_version",
        "state",
        "checked_at",
        "service_active",
        "restart_count",
        "readiness",
        "redis",
        "disk_percent",
        "memory_percent",
        "update_fresh",
        "backup_fresh",
        "runtime_immutable",
        "alerts",
        "alert_delivery_failed",
        "message",
    )
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _regular_inventory(root: Path) -> Dict[str, Path]:
    root = root.resolve(strict=True)
    inventory: Dict[str, Path] = {}
    for directory, names, filenames in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        for name in names:
            path = directory_path / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                raise ValueError("backup tree contains a link or special entry")
        for name in filenames:
            path = directory_path / name
            mode = path.lstat().st_mode
            if not stat.S_ISREG(mode):
                raise ValueError("backup tree contains a link or special entry")
            relative = path.relative_to(root).as_posix()
            if relative not in MANIFEST_METADATA:
                inventory[relative] = path
    return inventory


def build_manifest(root: Path, metadata: Mapping[str, Any]) -> Dict[str, Any]:
    files = []
    for relative, path in sorted(_regular_inventory(root).items()):
        info = path.lstat()
        files.append(
            {
                "path": relative,
                "sha256": sha256_file(path),
                "size": info.st_size,
                "mode": info.st_mode & 0o7777,
            }
        )
    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "metadata": dict(metadata),
        "files": files,
    }


def verify_manifest(root: Path, manifest: Mapping[str, Any]) -> List[str]:
    errors = []
    if manifest.get("schema_version") != 1:
        return ["unsupported manifest schema"]
    expected = manifest.get("files")
    if not isinstance(expected, list):
        return ["manifest files are invalid"]
    expected_by_path = {}
    for item in expected:
        if (
            not isinstance(item, dict)
            or set(item) != {"path", "sha256", "size", "mode"}
            or not isinstance(item.get("path"), str)
            or not isinstance(item.get("sha256"), str)
            or not isinstance(item.get("size"), int)
            or isinstance(item.get("size"), bool)
            or not isinstance(item.get("mode"), int)
            or isinstance(item.get("mode"), bool)
        ):
            errors.append("invalid manifest entry")
            continue
        relative = Path(item["path"])
        normalized = relative.as_posix()
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or "." in relative.parts
            or normalized in MANIFEST_METADATA
            or normalized in expected_by_path
        ):
            errors.append("unsafe manifest path")
            continue
        expected_by_path[normalized] = item
    try:
        actual = _regular_inventory(root)
    except (OSError, ValueError):
        return errors + ["restore tree contains a link or special entry"]
    expected_paths = set(expected_by_path)
    actual_paths = set(actual)
    for relative in sorted(expected_paths - actual_paths):
        errors.append("missing file: " + relative)
    for relative in sorted(actual_paths - expected_paths):
        errors.append("unexpected file: " + relative)
    for relative in sorted(expected_paths & actual_paths):
        target = actual[relative]
        item = expected_by_path[relative]
        info = target.lstat()
        if info.st_size != item["size"]:
            errors.append("size mismatch: " + relative)
        if info.st_mode & 0o7777 != item["mode"]:
            errors.append("mode mismatch: " + relative)
        if sha256_file(target) != item["sha256"]:
            errors.append("checksum mismatch: " + relative)
    return errors


def safe_extract_tar(archive: Path, destination: Path) -> None:
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    try:
        with tarfile.open(archive) as tar:
            members = tar.getmembers()
            if len(members) > 10_000:
                raise ValueError("archive contains too many members")
            if sum(member.size for member in members) > 100 * 1024 * 1024 * 1024:
                raise ValueError("archive expands beyond verification limit")
            validated = []
            seen = set()
            for member in members:
                name = member.name
                while name.startswith("./"):
                    name = name[2:]
                if name in ("", "."):
                    if member.isdir():
                        continue
                    raise ValueError("unsafe archive member")
                relative = Path(name)
                if (
                    relative.is_absolute()
                    or ".." in relative.parts
                    or "." in relative.parts
                    or member.issym()
                    or member.islnk()
                    or member.isdev()
                    or not (member.isdir() or member.isreg())
                    or relative.as_posix() in seen
                ):
                    raise ValueError("unsafe archive member")
                seen.add(relative.as_posix())
                validated.append((member, relative))
            for member, relative in validated:
                target = destination / relative
                if member.isdir():
                    target.mkdir(mode=member.mode & 0o7777, parents=True, exist_ok=True)
                    os.chmod(target, member.mode & 0o7777)
                    continue
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                source = tar.extractfile(member)
                if source is None:
                    raise ValueError("archive regular file has no payload")
                with source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, 1024 * 1024)
                os.chmod(target, member.mode & 0o7777)
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def copy_regular_source(source: Path, destination_root: Path) -> Path:
    """Copy an absolute allowlisted source without following any link."""
    if not source.is_absolute() or source == Path("/"):
        raise ValueError("backup source must be a specific absolute path")
    if source.is_symlink():
        raise ValueError("backup source symlinks are forbidden")
    # Activation paths may contain a parent symlink. Resolve it once and then
    # copy only from the resulting regular path; child links remain forbidden.
    source = source.resolve(strict=True)
    info = source.lstat()
    if stat.S_ISLNK(info.st_mode) or not (
        stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)
    ):
        raise ValueError("backup source is not a regular file or directory")
    target = destination_root / source.relative_to("/")
    if stat.S_ISREG(info.st_mode):
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copy2(source, target, follow_symlinks=False)
        return target
    target.mkdir(mode=info.st_mode & 0o7777, parents=True, exist_ok=True)
    for directory, names, filenames in os.walk(source, followlinks=False):
        directory_path = Path(directory)
        relative_dir = directory_path.relative_to(source)
        output_dir = target / relative_dir
        output_dir.mkdir(mode=directory_path.lstat().st_mode & 0o7777, exist_ok=True)
        for name in names:
            child = directory_path / name
            if not stat.S_ISDIR(child.lstat().st_mode):
                raise ValueError("backup source tree contains a link or special entry")
        for name in filenames:
            child = directory_path / name
            if not stat.S_ISREG(child.lstat().st_mode):
                raise ValueError("backup source tree contains a link or special entry")
            shutil.copy2(child, output_dir / name, follow_symlinks=False)
    return target


def copy_managed_runtime_state(
    source: Path,
    destination_root: Path,
    workspace_root: Path,
    immutable_source: Path,
) -> Path:
    """Copy only the writable work subtree from a validated commit workspace."""
    root = workspace_root.resolve(strict=True)
    source = source.resolve(strict=True)
    if (
        workspace_root.is_symlink()
        or source.parent != root
        or not re.fullmatch(r"[0-9a-f]{40}", source.name)
        or not source.is_dir()
    ):
        raise ValueError("managed runtime source is outside the commit layout")
    source_selector = source / "source"
    immutable_source = immutable_source.resolve(strict=True)
    if (
        not source_selector.is_symlink()
        or source_selector.lstat().st_uid != os.geteuid()
        or os.readlink(source_selector) != str(immutable_source)
        or source_selector.resolve(strict=True) != immutable_source
        or not immutable_source.is_dir()
        or immutable_source.name != source.name
    ):
        raise ValueError("immutable source does not match the runtime commit")
    source_info = source.lstat()
    if (
        source_info.st_uid != os.geteuid()
        or stat.S_IMODE(source_info.st_mode) != 0o750
        or {child.name for child in source.iterdir()} != {"source", "work"}
    ):
        raise ValueError("managed workspace selector layout is unsafe")
    work = source / "work"
    work_info = work.lstat()
    if (
        stat.S_ISLNK(work_info.st_mode)
        or not stat.S_ISDIR(work_info.st_mode)
        or stat.S_IMODE(work_info.st_mode) != 0o700
    ):
        raise ValueError("managed writable work directory is unsafe")
    target = destination_root / source.relative_to("/")
    target.mkdir(mode=source.lstat().st_mode & 0o7777, parents=True, exist_ok=True)
    for directory, names, filenames in os.walk(work, followlinks=False):
        directory_path = Path(directory)
        relative_dir = directory_path.relative_to(source)
        output_dir = target / relative_dir
        output_dir.mkdir(
            mode=directory_path.lstat().st_mode & 0o7777, exist_ok=True
        )
        for name in list(names):
            child = directory_path / name
            mode = child.lstat().st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                raise ValueError("mutable runtime state contains a special entry")
        for name in filenames:
            child = directory_path / name
            mode = child.lstat().st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
                raise ValueError("mutable runtime state contains a special entry")
            shutil.copy2(child, output_dir / name, follow_symlinks=False)
    return target


def copy_legacy_runtime_state(source: Path, destination_root: Path) -> None:
    """Copy only mutable state from the active legacy source directory."""
    if (
        not source.is_absolute()
        or source == Path("/")
        or source.is_symlink()
        or not source.is_dir()
    ):
        raise ValueError("legacy runtime source is unsafe")
    names = {
        ".env",
        ".megarc",
        "addons",
        "database.json",
        "db",
        "downloads",
        "logs",
        "sessions",
        "temp",
        "ultroid.json",
        "vcbot",
    }
    names.update(
        child.name
        for child in source.iterdir()
        if child.name.endswith((".session", ".db", ".sqlite", ".sqlite3"))
        or ".session-" in child.name
    )
    names.update(("resources/auth", "resources/auths", "resources/downloads"))
    for relative in sorted(names):
        item = source / relative
        if item.exists() or item.is_symlink():
            copy_regular_source(item, destination_root)


def resolve_active_runtime(active_link: Path, workspace_root: Path) -> Path:
    """Resolve only the managed active link to one commit-named workspace."""
    if not active_link.is_absolute() or not workspace_root.is_absolute():
        raise ValueError("managed runtime paths must be absolute")
    if not active_link.is_symlink():
        raise ValueError("active runtime must be a symlink")
    if workspace_root.is_symlink():
        raise ValueError("workspace root symlinks are forbidden")
    root = workspace_root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("workspace root is not a directory")
    runtime = active_link.resolve(strict=True)
    if (
        runtime.is_symlink()
        or not runtime.is_dir()
        or runtime.parent != root
        or not re.fullmatch(r"[0-9a-f]{40}", runtime.name)
        or {child.name for child in runtime.iterdir()} != {"source", "work"}
        or not (runtime / "source").is_symlink()
        or (runtime / "work").is_symlink()
        or not (runtime / "work").is_dir()
    ):
        raise ValueError("active runtime target is outside the managed commit layout")
    return runtime


def ensure_hmac_key(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        _load_hmac_key(path)
        return
    try:
        os.write(descriptor, secrets.token_bytes(32))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _load_hmac_key(path: Path) -> bytes:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise ValueError("HMAC key must be a private regular file")
    key = path.read_bytes()
    if len(key) < 32:
        raise ValueError("HMAC key is too short")
    return key


def hmac_file(path: Path, key_path: Path) -> str:
    digest = hmac.new(_load_hmac_key(key_path), digestmod=hashlib.sha256)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_hmac(path: Path, key_path: Path, signature_path: Path) -> None:
    signature = hmac_file(path, key_path)
    handle, temporary = tempfile.mkstemp(
        prefix="." + signature_path.name, dir=signature_path.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="ascii") as stream:
            stream.write(signature + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, signature_path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def verify_hmac(path: Path, key_path: Path, signature_path: Path) -> bool:
    try:
        supplied = signature_path.read_text("ascii").strip()
    except (OSError, UnicodeError):
        return False
    if not re.fullmatch(r"[0-9a-f]{64}", supplied):
        return False
    return hmac.compare_digest(hmac_file(path, key_path), supplied)


def _bucket(timestamp: datetime, now: datetime) -> str:
    age_days = (now.date() - timestamp.date()).days
    if age_days < 7:
        return "daily:" + timestamp.strftime("%Y-%m-%d")
    if age_days < 35:
        year, week, _ = timestamp.isocalendar()
        return "weekly:%04d-%02d" % (year, week)
    return "monthly:" + timestamp.strftime("%Y-%m")


def rotation_keep(
    paths: Sequence[Path],
    *,
    now: datetime,
    daily: int = 7,
    weekly: int = 4,
    monthly: int = 3,
) -> List[Path]:
    """Select newest unique time buckets for 7/4/3 retention."""
    parsed = []
    pattern = re.compile(r"^boudyos-(\d{8}T\d{6}Z)\.tar\.age$")
    for path in paths:
        match = pattern.match(path.name)
        if match:
            parsed.append(
                (
                    datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(
                        tzinfo=timezone.utc
                    ),
                    path,
                )
            )
    limits = {"daily": daily, "weekly": weekly, "monthly": monthly}
    buckets: Dict[str, set] = {key: set() for key in limits}
    kept: List[Path] = []
    for timestamp, path in sorted(parsed, reverse=True):
        bucket = _bucket(timestamp, now)
        kind = bucket.split(":", 1)[0]
        if bucket in buckets[kind]:
            continue
        if len(buckets[kind]) < limits[kind]:
            buckets[kind].add(bucket)
            kept.append(path)
    return kept


def sanitize_health_status(status: Mapping[str, Any]) -> Dict[str, Any]:
    unsafe_value = re.compile(
        r"https?://|traceback|(?:^|\s)/(?:etc|opt|root|home|var|tmp|run)/|"
        r"(?:token|password|secret|session)\s*[=:]|[0-9]{7,}",
        re.IGNORECASE,
    )

    def safe_text(value: Any, limit: int) -> str:
        text = str(value)[:limit].replace("\n", " ")
        return "details withheld" if unsafe_value.search(text) else text

    clean: Dict[str, Any] = {}
    for key, value in status.items():
        if key not in ALLOWED_HEALTH_KEYS or SECRET_KEY.search(key):
            continue
        if isinstance(value, bool) or isinstance(value, (int, float)):
            clean[key] = value
        elif isinstance(value, str):
            clean[key] = safe_text(value, 240)
        elif key == "alerts" and isinstance(value, list):
            clean[key] = [safe_text(item, 120) for item in value[:20]]
    return clean


def atomic_json(path: Path, value: Mapping[str, Any], mode: int = 0o600) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent_info = path.parent.stat()
    handle, temporary = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        if os.geteuid() == 0:
            os.chown(temporary, parent_info.st_uid, parent_info.st_gid)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    manifest_parser = subparsers.add_parser("manifest")
    manifest_parser.add_argument("root", type=Path)
    manifest_parser.add_argument("output", type=Path)
    rotate_parser = subparsers.add_parser("rotate")
    rotate_parser.add_argument("directory", type=Path)
    extract_parser = subparsers.add_parser("extract")
    extract_parser.add_argument("archive", type=Path)
    extract_parser.add_argument("destination", type=Path)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("root", type=Path)
    verify_parser.add_argument("manifest", type=Path)
    copy_parser = subparsers.add_parser("copy-source")
    copy_parser.add_argument("source", type=Path)
    copy_parser.add_argument("destination", type=Path)
    copy_parser.add_argument("--managed-workspace-root", type=Path)
    copy_parser.add_argument("--immutable-source", type=Path)
    legacy_copy_parser = subparsers.add_parser("copy-legacy-runtime")
    legacy_copy_parser.add_argument("source", type=Path)
    legacy_copy_parser.add_argument("destination", type=Path)
    active_parser = subparsers.add_parser("resolve-active-runtime")
    active_parser.add_argument("active_link", type=Path)
    active_parser.add_argument("workspace_root", type=Path)
    key_parser = subparsers.add_parser("ensure-hmac-key")
    key_parser.add_argument("key", type=Path)
    sign_parser = subparsers.add_parser("hmac-sign")
    sign_parser.add_argument("archive", type=Path)
    sign_parser.add_argument("key", type=Path)
    sign_parser.add_argument("signature", type=Path)
    auth_parser = subparsers.add_parser("hmac-verify")
    auth_parser.add_argument("archive", type=Path)
    auth_parser.add_argument("key", type=Path)
    auth_parser.add_argument("signature", type=Path)
    args = parser.parse_args()
    if args.command == "manifest":
        root = args.root.resolve()
        manifest = build_manifest(root, {"product": "BoudyOS"})
        atomic_json(args.output, manifest)
        return 0
    if args.command == "rotate":
        now = datetime.now(timezone.utc)
        backups = list(args.directory.glob("boudyos-*.tar.age"))
        keep = set(rotation_keep(backups, now=now))
        for path in backups:
            if path not in keep:
                path.unlink()
                path.with_name(path.name + ".hmac").unlink(missing_ok=True)
        return 0
    if args.command == "extract":
        safe_extract_tar(args.archive, args.destination)
        return 0
    if args.command == "verify":
        manifest = json.loads(args.manifest.read_text("utf-8"))
        errors = verify_manifest(args.root, manifest)
        if errors:
            for error in errors:
                print(error)
            return 1
        return 0
    if args.command == "copy-source":
        if args.managed_workspace_root is None:
            if args.immutable_source is not None:
                parser.error("--immutable-source requires --managed-workspace-root")
            copy_regular_source(args.source, args.destination)
        else:
            if args.immutable_source is None:
                parser.error("--managed-workspace-root requires --immutable-source")
            copy_managed_runtime_state(
                args.source,
                args.destination,
                args.managed_workspace_root,
                args.immutable_source,
            )
        return 0
    if args.command == "resolve-active-runtime":
        print(resolve_active_runtime(args.active_link, args.workspace_root))
        return 0
    if args.command == "copy-legacy-runtime":
        copy_legacy_runtime_state(args.source, args.destination)
        return 0
    if args.command == "ensure-hmac-key":
        args.key.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        ensure_hmac_key(args.key)
        return 0
    if args.command == "hmac-sign":
        write_hmac(args.archive, args.key, args.signature)
        return 0
    if args.command == "hmac-verify":
        return 0 if verify_hmac(args.archive, args.key, args.signature) else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(_main())
