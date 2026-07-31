"""Strict parsers for values that may come from an untrusted database."""

import ast
import json
from typing import Any, Iterable, Tuple


DEFAULT_NIGHT_TIME = (0, 0, 7, 0)
_TRUE_VALUES = frozenset(("1", "true", "yes", "on", "enabled"))


def parse_bool(value: Any, default: bool = False) -> bool:
    """Parse an opt-in setting. Unknown values fail closed."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in _TRUE_VALUES
    return default


def safe_data_value(value: str) -> Any:
    """Decode JSON or a legacy Python literal without executing code."""
    text = value.strip()
    if len(text) > 1024 * 1024:
        return text
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        try:
            tree = ast.parse(text, mode="eval")
            if sum(1 for _ in ast.walk(tree)) > 10_000:
                return text
            return ast.literal_eval(tree)
        except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
            return text


def _four_ints(value: Any) -> Iterable[int]:
    if isinstance(value, str):
        value = safe_data_value(value)
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError("night time must contain exactly four values")
    # bool is an int subclass, but is not a meaningful hour/minute.
    if any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        raise ValueError("night time values must be integers")
    return value


def parse_night_time(
    value: Any, default: Tuple[int, int, int, int] = DEFAULT_NIGHT_TIME
) -> Tuple[int, int, int, int]:
    """Return close-hour/minute and open-hour/minute, or a safe default."""
    try:
        return validate_night_time(value)
    except (ValueError, TypeError):
        return default


def validate_night_time(value: Any) -> Tuple[int, int, int, int]:
    """Validate a NIGHT_TIME value, raising ValueError when malformed."""
    close_hour, close_minute, open_hour, open_minute = _four_ints(value)
    if not 0 <= close_hour <= 23 or not 0 <= open_hour <= 23:
        raise ValueError("hours must be between 0 and 23")
    if not 0 <= close_minute <= 59 or not 0 <= open_minute <= 59:
        raise ValueError("minutes must be between 0 and 59")
    return close_hour, close_minute, open_hour, open_minute
