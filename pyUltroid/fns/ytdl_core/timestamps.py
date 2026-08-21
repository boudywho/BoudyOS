# Ultroid - UserBot
# Copyright (C) 2021-2026 TeamUltroid
#
# This file is a part of < https://github.com/TeamUltroid/Ultroid/ >
# PLease read the GNU Affero General Public License in
# <https://www.gnu.org/licenses/agpl-3.0.html>.

"""Strict timestamp parsing for full, open, and multiple media ranges."""

import re
from dataclasses import dataclass
from typing import List, Optional


class TimestampError(ValueError):
    pass


@dataclass(frozen=True, order=True)
class TimeRange:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


_FIRST_LAST = re.compile(r"^(first|last)\s+(\d+(?:\.\d+)?)s$", re.I)


def is_command_message(value: Optional[str], prefix: Optional[str] = ".") -> bool:
    """Check whether text represents a bot command that should bypass timestamp parsing."""
    text = (value or "").strip()
    if not text:
        return False
    if text == ".ytcancel" or text.startswith(".ytcancel ") or text.startswith(".ytcancel\n"):
        return True
    active_prefix = prefix or "."
    if active_prefix in (" ", "NO_HNDLR"):
        return False
    if text.startswith(active_prefix):
        remainder = text[len(active_prefix):]
        if remainder and (remainder[0].isalpha() or remainder[0] == "_"):
            return True
    return False



def _seconds(value: str) -> float:
    parts = value.strip().split(":")
    if not 1 <= len(parts) <= 3 or any(not part for part in parts):
        raise TimestampError(f"Invalid timestamp: {value!r}")
    try:
        numbers = [float(part) for part in parts]
    except ValueError as exc:
        raise TimestampError(f"Invalid timestamp: {value!r}") from exc
    if any(number < 0 for number in numbers):
        raise TimestampError("Timestamps cannot be negative.")
    if len(parts) > 1 and any(number >= 60 for number in numbers[1:]):
        raise TimestampError("Minutes and seconds components must be below 60.")
    if len(parts) == 1:
        return numbers[0]
    if len(parts) == 2:
        return numbers[0] * 60 + numbers[1]
    return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]


def parse_timestamp_ranges(value: str, duration: Optional[float]) -> List[TimeRange]:
    """Parse comma-separated ``start-end`` ranges and friendly first/last forms."""
    text = (value or "").strip()
    if not text or text.lower() in ("full", "full video"):
        return []
    if duration is not None and duration <= 0:
        raise TimestampError("Media duration is unavailable.")
    friendly = _FIRST_LAST.fullmatch(text)
    if friendly:
        amount = float(friendly.group(2))
        if amount <= 0:
            raise TimestampError("Range duration must be positive.")
        if duration is None:
            raise TimestampError("Media duration is required for this range.")
        if amount > duration:
            raise TimestampError("Range exceeds media duration.")
        return [
            TimeRange(0, amount)
            if friendly.group(1).lower() == "first"
            else TimeRange(duration - amount, duration)
        ]
    parsed = []
    for raw_range in text.split(","):
        item = raw_range.strip()
        if "-" not in item:
            raise TimestampError("Use start-end, first Ns, last Ns, or full.")
        start_text, end_text = (part.strip() for part in item.split("-", 1))
        if not start_text and not end_text:
            raise TimestampError("A range needs a start or end timestamp.")
        start = _seconds(start_text) if start_text else 0.0
        if end_text:
            end = _seconds(end_text)
        elif duration is not None:
            end = float(duration)
        else:
            raise TimestampError("An open end requires a known media duration.")
        if duration is not None and end > duration:
            raise TimestampError("Range exceeds media duration.")
        if start >= end:
            raise TimestampError("Range start must be before its end.")
        parsed.append(TimeRange(start, end))
    ordered = sorted(parsed)
    if len(set(ordered)) != len(ordered):
        raise TimestampError("Duplicate ranges are not allowed.")
    for previous, current in zip(ordered, ordered[1:]):
        if current.start < previous.end:
            raise TimestampError("Timestamp ranges cannot overlap.")
    return parsed
