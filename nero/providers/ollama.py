"""Ollama - das Modell im Haus.

Der Rueckfall, wenn Groq nicht erreichbar ist oder das Tagesbudget aufgebraucht
wurde. Ollama spricht dieselbe OpenAI-kompatible Schnittstelle, deshalb ist das
hier fast derselbe Code wie in ``groq.py`` - nur ohne Abrechnung, denn ein
Modell auf der eigenen Maschine kostet nichts ausser Strom.

Ein Modell dieser Groesse trifft nicht so zuverlaessig wie gpt-oss-20b. Das ist
in Ordnung: es kommt erst zum Zug, wenn die Alternative gar keine Antwort ist.
Der Keyword-Router faengt die haeufigen Befehle ohnehin vorher ab.

Laenger geduldig als Groq: ein 1,5B-Modell auf einer OptiPlex-CPU braucht
Sekunden statt Millisekunden.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from nero.providers.groq import parse_tool_call
from nero.schemas import ToolCall

logger = logging.getLogger(__name__)


class OllamaProvider:
    name = "ollama"
    #: Laeuft lokal - darf also auch bei erschoepftem Tagesbudget noch routen.
    free = True

    def __init__(self, base_url: str, model: str, timeout: float = 30.0) -> None:
        self._model = model
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)

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
            "temperature": 0,
            "stream": False,
        }
        try:
            response = await self._client.post("/v1/chat/completions", json=payload)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Ollama-Routing fehlgeschlagen: %s", exc)
            return None
        return parse_tool_call(body)
