"""Phase 6: das Modell im Haus als Rückfall."""

from __future__ import annotations

import httpx
import pytest
import respx

from nero.budget import DailyBudget
from nero.config import Settings
from nero.errors import BudgetExceeded
from nero.providers.chain import ChainProvider
from nero.providers.ollama import OllamaProvider
from nero.router.llm import llm_route
from nero.schemas import ToolCall
from tests.conftest import NOW

OLLAMA = "http://ollama.test:11434"


def antwort(tool: str = "system_time") -> dict:
    return {
        "choices": [
            {"message": {"tool_calls": [{"function": {"name": tool, "arguments": "{}"}}]}}
        ]
    }


def make_budget(tmp_path, limit: float = 0.5) -> DailyBudget:
    settings = Settings()
    return DailyBudget(
        tmp_path / "usage.json", limit, settings.price_eur_per_mtok,
        settings.price_eur_per_audio_hour,
    )


class FakeProvider:
    def __init__(self, name: str, free: bool, result: ToolCall | None) -> None:
        self.name = name
        self.free = free
        self._result = result
        self.calls = 0

    async def route(self, text, tools, system_prompt):
        self.calls += 1
        return self._result

    async def aclose(self) -> None:
        return None


# ---- Ollama ----------------------------------------------------------------


@respx.mock
async def test_ollama_spricht_dieselbe_schnittstelle():
    route = respx.post(f"{OLLAMA}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=antwort())
    )
    provider = OllamaProvider(OLLAMA, "qwen2.5:1.5b")
    try:
        assert await provider.route("wie spät", [], "prompt") == ToolCall("system.time", {})
    finally:
        await provider.aclose()

    payload = route.calls.last.request.read()
    assert b'"temperature":0' in payload.replace(b" ", b"")
    assert b'"stream":false' in payload.replace(b" ", b"")


@respx.mock
async def test_ollama_nicht_erreichbar_liefert_nichts_statt_zu_werfen():
    respx.post(f"{OLLAMA}/v1/chat/completions").mock(side_effect=httpx.ConnectError("weg"))
    provider = OllamaProvider(OLLAMA, "qwen2.5:1.5b")
    try:
        assert await provider.route("wie spät", [], "prompt") is None
    finally:
        await provider.aclose()


# ---- Die Kette -------------------------------------------------------------


async def test_groq_zuerst_ollama_bleibt_unangetastet(tmp_path):
    groq = FakeProvider("groq", free=False, result=ToolCall("system.time"))
    ollama = FakeProvider("ollama", free=True, result=ToolCall("system.date"))

    kette = ChainProvider([groq, ollama], make_budget(tmp_path))
    assert await kette.route("x", [], "p") == ToolCall("system.time")
    assert (groq.calls, ollama.calls) == (1, 0)


async def test_wenn_groq_schweigt_uebernimmt_ollama(tmp_path):
    groq = FakeProvider("groq", free=False, result=None)
    ollama = FakeProvider("ollama", free=True, result=ToolCall("system.date"))

    kette = ChainProvider([groq, ollama], make_budget(tmp_path))
    assert await kette.route("x", [], "p") == ToolCall("system.date")
    assert (groq.calls, ollama.calls) == (1, 1)


async def test_bei_erschoepftem_budget_wird_groq_gar_nicht_erst_gefragt(tmp_path):
    """Der eigentliche Gewinn von Phase 6.

    Bis hierher war der Befehl bei erreichtem Limit verloren. Jetzt kostet er
    nur ein paar Sekunden mehr.
    """
    groq = FakeProvider("groq", free=False, result=ToolCall("system.time"))
    ollama = FakeProvider("ollama", free=True, result=ToolCall("system.date"))

    budget = make_budget(tmp_path, limit=0.0)
    kette = ChainProvider([groq, ollama], budget)

    assert await kette.route("x", [], "p") == ToolCall("system.date")
    assert groq.calls == 0, "ein Aufruf, der Geld kostet, darf hier nicht passieren"


async def test_ohne_freien_weg_bremst_das_budget_wie_bisher(tmp_path):
    groq = FakeProvider("groq", free=False, result=ToolCall("system.time"))
    budget = make_budget(tmp_path, limit=0.0)

    with pytest.raises(BudgetExceeded):
        await llm_route("x", groq, budget, NOW)
    assert groq.calls == 0


async def test_mit_freiem_weg_bremst_das_budget_nicht_mehr(tmp_path):
    groq = FakeProvider("groq", free=False, result=None)
    ollama = FakeProvider("ollama", free=True, result=ToolCall("system.date"))
    budget = make_budget(tmp_path, limit=0.0)
    kette = ChainProvider([groq, ollama], budget)

    assert await llm_route("x", kette, budget, NOW) == ToolCall("system.date")


async def test_wenn_keiner_etwas_findet(tmp_path):
    kette = ChainProvider(
        [FakeProvider("groq", False, None), FakeProvider("ollama", True, None)],
        make_budget(tmp_path),
    )
    assert await kette.route("x", [], "p") is None


def test_der_name_zeigt_die_ganze_kette(tmp_path):
    kette = ChainProvider(
        [FakeProvider("groq", False, None), FakeProvider("ollama", True, None)],
        make_budget(tmp_path),
    )
    assert kette.name == "groq+ollama"
    assert kette.free is True


# ---- Zusammenbau ------------------------------------------------------------


def test_build_provider_baut_die_kette_nur_wenn_noetig(tmp_path):
    from nero.main import build_provider

    budget = make_budget(tmp_path)

    nur_groq = build_provider(Settings(groq_api_key="k", nero_llm_fallback="null"), budget)
    assert nur_groq.name == "groq"

    beide = build_provider(Settings(groq_api_key="k", nero_llm_fallback="ollama"), budget)
    assert beide.name == "groq+ollama"

    # Ohne Schlüssel bleibt Ollama allein übrig - genau der Offline-Fall.
    nur_ollama = build_provider(Settings(groq_api_key="", nero_llm_fallback="ollama"), budget)
    assert nur_ollama.name == "ollama" and nur_ollama.free is True

    aus = build_provider(Settings(groq_api_key="", nero_llm_fallback="null"), budget)
    assert aus.name == "null"
