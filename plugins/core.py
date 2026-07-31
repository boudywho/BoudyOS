# Ultroid - UserBot
# Copyright (C) 2021-2026 TeamUltroid
#
# This file is a part of < https://github.com/TeamUltroid/Ultroid/ >
# PLease read the GNU Affero General Public License in
# <https://www.github.com/TeamUltroid/Ultroid/blob/main/LICENSE/>.


from . import get_help

__doc__ = get_help("help_core")


import asyncio
import os
from pathlib import Path

from pyUltroid.startup.loader import load_addons
from pyUltroid.security.addons import (
    AddonInstallError,
    atomic_install,
    download_https,
    install_legacy_untrusted,
    load_registry,
)
from pyUltroid.security.settings import event_is_owner, setting_enabled
from pyUltroid.security.paths import UnsafePathError, safe_basename
from pyUltroid.paths import OFFICIAL_PLUGINS, TRUSTED_ADDON_REGISTRY

from . import (
    LOGS,
    eod,
    get_string,
    safeinstall,
    udB,
    ultroid_bot,
    ultroid_cmd,
    un_plug,
)


@ultroid_cmd(pattern="install", owner_only=True)
async def install(event):
    if not setting_enabled(udB, "ALLOW_UNTRUSTED_PLUGINS"):
        return await event.eor(
            "`Attachment installation is disabled. Review SECURITY.md and set "
            "ALLOW_UNTRUSTED_PLUGINS=true to accept in-process code risk.`"
        )
    await safeinstall(event)


@ultroid_cmd(
    pattern=r"unload( (.*)|$)",
    owner_only=True,
)
async def unload(event):
    shortname = event.pattern_match.group(1).strip()
    if not shortname:
        await event.eor(get_string("core_9"))
        return
    lsd = os.listdir("addons")
    zym = f"{shortname}.py"
    if zym in lsd:
        try:
            un_plug(shortname)
            await event.eor(f"**Unloaded** `{shortname}` **Successfully.**", time=3)
        except Exception as ex:
            LOGS.exception(ex)
            return await event.eor(str(ex))
    elif zym in os.listdir(OFFICIAL_PLUGINS):
        return await event.eor(get_string("core_11"), time=3)
    else:
        await event.eor(f"**No Plugin Named** `{shortname}`", time=3)


@ultroid_cmd(
    pattern=r"uninstall( (.*)|$)",
    owner_only=True,
)
async def uninstall(event):
    shortname = event.pattern_match.group(1).strip()
    if not shortname:
        await event.eor(get_string("core_13"))
        return
    lsd = os.listdir("addons")
    zym = f"{shortname}.py"
    if zym in lsd:
        try:
            un_plug(shortname)
            await event.eor(f"**Uninstalled** `{shortname}` **successfully.**", time=3)
            os.remove(f"addons/{shortname}.py")
        except Exception as ex:
            return await event.eor(str(ex))
    elif zym in os.listdir(OFFICIAL_PLUGINS):
        return await event.eor(get_string("core_15"), time=3)
    else:
        return await event.eor(f"**No Plugin Named** `{shortname}`", time=3)


@ultroid_cmd(
    pattern=r"load( (.*)|$)",
    owner_only=True,
)
async def load(event):
    if not setting_enabled(udB, "ALLOW_UNTRUSTED_PLUGINS"):
        return await event.eor(
            "`Local untrusted add-on loading is disabled. Review SECURITY.md "
            "before enabling ALLOW_UNTRUSTED_PLUGINS.`"
        )
    shortname = event.pattern_match.group(1).strip()
    if not shortname:
        await event.eor(get_string("core_16"))
        return
    try:
        filename = safe_basename(f"{shortname}.py", ".py")
    except UnsafePathError:
        return await event.eor("`Unsafe add-on filename.`", time=3)
    try:
        try:
            un_plug(shortname)
        except BaseException:
            pass
        load_addons(str(Path("addons") / filename))
        await event.eor(get_string("core_17").format(shortname), time=3)
    except Exception as e:
        LOGS.exception(e)
        await eod(
            event,
            get_string("core_18").format(shortname, e),
            time=3,
        )


@ultroid_cmd(pattern="getaddons( (.*)|$)", owner_only=True)
async def get_the_addons_lol(event):
    request = event.pattern_match.group(1).strip()
    xx = await event.eor(get_string("com_1"))
    registry_path = TRUSTED_ADDON_REGISTRY
    try:
        registry = load_registry(registry_path)
    except AddonInstallError as exc:
        LOGS.error("Trusted add-on registry error: %s", exc)
        return await xx.edit("`The trusted add-on registry is invalid.`")

    if not request:
        names = ", ".join(sorted(name[:-3] for name in registry)) or "none bundled"
        return await xx.edit(
            "**Safe add-on workflow**\n\n"
            f"Trusted registry entries: `{names}`\n"
            f"Install with `{event.text.split()[0]} trusted <name>`.\n\n"
            "Trusted add-ons are hash-verified and pinned, but still execute "
            "in-process with access to your Telegram account. Raw URL execution "
            "is disabled by default; local loading is owner-only and requires "
            "the explicit untrusted-code opt-in."
        )

    parts = request.split()
    mode = parts[0].lower()
    if not event_is_owner(event, udB, ultroid_bot):
        return await xx.edit("`Add-on installation is owner-only.`")

    try:
        if mode == "trusted" and len(parts) == 2:
            name = parts[1]
            if not name.endswith(".py"):
                name += ".py"
            entry = registry.get(name)
            if entry is None:
                return await xx.edit("`That add-on is not in the trusted registry.`")
            await xx.edit("`Downloading and verifying the trusted add-on...`")
            content = await asyncio.to_thread(download_https, entry.source_url)
            destination = Path("addons") / entry.name
            prior = destination.read_bytes() if destination.exists() else None
            installed = await asyncio.to_thread(
                atomic_install,
                content,
                entry.name,
                Path("addons"),
                expected_sha256=entry.sha256,
            )
            try:
                load_addons(str(installed))
            except Exception:
                if prior is None:
                    installed.unlink(missing_ok=True)
                else:
                    atomic_install(prior, entry.name, Path("addons"))
                raise
            return await xx.eor(
                get_string("core_17").format(installed.stem), time=15
            )
        if mode == "raw" and len(parts) == 3 and parts[2] == "CONFIRM":
            if not setting_enabled(udB, "ALLOW_UNTRUSTED_PLUGINS"):
                return await xx.edit(
                    "`Raw URL add-ons are disabled. See SECURITY.md before enabling "
                    "ALLOW_UNTRUSTED_PLUGINS.`"
                )
            await xx.edit(
                "`Installing explicitly confirmed UNTRUSTED code. It will have "
                "in-process account access...`"
            )
            raw_name = Path(parts[1].split("?", 1)[0]).name
            raw_destination = Path("addons") / raw_name
            prior = (
                raw_destination.read_bytes() if raw_destination.exists() else None
            )
            installed = await asyncio.to_thread(
                install_legacy_untrusted, parts[1], Path("addons")
            )
            try:
                load_addons(str(installed))
            except Exception:
                if prior is None:
                    installed.unlink(missing_ok=True)
                else:
                    atomic_install(prior, installed.name, Path("addons"))
                raise
            return await xx.eor(
                get_string("core_17").format(installed.stem), time=15
            )
    except AddonInstallError as exc:
        LOGS.warning("Add-on installation refused: %s", exc)
        return await xx.edit(f"`Add-on installation refused: {exc}`")
    except Exception:
        LOGS.exception("Add-on installation failed")
        return await xx.edit(
            "`Add-on installation failed; any previous trusted version was preserved.`"
        )

    return await xx.edit(
        "`Use getaddons trusted <name>. Legacy raw URLs require "
        "getaddons raw <https-url.py> CONFIRM and an explicit security opt-in.`"
    )
