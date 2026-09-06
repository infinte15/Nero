"""Der Tool-Vertrag.

Ein Tool ist eine Funktion, die auf einen bestehenden Endpunkt der Everything App
zeigt - Nero baut keine eigene API und haelt keine eigenen Daten.

Das ``speak``-Feld ist der wichtigste Teil: die gesprochene Antwort wird aus einer
Vorlage gebaut, nicht vom Sprachmodell formuliert. Das ist schneller, spart einen
zweiten Aufruf und garantiert, dass Nero keine Termine erfinden kann.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from nero.clients.everything import EverythingClient


@dataclass(frozen=True)
class ToolContext:
    """Alles, was ein Handler von aussen braucht.

    ``now`` steckt hier drin und wird nicht in den Handlern geholt, damit sich
    jedes zeitabhaengige Tool mit eingefrorener Uhr testen laesst.
    """

    client: EverythingClient
    now: datetime  # zonenbehaftet, Europe/Berlin
    #: Nur die device.*-Tools brauchen ihn; ``None`` heisst "kein Bus".
    devices: Any = None
    #: Nur die notes.*-Tools; ``None`` heisst "Nextcloud ist nicht eingerichtet".
    notes: Any = None
    #: Wieviele Saetze am Stueck vorgelesen werden, bevor zurueckgefragt wird.
    notes_max_sentences: int = 8


@dataclass(frozen=True)
class ParamSpec:
    description: str
    type: str = "string"
    required: bool = False
    enum: tuple[str, ...] | None = None

    def json_schema(self) -> dict[str, Any]:
        schema: dict[str, Any] = {"type": self.type, "description": self.description}
        if self.enum:
            schema["enum"] = list(self.enum)
        return schema


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    handler: Callable[..., Awaitable[Any]]
    speak: Callable[[Any, ToolContext], str]
    params: Mapping[str, ParamSpec] = field(default_factory=dict)
    #: Loest vor der Ausfuehrung eine Rueckfrage aus ("Soll ich wirklich ...?").
    destructive: bool = False
    #: Zweite Vorlage neben ``speak``, fuer Clients mit einem Bildschirm: dasselbe
    #: Ergebnis als Zeilen statt als Satz. Ein Satz kann drei Aufgaben nennen, eine
    #: Liste zeigt alle - und sie laesst sich antippen. Optional; ohne sie bleibt
    #: ``items`` leer und nichts aendert sich fuer den Satelliten.
    view: Callable[[Any, ToolContext], list[dict[str, Any]]] | None = None
    #: Was danach noch offen ist, als vorbereiteter Aufruf. Er wird nicht
    #: ausgefuehrt, sondern wie eine Rueckfrage hinterlegt: "Soll ich
    #: weiterlesen?" - und ein "ja" holt ihn ab. Derselbe Weg, den destruktive
    #: Tools schon gehen, nur wird hier nicht vor der Ausfuehrung gefragt,
    #: sondern danach.
    follow_up: Callable[[Any, ToolContext], Any] | None = None

    @property
    def wire_name(self) -> str:
        """Name fuer das LLM-Schema.

        Die OpenAI-kompatible Schnittstelle - und damit auch Groq - laesst in
        Funktionsnamen nur ``[A-Za-z0-9_-]`` zu. Der Punkt in ``app.create_task``
        wuerde abgelehnt, also wird er hier ersetzt und in der Registry
        zurueckgeuebersetzt.
        """
        return self.name.replace(".", "_")

    def llm_schema(self) -> dict[str, Any]:
        required = [name for name, spec in self.params.items() if spec.required]
        return {
            "type": "function",
            "function": {
                "name": self.wire_name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {n: s.json_schema() for n, s in self.params.items()},
                    "required": required,
                },
            },
        }

    def confirm_question(self, args: dict[str, Any]) -> str:
        detail = ", ".join(f"{k}: {v}" for k, v in args.items() if v is not None)
        suffix = f" ({detail})" if detail else ""
        return f"Soll ich wirklich {self.description.lower()}{suffix}?"
