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

    # ---- Kostenbremse ----
    daily_limit_eur: float = 0.50
    usage_file: Path = Path("data/usage.json")

    # Wie lange eine Rueckfrage bei destruktiven Tools gueltig bleibt.
    confirm_ttl_seconds: int = 120

    def price_eur_per_mtok(self, model: str) -> tuple[float, float]:
        prompt_usd, completion_usd = MODEL_PRICES_USD_PER_MTOK.get(model, DEFAULT_PRICE_USD)
        return prompt_usd * USD_TO_EUR, completion_usd * USD_TO_EUR


@lru_cache
def get_settings() -> Settings:
    return Settings()
