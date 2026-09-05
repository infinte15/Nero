"""Stufe 1 ist der Pfad, auf dem kein Paket das Haus verlaesst - er muss sitzen."""

from __future__ import annotations

import pytest

from nero.router.keyword import keyword_route

MATCHES = [
    ("Wie spät ist es?", "system.time", {}),
    ("wie viel uhr", "system.time", {}),
    ("Welcher Tag ist heute?", "system.date", {}),
    ("Was steht heute an?", "app.today_agenda", {}),
    ("Mein Tagesplan", "app.today_agenda", {}),
    ("Nächster Termin", "app.next_event", {}),
    ("Was kommt als nächstes?", "app.next_event", {}),
    ("Füge Aufgabe Milch kaufen hinzu.", "app.create_task", {"title": "Milch kaufen"}),
    ("Neue Aufgabe: Rechnung bezahlen", "app.create_task", {"title": "Rechnung bezahlen"}),
    ("Was habe ich noch offen?", "app.open_tasks", {}),
    ("Aufgabe Milch kaufen ist erledigt", "app.complete_task", {"title": "Milch kaufen"}),
    ("Welche Gewohnheiten habe ich heute?", "app.habits_today", {}),
    ("Ich habe Joggen gemacht", "app.complete_habit", {"name": "Joggen"}),
    ("Wie steht's mit dem Lernen?", "app.study_progress", {}),
    ("Lernfortschritt in Analysis", "app.study_progress", {"subject": "Analysis"}),
    ("Wie viele Karten sind fällig?", "app.flashcards_due", {}),
]


@pytest.mark.parametrize(("text", "tool", "args"), MATCHES)
def test_erkennt_befehl(text, tool, args):
    call = keyword_route(text)
    assert call is not None, text
    assert call.tool == tool
    assert call.args == args


def test_behaelt_schreibweise_des_titels():
    """Kleingeschriebene Titel landeten sonst so in der App."""
    call = keyword_route("Neue Aufgabe: Analysis-Übungsblatt abgeben")
    assert call.args["title"] == "Analysis-Übungsblatt abgeben"


@pytest.mark.parametrize(
    "text",
    [
        "Leg mir für Donnerstag eine Aufgabe an, Analysis-Übungsblatt abgeben",
        "Wie wird das Wetter morgen?",
        "",
        "   ",
    ],
)
def test_faellt_durch_an_stufe_zwei(text):
    assert keyword_route(text) is None


def test_jedes_muster_fuellt_sein_tool_vollstaendig():
    """Fängt drei Fehler auf einmal ab.

    Ein Muster, das auf ein Tool zeigt, das es nicht gibt. Eines, das ein
    Argument setzt, das das Tool nicht kennt. Und eines, das ein Pflichtfeld
    offen lässt - dann antwortet Nero mit "Dazu fehlt mir noch eine Angabe",
    obwohl der Befehl vollständig war.
    """
    from nero.router.keyword import PATTERNS
    from nero.tools.registry import TOOLS

    for entry in PATTERNS:
        pattern, name, groups = entry[0], entry[1], entry[2]
        fixed = entry[3] if len(entry) > 3 else {}

        assert name in TOOLS, name
        tool = TOOLS[name]
        geliefert = set(groups) | set(fixed)

        unbekannt = geliefert - set(tool.params)
        assert not unbekannt, f"{pattern}: {name} kennt {unbekannt} nicht"

        pflicht = {n for n, spec in tool.params.items() if spec.required}
        assert pflicht <= geliefert, f"{pattern}: {name} braucht noch {pflicht - geliefert}"
