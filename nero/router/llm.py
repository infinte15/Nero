"""Stufe 2: Absichtserkennung per Sprachmodell.

Laeuft nur, wenn Stufe 1 nichts gefunden hat. Das Modell bekommt ausschliesslich
den Befehlstext und die Tool-Beschreibungen zu sehen - **niemals** Inhalte aus der
App. Die Rueckrichtung gibt es gar nicht: das Ergebnis eines Tools wird von einer
Vorlage in Sprache uebersetzt und nie an ein Modell zurueckgereicht.
"""

from __future__ import annotations

from datetime import datetime

from nero.budget import DailyBudget
from nero.errors import BudgetExceeded
from nero.providers.base import IntentProvider
from nero.schemas import ToolCall
from nero.speech import WEEKDAYS
from nero.tools.registry import llm_schemas

SYSTEM_PROMPT = """Du bist der Absichts-Router für Nero, eine Sprachsteuerung für die \
persönliche Produktivitäts-App des Nutzers.

Wähle genau ein Werkzeug, das zur Anweisung passt, und fülle dessen Parameter aus.
Passt kein Werkzeug, rufe keines auf und antworte mit einem leeren Text.
Antworte selbst niemals inhaltlich - du wählst nur aus.

Heute ist {weekday}, der {date}. Es ist {time} Uhr, Zeitzone Europe/Berlin.
Löse relative Zeitangaben wie "morgen", "Donnerstag" oder "nächste Woche" selbst auf und \
gib Datumsangaben immer als ISO-Datum im Format JJJJ-MM-TT an."""


def build_system_prompt(now: datetime) -> str:
    return SYSTEM_PROMPT.format(
        weekday=WEEKDAYS[now.weekday()],
        date=now.date().isoformat(),
        time=now.strftime("%H:%M"),
    )


async def llm_route(
    text: str, provider: IntentProvider, budget: DailyBudget, now: datetime
) -> ToolCall | None:
    # Seit Phase 6 bremst das Budget nur noch, wenn es keinen kostenlosen Weg
    # gibt. Steht ein lokales Modell bereit, entscheidet der Provider selbst,
    # wen er ueberspringt - die Antwort dauert dann laenger, kommt aber.
    if not budget.allows() and not getattr(provider, "free", False):
        raise BudgetExceeded("Ich habe heute mein Limit erreicht.")
    return await provider.route(text, llm_schemas(), build_system_prompt(now))
