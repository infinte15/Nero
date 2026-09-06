"""Aufgaben.

``POST /api/tasks`` fuellt fehlende Felder serverseitig auf (Prioritaet 3, 60
Minuten, Status TODO), ein Titel genuegt also. Das Anlegen loest ueber
``ScheduleChangedEvent`` einen neuen Solverlauf aus - der Block taucht kurz darauf
von selbst im Kalender auf, ohne dass Nero etwas planen muesste.
"""

from __future__ import annotations

import re
from typing import Any

from nero.clients.everything import from_app
from nero.errors import ToolError
from nero.speech import fmt_day_relative, join_de, plural, quote
from nero.tools.base import ParamSpec, Tool, ToolContext
from nero.tools.match import pick

MAX_SPOKEN_TASKS = 3
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ISO_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$")


def _deadline(due: str | None) -> str | None:
    """Ein Datum wird zum Tagesende - "bis Donnerstag" heisst nicht "Donnerstag 0 Uhr"."""
    if not due:
        return None
    due = due.strip()
    if ISO_DATE.match(due):
        return f"{due}T23:59:00"
    if ISO_DATETIME.match(due):
        return due if len(due) > 16 else f"{due}:00"
    raise ToolError("Das Fälligkeitsdatum habe ich nicht verstanden.")


async def _create_task(
    ctx: ToolContext,
    title: str,
    due: str | None = None,
    duration_minutes: int | None = None,
) -> dict[str, Any]:
    title = (title or "").strip()
    if not title:
        raise ToolError("Wie soll die Aufgabe heißen?")

    body: dict[str, Any] = {"title": title}
    deadline = _deadline(due)
    if deadline:
        body["deadline"] = deadline
    if duration_minutes:
        body["estimatedDurationMinutes"] = int(duration_minutes)
    return await ctx.client.post("/api/tasks", json=body)


def _speak_created(task: dict[str, Any], ctx: ToolContext) -> str:
    title = task.get("title", "Aufgabe")
    sentence = f"Aufgabe {quote(title)} angelegt."
    deadline = from_app(task.get("deadline"))
    if deadline:
        sentence += f" Fällig {fmt_day_relative(deadline, ctx.now.date())}."
    return sentence


async def _open_tasks(ctx: ToolContext) -> list[dict[str, Any]]:
    payload = await ctx.client.get("/api/tasks/status/TODO")
    return payload if isinstance(payload, list) else []


def _speak_open(tasks: list[dict[str, Any]], _ctx: ToolContext) -> str:
    if not tasks:
        return "Du hast keine offenen Aufgaben."
    count = len(tasks)
    head = [t.get("title", "ohne Titel") for t in tasks[:MAX_SPOKEN_TASKS]]
    sentence = f"Du hast {count} offene {plural(count, 'Aufgabe', 'Aufgaben')}: {join_de(head)}"
    rest = count - len(head)
    if rest > 0:
        sentence += f", und {rest} {plural(rest, 'weitere', 'weitere')}"
    return sentence + "."


def _view_open(tasks: list[dict[str, Any]], ctx: ToolContext) -> list[dict[str, Any]]:
    """Alle offenen Aufgaben. Der Satz nennt drei, die Liste zeigt alle."""
    zeilen = []
    for task in tasks:
        deadline = from_app(task.get("deadline"))
        zeilen.append(
            {
                "label": task.get("title") or "ohne Titel",
                "meta": fmt_day_relative(deadline, ctx.now.date()) if deadline else None,
                "done": False,
            }
        )
    return zeilen


async def _complete_task(ctx: ToolContext, title: str) -> dict[str, Any]:
    tasks = await _open_tasks(ctx)
    task = pick(title, tasks, key="title", kind="Aufgabe")
    await ctx.client.put(f"/api/tasks/{task['id']}/complete")
    return task


TOOLS = [
    Tool(
        name="app.create_task",
        description="Eine neue Aufgabe anlegen",
        handler=_create_task,
        speak=_speak_created,
        params={
            "title": ParamSpec("Titel der Aufgabe", required=True),
            "due": ParamSpec(
                "Fälligkeitsdatum als ISO-Datum, z. B. 2026-09-10. Relative Angaben "
                "wie 'morgen' oder 'Donnerstag' vorher auflösen. Optional."
            ),
            "duration_minutes": ParamSpec(
                "Geschätzte Dauer in Minuten. Optional.", type="integer"
            ),
        },
    ),
    Tool(
        name="app.open_tasks",
        description="Die offenen Aufgaben vorlesen",
        handler=_open_tasks,
        speak=_speak_open,
        view=_view_open,
    ),
    Tool(
        name="app.complete_task",
        description="Eine Aufgabe als erledigt markieren",
        handler=_complete_task,
        speak=lambda task, _ctx: f"Aufgabe {quote(task.get('title', ''))} ist erledigt.",
        params={"title": ParamSpec("Titel der Aufgabe", required=True)},
    ),
]
