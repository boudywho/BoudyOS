"""Owner-only boot controls for plugins shipped in immutable BoudyOS source."""

import re

from decouple import config

from pyUltroid.paths import OFFICIAL_PLUGINS
from pyUltroid.security.profiles import resolve_profiles

from . import udB, ultroid_cmd


def _official_names():
    return sorted(
        path.stem
        for path in OFFICIAL_PLUGINS.glob("*.py")
        if not path.is_symlink()
        and path.is_file()
        and not path.name.startswith("_")
        and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", path.stem)
    )


def _setting(key):
    # Match startup's DB-over-environment precedence.
    return udB.get_key(key) or config(key, default=None)


def _split_list(value):
    if isinstance(value, list):
        return [str(item) for item in value]
    return str(value).split() if value else []


def _join_list(items):
    return " ".join(sorted(set(items)))


def _plugin_name(event):
    name = (event.pattern_match.group(1) or "").strip().removesuffix(".py")
    return name if name in _official_names() else None


@ultroid_cmd(pattern="plugins$", owner_only=True)
async def list_plugins(event):
    names = _official_names()
    # Do not reflect arbitrary DB contents into chat; show inventory-filtered names.
    exclude = set(_split_list(_setting("EXCLUDE_OFFICIAL"))).intersection(names)
    include = set(_split_list(_setting("INCLUDE_ONLY"))).intersection(names)
    await event.eor(
        f"**BoudyOS official inventory:** `{len(names)}`\n"
        f"**EXCLUDE_OFFICIAL:** `{_join_list(exclude) or '—'}`\n"
        f"**INCLUDE_ONLY:** `{_join_list(include) or '—'}`\n"
        "Toggle: `.disableplugin name` · `.enableplugin name`\n"
        "Profiles also apply unless INCLUDE_ONLY is set. Restart required."
    )


@ultroid_cmd(pattern="disableplugin( (.*)|$)", owner_only=True)
async def disable_plugin(event):
    name = _plugin_name(event)
    if name is None:
        return await event.eor("Provide a valid shipped official plugin name.")
    exclude = _split_list(_setting("EXCLUDE_OFFICIAL"))
    udB.set_key("EXCLUDE_OFFICIAL", _join_list(exclude + [name]))
    # Keep INCLUDE_ONLY intact: deleting its last entry would broaden boot selection.
    await event.eor(f"**Disabled** `{name}` for the next boot. Restart to unload it.")


@ultroid_cmd(pattern="enableplugin( (.*)|$)", owner_only=True)
async def enable_plugin(event):
    name = _plugin_name(event)
    if name is None:
        return await event.eor("Provide a valid shipped official plugin name.")
    exclude = [item for item in _split_list(_setting("EXCLUDE_OFFICIAL")) if item != name]
    if exclude:
        udB.set_key("EXCLUDE_OFFICIAL", _join_list(exclude))
    else:
        # Whitespace is a truthy override whose loader .split() is empty;
        # deleting the key would resurrect an environment exclusion.
        udB.set_key("EXCLUDE_OFFICIAL", " ")
    include = _split_list(_setting("INCLUDE_ONLY"))
    if include:
        udB.set_key("INCLUDE_ONLY", _join_list(include + [name]))
    else:
        try:
            selection = resolve_profiles(
                _setting("PLUGIN_PROFILES"),
                policy_marker=_setting("PLUGIN_PROFILE_POLICY"),
            )
        except ValueError:
            return await event.eor(
                "Exclusion removed, but plugin profiles are invalid. Fix profiles before restarting."
            )
        if not selection.legacy_all and name not in selection.include:
            return await event.eor(
                f"Exclusion removed for `{name}`, but the selected profiles still omit it. "
                "Select its profile or set INCLUDE_ONLY before restarting."
            )
    await event.eor(f"**Enabled** `{name}` for the next boot. Restart to load it.")
