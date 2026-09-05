"""Einstieg: ``python -m nero.agent``.

Laeuft auf jedem Rechner, den Nero steuern soll. Er kennt die Brain-URL, sein
Geraetetoken und seine Programmliste - sonst nichts.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("nero.agent")


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env.agent", env_file_encoding="utf-8", extra="ignore"
    )

    nero_brain_url: str = "http://localhost:8090"
    nero_device_token: str = ""
    # "gesprochener name=befehl,..." - nur was hier steht, laesst sich starten.
    nero_apps: str = ""


def parse_apps(raw: str) -> dict[str, str]:
    apps: dict[str, str] = {}
    for entry in raw.split(","):
        name, _, command = entry.partition("=")
        name, command = name.strip().casefold(), command.strip()
        if name and command:
            apps[name] = command
    return apps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m nero.agent", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true", help="Mehr Protokoll")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    from nero.agent import commands
    from nero.agent.bus import serve

    settings = AgentSettings()
    apps = parse_apps(settings.nero_apps)
    if not settings.nero_device_token:
        logger.warning("NERO_DEVICE_TOKEN ist leer - das klappt nur bei einem offenen Brain.")
    logger.info("Programme auf der Liste: %s", ", ".join(sorted(apps)) or "keins")

    async def handle(tool: str, call_args: dict) -> str:
        # Blockierendes subprocess gehoert nicht in die Ereignisschleife: ein
        # haengendes pactl wuerde sonst auch die Leitung zum Brain einfrieren.
        return await asyncio.to_thread(commands.dispatch, tool, call_args, apps)

    try:
        asyncio.run(serve(settings.nero_brain_url, settings.nero_device_token, handle))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
