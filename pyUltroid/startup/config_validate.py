"""Offline credential/remote database validation. Diagnostics never echo values."""
from __future__ import annotations

import os
import re
import sys
from urllib.parse import urlsplit

_API_HINT = "Get your own API_ID / API_HASH from https://my.telegram.org."
_DEFAULT_HASH = "eb06d4abfb49dc3eeb1aeb98ae0f581e"


def _truthy(value):
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def strict_config():
    return _truthy(os.getenv("ULTROID_STRICT_CONFIG"))


def auto_pip_enabled():
    """Compatibility API: runtime dependency installation is prohibited."""
    return False


def validate_redis_uri(uri):
    if not uri:
        return []
    raw = str(uri).strip()
    try:
        parsed = urlsplit("//" + raw)
        valid = (not any(char.isspace() for char in raw) and "://" not in raw
                 and parsed.hostname and parsed.port is not None
                 and 1 <= parsed.port <= 65535 and not parsed.username
                 and not parsed.password and not parsed.path and not parsed.query
                 and not parsed.fragment)
    except ValueError:
        valid = False
    return [] if valid else ["Invalid config: REDIS_URI — use host:port (port 1–65535), without credentials or a scheme."]


def _validate_url(value, name, schemes):
    if not value:
        return []
    try:
        raw = str(value).strip()
        parsed = urlsplit(raw)
        valid = (parsed.scheme in schemes and parsed.hostname
                 and not any(char.isspace() for char in raw)
                 and (parsed.port is None or 1 <= parsed.port <= 65535))
        if parsed.scheme == "mongodb+srv" and parsed.port is not None:
            valid = False
    except ValueError:
        valid = False
    return [] if valid else [f"Invalid config: {name} — use a valid provider URI with a hostname and supported scheme."]


def validate_mongo_uri(uri):
    return _validate_url(uri, "MONGO_URI", {"mongodb", "mongodb+srv"})


def validate_database_url(url):
    return _validate_url(url, "DATABASE_URL", {"postgres", "postgresql"})


def collect_config_issues(Var):
    errors, warnings = [], []
    api_id = getattr(Var, "API_ID", None)
    api_hash = getattr(Var, "API_HASH", None)
    try:
        valid_id = not isinstance(api_id, bool) and int(api_id) > 0 and str(api_id).isdigit()
    except (ValueError, TypeError):
        valid_id = False
    if not valid_id:
        errors.append("Invalid or missing config: API_ID — a positive integer is required. " + _API_HINT)
    if not api_hash or not re.fullmatch(r"[a-fA-F0-9]{32}", str(api_hash)):
        errors.append("Invalid or missing config: API_HASH — 32 hexadecimal characters are required. " + _API_HINT)
    if str(api_id) == "6" or str(api_hash).lower() == _DEFAULT_HASH:
        errors.append("Invalid config: API_ID / API_HASH — shared Telegram Android defaults are not allowed. " + _API_HINT)

    bot_mode = _truthy(getattr(Var, "BOTMODE", os.getenv("BOTMODE")))
    if bot_mode:
        if not getattr(Var, "BOT_TOKEN", None):
            errors.append("Missing required config: BOT_TOKEN for BOTMODE.")
    elif not getattr(Var, "SESSION", None):
        errors.append("Missing required config: SESSION — generate one with bash sessiongen.")

    redis_uri = getattr(Var, "REDIS_URI", None)
    redis_host = getattr(Var, "REDISHOST", None)
    errors.extend(validate_redis_uri(redis_uri))
    if redis_host and not redis_uri:
        port = getattr(Var, "REDISPORT", None) or 6379
        errors.extend(validate_redis_uri(f"{redis_host}:{port}"))
    errors.extend(validate_mongo_uri(getattr(Var, "MONGO_URI", None)))
    errors.extend(validate_database_url(getattr(Var, "DATABASE_URL", None)))
    if not any((redis_uri, redis_host, getattr(Var, "MONGO_URI", None), getattr(Var, "DATABASE_URL", None))):
        message = "No remote database configured; LocalDB is suitable for trials, not production."
        if _truthy(getattr(Var, "STRICT_CONFIG", getattr(Var, "ULTROID_STRICT_CONFIG", os.getenv("ULTROID_STRICT_CONFIG")))):
            errors.append(message + " Strict mode requires a remote DB.")
        else:
            warnings.append(message)
    return errors, warnings


def validate_config_or_exit(Var, logger=None):
    import logging

    logger = logger or logging.getLogger("pyUltroid")
    errors, warnings = collect_config_issues(Var)
    for warning in warnings:
        logger.warning("[config] %s", warning)
    for error in errors:
        logger.error("[config] %s", error)
    if errors:
        raise SystemExit(1)


def pip_install_hint(packages):
    return ("Missing Python dependencies; install them outside the running bot using "
            "requirements.txt and the matching constraints/py310.txt or constraints/py313.txt. "
            "Optional drivers: requirements/database.txt; media: requirements/media.txt.")
