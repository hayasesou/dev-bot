from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ChatChannel(Protocol):
    @property
    def channel_id(self) -> int: ...

    @property
    def channel_url(self) -> str: ...

    async def send(self, content: str) -> None: ...


@runtime_checkable
class ChatPort(Protocol):
    def get_channel(self, channel_id: int) -> ChatChannel | None: ...
