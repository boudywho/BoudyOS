# Ultroid - UserBot
# Copyright (C) 2021-2026 TeamUltroid
#
# This file is a part of < https://github.com/TeamUltroid/Ultroid/ >
# PLease read the GNU Affero General Public License in
# <https://www.github.com/TeamUltroid/Ultroid/blob/main/LICENSE/>.
"""
✘ Commands Available -

•`{i}glitch <reply to media>`
    gives a glitchy gif.
"""
import os

from pyUltroid.security.subprocess import run_exec
from pyUltroid.security.paths import cli_path

from . import bash, get_string, mediainfo, ultroid_cmd


@ultroid_cmd(pattern="glitch$")
async def _(e):
    try:
        import glitch_me  # ignore :pylint
    except ModuleNotFoundError:
        return await e.eor(
            "`glitch_me is not installed. Enable the experimental dependency "
            "group during deployment.`"
        )
    reply = await e.get_reply_message()
    if not reply or not reply.media:
        return await e.eor(get_string("cvt_3"))
    xx = await e.eor(get_string("glitch_1"))
    wut = mediainfo(reply.media)
    if wut.startswith(("pic", "sticker")):
        ok = await reply.download_media()
    elif reply.document and reply.document.thumbs:
        ok = await reply.download_media(thumb=-1)
    else:
        return await xx.eor(get_string("com_4"))
    result = await run_exec(
        [
            "glitch_me", "gif", "--line_count", "200", "-f", "10", "-d", "50",
            cli_path(ok), "ult.gif",
        ],
        timeout=300,
    )
    if not result.ok:
        return await xx.edit("`glitch conversion failed.`")
    await e.reply(file="ult.gif", force_document=False)
    await xx.delete()
    os.remove(ok)
    os.remove("ult.gif")
