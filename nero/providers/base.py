"""Das Provider-Interface.

Bewusst schmal gehalten: der Wechsel von Groq auf Gemini (EU-Rechtsraum) oder auf
ein lokales Ollama-Modell soll eine Umgebungsvariable sein und keine Umbauaktion.
"""

from __future__ import annotations

from typing import Any, Protocol

from nero.schemas import ToolCall


class IntentProvider(Protocol):
    name: str

    async def route(
        self, text: str, tools: list[dict[str, Any]], system_prompt: str
    ) -> ToolCall | None:
        """Waehlt genau ein Tool - oder ``None``, wenn keines passt."""
        ...

    async def aclose(self) -> None: ...
