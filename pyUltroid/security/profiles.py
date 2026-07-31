"""Backward-compatible official plugin profiles."""

from dataclasses import dataclass
from typing import FrozenSet, Iterable, Optional, Set, Tuple


PROFILE_PLUGINS = {
    "core": frozenset(
        (
            "_chatactions", "_help", "_inline", "_ultroid", "_userlogs", "_wspr",
            "afk", "asstcmd", "bot", "button", "calculator", "chats", "core",
            "database", "downloadupload", "extra", "filter", "fontgen",
            "greetings", "misc", "notes", "other", "pmpermit", "polls",
            "profile", "sudo", "tools", "usage", "utilities", "variables",
            "warn",
        )
    ),
    "media": frozenset(
        (
            "audiotools", "beautify", "compressor", "converter", "fileshare",
            "giftools", "imagetools", "mediatools", "pdftools", "qrcode",
            "resize", "search", "stickertools", "unsplash", "videotools",
            "webupload", "words", "writer", "youtube", "ziptools",
        )
    ),
    "admin": frozenset(
        (
            "admintools", "antiflood", "autoban", "blacklist", "broadcast",
            "channelhacks", "forcesubscribe", "globaltools", "locks", "mute",
            "nightmode", "nsfwfilter", "profanityfilter", "vctools",
        )
    ),
    "automation": frozenset(
        (
            "autopic", "cleanaction", "delayspam", "echo", "fakeaction",
            "schedulemsg", "snips", "tag",
        )
    ),
    "developer": frozenset(("devtools", "glitch", "specialtools")),
    "experimental": frozenset(
        ("aiwrapper", "chatbot", "gdrive", "logo", "stories", "twitter", "weather")
    ),
}
DEFAULT_NEW_PROFILES = ("core", "media")
PROFILE_POLICY_NEW = "new-safe-v1"
PROFILE_POLICY_LEGACY = "legacy-all-v1"
ASSISTANT_PROFILE_PLUGINS = {"games": "experimental"}


@dataclass(frozen=True)
class ProfileSelection:
    names: Tuple[str, ...]
    include: FrozenSet[str]
    legacy_all: bool = False


def resolve_profiles(
    value: Optional[str],
    *,
    existing_install: Optional[bool] = None,
    policy_marker: Optional[str] = None,
) -> ProfileSelection:
    """Resolve profiles without coupling upgrade behavior to startup notifications.

    ``existing_install`` remains accepted for upstream callers. New BoudyOS
    provisioning writes ``new-safe-v1`` explicitly; an unset marker fails
    toward legacy-all so upgrades never lose commands.
    """
    if not value:
        preserve_legacy = (
            existing_install is True
            or (existing_install is None and policy_marker != PROFILE_POLICY_NEW)
        )
        if preserve_legacy:
            return ProfileSelection(("legacy-all",), frozenset(), True)
        names = DEFAULT_NEW_PROFILES
    else:
        names = tuple(
            dict.fromkeys(item.strip().lower() for item in value.split(",") if item.strip())
        )
        unknown = set(names).difference(PROFILE_PLUGINS)
        if unknown:
            raise ValueError("unknown plugin profile: " + ", ".join(sorted(unknown)))
    included: Set[str] = set()
    for name in names:
        included.update(PROFILE_PLUGINS[name])
    return ProfileSelection(tuple(names), frozenset(included))


def excluded_for_profiles(
    all_plugin_names: Iterable[str], selection: ProfileSelection
) -> FrozenSet[str]:
    if selection.legacy_all:
        return frozenset()
    return frozenset(set(all_plugin_names).difference(selection.include))
