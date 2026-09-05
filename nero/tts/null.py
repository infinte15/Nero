"""Sprachausgabe, die nie spricht.

Das ist das Verhalten ohne Piper-Container - lokal ohne Docker der Normalfall.
``/command`` liefert dann weiterhin seinen Satz, nur eben ohne Ton. Gleichzeitig
die Vorgabe in den Tests, damit dort keine TCP-Verbindung entstehen kann.
"""

from __future__ import annotations

from nero.errors import TtsError


class NullTts:
    name = "null"

    async def synthesize(self, text: str) -> bytes:
        raise TtsError("Sprachausgabe ist nicht eingerichtet.")

    async def aclose(self) -> None:
        return None
