"""Einstieg: ``python -m nero.satellite``.

Laeuft dauerhaft neben dem Rechner, an dem gesprochen wird. Alles, was er kennt,
sind die Brain-URL und sein eigenes Geraetetoken - kein API-Schluessel, kein
App-Token. Das ist Grundregel 1 aus dem Plan.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from nero.satellite.config import SatelliteSettings

logger = logging.getLogger("nero.satellite")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m nero.satellite", description=__doc__)
    parser.add_argument(
        "--geraete", action="store_true", help="Verfügbare Audiogeräte auflisten und beenden"
    )
    parser.add_argument("--pegel", action="store_true", help="Nur den Mikrofonpegel anzeigen")
    parser.add_argument("-v", "--verbose", action="store_true", help="Mehr Protokoll")
    return parser.parse_args(argv)


async def _run(settings: SatelliteSettings) -> None:
    from nero.satellite.audio import Microphone, play
    from nero.satellite.client import BrainClient
    from nero.satellite.runner import Satellite
    from nero.satellite.wake import WakeWord

    wake = WakeWord(
        model=settings.nero_wake_model,
        threshold=settings.nero_wake_threshold,
        cooldown=settings.nero_wake_cooldown_seconds,
        vad_threshold=settings.nero_wake_vad_threshold,
    )
    brain = BrainClient(
        settings.nero_brain_url,
        settings.nero_device_token,
        settings.request_timeout_seconds,
    )

    async def _play(wav: bytes) -> None:
        await play(wav, settings.nero_output_device)

    try:
        with Microphone(settings.nero_input_device) as mic:
            await Satellite(settings, mic, wake, brain, _play).run(mic.frames())
    finally:
        await brain.aclose()


async def _pegel(settings: SatelliteSettings) -> None:
    """Hilfe beim Einstellen von nero_silence_factor.

    Zeigt fortlaufend den gemessenen Pegel. Einmal still sein, einmal normal
    sprechen - der Faktor gehoert dazwischen.
    """
    from nero.satellite.audio import Microphone
    from nero.satellite.endpoint import rms

    print("Pegel (Strg-C beendet). Erst still sein, dann normal sprechen.")
    with Microphone(settings.nero_input_device) as mic:
        async for frame in mic.frames():
            pegel = rms(frame)
            balken = "#" * min(60, int(pegel / 50))
            print(f"\r{pegel:7.0f}  {balken:<60}", end="", flush=True)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.geraete:
        from nero.satellite.audio import list_devices

        print(list_devices())
        return 0

    settings = SatelliteSettings()
    if not settings.nero_device_token:
        logger.warning("NERO_DEVICE_TOKEN ist leer - das klappt nur bei einem offenen Brain.")

    try:
        asyncio.run(_pegel(settings) if args.pegel else _run(settings))
    except KeyboardInterrupt:
        print()
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
