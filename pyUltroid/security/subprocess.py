"""Bounded asynchronous argv-only subprocess execution."""

import asyncio
import os
import signal
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Mapping, Optional, Sequence


@dataclass(frozen=True)
class ProcessResult:
    argv: tuple
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    stdout_truncated: bool = False
    stderr_truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


async def _read_bounded(
    stream: asyncio.StreamReader, limit: int
) -> tuple:
    chunks = bytearray()
    truncated = False
    while True:
        block = await stream.read(65536)
        if not block:
            break
        remaining = limit - len(chunks)
        if remaining > 0:
            chunks.extend(block[:remaining])
        if len(block) > remaining:
            truncated = True
    return bytes(chunks), truncated


def _kill_process_group(process: asyncio.subprocess.Process) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        try:
            process.kill()
        except ProcessLookupError:
            pass


async def _wait_with_timeout(
    process: asyncio.subprocess.Process,
    timeout: float,
    progress_callback: Optional[Callable[[], object]] = None,
    progress_interval: float = 1.0,
) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            _kill_process_group(process)
            await process.wait()
            return True
        try:
            await asyncio.wait_for(
                asyncio.shield(process.wait()),
                timeout=min(progress_interval, remaining),
            )
            return False
        except asyncio.TimeoutError:
            if progress_callback is not None:
                value = progress_callback()
                if inspect.isawaitable(value):
                    await value


async def run_exec(
    argv: Sequence[str],
    *,
    cwd: Optional[Path] = None,
    timeout: float = 120.0,
    output_limit: int = 1024 * 1024,
    env: Optional[Mapping[str, str]] = None,
    progress_callback: Optional[Callable[[], object]] = None,
    progress_interval: float = 1.0,
) -> ProcessResult:
    """Execute argv without a shell and return bounded, decoded output."""
    if not argv or any(not isinstance(item, str) or "\x00" in item for item in argv):
        raise ValueError("argv must contain non-empty, NUL-free strings")
    if timeout <= 0 or output_limit < 0 or progress_interval <= 0:
        raise ValueError("timeout and output_limit must be positive")
    command = tuple(argv)
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(cwd) if cwd is not None else None,
            env=dict(env) if env is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=(os.name == "posix"),
        )
    except FileNotFoundError as exc:
        return ProcessResult(command, 127, "", str(exc))

    stdout_task = asyncio.create_task(_read_bounded(process.stdout, output_limit))
    stderr_task = asyncio.create_task(_read_bounded(process.stderr, output_limit))
    timed_out = await _wait_with_timeout(
        process, timeout, progress_callback, progress_interval
    )
    stdout_data, stdout_truncated = await stdout_task
    stderr_data, stderr_truncated = await stderr_task
    return ProcessResult(
        command,
        process.returncode,
        stdout_data.decode("utf-8", "replace").strip(),
        stderr_data.decode("utf-8", "replace").strip(),
        timed_out,
        stdout_truncated,
        stderr_truncated,
    )


async def run_shell_compat(
    command: str,
    *,
    timeout: float = 300.0,
    output_limit: int = 1024 * 1024,
) -> ProcessResult:
    """Explicit dangerous-owner shell compatibility with group timeout."""
    if not isinstance(command, str) or "\x00" in command:
        raise ValueError("shell command must be a NUL-free string")
    process = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=(os.name == "posix"),
    )
    stdout_task = asyncio.create_task(_read_bounded(process.stdout, output_limit))
    stderr_task = asyncio.create_task(_read_bounded(process.stderr, output_limit))
    timed_out = await _wait_with_timeout(process, timeout)
    stdout_data, stdout_truncated = await stdout_task
    stderr_data, stderr_truncated = await stderr_task
    return ProcessResult(
        (command,),
        process.returncode,
        stdout_data.decode("utf-8", "replace").strip(),
        stderr_data.decode("utf-8", "replace").strip(),
        timed_out,
        stdout_truncated,
        stderr_truncated,
    )
