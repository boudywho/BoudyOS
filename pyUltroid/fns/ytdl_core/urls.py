# Ultroid - UserBot
# Copyright (C) 2021-2026 TeamUltroid
#
# This file is a part of < https://github.com/TeamUltroid/Ultroid/ >
# PLease read the GNU Affero General Public License in
# <https://www.gnu.org/licenses/agpl-3.0.html>.

"""URL extraction for the owner media downloader."""

import re
from urllib.parse import urlsplit, urlunsplit


class URLValidationError(ValueError):
    """Raised when a command does not contain one safe HTTP(S) URL."""


_URL = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)


def extract_media_url(text: str) -> str:
    """Return the first absolute HTTP(S) URL, stripped of common punctuation."""
    match = _URL.search(text or "")
    if not match:
        raise URLValidationError("Provide a valid http:// or https:// media URL.")
    candidate = match.group(0).rstrip(".,;!?)]}>'\"")
    parsed = urlsplit(candidate)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        raise URLValidationError("Provide a valid http:// or https:// media URL.")
    if parsed.username or parsed.password:
        raise URLValidationError("URLs containing credentials are not accepted.")
    try:
        parsed.port
    except ValueError as exc:
        raise URLValidationError("The media URL has an invalid port.") from exc
    return urlunsplit(parsed)
