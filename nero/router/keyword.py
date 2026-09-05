"""Stufe 1: Schluesselwort-Router.

Rein lokal, ~50 ms, kein Netzverkehr. Faengt die haeufigen Befehle ab, bevor
ueberhaupt die Frage aufkommt, ob etwas das Haus verlassen soll. Erst was hier
durchfaellt, geht an Stufe 2.
"""

from __future__ import annotations

import re

from nero.schemas import ToolCall

# (Muster, Tool, Namen der Gruppen in Reihenfolge) - optional gefolgt von einem
# Woerterbuch fester Argumente, fuer Befehle, die einen Wert nicht nennen
# ("Ton aus" meint Lautstaerke 0). Der Text ist beim Abgleich
# entzerrt und von Satzzeichen am Ende befreit, aber NICHT kleingeschrieben - sonst
# landete "Analysis-Uebungsblatt" kleingeschrieben als Aufgabentitel in der App.
# Die Muster greifen ueber re.IGNORECASE.
PATTERNS: list[tuple] = [
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
    # --- Geraete ---
    (r"^sperr(?:e)?(?: (?:den|meinen|das))? (?:pc|rechner|laptop|bildschirm|computer)$",
     "device.lock", ()),
    (r"^bildschirm sperren$", "device.lock", ()),
    (r"^lautst(?:ä|ae)rke auf (\d{1,3})\s*%?$", "device.volume", ("level",)),
    # Vor dem Muster fuer "öffne/starte", damit "mach den Ton aus" hier haengen
    # bleibt und nicht als Programmname durchgeht.
    (r"^(?:mach(?:e)? )?(?:den )?ton (?:aus|weg|stumm)$", "device.volume", (), {"level": 0}),
    (r"^(?:sei |sei mal )?(?:leise|still)$", "device.volume", (), {"level": 0}),
    # Bewusst ohne "mach": "mach das Licht an" waere sonst ein Programmname.
    # Kennt der Agent das Programm nicht, sagt er das - er hat eine Positivliste.
    (r"^(?:öffne|starte) (?:mir )?(?:das programm |die app )?(.+)$", "device.open_app", ("app",)),
    (r"^welche ger(?:ä|ae)te sind (?:verbunden|online)$", "device.list", ()),
    # --- Lernen ---
    (r"^wie (?:steht'?s|läuft es|lauft es) (?:mit )?(?:dem )?lernen$", "app.study_progress", ()),
    (r"^(?:mein )?lernfortschritt(?: in| für)? ?(.*)$", "app.study_progress", ("subject",)),
    (r"^wie viele karten sind f(?:ä|ae)llig$", "app.flashcards_due", ()),
    (r"^f(?:ä|ae)llige karteikarten$", "app.flashcards_due", ()),
]

COMPILED = [
    (re.compile(entry[0], re.IGNORECASE), entry[1], entry[2], entry[3] if len(entry) > 3 else {})
    for entry in PATTERNS
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

    for pattern, tool, group_names, fixed in COMPILED:
        match = pattern.match(normalized)
        if not match:
            continue
        args = dict(fixed)
        args.update(
            {
                name: value.strip()
                for name, value in zip(group_names, match.groups(), strict=True)
                if value and value.strip()
            }
        )
        return ToolCall(tool=tool, args=args)
    return None
