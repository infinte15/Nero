"""Nur das Auspacken der Antwort - die Anfrage selbst geht nie wirklich raus."""

from __future__ import annotations

import httpx
import respx

from nero.budget import DailyBudget
from nero.config import Settings
from nero.providers.groq import GroqProvider
from nero.tools.registry import llm_schemas

BASE = "https://groq.test/v1"


def make_provider(tmp_path):
    budget = DailyBudget(tmp_path / "usage.json", 0.5, Settings().price_eur_per_mtok)
    return GroqProvider("key", "openai/gpt-oss-20b", BASE, budget), budget


def completion(name: str, arguments: str, usage: dict | None = None):
    return {
        "choices": [
            {"message": {"tool_calls": [{"function": {"name": name, "arguments": arguments}}]}}
        ],
        "usage": usage or {"prompt_tokens": 800, "completion_tokens": 40},
    }


@respx.mock
async def test_uebersetzt_wire_name_zurueck(tmp_path):
    provider, budget = make_provider(tmp_path)
    respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json=completion(
                "app_create_task", '{"title": "Analysis abgeben", "due": "2026-09-10"}'
            ),
        )
    )
    call = await provider.route("...", llm_schemas(), "system")
    assert call.tool == "app.create_task"
    assert call.args == {"title": "Analysis abgeben", "due": "2026-09-10"}
    assert budget.spent_today() > 0
    await provider.aclose()


@respx.mock
async def test_kein_tool_call_ist_kein_fehler(tmp_path):
    provider, _budget = make_provider(tmp_path)
    respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "hm"}}]})
    )
    assert await provider.route("...", llm_schemas(), "system") is None
    await provider.aclose()


@respx.mock
async def test_erfundenes_tool_wird_verworfen(tmp_path):
    provider, _budget = make_provider(tmp_path)
    respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(200, json=completion("app_lösche_alles", "{}"))
    )
    assert await provider.route("...", llm_schemas(), "system") is None
    await provider.aclose()


@respx.mock
async def test_kaputte_argumente_ergeben_leere_args(tmp_path):
    provider, _budget = make_provider(tmp_path)
    respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(200, json=completion("app_today_agenda", "{nicht json"))
    )
    call = await provider.route("...", llm_schemas(), "system")
    assert call.tool == "app.today_agenda"
    assert call.args == {}
    await provider.aclose()


@respx.mock
async def test_ausfall_des_anbieters_faellt_still_durch(tmp_path):
    """Groq weg heisst: Nero versteht den Befehl nicht - nicht: Nero stuerzt ab."""
    provider, _budget = make_provider(tmp_path)
    respx.post(f"{BASE}/chat/completions").mock(side_effect=httpx.ConnectError("weg"))
    assert await provider.route("...", llm_schemas(), "system") is None
    await provider.aclose()


def test_alle_tool_namen_sind_fuer_die_api_zulaessig():
    """OpenAI-kompatible Funktionsnamen erlauben nur [A-Za-z0-9_-] - kein Punkt."""
    import re

    for schema in llm_schemas():
        assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", schema["function"]["name"])
