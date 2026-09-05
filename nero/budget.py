"""Tagesbudget fuer alles, was bei Groq Geld kostet.

Zweite Verteidigungslinie neben dem Hard-Limit beim Anbieter: ein Bug in einer
Schleife soll hier auflaufen und nicht erst auf der Rechnung.

Zwei Abrechnungsarten liegen darunter: das Sprachmodell zahlt nach Token, Whisper
nach Audiostunde. Beides laeuft in denselben Tagesbetrag.

Bei erreichtem Limit bleibt der Keyword-Router benutzbar - getippte Befehle
funktionieren also weiter. Gesprochene nicht: ohne Transkription gibt es keinen
Text, auf den der Keyword-Router angewendet werden koennte. Dagegen hilft erst
der lokale Fallback aus Phase 6.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)


class DailyBudget:
    def __init__(
        self,
        path: Path,
        limit_eur: float,
        prices_eur_per_mtok,
        price_eur_per_audio_hour=None,
    ) -> None:
        self._path = path
        self._limit = limit_eur
        self._prices = prices_eur_per_mtok
        self._audio_price = price_eur_per_audio_hour
        self._day, self._spent = self._load()

    # ---- oeffentlich ----

    def allows(self) -> bool:
        self._roll_over()
        return self._spent < self._limit

    def spent_today(self) -> float:
        self._roll_over()
        return self._spent

    def record(self, model: str, prompt_tokens: int, completion_tokens: int) -> None:
        self._roll_over()
        prompt_price, completion_price = self._prices(model)
        self._spent += (
            prompt_tokens * prompt_price + completion_tokens * completion_price
        ) / 1_000_000
        self._save()

    def record_audio(self, model: str, seconds: float) -> None:
        """Whisper rechnet nach Audiostunde ab, nicht nach Token."""
        if self._audio_price is None:
            return
        self._roll_over()
        self._spent += (seconds / 3600.0) * self._audio_price(model)
        self._save()

    # ---- intern ----

    def _roll_over(self) -> None:
        today = date.today()
        if self._day != today:
            self._day, self._spent = today, 0.0

    def _load(self) -> tuple[date, float]:
        # Ein fehlender oder kaputter Zaehler darf Nero nicht am Start hindern -
        # im Zweifel wird der Tag als unverbraucht behandelt.
        try:
            payload = json.loads(self._path.read_text())
            return date.fromisoformat(payload["date"]), float(payload["eur"])
        except (OSError, ValueError, KeyError, TypeError):
            return date.today(), 0.0

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps({"date": self._day.isoformat(), "eur": round(self._spent, 6)})
            )
        except OSError:
            logger.warning("Nutzungszähler konnte nicht geschrieben werden: %s", self._path)
