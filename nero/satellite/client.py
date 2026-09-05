"""Der Satellit spricht mit dem Brain.

Genau zwei Aufrufe: die Aufnahme an ``/listen``, der Antwortsatz an ``/speak``.
Mehr kennt der Satellit vom Brain nicht - und vom Rest der Welt gar nichts.

Ein Ausfall des Brains darf den Satelliten nicht beenden. Er laeuft 24/7 neben
einem Server, der neu startet, und ein Neustart des Brains soll hoechstens einen
verlorenen Befehl kosten. Fehler werden deshalb zu einer Meldung, die sich
vorlesen laesst, und nicht zu einer Ausnahme.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


class BrainClient:
    def __init__(self, base_url: str, token: str = "", timeout: float = 30.0) -> None:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=timeout, headers=headers
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def listen(self, wav: bytes) -> dict:
        """Aufnahme -> Antwort des Brains. Nie eine Ausnahme, immer ein Ergebnis."""
        try:
            response = await self._client.post(
                "/listen", files={"audio": ("befehl.wav", wav, "audio/wav")}
            )
            if response.status_code == 401:
                return {"speech": "Das Brain kennt mein Token nicht.", "text": ""}
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPError as exc:
            logger.warning("/listen fehlgeschlagen: %s", exc)
            return {"speech": "Ich erreiche das Brain gerade nicht.", "text": ""}
        except ValueError:
            return {"speech": "Das Brain hat unverständlich geantwortet.", "text": ""}
        return body if isinstance(body, dict) else {"speech": "", "text": ""}

    async def speak(self, text: str) -> bytes | None:
        """Satz -> WAV. ``None``, wenn die Sprachausgabe aus ist oder klemmt.

        Kein Ton ist kein Fehler: die Antwort steht im Log, und ein Satellit ohne
        Piper soll trotzdem Befehle ausfuehren.
        """
        if not text:
            return None
        try:
            response = await self._client.post("/speak", json={"text": text})
            if response.status_code != 200:
                logger.info("Sprachausgabe nicht verfügbar (%s)", response.status_code)
                return None
            return response.content
        except httpx.HTTPError as exc:
            logger.warning("/speak fehlgeschlagen: %s", exc)
            return None
