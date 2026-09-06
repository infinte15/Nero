"""Die Datentypen an der Aussenkante und zwischen Router und Dispatcher."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

Route = Literal["keyword", "llm", "confirm", "none"]


@dataclass(frozen=True)
class ToolCall:
    """Das Ergebnis beider Router-Stufen - die eine Sprache, die der Dispatcher versteht."""

    tool: str
    args: dict[str, Any] = field(default_factory=dict)


class CommandRequest(BaseModel):
    # Entweder ein Befehl ...
    text: str | None = Field(default=None, max_length=1000)
    # ... oder die Bestaetigung einer vorher gestellten Rueckfrage.
    confirm_token: str | None = None


class Item(BaseModel):
    """Eine Zeile fuer eine Anzeige - dieselbe Antwort, nur nicht als Satz.

    Der Satellit liest ``speech`` vor, das Tablet zeigt ``items`` an. Beides
    entsteht aus demselben Tool-Ergebnis und aus einer Vorlage, nicht aus einem
    Modell - die Grenze aus Kapitel 5 bleibt, wo sie ist. Ohne dieses Feld
    braeuchte eine Anzeige mit antippbaren Zeilen einen zweiten Endpunkt, und
    genau den soll es nicht geben.
    """

    label: str
    meta: str | None = None
    done: bool = False


class CommandResponse(BaseModel):
    speech: str
    tool: str | None = None
    route: Route = "none"
    needs_confirmation: bool = False
    confirm_token: str | None = None
    #: Nur Tools mit einer ``view``-Vorlage fuellen das; sonst bleibt es leer.
    items: list[Item] = Field(default_factory=list)


class SpeakRequest(BaseModel):
    text: str = Field(max_length=1000)


class ListenResponse(CommandResponse):
    """Wie CommandResponse, plus das, was Whisper verstanden hat.

    Das Feld ist kein Luxus: bei einer falsch erkannten Aufnahme ist es der
    einzige Hinweis darauf, dass nicht der Router danebenlag, sondern das Ohr.
    """

    text: str = ""
