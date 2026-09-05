"""Die Leitung zum Brain.

Der Agent verbindet sich **raus** und haelt die Verbindung offen. Faellt sie weg -
WLAN gewechselt, Brain neu gestartet, Laptop aufgeklappt -, wird sie neu
aufgebaut. Ein Agent, den ein Serverneustart beendet, muesste von Hand
nachgestartet werden; genau das soll er nicht.

Die Wartezeit zwischen den Versuchen waechst, damit ein dauerhaft ausgefallenes
Brain nicht dauerhaft angeklopft wird - gedeckelt, damit die Rueckkehr nicht
Minuten dauert.
"""

from __future__ import annotations

import asyncio
import json
import logging

logger = logging.getLogger(__name__)

FIRST_DELAY = 1.0
MAX_DELAY = 30.0

HINWEIS = (
    "websockets fehlt. Der Agent braucht die zusätzlichen Abhängigkeiten:\n"
    "    pip install -e '.[agent]'"
)


def agent_url(brain_url: str) -> str:
    """``http://server:8090`` -> ``ws://server:8090/agent`` (und https -> wss)."""
    base = brain_url.rstrip("/")
    if base.startswith("https://"):
        return "wss://" + base[len("https://"):] + "/agent"
    if base.startswith("http://"):
        return "ws://" + base[len("http://"):] + "/agent"
    return base + "/agent"


async def serve(brain_url: str, token: str, handle) -> None:
    """Verbindet, bearbeitet Befehle, verbindet nach einem Abriss neu.

    ``handle`` bekommt ``(tool, args)`` und liefert einen Text zurueck oder wirft.
    Die Antwort traegt immer dieselbe ``id`` wie die Anfrage - daran ordnet das
    Brain sie dem wartenden Aufruf zu.
    """
    try:
        import websockets
    except ImportError as exc:  # pragma: no cover - haengt an der Installation
        raise SystemExit(HINWEIS) from exc

    url = agent_url(brain_url)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    delay = FIRST_DELAY

    while True:
        try:
            async with websockets.connect(url, additional_headers=headers) as ws:
                logger.info("Verbunden mit %s", url)
                delay = FIRST_DELAY
                async for raw in ws:
                    await ws.send(json.dumps(await _answer(raw, handle)))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Verbindung weg (%s) - neuer Versuch in %.0f s", exc, delay)
            await asyncio.sleep(delay)
            delay = min(MAX_DELAY, delay * 2)


async def _answer(raw: str | bytes, handle) -> dict:
    try:
        message = json.loads(raw)
        call_id, tool = message["id"], message["tool"]
    except (ValueError, KeyError, TypeError):
        logger.warning("Unverständliche Anfrage verworfen.")
        return {"id": None, "error": "unverständliche Anfrage"}

    args = message.get("args") or {}
    logger.info("Befehl: %s %s", tool, args or "")
    try:
        return {"id": call_id, "result": await handle(tool, args)}
    except Exception as exc:
        logger.info("Befehl fehlgeschlagen: %s", exc)
        return {"id": call_id, "error": str(exc)}
