"""Die eine Quelle fuer alle Tools.

Aus derselben Liste entstehen der Dispatcher und die Tool-Schemas fuer das
Sprachmodell. Ein zweites, von Hand gepflegtes Schema koennte davon abdriften -
mit dem Ergebnis, dass das Modell Werkzeuge aufruft, die es nicht gibt.
"""

from __future__ import annotations

from typing import Any

from nero.errors import ToolError
from nero.schemas import ToolCall
from nero.tools import agenda, habits, study, system, tasks
from nero.tools.base import Tool, ToolContext

TOOLS: dict[str, Tool] = {
    tool.name: tool
    for module in (system, agenda, tasks, habits, study)
    for tool in module.TOOLS
}

_BY_WIRE_NAME: dict[str, str] = {tool.wire_name: name for name, tool in TOOLS.items()}


def get(name: str) -> Tool:
    tool = TOOLS.get(name)
    if tool is None:
        raise ToolError("Das kann ich nicht.")
    return tool


def resolve_wire_name(wire_name: str) -> str | None:
    """Uebersetzt den LLM-tauglichen Namen (``app_create_task``) zurueck."""
    return _BY_WIRE_NAME.get(wire_name)


def llm_schemas() -> list[dict[str, Any]]:
    return [tool.llm_schema() for tool in TOOLS.values()]


async def dispatch(call: ToolCall, ctx: ToolContext) -> tuple[Tool, str]:
    """Fuehrt einen Tool-Aufruf aus und formt die gesprochene Antwort.

    Unbekannte Argumente werden verworfen statt weitergereicht: ein Modell darf
    sich Parameter ausdenken, ohne dass das hier einen TypeError wirft.
    """
    tool = get(call.tool)
    accepted = {k: v for k, v in call.args.items() if k in tool.params and v is not None}

    missing = [n for n, spec in tool.params.items() if spec.required and n not in accepted]
    if missing:
        raise ToolError("Dazu fehlt mir noch eine Angabe.")

    result = await tool.handler(ctx, **accepted)
    return tool, tool.speak(result, ctx)
