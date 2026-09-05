"""Mikrofon und Lautsprecher.

Die einzige Datei des Satelliten, die Hardware anfasst - alles andere sieht nur
Bloecke aus Bytes und ist damit ohne Geraet testbar.

``sounddevice`` kommt erst hier ins Spiel, nicht beim Laden des Pakets: das Brain
installiert ``nero`` ohne den ``satellite``-Extra und hat weder PortAudio noch
eine Soundkarte.
"""

from __future__ import annotations

import asyncio
import io
import logging
import queue
import wave
from collections.abc import AsyncIterator

from nero.satellite.config import FRAME_SAMPLES, SAMPLE_RATE

logger = logging.getLogger(__name__)

HINWEIS = (
    "sounddevice fehlt oder findet PortAudio nicht. Der Satellit braucht:\n"
    "    pip install -e '.[satellite]'\n"
    "    sudo apt install libportaudio2"
)


def _sd():
    try:
        import sounddevice
    except (ImportError, OSError) as exc:  # pragma: no cover - haengt am System
        raise SystemExit(HINWEIS) from exc
    return sounddevice


def list_devices() -> str:  # pragma: no cover - reine Ausgabe
    return str(_sd().query_devices())


class Microphone:
    """Liefert Bloecke zu genau 1280 Samples - das Mass, das openWakeWord erwartet.

    PortAudio ruft aus einem eigenen Thread zurueck. Die Bloecke gehen deshalb
    ueber eine Queue in die Ereignisschleife; ``asyncio`` selbst hat mit dem
    Audiogeraet nie direkt zu tun.
    """

    def __init__(self, device: str | int | None = None, backlog: int = 100) -> None:
        self._device = device
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=backlog)
        self._stream = None
        self._verworfen = 0

    def __enter__(self) -> Microphone:
        sd = _sd()
        self._stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            blocksize=FRAME_SAMPLES,
            device=self._device,
            dtype="int16",
            channels=1,
            callback=self._on_frame,
        )
        self._stream.start()
        logger.info("Mikrofon offen: %s", self._device or "Systemvorgabe")
        return self

    def __exit__(self, *exc: object) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
        if self._verworfen:
            logger.warning("%d Blöcke verworfen - die Schleife kam nicht nach.", self._verworfen)

    def _on_frame(self, indata, frames, time_info, status) -> None:
        # Laeuft im PortAudio-Thread: nichts blockieren, nichts loggen.
        if status:
            self._verworfen += 1
        try:
            self._queue.put_nowait(bytes(indata))
        except queue.Full:
            self._verworfen += 1

    async def frames(self) -> AsyncIterator[bytes]:
        while True:
            yield await asyncio.to_thread(self._queue.get)

    def drain(self) -> None:
        """Aufgestaute Bloecke wegwerfen - etwa nach der eigenen Sprachausgabe."""
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return


async def play(wav: bytes, device: str | int | None = None) -> None:
    """WAV abspielen. Ein Fehler hier beendet den Satelliten nicht."""
    try:
        with wave.open(io.BytesIO(wav), "rb") as source:
            rate = source.getframerate()
            channels = source.getnchannels()
            pcm = source.readframes(source.getnframes())
    except (wave.Error, EOFError):
        logger.warning("Antwort war kein lesbares WAV.")
        return

    def _play() -> None:
        sd = _sd()
        import numpy as np

        samples = np.frombuffer(pcm, dtype=np.int16)
        if channels > 1:
            samples = samples.reshape(-1, channels)
        sd.play(samples, samplerate=rate, device=device, blocking=True)

    try:
        await asyncio.to_thread(_play)
    except Exception as exc:  # pragma: no cover - Soundkarten sind Soundkarten
        logger.warning("Abspielen fehlgeschlagen: %s", exc)
