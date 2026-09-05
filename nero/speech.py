"""Bausteine fuer die gesprochene Antwort.

Jede Antwort entsteht aus einer Vorlage, nie aus einem zweiten LLM-Aufruf. Das
spart nicht nur Latenz und Geld - es ist die Sicherheitsgrenze aus Kapitel 5 des
Plans: Tool-Ergebnisse duerfen unter keinen Umstaenden in ein Sprachmodell
zurueckfliessen, sonst wird jede vorgelesene Notiz zum Einfallstor fuer
Prompt Injection.
"""

from __future__ import annotations

from datetime import date, datetime

WEEKDAYS = (
    "Montag",
    "Dienstag",
    "Mittwoch",
    "Donnerstag",
    "Freitag",
    "Samstag",
    "Sonntag",
)

MONTHS = (
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
)


def fmt_time(value: datetime) -> str:
    return f"{value.hour}:{value.minute:02d} Uhr"


def fmt_date(value: date | datetime) -> str:
    if isinstance(value, datetime):
        value = value.date()
    return f"{WEEKDAYS[value.weekday()]}, {value.day}. {MONTHS[value.month - 1]}"


def fmt_day_relative(value: date | datetime, today: date) -> str:
    """"heute" / "morgen" / "am Donnerstag" - was ein Mensch sagen wuerde."""
    if isinstance(value, datetime):
        value = value.date()
    delta = (value - today).days
    if delta == 0:
        return "heute"
    if delta == 1:
        return "morgen"
    if delta == -1:
        return "gestern"
    if 2 <= delta <= 6:
        return f"am {WEEKDAYS[value.weekday()]}"
    return f"am {value.day}. {MONTHS[value.month - 1]}"


def fmt_number(value: float) -> str:
    """Deutsches Dezimalkomma, und ganze Zahlen ohne Nachkommastelle."""
    rounded = round(value, 1)
    if abs(rounded - round(rounded)) < 0.05:
        return str(int(round(rounded)))
    return f"{rounded:.1f}".replace(".", ",")


def plural(count: int, singular: str, plural_form: str) -> str:
    return singular if count == 1 else plural_form


def join_de(parts: list[str]) -> str:
    """['a', 'b', 'c'] -> 'a, b und c'."""
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return f"{', '.join(parts[:-1])} und {parts[-1]}"


def quote(text: str) -> str:
    return f"„{text}“"


# Anfuehrungszeichen aller Bauarten. Im Schriftbild markieren sie ein Zitat, im
# gesprochenen Satz haben sie keine Funktion - je nach Stimme liest espeak-ng sie
# als Pause oder verschluckt sie.
_QUOTES = str.maketrans({c: None for c in "„“”\"«»‚‘’"})


def normalize_for_speech(text: str) -> str:
    """Letzter Schliff, bevor der Satz an die Sprachausgabe geht.

    Bewusst nur Anfuehrungszeichen und Whitespace: Zahlen, Uhrzeiten (``9:30
    Uhr``) und Datumsangaben spricht das deutsche espeak-ng-Frontend von sich aus
    richtig aus. Jede weitere Regel hier waere eine Wette gegen den Phonemizer.
    """
    return " ".join(text.translate(_QUOTES).split())
