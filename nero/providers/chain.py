"""Mehrere Provider hintereinander.

Erst Groq, dann das Modell im Haus. Zwei Faelle fuehren zum Rueckfall, und sie
sind verschieden:

* Groq **antwortet nicht** - Internet weg, Groq hat eine Stoerung, Zeitueberschreitung.
* Das **Tagesbudget ist aufgebraucht**. Dann wird Groq gar nicht erst gefragt,
  denn der Aufruf wuerde ja Geld kosten. Ein lokales Modell kostet nichts und
  laeuft weiter.

Der zweite Fall ist der eigentliche Gewinn von Phase 6: bis hierher hiess ein
erreichtes Limit "Ich habe heute mein Limit erreicht" und der Befehl war weg.
Jetzt heisst es hoechstens, dass die Antwort ein paar Sekunden laenger braucht.
"""

from __future__ import annotations

import logging
from typing import Any

from nero.budget import DailyBudget
from nero.schemas import ToolCall

logger = logging.getLogger(__name__)


class ChainProvider:
    def __init__(self, providers: list[Any], budget: DailyBudget) -> None:
        self._providers = providers
        self._budget = budget

    @property
    def name(self) -> str:
        return "+".join(p.name for p in self._providers)

    @property
    def free(self) -> bool:
        """Wahr, sobald einer der Provider ohne Kosten laeuft."""
        return any(getattr(p, "free", False) for p in self._providers)

    async def route(
        self, text: str, tools: list[dict[str, Any]], system_prompt: str
    ) -> ToolCall | None:
        erlaubt = self._budget.allows()
        for provider in self._providers:
            if not erlaubt and not getattr(provider, "free", False):
                logger.info("%s übersprungen - Tagesbudget erreicht.", provider.name)
                continue
            call = await provider.route(text, tools, system_prompt)
            if call is not None:
                return call
            logger.info("%s hat nichts geliefert - nächster Provider.", provider.name)
        return None

    async def aclose(self) -> None:
        for provider in self._providers:
            await provider.aclose()
