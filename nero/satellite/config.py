"""Konfiguration des Satelliten.

Eigene Settings-Klasse statt der des Brains: der Satellit laeuft auf einem
anderen Rechner und darf gar nichts von APP_API_URL, GROQ_API_KEY oder
NERO_APP_TOKEN wissen. Das ist Grundregel 1 aus dem Plan - alle Schluessel
liegen ausschliesslich im Brain, kein Client kennt einen.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

# openWakeWord erwartet 16 kHz Mono in Bloecken von 1280 Samples (80 ms).
# Diese drei Zahlen sind keine Geschmackssache, sondern die Schnittstelle zum
# Modell - der Rest des Satelliten richtet sich danach.
SAMPLE_RATE = 16_000
FRAME_SAMPLES = 1280
SAMPLE_WIDTH = 2


class SatelliteSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env.satellite", env_file_encoding="utf-8", extra="ignore"
    )

    # ---- Brain ----
    nero_brain_url: str = "http://localhost:8090"
    # Das Token dieses Geraets, aus NERO_CLIENT_TOKENS im Brain.
    nero_device_token: str = ""
    request_timeout_seconds: float = 30.0

    # ---- Wake Word ----
    # Vortrainiert gibt es alexa, hey_mycroft, hey_jarvis, timer, weather. Hier
    # darf auch ein Pfad auf ein selbst trainiertes .onnx stehen.
    nero_wake_model: str = "hey_mycroft"
    # Ab welcher Wahrscheinlichkeit ausgeloest wird. Hoeher = weniger
    # Fehlausloeser, aber man muss deutlicher sprechen.
    nero_wake_threshold: float = 0.5
    # Silero-VAD vor dem Wake Word: nur was nach Stimme klingt, zaehlt als
    # Treffer. Der wirksamste Regler gegen Fehlausloeser durch Musik,
    # Fernseher und Tastaturgeklapper. 0 schaltet ihn ab.
    nero_wake_vad_threshold: float = 0.5
    # Sperre nach einem Treffer, damit ein langgezogenes Wort nicht zweimal zaehlt.
    nero_wake_cooldown_seconds: float = 2.0

    # ---- Aufnahme ----
    # Wie lange Stille den Befehl beendet.
    nero_silence_seconds: float = 0.8
    # Notbremse, falls die Stille nie kommt (Fernseher, Gespraech im Raum).
    nero_max_command_seconds: float = 12.0
    # Wie lange gewartet wird, bevor aufgegeben wird - jemand ruft das Wake Word
    # und ueberlegt dann erst.
    nero_max_lead_seconds: float = 3.0
    # Vielfaches des gemessenen Grundrauschens, ab dem etwas als Sprache gilt.
    # Der wichtigste Regler ueberhaupt: zu klein und der Satellit hoert nie auf,
    # zu gross und er schneidet leise Silben ab.
    nero_silence_factor: float = 2.5
    # Untergrenze, damit ein absolut stiller Raum den Schwellwert nicht auf null zieht.
    nero_noise_floor_min: float = 60.0

    # ---- Audiogeraete ----
    # None = Systemvorgabe. Namen oder Index aus "python -m nero.satellite --geraete".
    nero_input_device: str | None = None
    nero_output_device: str | None = None
