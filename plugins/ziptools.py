# Ultroid - UserBot
# Copyright (C) 2021-2026 TeamUltroid
#
# This file is a part of < https://github.com/TeamUltroid/Ultroid/ >
# PLease read the GNU Affero General Public License in
# <https://www.github.com/TeamUltroid/Ultroid/blob/main/LICENSE/>.
"""
✘ Commands Available

• `{i}zip <reply to file>`
    zip the replied file
    To set password on zip: `{i}zip <password>` reply to file

• `{i}unzip <reply to zip file>`
    unzip the replied file.

• `{i}azip <reply to file>`
   add file to batch for batch upload zip

• `{i}dozip`
   upload batch zip the files u added from `{i}azip`
   To set Password: `{i}dozip <password>`

"""
import os
import shutil
import time
import zipfile
from pathlib import Path

from pyUltroid.security.paths import (
    UnsafePathError,
    cli_path,
    zip_command,
    extract_archive,
    private_workspace,
    resolve_under,
)
from pyUltroid.security.subprocess import run_exec

from . import (
    HNDLR,
    ULTConfig,
    asyncio,
    bash,
    downloader,
    get_all_files,
    get_string,
    ultroid_cmd,
    uploader,
)


@ultroid_cmd(pattern="zip( (.*)|$)")
async def zipp(event):
    reply = await event.get_reply_message()
    t = time.time()
    if not reply:
        await event.eor(get_string("zip_1"))
        return
    xx = await event.eor(get_string("com_1"))
    if reply.media:
        if hasattr(reply.media, "document"):
            file = reply.media.document
            image = await downloader(
                reply.file.name, reply.media.document, xx, t, get_string("com_5")
            )
            file = image.name
        else:
            file = await event.download_media(reply)
    inp = file.replace(file.split(".")[-1], "zip")
    if event.pattern_match.group(1).strip():
        result = await run_exec(
            zip_command(file, inp, event.pattern_match.group(1).strip()),
            timeout=300,
        )
    else:
        with zipfile.ZipFile(inp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(file, arcname=Path(file).name)
        result = None
    if result is not None and not result.ok:
        return await xx.edit("`Archive creation failed.`")
    k = time.time()
    n_file, _ = await event.client.fast_uploader(
        inp, show_progress=True, event=event, message="Uploading...", to_delete=True
    )
    await event.client.send_file(
        event.chat_id,
        n_file,
        force_document=True,
        thumb=ULTConfig.thumb,
        caption=f"`{n_file.name}`",
        reply_to=reply,
    )
    os.remove(inp)
    os.remove(file)
    await xx.delete()


@ultroid_cmd(pattern="unzip( (.*)|$)")
async def unzipp(event):
    reply = await event.get_reply_message()
    file = event.pattern_match.group(1).strip()
    t = time.time()
    if not ((reply and reply.media) or file):
        await event.eor(get_string("zip_1"))
        return
    xx = await event.eor(get_string("com_1"))
    if reply.media:
        if not hasattr(reply.media, "document"):
            return await xx.edit(get_string("zip_3"))
        file = reply.media.document
        if not reply.file.name.lower().endswith((".zip", ".tar", ".tar.gz", ".tgz")):
            return await xx.edit(get_string("zip_3"))
        image = await downloader(
            reply.file.name, reply.media.document, xx, t, get_string("com_5")
        )
        file = image.name
    try:
        with private_workspace(Path.cwd(), ".boudyos-unzip-") as command_dir:
            archive_path = resolve_under(Path.cwd(), file, must_exist=True)
            extracted = extract_archive(
                archive_path,
                command_dir.name + "/content",
                workspace=Path.cwd(),
            )
            for x in get_all_files(str(extracted)):
                n_file, _ = await event.client.fast_uploader(
                    x,
                    show_progress=True,
                    event=event,
                    message="Uploading...",
                    to_delete=True,
                )
                await event.client.send_file(
                    event.chat_id,
                    n_file,
                    force_document=True,
                    thumb=ULTConfig.thumb,
                    caption=f"`{n_file.name}`",
                )
    except (UnsafePathError, OSError, ValueError, zipfile.BadZipFile):
        return await xx.edit(
            "`Archive rejected: unsupported, corrupt, encrypted, or unsafe paths.`"
        )
    finally:
        if reply and reply.media:
            Path(file).unlink(missing_ok=True)
    await xx.delete()


@ultroid_cmd(pattern="addzip$")
async def azipp(event):
    reply = await event.get_reply_message()
    t = time.time()
    if not (reply and reply.media):
        await event.eor(get_string("zip_1"))
        return
    xx = await event.eor(get_string("com_1"))
    if not os.path.isdir("zip"):
        os.mkdir("zip")
    if reply.media:
        if hasattr(reply.media, "document"):
            file = reply.media.document
            image = await downloader(
                f"zip/{reply.file.name}",
                reply.media.document,
                xx,
                t,
                get_string("com_5"),
            )

            file = image.name
        else:
            file = await event.download_media(reply.media, "zip/")
    await xx.edit(
        f"Downloaded `{file}` succesfully\nNow Reply To Other Files To Add And Zip all at once"
    )


@ultroid_cmd(pattern="dozip( (.*)|$)")
async def do_zip(event):
    if not os.path.isdir("zip"):
        return await event.eor(get_string("zip_2").format(HNDLR))
    xx = await event.eor(get_string("com_1"))
    if event.pattern_match.group(1).strip():
        result = await run_exec(
            zip_command("zip", "ultroid.zip", event.pattern_match.group(1).strip()),
            timeout=300,
        )
        if not result.ok:
            return await xx.edit("`Archive creation failed.`")
    else:
        with zipfile.ZipFile(
            "ultroid.zip", "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for path in Path("zip").rglob("*"):
                if path.is_file() and not path.is_symlink():
                    archive.write(path, arcname=path.relative_to("zip"))
    k = time.time()
    xxx = await uploader("ultroid.zip", "ultroid.zip", k, xx, get_string("com_6"))
    await event.client.send_file(
        event.chat_id,
        xxx,
        force_document=True,
        thumb=ULTConfig.thumb,
    )
    shutil.rmtree("zip", ignore_errors=True)
    os.remove("ultroid.zip")
    await xx.delete()
