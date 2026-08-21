# Ultroid - UserBot
# Copyright (C) 2021-2026 TeamUltroid
#
# This file is a part of < https://github.com/TeamUltroid/Ultroid/ >
# PLease read the GNU Affero General Public License in
# <https://www.gnu.org/licenses/agpl-3.0.html>.

"""FFmpeg clipping without shell interpolation."""

import asyncio
from pathlib import Path
from typing import Iterable

from .service import DownloadCancelled
from .timestamps import TimeRange


async def _run(args, cancel_event=None):
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
    )
    try:
        while True:
            try:
                _, stderr = await asyncio.wait_for(process.communicate(), timeout=0.5)
                break
            except asyncio.TimeoutError:
                if cancel_event is not None and cancel_event.is_set():
                    process.terminate()
                    await process.wait()
                    raise DownloadCancelled("Clipping cancelled.")
    except asyncio.CancelledError:
        process.terminate()
        await process.wait()
        raise
    if process.returncode:
        raise RuntimeError(stderr.decode("utf-8", "replace")[-1500:])


async def clip_media(source: Path, ranges: Iterable[TimeRange], cancel_event=None) -> Path:
    """Return source for full media; clip one range or render/concat many ranges."""
    source = Path(source).resolve(strict=True)
    selected = list(ranges)
    if not selected:
        return source
    workspace = source.parent
    suffix = source.suffix.lower()
    output = workspace / ("clipped" + suffix)
    if len(selected) == 1:
        item = selected[0]
        await _run(
            [
                "ffmpeg", "-y", "-ss", str(item.start), "-i", str(source),
                "-t", str(item.duration), "-map", "0", "-c", "copy", str(output),
            ],
            cancel_event,
        )
        return output
    parts = []
    for index, item in enumerate(selected):
        part = workspace / f"clip-{index:03d}{suffix}"
        codec = ["-c:a", "libmp3lame"] if suffix == ".mp3" else (
            ["-vn", "-c:a", "aac"] if suffix in (".m4a", ".aac") else
            ["-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac"]
        )
        await _run(
            ["ffmpeg", "-y", "-ss", str(item.start), "-i", str(source),
             "-t", str(item.duration), *codec, str(part)],
            cancel_event,
        )
        parts.append(part)
    manifest = workspace / "concat.txt"
    manifest.write_text("".join(f"file '{part.name}'\n" for part in parts), "utf-8")
    try:
        await _run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "1", "-i", str(manifest),
             "-c", "copy", str(output)],
            cancel_event,
        )
    finally:
        manifest.unlink(missing_ok=True)
        for part in parts:
            part.unlink(missing_ok=True)
    return output
