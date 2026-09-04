"""Gewohnheiten.

``GET /api/habits`` liefert die Wochentagsflaggen, den aktuellen Streak und
``completedDates`` als ISO-Tagesliste - "was steht heute an und was ist schon
abgehakt" laesst sich damit aus einer einzigen Antwort beantworten.
"""

from __future__ import annotations

from typing import Any

from nero.speech import join_de, plural, quote
from nero.tools.base import ParamSpec, Tool, ToolContext
from nero.tools.match import pick

WEEKDAY_FIELDS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


def _due_today(habit: dict[str, Any], weekday: int) -> bool:
    if habit.get("frequency") == "DAILY":
        return True
    return bool(habit.get(WEEKDAY_FIELDS[weekday]))


async def _all_habits(ctx: ToolContext) -> list[dict[str, Any]]:
    payload = await ctx.client.get("/api/habits")
    return payload if isinstance(payload, list) else []


async def _habits_today(ctx: ToolContext) -> list[dict[str, Any]]:
    weekday = ctx.now.weekday()
    return [h for h in await _all_habits(ctx) if _due_today(h, weekday)]


def _speak_today(habits: list[dict[str, Any]], ctx: ToolContext) -> str:
    if not habits:
        return "Für heute stehen keine Gewohnheiten an."

    today = ctx.now.date().isoformat()
    done, open_ = [], []
    for habit in habits:
        name = habit.get("name", "ohne Namen")
        completed = habit.get("completedDates") or []
        (done if today in completed else open_).append(name)

    if not open_:
        return f"Alle {len(done)} Gewohnheiten für heute sind erledigt."

    sentence = f"Offen: {join_de(open_)}."
    if done:
        sentence += f" Erledigt: {join_de(done)}."
    return sentence


async def _complete_habit(ctx: ToolContext, name: str) -> dict[str, Any]:
    habits = await _all_habits(ctx)
    habit = pick(name, habits, key="name", kind="Gewohnheit")
    already_done = ctx.now.date().isoformat() in (habit.get("completedDates") or [])

    # Ohne date-Parameter nimmt der Endpunkt den heutigen Tag.
    await ctx.client.post(f"/api/habits/{habit['id']}/complete")
    return {**habit, "_alreadyDone": already_done}


def _speak_completed(habit: dict[str, Any], _ctx: ToolContext) -> str:
    name = quote(habit.get("name", ""))
    already_done = habit.get("_alreadyDone", False)

    if already_done:
        sentence = f"{name} war heute schon abgehakt."
    else:
        sentence = f"{name} für heute abgehakt."

    # Der Streak stammt aus der Liste VOR dem Abhaken. War der Tag noch offen, kommt er dazu -
    # war er es nicht, hat markHabitComplete gar nichts getan und die Zahl stimmt schon.
    streak = habit.get("currentStreak")
    if isinstance(streak, int):
        days = streak if already_done else streak + 1
        if days > 0:
            sentence += f" Das sind {days} {plural(days, 'Tag', 'Tage')} am Stück."
    return sentence


TOOLS = [
    Tool(
        name="app.habits_today",
        description="Die Gewohnheiten für heute vorlesen und sagen, was noch offen ist",
        handler=_habits_today,
        speak=_speak_today,
    ),
    Tool(
        name="app.complete_habit",
        description="Eine Gewohnheit für heute als erledigt abhaken",
        handler=_complete_habit,
        speak=_speak_completed,
        params={"name": ParamSpec("Name der Gewohnheit", required=True)},
    ),
]
