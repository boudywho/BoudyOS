"""Compatibility helpers for security-sensitive opt-in settings."""

import os
from typing import Any

from .parsing import parse_bool


def setting_enabled(database: Any, key: str) -> bool:
    """Read DB first, then env, while defaulting to disabled."""
    value = database.get_key(key) if database is not None else None
    if value is None:
        value = os.environ.get(key)
    return parse_bool(value, default=False)


def event_is_owner(event: Any, database: Any, client: Any) -> bool:
    """Outgoing commands and the configured owner are the only owner identity."""
    owner_id = database.get_key("OWNER_ID") if database is not None else None
    owner_id = owner_id or getattr(client, "uid", None)
    return bool(getattr(event, "out", False) or event.sender_id == owner_id)
