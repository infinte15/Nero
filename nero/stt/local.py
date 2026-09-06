"""Whisper im Haus, ueber ``faster-whisper``.

Das Gegenstueck zu ``providers/ollama.py``, eine Etage frueher: dort geht es um
den Router, hier um das Ohr. Ohne Transkription gibt es keinen Text, auf den der
Keyword-Router ueberhaupt greifen koennte - "Internet weg" hiess damit bis hier
"Ollama routet weiter, aber niemand versteht dich".

Zwei Dinge sind bewusst so gebaut:

* **Das Modell wird beim ersten Aufruf geladen, nicht beim Start.** Der
  Normalfall ist, dass es nie gebraucht wird; ein Brain, das beim Hochfahren
  eine Minute lang ein Whisper-Modell laedt, waere ein hoher Preis fuer den
  Ausnahmefall.
* **Die Transkription laeuft in einem Thread.** ``faster-whisper`` rechnet
  blockierend auf der CPU; direkt in der Event-Loop wuerde sie fuer ein bis zwei
  Sekunden alles andere anhalten - auch den Geraetebus.

``faster-whisper`` haengt wie ``openwakeword`` in einem Extra und nicht in den
Grundabhaengigkeiten. Sonst zoege jedes Brain-Image ``ctranslate2`` mit, auch
das, welches den Fallback nie einschaltet.
"""

from __future__ import annotations

import asyncio
import io
import logging

from nero.errors import SttError

logger = logging.getLogger(__name__)

# "small" ist der Punkt, an dem Deutsch zuverlaessig wird; "base" verschluckt
# Endungen, "medium" braucht auf dieser CPU spuerbar laenger als der Satz dauert.
DEFAULT_MODEL = "small"


class LocalWhisper:
    name = "local"
    #: Kostet nichts - das Tagesbudget bremst diesen Weg deshalb nicht.
    free = True

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        language: str = "de",
        prompt: str = "",
        compute_type: str = "int8",
        device: str = "cpu",
    ) -> None:
        self._model_name = model
        self._language = language
        self._prompt = prompt
        self._compute_type = compute_type
        self._device = device
        self._model = None
        self._lock = asyncio.Lock()

    async def aclose(self) -> None:
        self._model = None

    async def transcribe(self, audio: bytes, filename: str) -> str:
        model = await self._load()
        try:
            return await asyncio.to_thread(self._transcribe, model, audio)
        except Exception as exc:
            logger.warning("Lokale Transkription fehlgeschlagen: %s", exc)
            raise SttError("Ich konnte die Aufnahme nicht verstehen.") from exc

    async def _load(self):
        """Modell beim ersten Bedarf laden - und nur einmal, auch bei zwei Aufrufen."""
        if self._model is not None:
            return self._model
        async with self._lock:
            if self._model is not None:
                return self._model
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:  # pragma: no cover - haengt an der Installation
                raise SttError("Die lokale Spracherkennung ist nicht installiert.") from exc

            logger.info("Lade Whisper-Modell %s (%s)", self._model_name, self._device)
            try:
                self._model = await asyncio.to_thread(
                    WhisperModel,
                    self._model_name,
                    device=self._device,
                    compute_type=self._compute_type,
                )
            except Exception as exc:
                logger.warning("Whisper-Modell %s lädt nicht: %s", self._model_name, exc)
                raise SttError("Die lokale Spracherkennung ist nicht bereit.") from exc
            return self._model

    def _transcribe(self, model, audio: bytes) -> str:
        """Laeuft im Thread. ``segments`` ist ein Generator - er rechnet erst beim Lesen."""
        segments, _info = model.transcribe(
            io.BytesIO(audio),
            language=self._language or None,
            initial_prompt=self._prompt or None,
            beam_size=1,  # Ein Befehl ist kurz; breiter suchen kostet nur Zeit.
            temperature=0,
            vad_filter=True,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()
