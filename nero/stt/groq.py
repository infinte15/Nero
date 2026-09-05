"""Groq Whisper.

Wie beim Sprachmodell direkt per ``httpx`` statt ueber das Groq-SDK - die
Schnittstelle ist OpenAI-kompatibel, ein Anbieterwechsel kostet damit keinen
Abhaengigkeitstausch.

Zwei Parameter verdienen eine Erklaerung:

``prompt`` ist kein Befehl an ein Sprachmodell, sondern ein Kontexthinweis: er
verschiebt Whispers Worterkennung in Richtung der genannten Begriffe. Fuer eine
App voller Eigennamen ("Spaces", "Karteikarten") ist das der billigste
Genauigkeitsgewinn, den es gibt.

``response_format=verbose_json`` liefert neben dem Text auch die Laenge der
Aufnahme. Die braucht das Tagesbudget, denn Whisper wird nach Audiostunde
abgerechnet und nicht nach Token.
"""

from __future__ import annotations

import logging

import httpx

from nero.budget import DailyBudget
from nero.errors import SttError

logger = logging.getLogger(__name__)

# Faellt "duration" wider Erwarten aus, wird konservativ geschaetzt. Lieber zu
# frueh bremsen als eine Schleife ungebremst laufen lassen.
UNKNOWN_AUDIO_SECONDS = 30.0


class GroqTranscriber:
    name = "groq"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        budget: DailyBudget,
        language: str = "de",
        prompt: str = "",
        timeout: float = 20.0,
    ) -> None:
        self._model = model
        self._budget = budget
        self._language = language
        self._prompt = prompt
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def transcribe(self, audio: bytes, filename: str) -> str:
        data = {
            "model": self._model,
            "language": self._language,
            "response_format": "verbose_json",
            "temperature": "0",
        }
        if self._prompt:
            data["prompt"] = self._prompt

        try:
            response = await self._client.post(
                "/audio/transcriptions",
                files={"file": (filename, audio)},
                data=data,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Transkription fehlgeschlagen: %s", exc)
            raise SttError("Ich konnte die Aufnahme nicht verstehen.") from exc

        self._record_usage(body)
        return str(body.get("text") or "").strip()

    def _record_usage(self, body: object) -> None:
        seconds = UNKNOWN_AUDIO_SECONDS
        if isinstance(body, dict):
            try:
                seconds = float(body["duration"])
            except (KeyError, TypeError, ValueError):
                logger.info("Keine Dauer in der Antwort - es wird konservativ geschätzt.")
        self._budget.record_audio(self._model, seconds)
