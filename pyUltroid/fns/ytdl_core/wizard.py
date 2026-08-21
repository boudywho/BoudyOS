# Ultroid - UserBot
# Copyright (C) 2021-2026 TeamUltroid
#
# This file is a part of < https://github.com/TeamUltroid/Ultroid/ >
# PLease read the GNU Affero General Public License in
# <https://www.gnu.org/licenses/agpl-3.0.html>.

"""Pure text-menu parsing for the owner media-download wizard."""

import re
from typing import Iterable, Optional

from .formats import MediaFormat


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").strip().casefold())


def parse_quality_choice(
    value: str, choices: Iterable[MediaFormat]
) -> Optional[str]:
    """Resolve a one-based menu number, format key, or displayed label."""
    available = list(choices)
    text = (value or "").strip()
    if text.isdigit():
        index = int(text) - 1
        return available[index].key if 0 <= index < len(available) else None
    wanted = _normalized(text)
    for choice in available:
        if wanted and wanted in (_normalized(choice.key), _normalized(choice.label)):
            return choice.key
    return None


def parse_timestamp_choice(value: str) -> Optional[str]:
    """Resolve a timestamp-menu selection to its workflow action."""
    aliases = {
        "0": "cancel",
        "1": "full",
        "2": "custom",
        "3": "first60",
        "4": "last30",
        "5": "quality",
        "cancel": "cancel",
        "full": "full",
        "fullvideo": "full",
        "custom": "custom",
        "customrange": "custom",
        "first60": "first60",
        "first60s": "first60",
        "last30": "last30",
        "last30s": "last30",
        "quality": "quality",
        "changequality": "quality",
    }
    return aliases.get(_normalized(value))


def parse_confirmation_choice(value: str) -> Optional[str]:
    """Resolve a confirmation-menu selection to its workflow action."""
    aliases = {
        "0": "cancel",
        "1": "confirm",
        "2": "quality",
        "3": "time",
        "4": "cancel",
        "confirm": "confirm",
        "yes": "confirm",
        "go": "confirm",
        "quality": "quality",
        "changequality": "quality",
        "time": "time",
        "timestamp": "time",
        "changetime": "time",
        "changetimestamp": "time",
        "cancel": "cancel",
    }
    return aliases.get(_normalized(value))
