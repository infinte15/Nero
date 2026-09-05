"""Die Schleife.

    warten -> Wake Word -> aufnehmen bis Stille -> /listen -> /speak -> warten

Mikrofon, Wake Word und Brain werden hereingereicht statt hier erzeugt. Das ist
kein Selbstzweck: so laesst sich der komplette Ablauf mit einem Mikrofon aus
Bytes und einem Wake Word aus einer Liste testen - inklusive der Faelle, die man
mit echter Hardware kaum provoziert (Brain weg, nichts gesagt, jemand redet
ununterbrochen).

Ein Detail, das man erst beim Ausprobieren merkt: die Aufnahme beginnt nicht
beim Wake Word, sondern ein Stueck davor. Wer "Hey Mycroft, was steht heute an"
in einem Zug spricht, haette sonst ein abgeschnittenes "as steht heute an" im
Upload. Deshalb laeuft ein Ringpuffer der letzten Bloecke immer mit.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import AsyncIterator

from nero.satellite.config import FRAME_SAMPLES, SAMPLE_RATE, SAMPLE_WIDTH, SatelliteSettings
from nero.satellite.endpoint import Endpointer, State
from nero.tts.wyoming import to_wav

logger = logging.getLogger(__name__)

# Wieviel vor dem Wake Word mit hochgeladen wird.
PREROLL_SECONDS = 0.5


def preroll_frames() -> int:
    return max(1, round(PREROLL_SECONDS * SAMPLE_RATE / FRAME_SAMPLES))


class Satellite:
    def __init__(self, settings: SatelliteSettings, mic, wake, brain, play=None) -> None:
        self._settings = settings
        self._mic = mic
        self._wake = wake
        self._brain = brain
        self._play = play

    def _new_endpointer(self, noise_floor: float) -> Endpointer:
        s = self._settings
        return Endpointer(
            silence_seconds=s.nero_silence_seconds,
            max_command_seconds=s.nero_max_command_seconds,
            max_lead_seconds=s.nero_max_lead_seconds,
            silence_factor=s.nero_silence_factor,
            noise_floor_min=s.nero_noise_floor_min,
            noise_floor=noise_floor,
        )

    async def run(self, frames: AsyncIterator[bytes]) -> None:
        preroll: deque[bytes] = deque(maxlen=preroll_frames())
        # Wird ueber Befehle hinweg mitgenommen: der Raum bleibt derselbe.
        noise_floor = self._settings.nero_noise_floor_min

        logger.info("Satellit läuft. Wake Word: %s", getattr(self._wake, "name", "?"))
        async for frame in frames:
            preroll.append(frame)
            if not self._wake.heard(frame):
                continue

            recorded, endpointer = await self._record(frames, list(preroll), noise_floor)
            # Der Raum bleibt derselbe - das Gelernte in den nächsten Befehl mitnehmen.
            noise_floor = endpointer.noise_floor
            preroll.clear()

            if endpointer.state is State.EMPTY:
                logger.info("Wake Word ohne Befehl - wieder ins Warten.")
            else:
                await self._handle(b"".join(recorded))

            self._wake.reset()
            self._mic.drain()

    async def _record(
        self, frames: AsyncIterator[bytes], preroll: list[bytes], noise_floor: float
    ):
        endpointer = self._new_endpointer(noise_floor)
        recorded = list(preroll)

        async for frame in frames:
            recorded.append(frame)
            if endpointer.feed(frame) in (State.DONE, State.EMPTY):
                break

        sekunden = len(recorded) * FRAME_SAMPLES / SAMPLE_RATE
        logger.info(
            "Aufnahme beendet nach %.1f s (%s, Schwelle %.0f)",
            sekunden,
            endpointer.state,
            endpointer.threshold,
        )
        return recorded, endpointer

    async def _handle(self, pcm: bytes) -> None:
        wav = to_wav(pcm, SAMPLE_RATE, SAMPLE_WIDTH, 1)
        body = await self._brain.listen(wav)

        gehoert, speech = body.get("text") or "", body.get("speech") or ""
        if gehoert:
            logger.info("Verstanden: %s", gehoert)
        logger.info("Antwort: %s", speech)

        if not speech or self._play is None:
            return
        audio = await self._brain.speak(speech)
        if audio:
            await self._play(audio)
