"""Spracheingabe: Whisper-Aufruf, Abrechnung nach Audiostunde, /listen."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from nero.budget import DailyBudget
from nero.config import Settings, get_settings
from nero.errors import SttError
from nero.schemas import ToolCall
from nero.stt.base import filename_for
from nero.stt.groq import UNKNOWN_AUDIO_SECONDS, GroqTranscriber
from nero.stt.null import NullStt
from tests.conftest import BASE_URL
from tests.test_command_endpoint import SpyProvider

GROQ_URL = "https://api.groq.test/openai/v1"
MODEL = "whisper-large-v3-turbo"
AUDIO = b"\x1aE\xdf\xa3 nicht wirklich webm, aber Bytes sind Bytes"


def make_budget(tmp_path, limit_eur: float = 0.50) -> DailyBudget:
    settings = Settings()
    return DailyBudget(
        tmp_path / "usage.json",
        limit_eur,
        settings.price_eur_per_mtok,
        settings.price_eur_per_audio_hour,
    )


def make_transcriber(budget: DailyBudget, **kwargs) -> GroqTranscriber:
    return GroqTranscriber(
        api_key="test-key", model=MODEL, base_url=GROQ_URL, budget=budget, **kwargs
    )


# ---- Dateiname -------------------------------------------------------------


def test_endung_kommt_aus_dem_mime_typ():
    # Die Endung entscheidet bei Groq, wie dekodiert wird - der Name selbst nicht.
    assert filename_for("audio/webm;codecs=opus") == "befehl.webm"
    assert filename_for("audio/ogg; codecs=opus") == "befehl.ogg"
    assert filename_for("AUDIO/WAV") == "befehl.wav"
    assert filename_for("audio/mp4") == "befehl.m4a"


def test_unbekannter_mime_typ_faellt_auf_webm_zurueck():
    assert filename_for(None) == "befehl.webm"
    assert filename_for("application/octet-stream") == "befehl.webm"


# ---- Whisper ---------------------------------------------------------------


@respx.mock
async def test_transkription_liefert_text(tmp_path):
    route = respx.post(f"{GROQ_URL}/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": " Was steht heute an? ", "duration": 2.4})
    )
    transcriber = make_transcriber(make_budget(tmp_path), prompt="Termine, Spaces")
    try:
        assert await transcriber.transcribe(AUDIO, "befehl.webm") == "Was steht heute an?"
    finally:
        await transcriber.aclose()

    body = route.calls.last.request.content
    assert AUDIO in body
    assert b'filename="befehl.webm"' in body
    # Der Domain-Hinweis aus Kapitel 2.2 des Plans und die deutsche Sprache.
    assert b"Termine, Spaces" in body
    assert b'name="language"\r\n\r\nde' in body
    assert b"verbose_json" in body


@respx.mock
async def test_dauer_wird_nach_audiostunde_abgerechnet(tmp_path):
    respx.post(f"{GROQ_URL}/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "Test", "duration": 3600.0})
    )
    budget = make_budget(tmp_path)
    transcriber = make_transcriber(budget)
    try:
        await transcriber.transcribe(AUDIO, "befehl.webm")
    finally:
        await transcriber.aclose()

    # Eine ganze Stunde turbo: 0,04 USD -> ~0,037 EUR.
    assert budget.spent_today() == pytest.approx(Settings().price_eur_per_audio_hour(MODEL))


@respx.mock
async def test_fehlende_dauer_wird_konservativ_geschaetzt(tmp_path):
    """Ohne Schaetzung waere die Kostenbremse bei einer Schleife wirkungslos."""
    respx.post(f"{GROQ_URL}/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "Test"})
    )
    budget = make_budget(tmp_path)
    transcriber = make_transcriber(budget)
    try:
        await transcriber.transcribe(AUDIO, "befehl.webm")
    finally:
        await transcriber.aclose()

    erwartet = UNKNOWN_AUDIO_SECONDS / 3600 * Settings().price_eur_per_audio_hour(MODEL)
    assert budget.spent_today() == pytest.approx(erwartet)


@respx.mock
async def test_fehler_von_groq_wird_zu_einer_vorlesbaren_meldung(tmp_path):
    respx.post(f"{GROQ_URL}/audio/transcriptions").mock(
        return_value=httpx.Response(413, json={"error": {"message": "file too large"}})
    )
    transcriber = make_transcriber(make_budget(tmp_path))
    try:
        with pytest.raises(SttError) as exc:
            await transcriber.transcribe(AUDIO, "befehl.webm")
    finally:
        await transcriber.aclose()
    assert exc.value.speech == "Ich konnte die Aufnahme nicht verstehen."


async def test_null_backend_erkennt_nichts():
    with pytest.raises(SttError):
        await NullStt().transcribe(AUDIO, "befehl.webm")


# ---- Endpunkt --------------------------------------------------------------


class StubStt:
    name = "stub"

    def __init__(self, text: str = "wie spät ist es") -> None:
        self.text = text
        self.calls: list[tuple[bytes, str]] = []

    async def transcribe(self, audio: bytes, filename: str) -> str:
        self.calls.append((audio, filename))
        return self.text

    async def aclose(self) -> None:
        return None


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_API_URL", BASE_URL)
    monkeypatch.setenv("NERO_APP_TOKEN", "test-token")
    monkeypatch.setenv("NERO_LLM_PROVIDER", "null")
    monkeypatch.setenv("NERO_STT_PROVIDER", "null")
    monkeypatch.setenv("NERO_TTS_PROVIDER", "null")
    monkeypatch.setenv("USAGE_FILE", str(tmp_path / "usage.json"))
    get_settings.cache_clear()

    from nero.main import app

    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def upload(api, data: bytes = AUDIO, content_type: str = "audio/webm;codecs=opus"):
    return api.post("/listen", files={"audio": ("befehl", data, content_type)})


def test_listen_laeuft_durch_denselben_router_wie_command(api):
    from nero.main import app

    app.state.stt = stub = StubStt("wie spät ist es")
    with respx.mock(assert_all_called=False) as mock:
        catch_all = mock.route(host="app.test")
        body = upload(api).json()

    assert body["text"] == "wie spät ist es"
    assert body["tool"] == "system.time"
    assert body["route"] == "keyword"
    # Derselbe lokale Weg wie bei /command: kein Paket verlaesst das Haus.
    assert not catch_all.called
    # Die Endung leitet der Endpunkt aus dem MIME-Typ ab, nicht aus dem Namen.
    assert stub.calls == [(AUDIO, "befehl.webm")]


@respx.mock
def test_listen_erreicht_auch_stufe_zwei(api):
    from nero.main import app

    app.state.stt = StubStt("Leg mir für Donnerstag eine Aufgabe an, Analysis abgeben")
    app.state.provider = SpyProvider(result=ToolCall("app.create_task", {"title": "Analysis"}))
    respx.post(f"{BASE_URL}/api/tasks").mock(
        return_value=httpx.Response(201, json={"id": 1, "title": "Analysis"})
    )

    body = upload(api).json()
    assert body["route"] == "llm"
    assert body["speech"] == "Aufgabe „Analysis“ angelegt."


def test_leere_transkription_wird_nicht_geroutet(api):
    from nero.main import app

    app.state.stt = StubStt("   ")
    app.state.provider = SpyProvider()

    body = upload(api).json()
    assert body["speech"] == "Ich habe nichts gehört."
    assert body["route"] == "none"
    assert app.state.provider.calls == []


def test_ohne_spracherkennung_bleibt_es_bei_einer_meldung(api):
    body = upload(api).json()
    assert body["speech"] == "Spracherkennung ist nicht eingerichtet."
    assert body["text"] == ""


def test_budget_bremst_vor_der_transkription(api):
    """Anders als bei /command hilft der Keyword-Router hier nicht.

    Ohne Transkription gibt es keinen Text, auf den er angewendet werden könnte -
    deshalb wird gar nicht erst aufgenommen, statt Geld auszugeben. Das gilt
    genau so lange, wie es kein Ohr im Haus gibt (siehe unten).
    """
    from nero.main import app

    app.state.budget._spent = 99.0
    app.state.stt = stub = StubStt()

    body = upload(api).json()
    assert body["speech"] == "Ich habe heute mein Limit erreicht."
    assert stub.calls == []


def test_mit_einem_ohr_im_haus_bremst_das_budget_nicht_mehr(api):
    """Die letzte Budgetlücke, geschlossen: das lokale Modell kostet nichts."""
    from nero.main import app

    app.state.budget._spent = 99.0
    app.state.stt = stub = StubStt()
    stub.free = True

    body = upload(api).json()
    assert body["text"] == "wie spät ist es"
    assert body["tool"] == "system.time"
    assert len(stub.calls) == 1


def test_leere_und_zu_grosse_aufnahmen(api):
    from nero.main import app

    app.state.stt = StubStt()
    assert upload(api, data=b"").status_code == 400
    grenze = app.state.settings.max_audio_bytes
    assert upload(api, data=b"x" * (grenze + 1)).status_code == 413
    assert api.post("/listen").status_code == 422


def test_status_meldet_die_spracherkennung(api):
    assert api.get("/status").json()["stt"] == "null"


def test_testseite_wird_ausgeliefert(api):
    response = api.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    # Die Seite spricht alle drei Endpunkte an.
    for pfad in ("/listen", "/command", "/speak"):
        assert pfad in response.text


def test_das_budget_der_app_kennt_die_audiopreise(api):
    """Sonst liefe Whisper an der Kostenbremse vorbei."""
    from nero.main import app

    app.state.budget.record_audio("whisper-large-v3-turbo", seconds=3600)
    assert app.state.budget.spent_today() > 0
