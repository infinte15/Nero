"""Wann ist der Befehl zu Ende?

Das ist der Teil, den der Plan zurecht als den frickeligsten bezeichnet. Ein
fester Lautstaerkeschwellwert funktioniert in genau einem Raum zu genau einer
Tageszeit; ein Luefter, ein offenes Fenster oder ein anderes Mikrofon
verschieben ihn. Deshalb wird nicht gegen eine feste Zahl verglichen, sondern
gegen das *gemessene* Grundrauschen:

    Schwelle = Grundrauschen x nero_silence_factor

Das Grundrauschen laeuft als langsamer gleitender Mittelwert mit, solange
niemand spricht. Es faellt schnell und steigt langsam - so gewoehnt sich der
Satellit an einen anlaufenden Luefter, laesst sich aber von einem einzelnen
lauten Wort nicht taub machen.

Zwei Abbruchgruende neben der Stille:

* Es faengt gar nicht erst an (jemand ruft das Wake Word und ueberlegt dann) -
  nach ``max_lead`` ist Schluss.
* Es hoert nie auf (Fernseher, Gespraech im Raum) - nach ``max_command`` auch.

Bewusst ohne WebRTC-VAD oder Silero: beides waere eine weitere Abhaengigkeit
und ein weiteres Modell fuer eine Entscheidung, die eine Handvoll Zahlen genauso
gut trifft. Diese Datei kennt kein Mikrofon und kein Modell - sie sieht nur
Bloecke und ist damit ohne Hardware testbar.
"""

from __future__ import annotations

import array
import math
from dataclasses import dataclass
from enum import StrEnum

from nero.satellite.config import FRAME_SAMPLES, SAMPLE_RATE


class State(StrEnum):
    LEAD = "lead"  # wartet darauf, dass jemand anfaengt
    SPEECH = "speech"  # nimmt auf
    DONE = "done"  # fertig, es kam etwas
    EMPTY = "empty"  # fertig, es kam nichts


def _in_frames(seconds: float) -> int:
    """Sekunden -> Anzahl Bloecke, mindestens einer."""
    return max(1, round(seconds * SAMPLE_RATE / FRAME_SAMPLES))


def rms(frame: bytes) -> float:
    """Lautstaerke eines Blocks als quadratisches Mittel (0 bis ~32768)."""
    samples = array.array("h")
    samples.frombytes(frame[: len(frame) - len(frame) % 2])
    if not samples:
        return 0.0
    return math.sqrt(sum(float(s) * s for s in samples) / len(samples))


@dataclass
class Endpointer:
    """Entscheidet blockweise, ob der Befehl weitergeht oder zu Ende ist."""

    silence_seconds: float = 0.8
    max_command_seconds: float = 12.0
    max_lead_seconds: float = 3.0
    silence_factor: float = 2.5
    noise_floor_min: float = 60.0
    noise_floor: float = 0.0

    def __post_init__(self) -> None:
        self.state = State.LEAD
        # Intern wird in Bloecken gezaehlt, nicht in Sekunden. 0,08 Sekunden
        # zehnmal addiert ergeben 0,7999999999999999 - eine Grenze von 0,8 waere
        # damit erst nach elf Bloecken erreicht. Ganze Zahlen haben das Problem nicht.
        self._frames = 0
        self._silent_frames = 0
        self._max_command = _in_frames(self.max_command_seconds)
        self._max_lead = _in_frames(self.max_lead_seconds)
        self._needed_silence = _in_frames(self.silence_seconds)
        self.noise_floor = max(self.noise_floor, self.noise_floor_min)

    @property
    def threshold(self) -> float:
        return self.noise_floor * self.silence_factor

    def feed(self, frame: bytes) -> State:
        if self.state in (State.DONE, State.EMPTY):
            return self.state

        self._frames += 1
        level = rms(frame)
        loud = level > self.threshold

        if self.state is State.LEAD:
            if loud:
                self.state = State.SPEECH
                self._silent_frames = 0
            elif self._frames >= self._max_lead:
                self.state = State.EMPTY
            else:
                # Solange niemand spricht, weiter am Raum lernen.
                self._adapt(level)
            return self.state

        self._silent_frames = 0 if loud else self._silent_frames + 1
        if self._silent_frames >= self._needed_silence or self._frames >= self._max_command:
            self.state = State.DONE
        return self.state

    def _adapt(self, level: float) -> None:
        """Schnell nach unten, langsam nach oben.

        Ein kurzes Geraeusch soll den Schwellwert nicht hochziehen, ein leiser
        gewordener Raum aber sofort beruecksichtigt werden.
        """
        alpha = 0.25 if level < self.noise_floor else 0.02
        self.noise_floor = max(
            self.noise_floor_min,
            (1 - alpha) * self.noise_floor + alpha * level,
        )
