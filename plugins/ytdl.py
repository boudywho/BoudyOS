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
import time
from pathlib import Path

from telethon import events
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
    parse_confirmation_choice,
    parse_quality_choice,
    parse_timestamp_choice,
    parse_timestamp_ranges,
)
from pyUltroid.fns.ytdl_core.ffmpeg import clip_media
from pyUltroid.security.paths import private_workspace

from . import HNDLR, LOGS, humanbytes, udB, ultroid_bot, ultroid_cmd


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
    options = "\n".join(
        f"{index}. {item.label} (`{item.key}`)"
        for index, item in enumerate(choices, 1)
    )
    title = _clean(state.metadata.get("title"))
    text = (
        f"**YouTube / media download**\n\n`{title}`\n"
        f"Duration: `{_duration(state.metadata.get('duration'))}`\n\n"
        f"Choose quality:\n{options}\n\n"
        "Send a number, quality key/name, or `cancel`."
    )
    thumbnail = state.metadata.get("thumbnail")
    if isinstance(thumbnail, str):
        try:
            if extract_media_url(thumbnail) == thumbnail:
                text += f"\n[Thumbnail]({thumbnail})"
        except URLValidationError:
            pass
    return text


def _timestamp_screen(state):
    return (
        "Choose the portion to download. Custom ranges support `SS`, `MM:SS`, "
        "`HH:MM:SS`, open ends, and comma-separated ranges.\n\n"
        "1. Full video (`full`)\n"
        "2. Custom range (`custom`)\n"
        "3. First 60s (`first60`)\n"
        "4. Last 30s (`last30`)\n"
        "5. Change quality (`change-quality`)\n\n"
        "Send a number, option name, or `cancel`."
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
    return (
        f"{text}\n\n"
        "1. Confirm (`confirm` / `yes`)\n"
        "2. Change quality (`quality`)\n"
        "3. Change timestamp (`time` / `timestamp`)\n"
        "4. Cancel (`cancel`)"
    )


async def _edit_status(state, text):
    return await ultroid_bot.edit_message(
        state.chat_id, state.status_message_id, text, link_preview=True
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
            lambda: asyncio.create_task(_edit_status(state, text))
        )

    try:
        async with _JOB_LIMIT:
            if state.cancel_event.is_set():
                raise DownloadCancelled("Download cancelled.")
            state.phase = "downloading"
            await _edit_status(
                state,
                f"Downloading `{selected.label}`: `starting`",
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
                )
                output = await clip_media(downloaded, _ranges(state), state.cancel_event)
                if state.cancel_event.is_set():
                    raise DownloadCancelled("Download cancelled.")
                state.phase = "uploading"
                await _edit_status(
                    state,
                    "Uploading media…",
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
        status = await ultroid_bot.send_message(
            event.chat_id, "Reading media metadata…", reply_to=event.id
        )
    except Exception as exc:
        LOGS.warning("Could not create YouTube status message: %s", exc)
        return await event.eor(f"`Could not start media workflow: {_clean(exc)}`")
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
        await _edit_status(state, _quality_screen(state))
    except (OSError, RuntimeError, ValueError) as exc:
        LOGS.exception("Media metadata extraction failed: %s", exc)
        await ultroid_bot.edit_message(
            event.chat_id,
            status.id,
            f"Could not read media metadata: `{_clean(exc)}`",
        )


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


@ultroid_bot.on(events.NewMessage(outgoing=True))
async def youtube_media_text_wizard(event):
    if event.sender_id != ultroid_bot.uid:
        return
    state = _REQUESTS.find(owner_id=ultroid_bot.uid, chat_id=event.chat_id)
    if not state or event.id in (state.command_message_id, state.status_message_id):
        return
    state = _REQUESTS.get_bound(
        state.token,
        owner_id=event.sender_id,
        chat_id=event.chat_id,
        status_message_id=state.status_message_id,
    )
    if not state or state.phase not in (
        "quality",
        "timestamp",
        "awaiting_timestamp",
        "confirm",
    ):
        return
    value = (event.raw_text or "").strip()
    if is_command_message(value, HNDLR):
        return

    if value.casefold() == "cancel" or value == "0":
        _cancel_state(state)
        _REQUESTS.pop(state.token)
        await _edit_status(state, "Download cancelled.")
        return

    if state.phase == "quality":
        selected = parse_quality_choice(value, _choices(state).values())
        if not selected:
            await _edit_status(
                state, f"`Unknown quality: {_clean(value)}`\n\n{_quality_screen(state)}"
            )
            return
        state.selected_format = selected
        state.phase = "timestamp"
        await _edit_status(state, _timestamp_screen(state))
        return

    if state.phase == "timestamp":
        action = parse_timestamp_choice(value)
        if action == "cancel":
            _REQUESTS.pop(state.token)
            await _edit_status(state, "Download cancelled.")
        elif action == "quality":
            state.phase = "quality"
            await _edit_status(state, _quality_screen(state))
        elif action == "custom":
            state.phase = "awaiting_timestamp"
            await _edit_status(
                state,
                "Send the custom range now in this chat, for example "
                "`1:20-2:10, 3:00-`. Send `cancel` to stop.",
            )
        elif action in ("full", "first60", "last30"):
            state.timestamp_text = {
                "full": "full",
                "first60": "first 60s",
                "last30": "last 30s",
            }[action]
            try:
                _ranges(state)
            except TimestampError as exc:
                await _edit_status(
                    state, f"`{_clean(exc)}`\n\n{_timestamp_screen(state)}"
                )
                return
            state.phase = "confirm"
            await _edit_status(state, _confirmation_screen(state))
        else:
            await _edit_status(
                state, f"`Unknown time option: {_clean(value)}`\n\n{_timestamp_screen(state)}"
            )
        return

    if state.phase == "awaiting_timestamp":
        try:
            parse_timestamp_ranges(value, state.metadata.get("duration"))
        except TimestampError as exc:
            await _edit_status(
                state,
                f"`{_clean(exc)}`\n\nSend a custom range such as "
                "`1:20-2:10, 3:00-`, or send `cancel`.",
            )
            return
        state.timestamp_text = value
        state.phase = "confirm"
        await _edit_status(state, _confirmation_screen(state))
        return

    action = parse_confirmation_choice(value)
    if action == "quality":
        state.phase = "quality"
        await _edit_status(state, _quality_screen(state))
    elif action == "time":
        state.phase = "timestamp"
        await _edit_status(state, _timestamp_screen(state))
    elif action == "confirm" and state.selected_format in _choices(state):
        if state.token not in _JOBS:
            state.phase = "queued"
            await _edit_status(state, "Download queued…")
            task = asyncio.create_task(_run_job(state))
            _JOBS[state.token] = task
    elif action == "cancel":
        _REQUESTS.pop(state.token)
        await _edit_status(state, "Download cancelled.")
    else:
        await _edit_status(
            state,
            f"`Unknown confirmation option: {_clean(value)}`\n\n"
            f"{_confirmation_screen(state)}",
        )
