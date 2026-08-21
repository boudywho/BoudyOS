# Ultroid - UserBot
# Copyright (C) 2021-2026 TeamUltroid
#
# This file is a part of < https://github.com/TeamUltroid/Ultroid/ >
# PLease read the GNU Affero General Public License in
# <https://www.gnu.org/licenses/agpl-3.0.html>.

"""Reusable, Telegram-independent media download primitives."""

from .formats import MediaFormat, build_format_choices
from .service import DownloadCancelled, YTDLPService
from .state import RequestState, RequestStore
from .timestamps import (
    TimeRange,
    TimestampError,
    is_command_message,
    parse_timestamp_ranges,
)
from .urls import URLValidationError, extract_media_url
from .wizard import (
    parse_confirmation_choice,
    parse_quality_choice,
    parse_timestamp_choice,
)

__all__ = (
    "DownloadCancelled",
    "MediaFormat",
    "RequestState",
    "RequestStore",
    "TimeRange",
    "TimestampError",
    "URLValidationError",
    "YTDLPService",
    "build_format_choices",
    "extract_media_url",
    "is_command_message",
    "parse_confirmation_choice",
    "parse_quality_choice",
    "parse_timestamp_choice",
    "parse_timestamp_ranges",
)
