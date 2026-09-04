from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from nero.clients.everything import EverythingClient
from nero.tools.base import ToolContext

BASE_URL = "http://app.test"
BERLIN = ZoneInfo("Europe/Berlin")

# Freitag, 4. September 2026, 09:30 - alle zeitabhaengigen Erwartungen haengen daran.
NOW = datetime(2026, 9, 4, 9, 30, tzinfo=BERLIN)


@pytest.fixture
async def client():
    api = EverythingClient(BASE_URL, token="test-token")
    yield api
    await api.aclose()


@pytest.fixture
def ctx(client) -> ToolContext:
    return ToolContext(client=client, now=NOW)
