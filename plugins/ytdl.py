# Ultroid - UserBot
# Copyright (C) 2021-2026 TeamUltroid
#
# This file is a part of < https://github.com/TeamUltroid/Ultroid/ >
# PLease read the GNU Affero General Public License in
# <https://www.gnu.org/licenses/agpl-3.0.html>.
"""
✘ Commands Available -

• `{i}yt <URL>`
   Download a URL with quality and timestamp controls.

• `{i}ytcancel`
   Cancel the pending or active download in this chat.
"""

import asyncio
import os
import re
import time
from pathlib import Path

from telethon import Button, events
from telethon.tl.types import DocumentAttributeAudio, DocumentAttributeVideo

from pyUltroid.fns.tools import set_attributes
from pyUltroid.fns.ytdl_core import (
    DownloadCancelled,
    RequestStore,
    TimestampError,
    URLValidationError,
    YTDLPService,
    build_format_choices,
    extract_media_url,
    is_command_message,
    parse_timestamp_ranges,
)
from pyUltroid.fns.ytdl_core.ffmpeg import clip_media
from pyUltroid.security.paths import private_workspace

from . import HNDLR, LOGS, asst, callback, humanbytes, udB, ultroid_bot, ultroid_cmd


_REQUESTS = RequestStore(ttl=15 * 60, max_entries=64)
_SERVICE = YTDLPService()
_JOBS = {}
_JOB_LIMIT = asyncio.Semaphore(2)
_WORK_ROOT = Path("resources/downloads")


def _clean(value, limit=300):
    return str(value or "Unknown").replace("`", "'")[:limit]


def _duration(value):
    total = int(value or 0)
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:d}:{seconds:02d}"


def _choices(state):
    return {item.key: item for item in build_format_choices(state.metadata)}


def _quality_screen(state):
    choices = list(_choices(state).values())
    buttons = []
    for index in range(0, len(choices), 2):
        buttons.append(
            [
                Button.inline(item.label, data=f"ytdl:q:{state.token}:{item.key}")
                for item in choices[index : index + 2]
            ]
        )
    buttons.append([Button.inline("Cancel", data=f"ytdl:x:{state.token}:cancel")])
    title = _clean(state.metadata.get("title"))
    text = (
        f"**YouTube / media download**\n\n`{title}`\n"
        f"Duration: `{_duration(state.metadata.get('duration'))}`\n\n"
        "Choose quality."
    )
    thumbnail = state.metadata.get("thumbnail")
    if isinstance(thumbnail, str):
        try:
            if extract_media_url(thumbnail) == thumbnail:
                text += f"\n[Thumbnail]({thumbnail})"
        except URLValidationError:
            pass
    return text, buttons


def _timestamp_screen(state):
    token = state.token
    return (
        "Choose the portion to download. Custom ranges support `SS`, `MM:SS`, "
        "`HH:MM:SS`, open ends, and comma-separated ranges.",
        [
            [
                Button.inline("Full video", data=f"ytdl:t:{token}:full"),
                Button.inline("Custom range", data=f"ytdl:t:{token}:custom"),
            ],
            [
                Button.inline("First 60s", data=f"ytdl:t:{token}:first60"),
                Button.inline("Last 30s", data=f"ytdl:t:{token}:last30"),
            ],
            [
                Button.inline("Change quality", data=f"ytdl:t:{token}:quality"),
                Button.inline("Cancel", data=f"ytdl:x:{token}:cancel"),
            ],
        ],
    )


def _confirmation_screen(state):
    selected = _choices(state)[state.selected_format]
    estimate = (
        humanbytes(selected.estimated_size)
        if selected.estimated_size
        else "unknown"
    )
    text = (
        "**Confirm media download**\n\n"
        f"Title: `{_clean(state.metadata.get('title'))}`\n"
        f"Duration: `{_duration(state.metadata.get('duration'))}`\n"
        f"Quality: `{selected.label}`\n"
        f"Estimated size: `{estimate}` (informational)\n"
        f"Timestamp: `{state.timestamp_text}`\n"
        f"Output: `{selected.output_type.upper()} / {selected.extension.upper()}`"
    )
    token = state.token
    buttons = [
        [Button.inline("Confirm", data=f"ytdl:c:{token}:go")],
        [
            Button.inline("Change quality", data=f"ytdl:c:{token}:quality"),
            Button.inline("Change timestamp", data=f"ytdl:c:{token}:time"),
        ],
        [Button.inline("Cancel", data=f"ytdl:x:{token}:cancel")],
    ]
    return text, buttons


async def _edit_status(state, text, buttons=None):
    return await asst.edit_message(
        state.chat_id, state.status_message_id, text, buttons=buttons, link_preview=True
    )


def _ranges(state):
    return parse_timestamp_ranges(state.timestamp_text, state.metadata.get("duration"))


def _hard_limit():
    raw = udB.get_key("YTDL_MAX_BYTES") or os.environ.get("YTDL_MAX_BYTES")
    if raw in (None, ""):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        LOGS.warning("Ignoring invalid YTDL_MAX_BYTES value")
        return None
    return value if value > 0 else None


def _cancel_state(state):
    state.cancel_event.set()
    task = _JOBS.get(state.token)
    if task is not None and state.phase in ("queued", "uploading"):
        task.cancel()


async def _upload(state, path, selected):
    attributes = None
    try:
        attributes = await set_attributes(str(path))
    except Exception:
        LOGS.debug("Could not probe yt-dlp output attributes", exc_info=True)
    if not attributes:
        duration = int(
            sum(item.duration for item in _ranges(state))
            or state.metadata.get("duration")
            or 0
        )
        if selected.output_type == "video":
            attributes = [
                DocumentAttributeVideo(
                    duration=duration,
                    w=int(state.metadata.get("width") or 1280),
                    h=int(state.metadata.get("height") or selected.height or 720),
                    supports_streaming=True,
                )
            ]
        else:
            attributes = [
                DocumentAttributeAudio(
                    duration=duration,
                    title=_clean(state.metadata.get("title")),
                    performer=_clean(state.metadata.get("uploader")),
                )
            ]
    uploaded, _ = await ultroid_bot.fast_uploader(
        str(path), filename=path.name, show_progress=False
    )
    await ultroid_bot.send_file(
        state.chat_id,
        uploaded,
        caption=f"`{_clean(state.metadata.get('title'))}`",
        attributes=attributes,
        supports_streaming=selected.output_type == "video",
        reply_to=state.command_message_id,
    )


async def _run_job(state):
    selected = _choices(state)[state.selected_format]
    loop = asyncio.get_running_loop()
    last_update = [0.0]

    def progress(status):
        now = time.monotonic()
        if status.get("status") != "finished" and now - last_update[0] < 2.5:
            return
        last_update[0] = now
        downloaded = status.get("downloaded_bytes") or 0
        total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
        percent = f"{downloaded * 100 / total:.1f}%" if total else "working"
        text = f"Downloading `{selected.label}`: `{percent}`"
        loop.call_soon_threadsafe(
            lambda: asyncio.create_task(
                _edit_status(
                    state,
                    text,
                    [[Button.inline("Cancel", data=f"ytdl:x:{state.token}:cancel")]],
                )
            )
        )

    try:
        async with _JOB_LIMIT:
            if state.cancel_event.is_set():
                raise DownloadCancelled("Download cancelled.")
            state.phase = "downloading"
            await _edit_status(
                state,
                f"Downloading `{selected.label}`: `starting`",
                [[Button.inline("Cancel", data=f"ytdl:x:{state.token}:cancel")]],
            )
            _WORK_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
            with private_workspace(_WORK_ROOT, f"ytdl-{state.token}-") as workspace:
                downloaded = await _SERVICE.download(
                    state.url,
                    selected,
                    workspace,
                    cancel_event=state.cancel_event,
                    progress_hook=progress,
                    max_bytes=_hard_limit(),
                )
                limit = _hard_limit()
                if limit is not None and downloaded.stat().st_size > limit:
                    raise ValueError("Downloaded media exceeds configured YTDL_MAX_BYTES.")
                state.phase = "clipping"
                await _edit_status(
                    state,
                    "Preparing media…",
                    [[Button.inline("Cancel", data=f"ytdl:x:{state.token}:cancel")]],
                )
                output = await clip_media(downloaded, _ranges(state), state.cancel_event)
                if state.cancel_event.is_set():
                    raise DownloadCancelled("Download cancelled.")
                state.phase = "uploading"
                await _edit_status(
                    state,
                    "Uploading media…",
                    [[Button.inline("Cancel", data=f"ytdl:x:{state.token}:cancel")]],
                )
                await _upload(state, output, selected)
        await _edit_status(state, "Media sent. ✅")
    except DownloadCancelled:
        await _edit_status(state, "Download cancelled.")
    except asyncio.CancelledError:
        await _edit_status(state, "Download cancelled.")
    except Exception as exc:
        LOGS.exception("Media workflow failed: %s", exc)
        await _edit_status(state, f"Media workflow failed: `{_clean(exc)}`")
    finally:
        _JOBS.pop(state.token, None)
        _REQUESTS.pop(state.token)


@ultroid_cmd(pattern="yt( |$)(.*)", owner_only=True)
async def youtube_media_command(event):
    try:
        url = extract_media_url(event.pattern_match.group(2))
    except URLValidationError as exc:
        return await event.eor(f"`{exc}`")
    try:
        status = await asst.send_message(
            event.chat_id, "Reading media metadata…", reply_to=event.id
        )
    except Exception as exc:
        LOGS.warning("Assistant could not create YouTube controls: %s", exc)
        return await event.eor(
            "`The assistant bot must be present and able to send buttons in this chat.`"
        )
    try:
        metadata = await _SERVICE.extract(url)
        state = _REQUESTS.create(
            owner_id=ultroid_bot.uid,
            chat_id=event.chat_id,
            command_message_id=event.id,
            status_message_id=status.id,
            url=url,
            metadata=metadata,
        )
        text, buttons = _quality_screen(state)
        await status.edit(text, buttons=buttons, link_preview=True)
    except (OSError, RuntimeError, ValueError) as exc:
        LOGS.exception("Media metadata extraction failed: %s", exc)
        await status.edit(f"Could not read media metadata: `{_clean(exc)}`")


@ultroid_cmd(pattern="ytcancel$", owner_only=True)
async def youtube_media_cancel(event):
    state = _REQUESTS.find(owner_id=ultroid_bot.uid, chat_id=event.chat_id)
    if not state:
        return await event.eor("`No pending media request in this chat.`")
    _cancel_state(state)
    if state.token not in _JOBS:
        _REQUESTS.pop(state.token)
    await _edit_status(state, "Download cancelled.")
    await event.delete()


@callback(re.compile(b"^ytdl:(?:q|t|c|x):"), owner=True)
async def youtube_media_callback(event):
    try:
        data = (
            event.data.decode("utf-8")
            if isinstance(event.data, bytes)
            else str(event.data)
        )
        _, action, token, value = data.split(":", 3)
    except (AttributeError, UnicodeDecodeError, ValueError):
        return await event.answer("Invalid media action.", alert=True)
    message_id = getattr(event, "message_id", None) or event.message.id
    state = _REQUESTS.get_bound(
        token,
        owner_id=event.sender_id,
        chat_id=event.chat_id,
        status_message_id=message_id,
    )
    if not state:
        return await event.answer("This media request expired or is not yours.", alert=True)
    if action == "x":
        _cancel_state(state)
        if token not in _JOBS:
            _REQUESTS.pop(token)
        await event.edit("Download cancelled.")
        return
    if action == "q":
        if state.phase != "quality":
            return await event.answer("That action is no longer current.", alert=True)
        if value not in _choices(state):
            return await event.answer("That quality is unavailable.", alert=True)
        state.selected_format = value
        state.phase = "timestamp"
        text, buttons = _timestamp_screen(state)
        await event.edit(text, buttons=buttons)
        return
    if action == "t":
        if state.phase != "timestamp":
            return await event.answer("That action is no longer current.", alert=True)
        if value == "quality":
            state.phase = "quality"
            text, buttons = _quality_screen(state)
            await event.edit(text, buttons=buttons, link_preview=True)
            return
        if value == "custom":
            state.phase = "awaiting_timestamp"
            await event.edit(
                "Send the custom range now in this chat, for example "
                "`1:20-2:10, 3:00-`.",
                buttons=[[Button.inline("Cancel", data=f"ytdl:x:{token}:cancel")]],
            )
            return
        timestamp = {
            "full": "full",
            "first60": "first 60s",
            "last30": "last 30s",
        }.get(value)
        if timestamp is None:
            return await event.answer("Invalid timestamp action.", alert=True)
        state.timestamp_text = timestamp
        try:
            _ranges(state)
        except TimestampError as exc:
            return await event.answer(str(exc), alert=True)
        state.phase = "confirm"
        text, buttons = _confirmation_screen(state)
        await event.edit(text, buttons=buttons)
        return
    if action == "c" and value in ("quality", "time"):
        if state.phase != "confirm":
            return await event.answer("That action is no longer current.", alert=True)
        if value == "quality":
            state.phase = "quality"
            text, buttons = _quality_screen(state)
        else:
            state.phase = "timestamp"
            text, buttons = _timestamp_screen(state)
        await event.edit(text, buttons=buttons)
        return
    if (
        action == "c"
        and value == "go"
        and state.phase == "confirm"
        and state.selected_format in _choices(state)
        and token not in _JOBS
    ):
        state.phase = "queued"
        task = asyncio.create_task(_run_job(state))
        _JOBS[token] = task
        await event.answer("Download queued.")
        return
    await event.answer("Invalid or stale media action.", alert=True)


@ultroid_bot.on(events.NewMessage(outgoing=True))
async def youtube_media_custom_timestamp(event):
    if event.sender_id != ultroid_bot.uid:
        return
    state = _REQUESTS.find(
        owner_id=ultroid_bot.uid, chat_id=event.chat_id, phase="awaiting_timestamp"
    )
    if not state or event.id == state.command_message_id:
        return
    value = (event.raw_text or "").strip()
    if is_command_message(value, HNDLR):
        return
    try:
        parse_timestamp_ranges(value, state.metadata.get("duration"))
    except TimestampError as exc:
        await event.reply(f"`{_clean(exc)}`")
        return
    state.timestamp_text = value
    state.phase = "confirm"
    text, buttons = _confirmation_screen(state)
    await _edit_status(state, text, buttons)
