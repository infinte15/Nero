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


class CommandResponse(BaseModel):
    speech: str
    tool: str | None = None
    route: Route = "none"
    needs_confirmation: bool = False
    confirm_token: str | None = None
