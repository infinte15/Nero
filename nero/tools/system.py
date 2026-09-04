"""Rein lokale Tools. Kein API-Aufruf, kein Netzverkehr - die schnellsten Antworten."""

from __future__ import annotations

from nero.speech import fmt_date, fmt_time
from nero.tools.base import Tool, ToolContext


async def _time(ctx: ToolContext) -> None:
    return None


async def _date(ctx: ToolContext) -> None:
    return None


TOOLS = [
    Tool(
        name="system.time",
        description="Die aktuelle Uhrzeit nennen",
        handler=_time,
        speak=lambda _result, ctx: f"Es ist {fmt_time(ctx.now)}.",
    ),
    Tool(
        name="system.date",
        description="Das heutige Datum nennen",
        handler=_date,
        speak=lambda _result, ctx: f"Heute ist {fmt_date(ctx.now)}.",
    ),
]
