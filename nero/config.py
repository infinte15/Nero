"""Konfiguration. Alles kommt aus der Umgebung bzw. aus .env - nichts ist eingecheckt."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# Groq rechnet in US-Dollar ab, das Tagesbudget im Plan steht in Euro. Der Kurs
# muss nicht genau sein - er entscheidet ueber eine Bremse bei 50 Cent, nicht
# ueber eine Rechnung.
USD_TO_EUR = 0.92

# (Eingabe, Ausgabe) in US-Dollar pro Million Token, Stand September 2026.
# Unbekannte Modelle werden ueber DEFAULT_PRICE_USD konservativ geschaetzt.
MODEL_PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "openai/gpt-oss-20b": (0.075, 0.30),
    "openai/gpt-oss-120b": (0.15, 0.60),
}
DEFAULT_PRICE_USD = (0.50, 1.50)

# Whisper wird nicht nach Token abgerechnet, sondern nach Audiostunde.
# US-Dollar pro Stunde, Stand September 2026.
AUDIO_PRICES_USD_PER_HOUR: dict[str, float] = {
    "whisper-large-v3-turbo": 0.04,
    "whisper-large-v3": 0.111,
}
DEFAULT_AUDIO_PRICE_USD = 0.15


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---- Everything App ----
    app_api_url: str = "http://localhost:8080"
    nero_app_token: str = ""
    request_timeout_seconds: float = 10.0

    # Die Everything-App-API ist zeitzonennaiv (siehe clients/everything.py).
    # Diese Zone ist die einzige Stelle, an der die Wanduhr definiert wird.
    timezone: str = "Europe/Berlin"

    # ---- LLM ----
    nero_llm_provider: Literal["groq", "null"] = "groq"
    nero_llm_model: str = "openai/gpt-oss-20b"
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    llm_timeout_seconds: float = 8.0

    # ---- Offline-Fallback (Phase 6) ----
    # "ollama" oder "null". Greift, wenn Groq nicht antwortet ODER das
    # Tagesbudget erreicht ist - ein lokales Modell kostet nichts.
    nero_llm_fallback: Literal["ollama", "null"] = "null"
    ollama_url: str = "http://ollama:11434"
    # qwen2.5:1.5b ist der Nachfolger des im Plan genannten Qwen 1.5B und kann
    # Tool-Calls. Ein groesseres Modell trifft besser, braucht auf dieser CPU
    # aber spuerbar laenger.
    ollama_model: str = "qwen2.5:1.5b"
    ollama_timeout_seconds: float = 30.0

    # ---- Spracheingabe ----
    nero_stt_provider: Literal["groq", "null"] = "groq"
    nero_stt_model: str = "whisper-large-v3-turbo"
    stt_language: str = "de"
    # Whispers "prompt" ist ein Kontexthinweis, keine Anweisung: er verschiebt die
    # Worterkennung in Richtung dieser Begriffe. Ohne ihn wird aus "Space" gern
    # "Speis" und aus "Habit" "Hebet".
    stt_prompt: str = (
        "Nero. Termine, Kalender, Aufgaben, Spaces, Gewohnheiten, Lernen, "
        "Karteikarten, Analysis, Übungsblatt, Uni."
    )
    stt_timeout_seconds: float = 20.0

    # Whisper im Haus, als zweites Glied hinter Groq. Greift, wenn Groq nicht
    # antwortet ODER das Tagesbudget erreicht ist - das lokale Modell kostet
    # nichts. Braucht "faster-whisper" aus dem Extra [stt-local].
    nero_stt_fallback: Literal["local", "null"] = "null"
    # tiny/base/small/medium/large-v3. "small" ist der Punkt, an dem Deutsch
    # zuverlaessig wird; darueber wird es auf dieser CPU langsamer als der Satz.
    nero_stt_local_model: str = "small"
    # int8 rechnet auf einer CPU ohne AVX-512 am schnellsten; float32 ist genauer.
    nero_stt_local_compute_type: str = "int8"
    nero_stt_local_device: str = "cpu"
    # Groq nimmt bis 25 MB. Ein gesprochener Befehl liegt bei wenigen Dutzend
    # Kilobyte - alles darueber ist ein Fehler und kein Befehl.
    max_audio_bytes: int = 10 * 1024 * 1024

    # ---- Sprachausgabe ----
    # Piper laeuft als eigener Container und spricht rohes TCP (Wyoming), nicht
    # HTTP - deshalb Host und Port statt einer URL. "null" schaltet die Ausgabe
    # ab; /speak antwortet dann 503, /command bleibt unberuehrt.
    nero_tts_provider: Literal["wyoming", "null"] = "wyoming"
    piper_host: str = "piper"
    piper_port: int = 10200
    # Leer = die Stimme, mit der der Container gestartet wurde (--voice).
    nero_tts_voice: str = ""
    tts_timeout_seconds: float = 20.0

    # ---- Geraete ----
    # "name:token,name2:token2". Leer = offen; das ist der lokale Fall und das
    # Verhalten der Phasen 1-3. Sobald ein Port offen ist, gehoeren hier Tokens
    # hinein - je Geraet eines, damit sich eines einzeln sperren laesst.
    nero_client_tokens: str = ""

    # ---- Kostenbremse ----
    daily_limit_eur: float = 0.50
    usage_file: Path = Path("data/usage.json")

    # ---- Nextcloud (Vorlesequelle) ----
    # Leer = die notes.*-Tools sagen, dass Nextcloud nicht eingerichtet ist.
    # Das Passwort ist ein APP-Passwort aus den Nextcloud-Einstellungen, nicht
    # das Hauptpasswort: es laesst sich einzeln widerrufen.
    nextcloud_url: str = ""
    nextcloud_user: str = ""
    nextcloud_app_password: str = ""
    nextcloud_notes_path: str = "Notes"
    # Wieviele Saetze am Stueck vorgelesen werden. Eine vierzigseitige Notiz
    # will niemand am Stueck hoeren - danach wird gefragt, ob es weitergehen soll.
    notes_max_sentences: int = 8

    # Wie lange eine Rueckfrage bei destruktiven Tools gueltig bleibt. Dieselbe
    # Frist gilt fuer ein "Soll ich weiterlesen?".
    confirm_ttl_seconds: int = 120

    def price_eur_per_mtok(self, model: str) -> tuple[float, float]:
        prompt_usd, completion_usd = MODEL_PRICES_USD_PER_MTOK.get(model, DEFAULT_PRICE_USD)
        return prompt_usd * USD_TO_EUR, completion_usd * USD_TO_EUR

    def price_eur_per_audio_hour(self, model: str) -> float:
        return AUDIO_PRICES_USD_PER_HOUR.get(model, DEFAULT_AUDIO_PRICE_USD) * USD_TO_EUR


@lru_cache
def get_settings() -> Settings:
    return Settings()
