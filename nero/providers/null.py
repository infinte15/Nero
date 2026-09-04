"""Provider, der nie routet.

Das ist das Verhalten ohne API-Schluessel und ohne Internet: es bleibt beim
Keyword-Router. Gleichzeitig der Standard-Provider in den Tests, damit dort kein
Aufruf nach draussen passieren kann.
"""

from __future__ import annotations

from typing import Any

from nero.schemas import ToolCall


class NullProvider:
    name = "null"

    async def route(
        self, text: str, tools: list[dict[str, Any]], system_prompt: str
    ) -> ToolCall | None:
        return None

    async def aclose(self) -> None:
        return None
