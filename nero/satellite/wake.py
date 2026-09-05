"""Das Wake Word - openWakeWord, rein lokal.

Solange das Wort nicht faellt, verlaesst kein Audio den Rechner. Das ist der
eigentliche Zweck dieser Datei und der Grund, warum sie vor dem Netz sitzt und
nicht dahinter.

openWakeWord wird erst hier importiert, nicht beim Laden des Pakets: das Brain
installiert ``nero`` ohne den ``satellite``-Extra, und ein Import auf Modulebene
wuerde dessen Image um onnxruntime und numpy verbreitern.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

HINWEIS = (
    "openWakeWord fehlt. Der Satellit braucht die zusätzlichen Abhängigkeiten:\n"
    "    pip install -e '.[satellite]'"
)


class WakeWord:
    def __init__(
        self,
        model: str = "hey_mycroft",
        threshold: float = 0.5,
        cooldown: float = 2.0,
        vad_threshold: float = 0.5,
    ) -> None:
        try:
            import numpy as np
            import openwakeword
            from openwakeword.model import Model
        except ImportError as exc:  # pragma: no cover - haengt an der Installation
            raise SystemExit(HINWEIS) from exc

        self._np = np
        self._threshold = threshold
        self._cooldown = cooldown
        self._silent_until = 0.0
        self.name = model

        # openWakeWord 0.6 nimmt Pfade entgegen, keine Namen. Die vortrainierten
        # Modelle liegen dem Paket bei - ein Name wird hier nachgeschlagen, ein
        # Pfad auf ein selbst trainiertes .onnx direkt durchgereicht.
        path = openwakeword.models.get(model, {}).get("model_path", model)
        if not Path(path).is_file():
            raise SystemExit(
                f"Wake-Word-Modell nicht gefunden: {model}\n"
                f"Mitgeliefert sind: {', '.join(sorted(openwakeword.models))}\n"
                "Oder ein Pfad auf ein selbst trainiertes .onnx."
            )

        # Silero-VAD als zweite Instanz: nur Bloecke, die ueberhaupt nach Stimme
        # klingen, zaehlen als Treffer. Das ist der wirksamste Regler gegen
        # Fehlausloeser durch Musik, Fernseher und Tastaturgeklapper. 0 schaltet
        # ihn ab.
        self._model = Model(wakeword_model_paths=[path], vad_threshold=vad_threshold)
        logger.info(
            "Wake Word aktiv: %s (Schwelle %.2f, VAD %.2f)", model, threshold, vad_threshold
        )

    def heard(self, frame: bytes) -> bool:
        """Ein Block von 1280 Samples rein, ausgeloest ja/nein raus."""
        now = time.monotonic()
        samples = self._np.frombuffer(frame, dtype=self._np.int16)
        scores = self._model.predict(samples)
        best = max(scores.values()) if scores else 0.0

        if now < self._silent_until or best < self._threshold:
            return False

        self._silent_until = now + self._cooldown
        logger.info("Wake Word erkannt (%.2f)", best)
        return True

    def reset(self) -> None:
        """Nach einem Befehl den Verlauf leeren, damit nichts nachklingt."""
        self._model.reset()
        self._silent_until = time.monotonic() + self._cooldown
