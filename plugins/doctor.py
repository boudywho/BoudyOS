"""Read-only, secret-safe BoudyOS health summary."""

import asyncio
import platform
import shutil

from pyUltroid.loader import LOAD_REPORT
from pyUltroid.version import __version__ as pyult_ver
from pyUltroid.version import ultroid_version

from . import udB, ultroid_cmd


def _build_report(ping_status="not checked") -> str:
    lines = [
        "**BoudyOS doctor**",
        f"• BoudyOS (Ultroid `{ultroid_version}` · pyUltroid `{pyult_ver}`)",
        f"• Python `{platform.python_version()}`",
    ]
    try:
        usage = shutil.disk_usage(".")
        lines.append(
            f"• Disk `{usage.free // (1024 * 1024)} MB` free / "
            f"`{usage.total // (1024 * 1024)} MB` total"
        )
    except OSError:
        lines.append("• Disk `unavailable`")
    # Report counts only: dependency names, DB names and error text can hold secrets.
    lines.append(f"• DB ping `{ping_status}`")
    lines.append(
        f"• Plugins loaded `{len(LOAD_REPORT.get('loaded') or [])}` · "
        f"missing-dep `{len(LOAD_REPORT.get('skipped_missing_dep') or [])}` · "
        f"failed `{len(LOAD_REPORT.get('failed') or [])}`"
    )
    return "\n".join(lines)


@ultroid_cmd(pattern="doctor$", owner_only=True)
async def doctor_cmd(event):
    msg = await event.eor("`Running BoudyOS doctor…`")
    try:
        result = await asyncio.wait_for(asyncio.to_thread(udB.ping), timeout=3)
        status = "ok" if result else "failed"
    except Exception:
        status = "unavailable"
    try:
        text = _build_report(status)
    except Exception:
        text = "BoudyOS doctor: report unavailable."
    await msg.edit(text)
