# Ultroid - UserBot
# Copyright (C) 2021-2026 TeamUltroid
#
# This file is a part of < https://github.com/TeamUltroid/Ultroid/ >
# PLease read the GNU Affero General Public License in
# <https://www.gnu.org/licenses/agpl-3.0.html>.

"""Format grouping based only on extractor metadata, never Bot API limits."""

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional


@dataclass(frozen=True)
class MediaFormat:
    key: str
    label: str
    selector: str
    output_type: str
    extension: str
    height: Optional[int] = None
    estimated_size: Optional[int] = None


_HEIGHTS = (2160, 1440, 1080, 720, 480, 360)


def _size(format_info: Dict[str, Any]) -> Optional[int]:
    value = format_info.get("filesize") or format_info.get("filesize_approx")
    return int(value) if isinstance(value, (int, float)) and value > 0 else None


def _estimate(formats: Iterable[Dict[str, Any]], height: int) -> Optional[int]:
    videos = [
        item
        for item in formats
        if item.get("vcodec") not in (None, "none")
        and isinstance(item.get("height"), (int, float))
        and item["height"] <= height
    ]
    if not videos:
        return None
    target_height = max(item["height"] for item in videos)
    candidates = [item for item in videos if item["height"] == target_height]
    preferred = [item for item in candidates if item.get("ext") == "mp4"] or candidates
    video_size = max((_size(item) or 0 for item in preferred), default=0)
    audios = [
        item
        for item in formats
        if item.get("acodec") not in (None, "none")
        and item.get("vcodec") == "none"
    ]
    preferred_audio = [item for item in audios if item.get("ext") == "m4a"] or audios
    audio_size = max((_size(item) or 0 for item in preferred_audio), default=0)
    total = video_size + audio_size
    return total or None


def _video_selector(height: int) -> str:
    return (
        f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/"
        f"bestvideo[height<={height}]+bestaudio/"
        f"best[height<={height}][ext=mp4]/best[height<={height}]"
    )


def build_format_choices(metadata: Dict[str, Any]) -> List[MediaFormat]:
    """Build stable practical choices without filtering on Telegram file size."""
    raw = [item for item in metadata.get("formats") or [] if isinstance(item, dict)]
    available = {
        int(item["height"])
        for item in raw
        if item.get("vcodec") not in (None, "none")
        and isinstance(item.get("height"), (int, float))
    }
    choices = [
        MediaFormat(
            "best",
            "Best",
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best",
            "video",
            "mp4",
        )
    ]
    for height in _HEIGHTS:
        if height in available:
            choices.append(
                MediaFormat(
                    f"{height}p",
                    f"{height}p",
                    _video_selector(height),
                    "video",
                    "mp4",
                    height,
                    _estimate(raw, height),
                )
            )
    choices.extend(
        (
            MediaFormat(
                "audio-m4a",
                "Audio M4A",
                "bestaudio[ext=m4a]/bestaudio",
                "audio",
                "m4a",
            ),
            MediaFormat(
                "audio-mp3",
                "Audio MP3",
                "bestaudio[ext=m4a]/bestaudio",
                "audio",
                "mp3",
            ),
        )
    )
    return list({item.key: item for item in choices}.values())
