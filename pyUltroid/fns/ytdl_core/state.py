# Ultroid - UserBot
# Copyright (C) 2021-2026 TeamUltroid
#
# This file is a part of < https://github.com/TeamUltroid/Ultroid/ >
# PLease read the GNU Affero General Public License in
# <https://www.gnu.org/licenses/agpl-3.0.html>.

"""Bounded, expiring request state for interactive downloads."""

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Tuple


@dataclass
class RequestState:
    token: str
    owner_id: int
    chat_id: int
    command_message_id: int
    status_message_id: int
    url: str
    created_at: float
    expires_at: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    selected_format: Optional[str] = None
    timestamp_text: str = "full"
    phase: str = "quality"
    cancel_event: threading.Event = field(default_factory=threading.Event)


class RequestStore:
    def __init__(
        self,
        ttl: float = 900,
        max_entries: int = 64,
        clock: Callable[[], float] = time.monotonic,
    ):
        if ttl <= 0 or max_entries <= 0:
            raise ValueError("ttl and max_entries must be positive")
        self.ttl = ttl
        self.max_entries = max_entries
        self._clock = clock
        self._items: Dict[str, RequestState] = {}

    def create(
        self,
        *,
        owner_id: int,
        chat_id: int,
        command_message_id: int,
        status_message_id: int,
        url: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RequestState:
        self.cleanup()
        for token, state in list(self._items.items()):
            if (state.owner_id, state.chat_id) == (owner_id, chat_id):
                state.cancel_event.set()
                self._items.pop(token, None)
        while len(self._items) >= self.max_entries:
            oldest = min(self._items.values(), key=lambda item: item.created_at)
            oldest.cancel_event.set()
            self._items.pop(oldest.token, None)
        now = self._clock()
        token = secrets.token_urlsafe(6).rstrip("=")
        while token in self._items:
            token = secrets.token_urlsafe(6).rstrip("=")
        state = RequestState(
            token=token,
            owner_id=owner_id,
            chat_id=chat_id,
            command_message_id=command_message_id,
            status_message_id=status_message_id,
            url=url,
            created_at=now,
            expires_at=now + self.ttl,
            metadata=dict(metadata or {}),
        )
        self._items[token] = state
        return state

    def get_bound(
        self, token: str, *, owner_id: int, chat_id: int, status_message_id: int
    ) -> Optional[RequestState]:
        self.cleanup()
        state = self._items.get(token)
        if state and (
            state.owner_id,
            state.chat_id,
            state.status_message_id,
        ) == (owner_id, chat_id, status_message_id):
            return state
        return None

    def find(self, *, owner_id: int, chat_id: int, phase: Optional[str] = None):
        self.cleanup()
        for state in self._items.values():
            if (state.owner_id, state.chat_id) == (owner_id, chat_id) and (
                phase is None or state.phase == phase
            ):
                return state
        return None

    def pop(self, token: str) -> Optional[RequestState]:
        return self._items.pop(token, None)

    def cleanup(self) -> Tuple[str, ...]:
        now = self._clock()
        expired = tuple(
            token for token, state in self._items.items() if state.expires_at <= now
        )
        for token in expired:
            state = self._items.pop(token)
            state.cancel_event.set()
        return expired

    def __len__(self) -> int:
        self.cleanup()
        return len(self._items)
