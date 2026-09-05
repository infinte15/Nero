"""Der Geraete-Bus, die device.*-Tools und der Agent - alles ohne echten Rechner."""

from __future__ import annotations

import asyncio
import json

import pytest

from nero.agent.__main__ import parse_apps
from nero.agent.bus import agent_url
from nero.agent.commands import CommandError, dispatch, open_app
from nero.devices import DeviceBus
from nero.errors import ToolError
from nero.tools import registry
from nero.tools.base import ToolContext


class FakeAgent:
    """Nimmt Befehle entgegen und antwortet, wie ein Agent es taete."""

    def __init__(self, bus: DeviceBus, result="ok", error: str | None = None, stumm=False) -> None:
        self.bus = bus
        self.result = result
        self.error = error
        self.stumm = stumm
        self.gesehen: list[dict] = []

    async def send(self, raw: str) -> None:
        message = json.loads(raw)
        self.gesehen.append(message)
        if self.stumm:
            return
        antwort = {"id": message["id"]}
        antwort["error" if self.error else "result"] = self.error or self.result
        # Wie im echten Betrieb: die Antwort kommt aus einer anderen Aufgabe.
        asyncio.get_running_loop().call_soon(self.bus.on_reply, json.dumps(antwort))


def make_bus(*namen: str, **kwargs) -> tuple[DeviceBus, dict[str, FakeAgent]]:
    bus = DeviceBus(**kwargs)
    agenten = {}
    for name in namen:
        agent = FakeAgent(bus)
        bus.register(name, agent.send)
        agenten[name] = agent
    return bus, agenten


# ---- Bus -------------------------------------------------------------------


async def test_aufruf_geht_hin_und_die_antwort_zurueck():
    bus, agenten = make_bus("laptop")
    assert await bus.call("laptop", "lock", {}) == "ok"
    assert agenten["laptop"].gesehen[0]["tool"] == "lock"
    # Jeder Aufruf traegt eine eigene id - sonst liessen sich Antworten nicht zuordnen.
    assert agenten["laptop"].gesehen[0]["id"]


async def test_zwei_aufrufe_gleichzeitig_werden_nicht_vertauscht():
    bus = DeviceBus()
    antworten: dict[str, str] = {}

    async def send(raw: str) -> None:
        message = json.loads(raw)
        antworten[message["args"]["app"]] = message["id"]
        # Absichtlich in umgekehrter Reihenfolge beantworten.
        if len(antworten) == 2:
            for app, call_id in reversed(list(antworten.items())):
                bus.on_reply(json.dumps({"id": call_id, "result": app}))

    bus.register("pc", send)
    a, b = await asyncio.gather(
        bus.call("pc", "open_app", {"app": "erste"}),
        bus.call("pc", "open_app", {"app": "zweite"}),
    )
    assert (a, b) == ("erste", "zweite")


async def test_fehler_des_agenten_wird_zur_vorlesbaren_meldung():
    bus, _ = make_bus("laptop")
    bus._devices["laptop"].send = FakeAgent(bus, error="kein xdotool").send
    with pytest.raises(ToolError) as exc:
        await bus.call("laptop", "type_text", {"text": "hallo"})
    assert "kein xdotool" in exc.value.speech


async def test_agent_der_nicht_antwortet_laeuft_in_den_timeout():
    bus = DeviceBus(timeout=0.1)
    bus.register("laptop", FakeAgent(bus, stumm=True).send)
    with pytest.raises(ToolError) as exc:
        await bus.call("laptop", "lock", {})
    assert exc.value.speech == "laptop antwortet nicht."
    # Der Warteeintrag muss weg sein, sonst waechst der Speicher mit jedem Timeout.
    assert bus._waiting == {}


async def test_unbekanntes_geraet():
    bus, _ = make_bus("laptop")
    with pytest.raises(ToolError):
        await bus.call("spiegel", "lock", {})


def test_verspaetete_antwort_stuerzt_nicht_ab():
    bus = DeviceBus()
    bus.on_reply(json.dumps({"id": "gibtsnicht", "result": "spät"}))
    bus.on_reply("kein json")
    bus.on_reply(json.dumps({"ohne": "id"}))


# ---- Auswahl des Geraets ---------------------------------------------------


def test_ein_einziges_geraet_ist_eindeutig():
    bus, _ = make_bus("laptop")
    assert bus.resolve(None) == "laptop"
    assert bus.resolve("laptop") == "laptop"


def test_bei_mehreren_wird_gefragt_statt_geraten():
    """"Sperr den Rechner" auf dem falschen Rechner ist unangenehm."""
    bus, _ = make_bus("laptop", "arbeitsrechner")
    with pytest.raises(ToolError) as exc:
        bus.resolve(None)
    assert "laptop" in exc.value.speech and "arbeitsrechner" in exc.value.speech


def test_name_wird_unscharf_aufgeloest():
    bus, _ = make_bus("arbeitsrechner", "spiegel")
    assert bus.resolve("arbeit") == "arbeitsrechner"


def test_ohne_geraete_gibt_es_eine_klare_ansage():
    with pytest.raises(ToolError) as exc:
        DeviceBus().resolve(None)
    assert exc.value.speech == "Gerade ist kein Gerät verbunden."


def test_neuverbinden_raeumt_nicht_den_neuen_eintrag_weg():
    bus = DeviceBus()
    alt = bus.register("laptop", FakeAgent(bus).send)
    bus.register("laptop", FakeAgent(bus).send)
    bus.unregister(alt)  # der alte Abgang trudelt verspätet ein
    assert bus.names == ["laptop"]


# ---- Tools -----------------------------------------------------------------


async def run_tool(bus, name: str, **args):
    ctx = ToolContext(client=None, now=None, devices=bus)
    from nero.schemas import ToolCall

    _, speech = await registry.dispatch(ToolCall(name, args), ctx)
    return speech


async def test_sperren_meldet_was_der_agent_gemeldet_hat():
    bus, agenten = make_bus("laptop")
    agenten["laptop"].result = "Bildschirm gesperrt."
    assert await run_tool(bus, "device.lock") == "Bildschirm gesperrt."


async def test_lautstaerke_wird_begrenzt_und_umgerechnet():
    bus, agenten = make_bus("laptop")
    await run_tool(bus, "device.volume", level="250")
    await run_tool(bus, "device.volume", level="30 %")
    await run_tool(bus, "device.volume", level=0)
    assert [m["args"]["level"] for m in agenten["laptop"].gesehen] == [100, 30, 0]


async def test_unsinnige_lautstaerke_wird_abgelehnt():
    bus, _ = make_bus("laptop")
    with pytest.raises(ToolError):
        await run_tool(bus, "device.volume", level="ziemlich laut")


async def test_tippen_fragt_zurueck():
    """Getippt wird in das Fenster mit dem Fokus - und der Text kam aus einer STT."""
    assert registry.TOOLS["device.type_text"].destructive is True


async def test_ohne_bus_gibt_es_eine_meldung_statt_eines_absturzes():
    ctx = ToolContext(client=None, now=None)
    from nero.schemas import ToolCall

    with pytest.raises(ToolError):
        await registry.dispatch(ToolCall("device.lock", {}), ctx)


async def test_geraeteliste():
    bus, _ = make_bus("laptop", "spiegel")
    assert await run_tool(bus, "device.list") == "Verbunden: laptop und spiegel."
    assert await run_tool(DeviceBus(), "device.list") == "Gerade ist kein Gerät verbunden."


# ---- Agent -----------------------------------------------------------------


def test_url_wird_zur_websocket_adresse():
    assert agent_url("http://server:8090") == "ws://server:8090/agent"
    assert agent_url("https://nero.example.de/") == "wss://nero.example.de/agent"


def test_programmliste_wird_gelesen():
    assert parse_apps("firefox=firefox,Musik=spotify --no-splash") == {
        "firefox": "firefox",
        "musik": "spotify --no-splash",
    }
    assert parse_apps("kaputt,=leer,name=") == {}


def test_nur_programme_von_der_liste_starten():
    """Der Entwurf im Plan würde hier alles ausführen, was ankommt."""
    with pytest.raises(CommandError) as exc:
        open_app("rm -rf /", {"firefox": "firefox"})
    assert "steht nicht auf meiner Liste" in str(exc.value)
    assert "firefox" in str(exc.value)


def test_leere_liste_laesst_nichts_durch():
    with pytest.raises(CommandError):
        open_app("firefox", {})


def test_unbekannter_befehl_wird_abgelehnt():
    with pytest.raises(CommandError):
        dispatch("format_festplatte", {}, {})


# ---- Der Spiegel (Phase 7) -------------------------------------------------


def test_spiegel_nutzt_nur_die_bestehende_schnittstelle():
    """Der Plan verspricht für Phase 7: neuer Client, gleiche Schnittstelle.

    Diese Zusage ist nachprüfbar - die Seite darf keinen eigenen Endpunkt
    ansprechen, sonst wäre der Spiegel doch ein Umbau am Brain.
    """
    from pathlib import Path

    import nero

    seite = (Path(nero.__file__).parent / "static" / "spiegel.html").read_text(encoding="utf-8")
    assert "/command" in seite
    for eigener in ("/spiegel/", "/mirror", "/agenda", "/api/"):
        assert eigener not in seite
