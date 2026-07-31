# Ultroid - UserBot
# Copyright (C) 2021-2026 TeamUltroid
#
# This file is a part of < https://github.com/TeamUltroid/Ultroid/ >
# PLease read the GNU Affero General Public License in
# <https://www.github.com/TeamUltroid/Ultroid/blob/main/LICENSE/>.

from . import get_help

__doc__ = get_help("help_compressor")


import os
import re
import time
from datetime import datetime as dt
from pathlib import Path

from telethon.errors.rpcerrorlist import MessageNotModifiedError
from telethon.tl.types import DocumentAttributeVideo

from pyUltroid.fns.tools import metadata
from pyUltroid.security.subprocess import run_exec
from pyUltroid.security.paths import cli_path

from . import (
    ULTConfig,
    bash,
    downloader,
    get_string,
    humanbytes,
    math,
    mediainfo,
    time_formatter,
    ultroid_cmd,
    uploader,
)


@ultroid_cmd(pattern="compress( (.*)|$)")
async def _(e):
    cr = e.pattern_match.group(1).strip()
    crf = 27
    to_stream = False
    if cr:
        k = e.text.split()
        if len(k) == 2:
            crf = int(k[1]) if k[1].isdigit() else 27
        elif len(k) > 2:
            crf = int(k[1]) if k[1].isdigit() else 27
            to_stream = "stream" in k[2]
    vido = await e.get_reply_message()
    if vido and vido.media and "video" in mediainfo(vido.media):
        if hasattr(vido.media, "document"):
            vfile = vido.media.document
            name = vido.file.name
        else:
            vfile = vido.media
            name = ""
        if not name:
            name = "video_" + dt.now().isoformat("_", "seconds") + ".mp4"
        xxx = await e.eor(get_string("audiotools_5"))
        c_time = time.time()
        file = await downloader(
            f"resources/downloads/{name}",
            vfile,
            xxx,
            c_time,
            f"Downloading {name}...",
        )

        o_size = os.path.getsize(file.name)
        d_time = time.time()
        diff = time_formatter((d_time - c_time) * 1000)
        file_name = (file.name).split("/")[-1]
        out = file_name.replace(file_name.split(".")[-1], "compressed.mkv")
        await xxx.edit(
            f"`Downloaded {file.name} of {humanbytes(o_size)} in {diff}.\nNow Compressing...`"
        )
        probe = await run_exec(
            [
                "ffprobe", "-v", "error", "-count_frames", "-select_streams",
                "v:0", "-show_entries", "stream=nb_read_frames", "-of",
                "default=nokey=1:noprint_wrappers=1", cli_path(file.name),
            ],
            timeout=120,
        )
        if not probe.ok:
            return await xxx.edit("`ffprobe could not inspect this video.`")
        total_frames = probe.stdout.splitlines()[0]
        progress = f"progress-{c_time}.txt"
        with open(progress, "w"):
            pass
        async def update_progress():
            try:
                text = Path(progress).read_text("utf-8")
                frames = re.findall(r"frame=(\d+)", text)
                sizes = re.findall(r"total_size=(\d+)", text)
                elapsed = int(frames[-1])
                size = int(sizes[-1])
                total = int(total_frames)
                percent = min(100.0, elapsed * 100 / total)
                speed = elapsed / max(time.time() - d_time, 0.1)
                eta = ((total - elapsed) / speed) * 1000 if speed else 0
                await xxx.edit(
                    f"`Compressing {file_name} at {crf} CRF.\n"
                    f"{percent:.2f}% · {humanbytes(size)} · "
                    f"~{time_formatter(eta)}`"
                )
            except (OSError, ValueError, IndexError, ZeroDivisionError, MessageNotModifiedError):
                pass

        try:
            result = await run_exec(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-progress",
                    cli_path(progress), "-i", cli_path(file.name), "-preset",
                    "ultrafast", "-vcodec", "libx265", "-crf", str(crf),
                    "-c:a", "copy", "-y", cli_path(out),
                ],
                timeout=1800,
                progress_callback=update_progress,
                progress_interval=3,
            )
        finally:
            Path(progress).unlink(missing_ok=True)
        if not result.ok:
            Path(file.name).unlink(missing_ok=True)
            Path(out).unlink(missing_ok=True)
            return await xxx.edit("`ffmpeg compression failed or timed out.`")
        os.remove(file.name)
        c_size = os.path.getsize(out)
        f_time = time.time()
        difff = time_formatter((f_time - d_time) * 1000)
        await xxx.edit(
            f"`Compressed {humanbytes(o_size)} to {humanbytes(c_size)} in {difff}\nTrying to Upload...`"
        )
        differ = 100 - ((c_size / o_size) * 100)
        caption = f"**Original Size: **`{humanbytes(o_size)}`\n"
        caption += f"**Compressed Size: **`{humanbytes(c_size)}`\n"
        caption += f"**Compression Ratio: **`{differ:.2f}%`\n"
        caption += f"\n**Time Taken To Compress: **`{difff}`"
        n_file, _ = await e.client.fast_uploader(
            out, show_progress=True, event=e, message="Uploading...", to_delete=True
        )
        if to_stream:
            data = await metadata(out)
            width = data["width"]
            height = data["height"]
            duration = data["duration"]
            attributes = [
                DocumentAttributeVideo(
                    duration=duration, w=width, h=height, supports_streaming=True
                )
            ]
            await e.client.send_file(
                e.chat_id,
                n_file,
                thumb=ULTConfig.thumb,
                caption=caption,
                attributes=attributes,
                force_document=False,
                reply_to=e.reply_to_msg_id,
            )
        else:
            await e.client.send_file(
                e.chat_id,
                n_file,
                thumb=ULTConfig.thumb,
                caption=caption,
                force_document=True,
                reply_to=e.reply_to_msg_id,
            )
            await xxx.delete()
            os.remove(out)
    else:
        await e.eor(get_string("audiotools_8"), time=5)
