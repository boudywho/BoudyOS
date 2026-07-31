# Ultroid - UserBot
# Copyright (C) 2021-2026 TeamUltroid
#
# This file is a part of < https://github.com/TeamUltroid/Ultroid/ >
# PLease read the GNU Affero General Public License in
# <https://github.com/TeamUltroid/pyUltroid/blob/main/LICENSE>.

from . import *


def main():
    import os
    import sys
    import time

    from .fns.helper import bash, time_formatter, updater
    from .paths import SOURCE_ROOT
    from .startup.funcs import (
        WasItRestart,
        autopilot,
        customize,
        keep_redis_alive,
        plug,
        ready,
        startup_stuff,
    )
    from .startup.loader import load_other_plugins

    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
    except ImportError:
        AsyncIOScheduler = None

    # Compatibility setting now performs a check only. Deployment is external.
    if (
        udB.get_key("UPDATE_ON_RESTART")
        and (SOURCE_ROOT / ".git").is_dir()
        and ultroid_bot.run_in_loop(updater())
    ):
        LOGS.warning(
            "A BoudyOS update is available. UPDATE_ON_RESTART no longer mutates "
            "the checkout; use the documented deployment helper."
        )

    ultroid_bot.run_in_loop(startup_stuff())

    ultroid_bot.me.phone = None

    if not ultroid_bot.me.bot:
        udB.set_key("OWNER_ID", ultroid_bot.uid)

    LOGS.info("Initialising...")

    ultroid_bot.run_in_loop(autopilot())
    ultroid_bot.loop.create_task(keep_redis_alive())

    pmbot = udB.get_key("PMBOT")
    manager = udB.get_key("MANAGER")
    addons = udB.get_key("ADDONS") or Var.ADDONS
    vcbot = udB.get_key("VCBOT") or Var.VCBOT
    if HOSTED_ON == "okteto":
        vcbot = False

    if (HOSTED_ON == "termux" or udB.get_key("LITE_DEPLOY")) and udB.get_key(
        "EXCLUDE_OFFICIAL"
    ) is None:
        _plugins = "autocorrect autopic audiotools compressor forcesubscribe fedutils gdrive glitch instagram nsfwfilter nightmode pdftools profanityfilter writer youtube"
        udB.set_key("EXCLUDE_OFFICIAL", _plugins)

    load_other_plugins(addons=addons, pmbot=pmbot, manager=manager, vcbot=vcbot)

    suc_msg = """
            ----------------------------------------------------------------------
                BoudyOS is ready: https://github.com/boudywho/BoudyOS
            ----------------------------------------------------------------------
    """

    # for channel plugins
    plugin_channels = udB.get_key("PLUGIN_CHANNEL")

    # Customize Ultroid Assistant...
    ultroid_bot.run_in_loop(customize())

    # Load Addons from Plugin Channels.
    if plugin_channels:
        ultroid_bot.run_in_loop(plug(plugin_channels))

    # Send/Ignore Deploy Message..
    if not udB.get_key("LOG_OFF"):
        ultroid_bot.run_in_loop(ready())

    # Operational readiness is unconditional and independent of log delivery.
    from .security.status import mark_ready, readiness_heartbeat

    ready_path = os.environ.get("BOUDYOS_READY_FILE", "")
    if ready_path:
        try:
            mark_ready(ready_path)
        except (OSError, ValueError) as exc:
            LOGS.warning("Readiness marker was not written: %s", exc)
        ultroid_bot.loop.create_task(readiness_heartbeat(ready_path))

    # Edit Restarting Message (if It's restarting)
    ultroid_bot.run_in_loop(WasItRestart(udB))

    try:
        udB.re_cache()
    except BaseException:
        pass

    LOGS.info(
        f"BoudyOS started in {time_formatter((time.time() - start_time)*1000)}"
    )
    LOGS.info(suc_msg)


if __name__ == "__main__":
    main()

    asst.run()
