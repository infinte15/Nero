"""Stufe 1: Schluesselwort-Router.

Rein lokal, ~50 ms, kein Netzverkehr. Faengt die haeufigen Befehle ab, bevor
ueberhaupt die Frage aufkommt, ob etwas das Haus verlassen soll. Erst was hier
durchfaellt, geht an Stufe 2.
"""

from __future__ import annotations

import re

from nero.schemas import ToolCall

# (Muster, Tool, Namen der Gruppen in Reihenfolge). Der Text ist beim Abgleich
# entzerrt und von Satzzeichen am Ende befreit, aber NICHT kleingeschrieben - sonst
# landete "Analysis-Uebungsblatt" kleingeschrieben als Aufgabentitel in der App.
# Die Muster greifen ueber re.IGNORECASE.
PATTERNS: list[tuple[str, str, tuple[str, ...]]] = [
    # --- lokal, ohne API ---
    (r"^wie (?:spät|viel uhr)(?: ist es)?$", "system.time", ()),
    (r"^(?:wie viel uhr haben wir|sag mir die uhrzeit)$", "system.time", ()),
    (r"^(?:welcher tag|welches datum)(?: ist| haben wir)?(?: heute)?$", "system.date", ()),
    (r"^der wievielte ist heute$", "system.date", ()),
    # --- Kalender ---
    (r"^was (?:steht|ist|hab ich|habe ich) heute an$", "app.today_agenda", ()),
    (r"^(?:mein )?(?:tagesplan|agenda|tag)(?: heute)?$", "app.today_agenda", ()),
    (r"^was (?:steht|ist) (?:heute )?(?:so )?los$", "app.today_agenda", ()),
    (r"^(?:was ist der )?n(?:ä|ae)chste[rn]? termin$", "app.next_event", ()),
    (r"^was kommt als n(?:ä|ae)chstes$", "app.next_event", ()),
    # --- Aufgaben ---
    (r"^(?:füg|füge|leg|leg mir) (?:die |eine )?aufgabe (.+?) (?:hinzu|an)$",
     "app.create_task", ("title",)),
    (r"^neue aufgabe:? (.+)$", "app.create_task", ("title",)),
    (r"^merk dir:? (.+)$", "app.create_task", ("title",)),
    (r"^(?:was (?:hab ich|habe ich)|was ist)(?: noch)? offen$", "app.open_tasks", ()),
    (r"^(?:meine )?offene[n]? aufgaben$", "app.open_tasks", ()),
    (r"^aufgabe (.+?) (?:ist )?erledigt$", "app.complete_task", ("title",)),
    (r"^hak(?:e)? (?:die )?aufgabe (.+?) ab$", "app.complete_task", ("title",)),
    # --- Gewohnheiten ---
    (r"^(?:welche )?gewohnheiten(?: (?:hab ich|habe ich))?(?: heute)?$", "app.habits_today", ()),
    (r"^was (?:muss|soll) ich heute noch machen$", "app.habits_today", ()),
    (r"^(?:ich habe|ich hab|hab|habe) (.+?) (?:gemacht|erledigt)$",
     "app.complete_habit", ("name",)),
    # --- Lernen ---
    (r"^wie (?:steht'?s|läuft es|lauft es) (?:mit )?(?:dem )?lernen$", "app.study_progress", ()),
    (r"^(?:mein )?lernfortschritt(?: in| für)? ?(.*)$", "app.study_progress", ("subject",)),
    (r"^wie viele karten sind f(?:ä|ae)llig$", "app.flashcards_due", ()),
    (r"^f(?:ä|ae)llige karteikarten$", "app.flashcards_due", ()),
]

COMPILED = [
    (re.compile(pattern, re.IGNORECASE), tool, groups)
    for pattern, tool, groups in PATTERNS
]

_TRAILING_PUNCTUATION = re.compile(r"[.?!,;:\s]+$")
_WHITESPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Mehrfach-Leerzeichen zusammenziehen und Satzzeichen am Ende abschneiden.

    Die Gross-/Kleinschreibung bleibt erhalten - die Muster gleichen ohnehin
    unabhaengig davon ab, und die eingefangenen Gruppen werden als Titel
    weiterverwendet.
    """
    text = _WHITESPACE.sub(" ", text).strip()
    return _TRAILING_PUNCTUATION.sub("", text)


def keyword_route(text: str) -> ToolCall | None:
    normalized = normalize(text)
    if not normalized:
        return None

    for pattern, tool, group_names in COMPILED:
        match = pattern.match(normalized)
        if not match:
            continue
        args = {
            name: value.strip()
            for name, value in zip(group_names, match.groups(), strict=True)
            if value and value.strip()
        }
        return ToolCall(tool=tool, args=args)
    return None
