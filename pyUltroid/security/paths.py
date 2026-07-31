"""Runtime path and archive validation."""

import os
import errno
import shutil
import stat
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from contextlib import contextmanager
import tempfile
from typing import Iterable, Union


class UnsafePathError(ValueError):
    pass


def cli_path(value: Union[str, Path]) -> str:
    """Make a local path beginning with '-' unambiguous to argv tools."""
    text = os.fspath(value)
    if "\x00" in text:
        raise UnsafePathError("path contains a NUL byte")
    if text.startswith("-"):
        return "." + os.sep + text
    return text


def zip_command(
    source: Union[str, Path],
    archive: Union[str, Path],
    password: str,
) -> list:
    """Build Info-ZIP argv with options before archive and `--` before input."""
    if not password or "\x00" in password:
        raise UnsafePathError("zip password is invalid")
    return [
        "zip",
        "-r",
        "--password",
        password,
        cli_path(archive),
        "--",
        cli_path(source),
    ]


def curl_file_reference(path: Union[str, Path]) -> str:
    """Return an absolute curl @file reference immune to option parsing."""
    value = Path(path)
    if value.is_symlink() or not value.is_file():
        raise UnsafePathError("curl input is not a regular file")
    return "@" + str(value.resolve(strict=True))


def resolve_under(
    root: Union[str, Path],
    candidate: Union[str, Path],
    *,
    must_exist: bool = False,
) -> Path:
    root_path = Path(root).resolve()
    raw = Path(candidate)
    if raw.is_absolute():
        raise UnsafePathError("absolute paths are not allowed")
    target = (root_path / raw).resolve(strict=must_exist)
    try:
        target.relative_to(root_path)
    except ValueError as exc:
        raise UnsafePathError("path escapes the runtime workspace") from exc
    return target


def safe_basename(name: str, suffix: str = "") -> str:
    if (
        not name
        or name in (".", "..")
        or Path(name).name != name
        or name.startswith("-")
        or "\x00" in name
    ):
        raise UnsafePathError("unsafe filename")
    if suffix and not name.endswith(suffix):
        raise UnsafePathError("unexpected filename suffix")
    return name


def atomic_copy_file(source: Union[str, Path], destination: Union[str, Path]) -> Path:
    """Persist a regular file atomically without trusting cross-filesystem rename."""
    source_path = Path(source)
    destination_path = Path(destination)
    if source_path.is_symlink() or not source_path.is_file():
        raise UnsafePathError("source is not a regular file")
    destination_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix="." + destination_path.name + ".", dir=destination_path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as output, source_path.open("rb") as stream:
            shutil.copyfileobj(stream, output, 1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, source_path.stat().st_mode & 0o777)
        os.replace(temporary, destination_path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return destination_path


def safe_move(source: Union[str, Path], destination: Union[str, Path]) -> Path:
    """Move a regular file, falling back safely when rename crosses filesystems."""
    source_path = Path(source)
    destination_path = Path(destination)
    destination_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.replace(source_path, destination_path)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        atomic_copy_file(source_path, destination_path)
        source_path.unlink()
    return destination_path


@contextmanager
def private_workspace(root: Union[str, Path], prefix: str):
    root_path = Path(root).resolve(strict=True)
    path = Path(tempfile.mkdtemp(prefix=prefix, dir=root_path))
    os.chmod(path, 0o700)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _validate_member(name: str) -> PurePosixPath:
    normalized = name.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    member = PurePosixPath(normalized)
    if (
        not normalized
        or normalized.startswith("/")
        or member.is_absolute()
        or any(part in ("", ".", "..") for part in member.parts)
    ):
        raise UnsafePathError("archive contains an unsafe path")
    return member


def validate_zip(
    path: Union[str, Path],
    *,
    max_members: int = 1000,
    max_uncompressed: int = 1024 * 1024 * 1024,
) -> None:
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if len(members) > max_members:
            raise UnsafePathError("archive contains too many files")
        total = 0
        seen = set()
        for info in members:
            member = _validate_member(info.filename)
            if member.as_posix() in seen:
                raise UnsafePathError("archive contains duplicate paths")
            seen.add(member.as_posix())
            total += info.file_size
            if total > max_uncompressed:
                raise UnsafePathError("archive expands beyond the size limit")
            if info.compress_size and info.file_size / info.compress_size > 200:
                raise UnsafePathError("archive compression ratio is unsafe")
            mode = info.external_attr >> 16
            if mode and stat.S_ISLNK(mode):
                raise UnsafePathError("archive links are not allowed")


def validate_tar(
    path: Union[str, Path],
    *,
    max_members: int = 1000,
    max_uncompressed: int = 1024 * 1024 * 1024,
) -> None:
    with tarfile.open(path) as archive:
        members = archive.getmembers()
        if len(members) > max_members:
            raise UnsafePathError("archive contains too many files")
        total = 0
        seen = set()
        for member in members:
            if member.name.replace("\\", "/") in (".", "./") and member.isdir():
                continue
            relative = _validate_member(member.name)
            if relative.as_posix() in seen:
                raise UnsafePathError("archive contains duplicate paths")
            seen.add(relative.as_posix())
            total += member.size
            if total > max_uncompressed:
                raise UnsafePathError("archive expands beyond the size limit")
            if (
                member.issym()
                or member.islnk()
                or member.isdev()
                or not (member.isdir() or member.isreg())
            ):
                raise UnsafePathError("archive links and devices are not allowed")


def extract_archive(
    archive_path: Union[str, Path],
    destination: Union[str, Path],
    *,
    workspace: Union[str, Path],
) -> Path:
    source = Path(archive_path).resolve(strict=True)
    workspace_path = Path(workspace).resolve(strict=True)
    try:
        source.relative_to(workspace_path)
    except ValueError as exc:
        raise UnsafePathError("archive is outside the runtime workspace") from exc
    destination_path = resolve_under(workspace_path, destination)
    if destination_path.exists():
        raise UnsafePathError("archive destination already exists")
    destination_path.mkdir(parents=True)
    try:
        if zipfile.is_zipfile(source):
            validate_zip(source)
            with zipfile.ZipFile(source) as archive:
                for info in archive.infolist():
                    relative = _validate_member(info.filename)
                    target = destination_path.joinpath(*relative.parts)
                    if info.is_dir():
                        target.mkdir(mode=0o700, parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    with archive.open(info) as stream, target.open("xb") as output:
                        shutil.copyfileobj(stream, output, 1024 * 1024)
                    mode = info.external_attr >> 16
                    os.chmod(target, (mode & 0o777) or 0o600)
        elif tarfile.is_tarfile(source):
            validate_tar(source)
            with tarfile.open(source) as archive:
                for member in archive.getmembers():
                    if (
                        member.name.replace("\\", "/") in (".", "./")
                        and member.isdir()
                    ):
                        continue
                    relative = _validate_member(member.name)
                    target = destination_path.joinpath(*relative.parts)
                    if member.isdir():
                        target.mkdir(
                            mode=member.mode & 0o777,
                            parents=True,
                            exist_ok=True,
                        )
                        continue
                    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    stream = archive.extractfile(member)
                    if stream is None:
                        raise UnsafePathError("archive file has no payload")
                    with stream, target.open("xb") as output:
                        shutil.copyfileobj(stream, output, 1024 * 1024)
                    os.chmod(target, member.mode & 0o777)
        else:
            raise UnsafePathError("unsupported or invalid archive")
    except Exception:
        shutil.rmtree(destination_path, ignore_errors=True)
        raise
    for path in destination_path.rglob("*"):
        if path.is_symlink():
            shutil.rmtree(destination_path, ignore_errors=True)
            raise UnsafePathError("extracted archive contains a symlink")
        try:
            path.resolve().relative_to(destination_path)
        except ValueError as exc:
            shutil.rmtree(destination_path, ignore_errors=True)
            raise UnsafePathError("extracted path escaped destination") from exc
    return destination_path
