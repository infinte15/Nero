"""Mehrere Ohren hintereinander - dieselbe Form wie ``providers/chain.py``.

Erst Groq Whisper, dann das Modell im Haus. Zwei Faelle fuehren zum Rueckfall,
und sie sind verschieden:

* Groq **antwortet nicht** - Internet weg, Stoerung, Zeitueberschreitung.
* Das **Tagesbudget ist aufgebraucht**. Dann wird Groq gar nicht erst gefragt,
  denn der Aufruf wuerde ja Geld kosten.

Der zweite Fall ist die Luecke, die Phase 6 offen gelassen hat. Fuer das
Sprachmodell war sie damals geschlossen worden, fuer die Spracheingabe nicht -
und ohne Transkription gibt es keinen Text, auf den der Keyword-Router greifen
koennte. Ein erreichtes Limit hiess damit: Nero hoert nicht mehr zu.

Eine leere Transkription ist **kein** Rueckfallgrund. Wer nichts gesagt hat, hat
nichts gesagt; ein zweites Modell zu fragen, kostet nur ein bis zwei Sekunden
und findet dasselbe.
"""

from __future__ import annotations

import logging
from typing import Any

from nero.budget import DailyBudget
from nero.errors import SttError

logger = logging.getLogger(__name__)


class ChainTranscriber:
    def __init__(self, transcribers: list[Any], budget: DailyBudget) -> None:
        self._transcribers = transcribers
        self._budget = budget

    @property
    def name(self) -> str:
        return "+".join(t.name for t in self._transcribers)

    @property
    def free(self) -> bool:
        """Wahr, sobald eines der Ohren ohne Kosten laeuft."""
        return any(getattr(t, "free", False) for t in self._transcribers)

    async def transcribe(self, audio: bytes, filename: str) -> str:
        erlaubt = self._budget.allows()
        letzter: SttError | None = None

        for transcriber in self._transcribers:
            if not erlaubt and not getattr(transcriber, "free", False):
                logger.info("%s übersprungen - Tagesbudget erreicht.", transcriber.name)
                continue
            try:
                return await transcriber.transcribe(audio, filename)
            except SttError as exc:
                logger.info("%s hat nicht verstanden - nächstes Ohr.", transcriber.name)
                letzter = exc

        raise letzter or SttError("Spracherkennung ist nicht eingerichtet.")

    async def aclose(self) -> None:
        for transcriber in self._transcribers:
            await transcriber.aclose()
