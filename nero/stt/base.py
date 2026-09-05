"""Das Interface der Spracherkennung.

Dieselbe schmale Form wie ``providers/base.py`` und ``tts/base.py``: Groq Whisper
ist die Vorgabe, ein lokales ``faster-whisper`` als Offline-Fallback (Phase 6)
soll eine Umgebungsvariable sein und kein Umbau.

Der Audioschnipsel kommt so weiter, wie der Browser ihn aufgenommen hat - meist
Opus in einem WebM- oder Ogg-Container. Ein Umkodieren waere eine
ffmpeg-Abhaengigkeit fuer nichts: Whisper nimmt beides direkt an.
"""

from __future__ import annotations

from typing import Protocol


class Transcriber(Protocol):
    name: str

    async def transcribe(self, audio: bytes, filename: str) -> str:
        """Audio -> Text. Scheitert mit ``SttError``."""
        ...

    async def aclose(self) -> None: ...


# Was Groq Whisper annimmt. Der Dateiname ist dort nicht Deko - die Endung
# entscheidet, wie die Datei dekodiert wird.
_EXTENSIONS = {
    "audio/webm": ".webm",
    "video/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/opus": ".ogg",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/aac": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/flac": ".flac",
}

# Was der Browser aufnimmt, wenn er nichts anderes sagt.
DEFAULT_EXTENSION = ".webm"


def filename_for(content_type: str | None) -> str:
    """MIME-Typ des Uploads -> Dateiname mit passender Endung."""
    base = (content_type or "").split(";")[0].strip().lower()
    return f"befehl{_EXTENSIONS.get(base, DEFAULT_EXTENSION)}"
