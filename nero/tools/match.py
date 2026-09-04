"""Namensaufloesung: gesprochener Titel -> Datensatz-ID.

Bewusst lokal mit ``difflib`` statt mit einem zweiten LLM-Aufruf. Es geht dabei
nicht um Geld, sondern um die Grenze aus Kapitel 5: haetten wir hier ein Modell,
liefen App-Inhalte (Aufgabentitel, Gewohnheitsnamen) durch einen Prompt - genau
der Rueckfluss, den Nero nicht haben darf.
"""

from __future__ import annotations

import difflib
from typing import Any

from nero.errors import ToolError
from nero.speech import join_de, quote

CUTOFF = 0.6


def pick(
    query: str,
    items: list[dict[str, Any]],
    key: str,
    kind: str = "Aufgabe",
) -> dict[str, Any]:
    """Sucht den Eintrag, dessen ``key`` am besten zu ``query`` passt.

    Kein Treffer oder mehrere gleich gute Treffer fuehren zu einer Rueckfrage -
    Nero raet nicht. Das ist kein Luxus: mehrere Endpunkte der App pruefen die
    Eigentuemerschaft nicht, eine falsch aufgeloeste ID wuerde also stillschweigend
    den falschen Datensatz aendern statt zu scheitern.
    """
    if not items:
        raise ToolError(f"Ich sehe gerade keine offene {kind}.")

    titles = [str(item.get(key, "")) for item in items]
    needle = query.strip().casefold()

    # Exakte und Teil-Treffer schlagen die Aehnlichkeitssuche - "Analysis" soll
    # "Analysis-Uebungsblatt abgeben" finden, auch wenn der Quotient niedrig ist.
    contained = [i for i, t in enumerate(titles) if needle and needle in t.casefold()]
    if len(contained) == 1:
        return items[contained[0]]
    if len(contained) > 1:
        raise _ambiguous(kind, [titles[i] for i in contained])

    folded = [t.casefold() for t in titles]
    close = difflib.get_close_matches(needle, folded, n=3, cutoff=CUTOFF)
    if not close:
        raise ToolError(f"Ich finde keine {kind}, die so heißt.")

    best_score = difflib.SequenceMatcher(None, needle, close[0]).ratio()
    tied = [
        c for c in close
        if difflib.SequenceMatcher(None, needle, c).ratio() >= best_score - 0.05
    ]
    if len(tied) > 1:
        raise _ambiguous(kind, [titles[folded.index(c)] for c in tied])

    return items[folded.index(close[0])]


def _ambiguous(kind: str, candidates: list[str]) -> ToolError:
    options = join_de([quote(c) for c in candidates[:3]])
    return ToolError(f"Ich habe mehrere Treffer: {options}. Welche {kind} meinst du?")
