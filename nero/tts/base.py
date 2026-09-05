"""Das Interface der Sprachausgabe.

Bewusst genauso schmal wie ``providers/base.py``: Piper ist die Vorgabe, aber der
Wechsel auf eine andere Stimme - ein anderes lokales Modell, notfalls ein
Cloud-Dienst - soll eine Umgebungsvariable sein und kein Umbau.

Rueckgabe ist immer ein vollstaendiges WAV, kein Strom von PCM-Bloecken. Fuer
einzelne Saetze ist das die einfachere Variante, und der WAV-Header braucht die
Gesamtlaenge ohnehin.
"""

from __future__ import annotations

from typing import Protocol


class SpeechSynthesizer(Protocol):
    name: str

    async def synthesize(self, text: str) -> bytes:
        """Text -> fertiges WAV. Scheitert mit ``TtsError``."""
        ...

    async def aclose(self) -> None: ...
