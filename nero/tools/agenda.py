"""Kalender.

Der Smart Scheduler der Everything App materialisiert Aufgaben, Gewohnheiten,
Workouts, Uni-Kurse und Projekt-Sessions alle als ``CalendarEvent``-Zeilen. Eine
einzige Bereichsabfrage liefert damit den kompletten Tag ueber alle Spaces hinweg -
ein eigener Agenda-Endpunkt im Backend ist dafuer nicht noetig. Das Repository
sortiert bereits aufsteigend nach Startzeit.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from nero.clients.everything import from_app, to_app
from nero.speech import fmt_day_relative, fmt_time, join_de, plural
from nero.tools.base import Tool, ToolContext

MAX_SPOKEN_EVENTS = 5


def _active(events: Any) -> list[dict[str, Any]]:
    """Abgehakte und uebersprungene Bloecke gehoeren nicht in die Vorschau."""
    if not isinstance(events, list):
        return []
    return [
        e
        for e in events
        if isinstance(e, dict) and not e.get("completedAt") and not e.get("skippedAt")
    ]


async def _events_between(ctx: ToolContext, start, end) -> list[dict[str, Any]]:
    payload = await ctx.client.get(
        "/api/calendar/events",
        params={"startDate": to_app(start), "endDate": to_app(end)},
    )
    return _active(payload)


async def _today_agenda(ctx: ToolContext) -> list[dict[str, Any]]:
    start = ctx.now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(hour=23, minute=59, second=59)
    return await _events_between(ctx, start, end)


def _speak_agenda(events: list[dict[str, Any]], ctx: ToolContext) -> str:
    if not events:
        return "Heute steht nichts an."

    count = len(events)
    head = events[:MAX_SPOKEN_EVENTS]
    parts = []
    for event in head:
        start = from_app(event.get("startTime"))
        title = event.get("title") or "ohne Titel"
        parts.append(f"{fmt_time(start)} {title}" if start else title)

    sentence = f"Heute hast du {count} {plural(count, 'Eintrag', 'Einträge')}: {join_de(parts)}"
    rest = count - len(head)
    if rest > 0:
        sentence += f", und {rest} {plural(rest, 'weiteren', 'weitere')}"
    return sentence + "."


async def _next_event(ctx: ToolContext) -> dict[str, Any] | None:
    events = await _events_between(ctx, ctx.now, ctx.now + timedelta(days=7))
    naive_now = ctx.now.replace(tzinfo=None)
    for event in events:
        start = from_app(event.get("startTime"))
        if start and start >= naive_now:
            return event
    return None


def _speak_next(event: dict[str, Any] | None, ctx: ToolContext) -> str:
    if not event:
        return "In den nächsten sieben Tagen steht nichts an."
    title = event.get("title") or "ein Termin"
    start = from_app(event.get("startTime"))
    if not start:
        return f"Als nächstes: {title}."
    when = fmt_day_relative(start, ctx.now.date())
    return f"Als nächstes: {title} {when} um {fmt_time(start)}."


TOOLS = [
    Tool(
        name="app.today_agenda",
        description="Alle Termine, Aufgabenblöcke und Gewohnheiten für heute vorlesen",
        handler=_today_agenda,
        speak=_speak_agenda,
    ),
    Tool(
        name="app.next_event",
        description="Den nächsten anstehenden Termin nennen",
        handler=_next_event,
        speak=_speak_next,
    ),
]
