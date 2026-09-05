"""Tools, die einen Rechner steuern statt der Everything App.

Der einzige Bruch mit dem Muster der uebrigen Tools: hier steht kein
REST-Endpunkt am Ende, sondern ein Agent am anderen Ende einer WebSocket-
Leitung. Alles andere bleibt gleich - auch dass die Antwort aus einer Vorlage
kommt und nicht aus einem Modell.

``device.type_text`` ist als destruktiv markiert und fragt zurueck. Das ist
keine Uebervorsicht: getippt wird in das Fenster, das gerade den Fokus hat, und
der Text kommt aus einer Spracherkennung. Ein Missverstaendnis landet sonst
mitten in einem offenen Dokument oder einem Terminal.
"""

from __future__ import annotations

from typing import Any

from nero.errors import ToolError
from nero.speech import join_de
from nero.tools.base import ParamSpec, Tool, ToolContext

DEVICE_PARAM = ParamSpec(
    "Name des Geräts, etwa 'Laptop' oder 'PC'. Weglassen, wenn nur eines verbunden ist."
)


def _bus(ctx: ToolContext):
    if ctx.devices is None:
        raise ToolError("Der Gerätebus ist nicht eingerichtet.")
    return ctx.devices


async def _call(ctx: ToolContext, device: str | None, tool: str, **args: Any) -> dict[str, Any]:
    bus = _bus(ctx)
    name = bus.resolve(device)
    result = await bus.call(name, tool, args)
    return {"device": name, "result": result}


async def lock(ctx: ToolContext, device: str | None = None) -> dict[str, Any]:
    return await _call(ctx, device, "lock")


async def open_app(ctx: ToolContext, app: str, device: str | None = None) -> dict[str, Any]:
    return await _call(ctx, device, "open_app", app=app)


async def set_volume(ctx: ToolContext, level: Any, device: str | None = None) -> dict[str, Any]:
    try:
        value = max(0, min(100, int(float(str(level).replace("%", "").replace(",", ".")))))
    except (TypeError, ValueError) as exc:
        raise ToolError("Ich habe die Lautstärke nicht verstanden.") from exc
    return await _call(ctx, device, "volume", level=value)


async def type_text(ctx: ToolContext, text: str, device: str | None = None) -> dict[str, Any]:
    return await _call(ctx, device, "type_text", text=text)


async def devices_online(ctx: ToolContext) -> list[str]:
    return _bus(ctx).names


def _said(result: dict[str, Any], ctx: ToolContext) -> str:
    """Was der Agent gemeldet hat - er kennt seinen Rechner besser als wir."""
    said = str(result.get("result") or "").strip()
    return said or "Erledigt."


TOOLS = [
    Tool(
        name="device.lock",
        description="Den Bildschirm eines Rechners sperren",
        params={"device": DEVICE_PARAM},
        handler=lock,
        speak=_said,
    ),
    Tool(
        name="device.open_app",
        description="Ein Programm auf einem Rechner öffnen",
        params={
            "app": ParamSpec("Name des Programms, etwa 'Firefox' oder 'Musik'", required=True),
            "device": DEVICE_PARAM,
        },
        handler=open_app,
        speak=_said,
    ),
    Tool(
        name="device.volume",
        description="Die Lautstärke eines Rechners setzen",
        params={
            "level": ParamSpec("Lautstärke von 0 bis 100", type="integer", required=True),
            "device": DEVICE_PARAM,
        },
        handler=set_volume,
        speak=_said,
    ),
    Tool(
        name="device.type_text",
        description="Text auf einem Rechner eintippen",
        params={
            "text": ParamSpec("Der Text, der getippt werden soll", required=True),
            "device": DEVICE_PARAM,
        },
        handler=type_text,
        # Getippt wird in das Fenster mit dem Fokus - hier wird zurueckgefragt.
        destructive=True,
        speak=_said,
    ),
    Tool(
        name="device.list",
        description="Welche Geräte gerade verbunden sind",
        params={},
        handler=devices_online,
        speak=lambda names, ctx: (
            "Gerade ist kein Gerät verbunden."
            if not names
            else f"Verbunden: {join_de(names)}."
        ),
    ),
]
