from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from nero.budget import DailyBudget
from nero.config import Settings

PRICES = Settings().price_eur_per_mtok
AUDIO_PRICES = Settings().price_eur_per_audio_hour


def test_zaehlt_und_bremst(tmp_path):
    budget = DailyBudget(tmp_path / "usage.json", limit_eur=0.001, prices_eur_per_mtok=PRICES)
    assert budget.allows()

    budget.record("openai/gpt-oss-20b", prompt_tokens=1_000_000, completion_tokens=0)
    assert budget.spent_today() > 0.001
    assert not budget.allows()


def test_ueberlebt_neustart(tmp_path):
    path = tmp_path / "usage.json"
    DailyBudget(path, 0.5, PRICES).record("openai/gpt-oss-20b", 100_000, 10_000)
    spent = json.loads(path.read_text())["eur"]
    assert DailyBudget(path, 0.5, PRICES).spent_today() == spent


def test_zaehler_von_gestern_zaehlt_nicht_mehr(tmp_path):
    path = tmp_path / "usage.json"
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    path.write_text(json.dumps({"date": yesterday, "eur": 99.0}))

    budget = DailyBudget(path, 0.5, PRICES)
    assert budget.spent_today() == 0.0
    assert budget.allows()


def test_kaputter_zaehler_haelt_nero_nicht_auf(tmp_path):
    path = tmp_path / "usage.json"
    path.write_text("{ kein json")
    assert DailyBudget(path, 0.5, PRICES).allows()


def test_unbekanntes_modell_wird_konservativ_geschaetzt(tmp_path):
    budget = DailyBudget(tmp_path / "usage.json", 0.5, PRICES)
    budget.record("irgendein/neues-modell", 1_000_000, 0)
    # Teurer als gpt-oss-20b - lieber zu früh bremsen als zu spät.
    assert budget.spent_today() > PRICES("openai/gpt-oss-20b")[0]


def test_audio_zaehlt_in_denselben_tagesbetrag(tmp_path):
    """Whisper rechnet nach Audiostunde ab, das Sprachmodell nach Token."""
    budget = DailyBudget(tmp_path / "usage.json", 0.5, PRICES, AUDIO_PRICES)
    budget.record("openai/gpt-oss-20b", 100_000, 0)
    nach_token = budget.spent_today()

    budget.record_audio("whisper-large-v3-turbo", seconds=1800)
    assert budget.spent_today() == pytest.approx(
        nach_token + AUDIO_PRICES("whisper-large-v3-turbo") / 2
    )


def test_ohne_audiopreise_wird_nichts_verbucht(tmp_path):
    """Der vierte Parameter ist optional - ein Budget ohne ihn bleibt brauchbar."""
    budget = DailyBudget(tmp_path / "usage.json", 0.5, PRICES)
    budget.record_audio("whisper-large-v3-turbo", seconds=3600)
    assert budget.spent_today() == 0.0
