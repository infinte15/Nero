"""Lernen.

Die Lernziele (``/api/study/goals``) sind die eigentliche Fortschrittsanzeige der
App: sie liefern ``loggedHours``, ``weeklyGoalHours``, ``remainingHours`` und
``progress`` bereits ausgerechnet mit - Nero muss nichts nachrechnen.
"""

from __future__ import annotations

from typing import Any

from nero.speech import fmt_number, join_de, plural
from nero.tools.base import ParamSpec, Tool, ToolContext
from nero.tools.match import pick


async def _study_progress(ctx: ToolContext, subject: str | None = None) -> Any:
    payload = await ctx.client.get("/api/study/goals")
    goals = payload if isinstance(payload, list) else []
    if subject and goals:
        return [pick(subject, goals, key="courseName", kind="Lernziel")]
    return goals


def _goal_sentence(goal: dict[str, Any]) -> str:
    name = goal.get("courseName") or "ohne Fach"
    logged = float(goal.get("loggedHours") or 0)
    target = float(goal.get("weeklyGoalHours") or 0)
    hours = plural(int(target), "Stunde", "Stunden")
    return f"{name} {fmt_number(logged)} von {fmt_number(target)} {hours}"


def _speak_progress(goals: list[dict[str, Any]], _ctx: ToolContext) -> str:
    if not goals:
        return "Du hast noch keine Lernziele angelegt."
    if len(goals) == 1:
        goal = goals[0]
        remaining = float(goal.get("remainingHours") or 0)
        sentence = f"In {_goal_sentence(goal)} geschafft."
        if remaining > 0:
            hours = plural(int(remaining), "Stunde", "Stunden")
            sentence += f" Es fehlen noch {fmt_number(remaining)} {hours}."
        else:
            sentence += " Das Wochenziel steht."
        return sentence
    return "Diese Woche: " + join_de([_goal_sentence(g) for g in goals]) + "."


async def _flashcards_due(ctx: ToolContext) -> list[dict[str, Any]]:
    payload = await ctx.client.get("/api/study/flashcards/due")
    return payload if isinstance(payload, list) else []


def _speak_due(cards: list[dict[str, Any]], _ctx: ToolContext) -> str:
    count = len(cards)
    if count == 0:
        return "Es sind keine Karteikarten fällig."

    per_deck: dict[str, int] = {}
    for card in cards:
        deck = card.get("deckName") or "ohne Stapel"
        per_deck[deck] = per_deck.get(deck, 0) + 1

    verb = plural(count, "ist", "sind")
    noun = plural(count, "Karte", "Karten")
    sentence = f"Es {verb} {count} {noun} fällig"
    if len(per_deck) > 1:
        top = sorted(per_deck.items(), key=lambda kv: -kv[1])[:3]
        sentence += ", davon " + join_de([f"{n} in {deck}" for deck, n in top])
    return sentence + "."


TOOLS = [
    Tool(
        name="app.study_progress",
        description="Den Lernfortschritt der Woche nennen, optional für ein einzelnes Fach",
        handler=_study_progress,
        speak=_speak_progress,
        params={"subject": ParamSpec("Name des Fachs oder Moduls. Optional.")},
    ),
    Tool(
        name="app.flashcards_due",
        description="Sagen, wie viele Karteikarten zur Wiederholung fällig sind",
        handler=_flashcards_due,
        speak=_speak_due,
    ),
]
