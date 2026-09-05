"""Der Geraete-Bus.

Die Richtung ist der ganze Trick: Geraete verbinden sich **raus** zum Brain und
halten die Verbindung offen. Kein Port-Forwarding, keine feste IP, kein
VPN - und es funktioniert auch aus dem Uni-WLAN heraus. Das Brain schickt
Befehle durch die bestehende Leitung zurueck.

Ein Aufruf ist ein Paar aus zwei Nachrichten:

    Brain -> Agent   {"id": "7f3a", "tool": "lock", "args": {}}
    Agent -> Brain   {"id": "7f3a", "result": "gesperrt"}
                oder {"id": "7f3a", "error": "kein xdotool"}

Die ``id`` ist noetig, weil mehrere Aufrufe gleichzeitig unterwegs sein koennen
und WebSockets keine Zuordnung von sich aus mitbringen. Wer wartet, wartet auf
ein Future - kein Abfragen, kein Schlafen.

Wer welches Geraet ist, entscheidet das Token und nicht das Geraet selbst. Sonst
koennte sich ein Agent als ein anderer ausgeben und Befehle abfangen, die nicht
fuer ihn bestimmt waren.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from nero.errors import ToolError
from nero.speech import join_de, quote

logger = logging.getLogger(__name__)

CALL_TIMEOUT = 15.0


@dataclass
class Device:
    name: str
    send: Any  # Coroutine-Funktion: str -> None
    connected_at: float = field(default_factory=time.monotonic)


class DeviceBus:
    def __init__(self, timeout: float = CALL_TIMEOUT) -> None:
        self._devices: dict[str, Device] = {}
        self._waiting: dict[str, asyncio.Future[Any]] = {}
        self._timeout = timeout

    # ---- Verbindungen ----

    def register(self, name: str, send) -> Device:
        if name in self._devices:
            logger.info("%s verbindet sich neu - die alte Leitung gilt als tot.", name)
        device = Device(name=name, send=send)
        self._devices[name] = device
        logger.info("Gerät verbunden: %s (jetzt %d)", name, len(self._devices))
        return device

    def unregister(self, device: Device) -> None:
        # Nur loesen, wenn es noch dieselbe Verbindung ist: bei einem schnellen
        # Neuverbinden raeumt sonst der alte Abgang den neuen Eintrag weg.
        if self._devices.get(device.name) is device:
            del self._devices[device.name]
            logger.info("Gerät getrennt: %s (jetzt %d)", device.name, len(self._devices))

    @property
    def names(self) -> list[str]:
        return sorted(self._devices)

    # ---- Aufrufe ----

    def resolve(self, query: str | None) -> str:
        """Welches Geraet ist gemeint?

        Ohne Angabe und mit genau einem verbundenen Geraet ist die Sache klar.
        Sonst wird gefragt - geraten wird nicht, denn "sperr den Rechner" auf dem
        falschen Rechner ist eine unangenehme Ueberraschung.
        """
        if not self._devices:
            raise ToolError("Gerade ist kein Gerät verbunden.")

        if not query:
            if len(self._devices) == 1:
                return self.names[0]
            raise ToolError(f"Welches Gerät meinst du: {join_de([quote(n) for n in self.names])}?")

        from nero.tools.match import pick

        return pick(query, [{"name": n} for n in self.names], key="name", kind="Gerät")["name"]

    async def call(self, name: str, tool: str, args: dict[str, Any] | None = None) -> Any:
        device = self._devices.get(name)
        if device is None:
            raise ToolError(f"{name} ist gerade nicht verbunden.")

        call_id = secrets.token_hex(4)
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._waiting[call_id] = future
        try:
            await device.send(json.dumps({"id": call_id, "tool": tool, "args": args or {}}))
            return await asyncio.wait_for(future, timeout=self._timeout)
        except TimeoutError as exc:
            raise ToolError(f"{name} antwortet nicht.") from exc
        except (OSError, RuntimeError) as exc:
            logger.warning("Senden an %s fehlgeschlagen: %s", name, exc)
            raise ToolError(f"Ich erreiche {name} gerade nicht.") from exc
        finally:
            self._waiting.pop(call_id, None)

    def on_reply(self, raw: str) -> None:
        """Antwort eines Agenten einsortieren. Muell wird verworfen, nicht geworfen."""
        try:
            payload = json.loads(raw)
            call_id = payload["id"]
        except (ValueError, KeyError, TypeError):
            logger.warning("Unverständliche Antwort vom Agenten verworfen.")
            return

        future = self._waiting.get(call_id)
        if future is None or future.done():
            # Zu spaet - der Aufruf ist schon in den Timeout gelaufen.
            return
        if error := payload.get("error"):
            future.set_exception(ToolError(f"Das hat nicht geklappt: {error}"))
        else:
            future.set_result(payload.get("result"))

    def shutdown(self) -> None:
        for future in self._waiting.values():
            if not future.done():
                with contextlib.suppress(Exception):
                    future.set_exception(ToolError("Nero fährt gerade herunter."))
        self._waiting.clear()
        self._devices.clear()
