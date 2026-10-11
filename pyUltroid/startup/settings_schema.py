# Ultroid - UserBot
# Copyright (C) 2021-2026 TeamUltroid
#
# This file is a part of < https://github.com/TeamUltroid/Ultroid/ >
# PLease read the GNU Affero General Public License in
# <https://github.com/TeamUltroid/pyUltroid/blob/main/LICENSE>.

"""Known udB keys with types/defaults for setdb validation.

Unknown keys are still allowed (addons/custom). Known keys get type coercion
and clear errors on bad values.
"""

from __future__ import annotations

import ast
from typing import Any

from pyUltroid.security.parsing import parse_bool
from pyUltroid.security.profiles import resolve_profiles

# type -> callable that parses a string into the stored value (or raises ValueError)
_TRUE = {"1", "true", "yes", "on", "y"}
_FALSE = {"0", "false", "no", "off", "n"}


def _as_bool(raw: str) -> bool:
    s = str(raw).strip().lower()
    if s in _TRUE | {"enabled"}:
        return parse_bool("true" if s == "y" else s)
    if s in _FALSE | {"disabled"}:
        return parse_bool("false")
    raise ValueError("expected boolean (true/false, 1/0, yes/no, on/off)")


def _as_int(raw: str) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError) as er:
        raise ValueError("expected integer") from er


def _as_str(raw: str) -> str:
    return str(raw)


def _as_list(raw: str) -> list:
    s = str(raw).strip()
    if not s:
        return []
    # Prefer Python-literal list, else whitespace-separated tokens
    if s.startswith("["):
        try:
            val = ast.literal_eval(s)
        except Exception as er:
            raise ValueError("expected a Python list literal, e.g. [1, 2]") from er
        if not isinstance(val, list):
            raise ValueError("expected a list")
        return val
    return s.split()


def _as_filter(raw: str) -> str:
    items = _as_list(raw)
    if any(not isinstance(item, str) or not item.isidentifier() for item in items):
        raise ValueError("expected space-separated plugin names")
    return " ".join(dict.fromkeys(items))


def _as_profiles(raw: str) -> str:
    value = str(raw).strip()
    if not value:
        raise ValueError("expected comma-separated profile names")
    return ",".join(resolve_profiles(value).names)


def _as_profile_policy(raw: str) -> str:
    value = str(raw).strip()
    if value not in {"new-safe-v1", "legacy-all-v1"}:
        raise ValueError("expected a supported profile policy")
    return value


def _as_addon_mode(raw: str) -> str:
    if str(raw).strip() != "official-only":
        raise ValueError("only official-only is supported; use the trusted registry for addons")
    return "official-only"


def _as_hndlr(raw: str) -> str:
    s = str(raw).strip()
    if not s or len(s) > 5:
        raise ValueError("handler must be 1–5 characters")
    return s


# key -> (type_name, parser, description)
KNOWN_KEYS: dict[str, tuple[str, Any, str]] = {
    # core toggles
    "ADDONS": ("bool", _as_bool, "Load UltroidAddons on boot"),
    "ADDONS_MODE": ("str", _as_addon_mode, "Only official-only; addons require the trusted registry"),
    "ALLOW_UNTRUSTED_PLUGINS": ("bool", _as_bool, "Explicit untrusted plugin opt-in (unsafe)"),
    "ALLOW_DANGEROUS_DEV_EXEC": ("bool", _as_bool, "Owner eval/shell opt-in (unsafe)"),
    "PLUGIN_PROFILES": ("str", _as_profiles, "Comma-separated official plugin profiles"),
    "PLUGIN_PROFILE_POLICY": ("str", _as_profile_policy, "new-safe-v1 or legacy-all-v1"),
    "VCBOT": ("bool", _as_bool, "Load VcBot on boot"),
    "PMBOT": ("bool", _as_bool, "Enable assistant PM bot"),
    "MANAGER": ("bool", _as_bool, "Enable group manager plugins"),
    "BOTMODE": ("bool", _as_bool, "Run in bot-only mode"),
    "DUAL_MODE": ("bool", _as_bool, "Dual user+bot mode"),
    "USER_MODE": ("bool", _as_bool, "User-only mode (no assistant client)"),
    "LITE_DEPLOY": ("bool", _as_bool, "Lite plugin set (Termux-style)"),
    "LOG_OFF": ("bool", _as_bool, "Disable deploy/ready messages"),
    "UPDATE_ON_RESTART": ("bool", _as_bool, "git pull on restart"),
    "DISABLE_AST_PLUGINS": ("bool", _as_bool, "Skip assistant plugins"),
    "SKIP_AUTOPILOT": ("bool", _as_bool, "Do not auto-create LOG_CHANNEL"),
    "SKIP_AUTOBOT": ("bool", _as_bool, "Do not auto-create BOT_TOKEN"),
    "SKIP_AUTOJOIN": ("bool", _as_bool, "Do not join @TheUltroid"),
    "SKIP_ASSISTANT_CUSTOMIZE": ("bool", _as_bool, "Skip BotFather customisation"),
    "PMLOG": ("bool", _as_bool, "Log private messages"),
    # strings / ids
    "HNDLR": ("handler", _as_hndlr, "Command handler prefix"),
    "DUAL_HNDLR": ("handler", _as_hndlr, "Assistant dual handler"),
    "SUDO_HNDLR": ("handler", _as_hndlr, "Sudo handler"),
    "language": ("str", _as_str, "UI language code (en, hi, …)"),
    "BOT_TOKEN": ("str", _as_str, "Assistant bot token"),
    "LOG_CHANNEL": ("int", _as_int, "Log channel/group id"),
    "OWNER_ID": ("int", _as_int, "Owner user id"),
    "TIMEZONE": ("str", _as_str, "IANA timezone name"),
    "ALIVE_TEXT": ("str", _as_str, "Custom alive message"),
    "ALIVE_EMOJI": ("str", _as_str, "Alive emoji"),
    "ALIVE_PIC": ("str", _as_str, "Alive media URL"),
    "CUSTOM_THUMBNAIL": ("str", _as_str, "Thumbnail URL (False to disable)"),
    "ADDONS_URL": ("str", _as_str, "Custom addons git URL"),
    "VC_SESSION": ("str", _as_str, "Separate VC session string"),
    # space-separated / list-like
    "EXCLUDE_OFFICIAL": ("str", _as_filter, "Official plugins to skip (space-separated)"),
    "INCLUDE_ONLY": ("str", _as_filter, "Only load these official plugins"),
    "EXCLUDE_ADDONS": ("str", _as_filter, "Addon plugins to skip"),
    "INCLUDE_ADDONS": ("str", _as_filter, "Only load these addon plugins"),
    "PLUGIN_CHANNEL": ("list", _as_list, "Plugin channel ids/usernames"),
    "SUDOS": ("list", _as_list, "Sudo user ids"),
    "REDIS_KEEPALIVE_INTERVAL": ("int", _as_int, "Redis keepalive seconds"),
}


def coerce_value(key: str, raw: str) -> tuple[Any, str | None]:
    """Return (value, warning_or_None). Raises ValueError on bad known keys."""
    meta = KNOWN_KEYS.get(key)
    if not meta:
        # Unknown key — store as string (legacy behaviour)
        return raw, f"unknown key `{key}` (stored as string; see `{key}` docs or .set keys)"
    _tname, parser, _desc = meta
    return parser(raw), None


def format_keys_help(filter_text: str | None = None) -> str:
    lines = ["**Known DB keys** (type-checked by setdb):\n"]
    items = sorted(KNOWN_KEYS.items())
    if filter_text:
        ft = filter_text.lower()
        items = [(k, v) for k, v in items if ft in k.lower() or ft in v[2].lower()]
    if not items:
        return "No matching known keys."
    for key, (tname, _p, desc) in items:
        lines.append(f"• `{key}` ({tname}) — {desc}")
    lines.append("\nUnknown keys are still accepted as free-form strings.")
    return "\n".join(lines)
