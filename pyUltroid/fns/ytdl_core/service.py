# Ultroid - UserBot
# Copyright (C) 2021-2026 TeamUltroid
#
# This file is a part of < https://github.com/TeamUltroid/Ultroid/ >
# PLease read the GNU Affero General Public License in
# <https://www.gnu.org/licenses/agpl-3.0.html>.

"""Async boundary around yt-dlp's blocking Python API."""

import asyncio
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .formats import MediaFormat


class DownloadCancelled(RuntimeError):
    pass


class YTDLPService:
    def __init__(self, ydl_factory=None):
        self._ydl_factory = ydl_factory

    def _factory(self):
        if self._ydl_factory is not None:
            return self._ydl_factory
        from yt_dlp import YoutubeDL

        return YoutubeDL

    async def extract(self, url: str) -> Dict[str, Any]:
        def blocking():
            options = {
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "skip_download": True,
            }
            with self._factory()(options) as downloader:
                result = downloader.extract_info(url, download=False)
            if result.get("entries"):
                result = next((item for item in result["entries"] if item), None)
            if not isinstance(result, dict):
                raise ValueError("The extractor returned no media metadata.")
            return result

        try:
            return await asyncio.to_thread(blocking)
        except (OSError, ValueError):
            raise
        except Exception as exc:
            raise RuntimeError(str(exc)) from exc

    async def download(
        self,
        url: str,
        media_format: MediaFormat,
        workspace: Path,
        *,
        cancel_event: Optional[threading.Event] = None,
        progress_hook: Optional[Callable[[Dict[str, Any]], None]] = None,
        max_bytes: Optional[int] = None,
    ) -> Path:
        workspace = Path(workspace).resolve(strict=True)

        def hook(status):
            if cancel_event is not None and cancel_event.is_set():
                raise DownloadCancelled("Download cancelled.")
            downloaded = status.get("downloaded_bytes") or 0
            if max_bytes is not None and downloaded > max_bytes:
                raise ValueError("Download exceeds the configured safety limit.")
            if progress_hook is not None:
                progress_hook(dict(status))

        def blocking():
            options = {
                "format": media_format.selector,
                "outtmpl": str(workspace / "media-%(id).80s.%(ext)s"),
                "noplaylist": True,
                "merge_output_format": "mp4",
                "restrictfilenames": True,
                "quiet": True,
                "no_warnings": True,
                "progress_hooks": [hook],
            }
            if media_format.key in ("audio-m4a", "audio-mp3"):
                options["postprocessors"] = [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": media_format.extension,
                        "preferredquality": "192",
                    }
                ]
            with self._factory()(options) as downloader:
                result = downloader.extract_info(url, download=True)
                prepared = Path(downloader.prepare_filename(result))
            expected = prepared.with_suffix("." + media_format.extension)
            candidates = [expected, prepared]
            candidates.extend(
                path
                for path in workspace.glob("media-*")
                if path.is_file() and not path.name.endswith((".part", ".ytdl"))
            )
            for candidate in candidates:
                try:
                    resolved = candidate.resolve(strict=True)
                    resolved.relative_to(workspace)
                except (FileNotFoundError, ValueError):
                    continue
                if resolved.is_file():
                    return resolved
            raise FileNotFoundError("yt-dlp did not produce an output file")

        try:
            return await asyncio.to_thread(blocking)
        except DownloadCancelled:
            raise
        except (OSError, ValueError):
            raise
        except Exception as exc:
            if cancel_event is not None and cancel_event.is_set():
                raise DownloadCancelled("Download cancelled.") from exc
            raise RuntimeError(str(exc)) from exc
