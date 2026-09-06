"""Die Geraeteschranke aus Phase 4."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from nero.auth import bearer_token, parse_clients
from nero.config import get_settings
from tests.conftest import BASE_URL

TOKENS = "laptop:abc123,spiegel:def456"


def test_liste_wird_zu_token_zu_name():
    assert parse_clients(TOKENS) == {"abc123": "laptop", "def456": "spiegel"}


def test_halb_getippte_eintraege_werden_verworfen():
    # Sonst wuerde "laptop:" zu einem Geraet mit leerem Token - also zu einem,
    # bei dem ein fehlender Header genuegt.
    assert parse_clients("laptop:,:abc,kaputt, ,pc:xyz") == {"xyz": "pc"}
    assert parse_clients("") == {}


def test_nur_bearer_zaehlt():
    assert bearer_token("Bearer abc") == "abc"
    assert bearer_token("bearer  abc ") == "abc"
    assert bearer_token("Basic abc") == ""
    assert bearer_token(None) == ""


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_API_URL", BASE_URL)
    monkeypatch.setenv("NERO_APP_TOKEN", "test-token")
    monkeypatch.setenv("NERO_LLM_PROVIDER", "null")
    monkeypatch.setenv("NERO_STT_PROVIDER", "null")
    monkeypatch.setenv("NERO_TTS_PROVIDER", "null")
    monkeypatch.setenv("NERO_CLIENT_TOKENS", TOKENS)
    monkeypatch.setenv("USAGE_FILE", str(tmp_path / "usage.json"))
    get_settings.cache_clear()

    from nero.main import app

    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def test_ohne_token_kein_befehl(api):
    response = api.post("/command", json={"text": "wie spät ist es"})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_mit_token_geht_es(api):
    body = api.post(
        "/command",
        json={"text": "wie spät ist es"},
        headers={"Authorization": "Bearer abc123"},
    ).json()
    assert body["tool"] == "system.time"


def test_falsches_token_wird_abgewiesen(api):
    for header in ({"Authorization": "Bearer abc124"}, {"Authorization": "Basic abc123"}):
        assert api.post("/command", json={"text": "wie spät"}, headers=header).status_code == 401


def test_alle_teuren_endpunkte_sind_geschuetzt(api):
    """/listen und /speak kosten Geld bzw. Rechenzeit - beide brauchen ein Token."""
    assert api.post("/speak", json={"text": "Test"}).status_code == 401
    assert api.post("/listen", files={"audio": ("a.webm", b"x", "audio/webm")}).status_code == 401


def test_health_und_testseite_bleiben_offen(api):
    # /health braucht der Docker-Healthcheck, / kann keinen Header mitschicken -
    # die Seite fragt das Token selbst ab und legt es an die fetch-Aufrufe.
    assert api.get("/health").status_code == 200
    assert api.get("/").status_code == 200


def test_die_betriebsdaten_stehen_nicht_offen_im_netz(api):
    """Geraetenamen und Tagesausgaben gehen niemanden an, der nur die Domain kennt."""
    assert "clients" not in api.get("/health").json()
    assert api.get("/status").status_code == 401
    assert api.get("/status", headers={"Authorization": "Bearer abc123"}).json()["clients"] == 2


def test_ohne_konfigurierte_tokens_bleibt_alles_offen(monkeypatch, tmp_path):
    """Das Verhalten der Phasen 1-3 und der lokale Entwicklungsfall."""
    monkeypatch.setenv("NERO_APP_TOKEN", "test-token")
    monkeypatch.setenv("NERO_LLM_PROVIDER", "null")
    monkeypatch.setenv("NERO_STT_PROVIDER", "null")
    monkeypatch.setenv("NERO_TTS_PROVIDER", "null")
    monkeypatch.setenv("NERO_CLIENT_TOKENS", "")
    monkeypatch.setenv("USAGE_FILE", str(tmp_path / "usage.json"))
    get_settings.cache_clear()

    from nero.main import app

    with TestClient(app) as client:
        assert client.post("/command", json={"text": "wie spät ist es"}).status_code == 200
    get_settings.cache_clear()
