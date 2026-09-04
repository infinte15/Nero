"""Groq ueber die OpenAI-kompatible Schnittstelle.

Absichtlich direkt per ``httpx`` statt ueber das Groq-SDK: die Anfrageform ist bei
Groq, Gemini und einem lokalen Ollama praktisch dieselbe, und so kostet ein
Anbieterwechsel keinen Abhaengigkeitstausch.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from nero.budget import DailyBudget
from nero.schemas import ToolCall
from nero.tools.registry import resolve_wire_name

logger = logging.getLogger(__name__)


class GroqProvider:
    name = "groq"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        budget: DailyBudget,
        timeout: float = 8.0,
    ) -> None:
        self._model = model
        self._budget = budget
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def route(
        self, text: str, tools: list[dict[str, Any]], system_prompt: str
    ) -> ToolCall | None:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            "tools": tools,
            "tool_choice": "auto",
            # Pflicht, nicht Geschmackssache: gewuenscht ist deterministische
            # Befehlserkennung, keine Kreativitaet.
            "temperature": 0,
            "max_tokens": 512,
        }

        try:
            response = await self._client.post("/chat/completions", json=payload)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("LLM-Routing fehlgeschlagen: %s", exc)
            return None

        self._record_usage(body.get("usage"))
        return _parse_tool_call(body)

    def _record_usage(self, usage: Any) -> None:
        if not isinstance(usage, dict):
            return
        self._budget.record(
            self._model,
            int(usage.get("prompt_tokens") or 0),
            int(usage.get("completion_tokens") or 0),
        )


def _parse_tool_call(body: dict[str, Any]) -> ToolCall | None:
    try:
        message = body["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return None

    calls = message.get("tool_calls") or []
    if not calls:
        return None

    function = calls[0].get("function") or {}
    tool = resolve_wire_name(function.get("name", ""))
    if tool is None:
        # Das Modell hat sich ein Werkzeug ausgedacht.
        logger.info("Unbekanntes Tool vom Modell: %s", function.get("name"))
        return None

    raw_args = function.get("arguments") or "{}"
    try:
        args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
    except (ValueError, TypeError):
        args = {}
    if not isinstance(args, dict):
        args = {}

    return ToolCall(tool=tool, args=args)
