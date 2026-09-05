"""Spracherkennung, die nie erkennt.

Das Verhalten ohne GROQ_API_KEY und ohne Internet: /listen antwortet 503, der
getippte Weg ueber /command bleibt offen. Gleichzeitig die Vorgabe in den Tests,
damit dort kein Aufruf nach draussen passieren kann.
"""

from __future__ import annotations

from nero.errors import SttError


class NullStt:
    name = "null"

    async def transcribe(self, audio: bytes, filename: str) -> str:
        raise SttError("Spracherkennung ist nicht eingerichtet.")

    async def aclose(self) -> None:
        return None
