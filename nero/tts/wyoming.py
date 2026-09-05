"""Piper ueber das Wyoming-Protokoll.

Piper laeuft als eigener Container (``rhasspy/wyoming-piper``) und spricht rohes
TCP auf Port 10200 - kein HTTP, deshalb auch kein ``httpx`` wie beim Rest.

Das Protokoll ist ein Strom von Events. Ein Event besteht aus einer
JSON-Kopfzeile, die mit ``\\n`` endet::

    {"type": "audio-chunk", "data_length": 42, "payload_length": 2048}\\n
    <42 Bytes JSON>
    <2048 Bytes Nutzlast>

``data`` steht je nach Version des Servers entweder inline in der Kopfzeile oder
als eigener Block dahinter; gelesen werden beide Formen. Das sind rund vierzig
Zeilen - das PyPI-Paket ``wyoming`` wuerde dafuer ``zeroconf`` und dessen Baum
mitbringen, den Nero nirgends braucht.

Eine Synthese sieht so aus::

    ->  synthesize   {"text": ..., "voice": {"name": ...}}
    <-  audio-start  {"rate": 22050, "width": 2, "channels": 1}
    <-  audio-chunk  x n   (payload = rohes PCM)
    <-  audio-stop

Die Bloecke werden gesammelt und bekommen am Ende einen WAV-Header - Rate,
Breite und Kanalzahl kommen aus ``audio-start``.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import logging
import wave
from dataclasses import dataclass, field
from typing import Any

from nero.errors import TtsError

logger = logging.getLogger(__name__)

# Womit Piper antwortet, wenn "audio-start" wider Erwarten fehlt. Entspricht den
# Piper-Stimmen in *-high (22,05 kHz, 16 bit, mono).
FALLBACK_FORMAT = (22050, 2, 1)


@dataclass(frozen=True)
class Event:
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    payload: bytes | None = None


async def read_event(reader: asyncio.StreamReader) -> Event | None:
    """Naechstes Event vom Strom. ``None`` am sauberen Ende."""
    line = await reader.readline()
    if not line:
        return None
    try:
        header = json.loads(line)
    except ValueError as exc:
        raise TtsError("Die Sprachausgabe antwortet nicht wie erwartet.") from exc

    data = header.get("data") or {}
    if (data_length := header.get("data_length")) is not None:
        data = json.loads(await reader.readexactly(data_length))

    payload = None
    if (payload_length := header.get("payload_length")) is not None:
        payload = await reader.readexactly(payload_length)

    return Event(type=header["type"], data=data, payload=payload)


async def write_event(writer: asyncio.StreamWriter, event: Event) -> None:
    header: dict[str, Any] = {"type": event.type}
    data = json.dumps(event.data, ensure_ascii=False).encode() if event.data else None
    if data is not None:
        header["data_length"] = len(data)
    if event.payload is not None:
        header["payload_length"] = len(event.payload)

    writer.write(json.dumps(header, ensure_ascii=False).encode() + b"\n")
    if data is not None:
        writer.write(data)
    if event.payload is not None:
        writer.write(event.payload)
    await writer.drain()


class WyomingTts:
    """Sprachausgabe ueber einen Wyoming-Server (Piper).

    Pro Synthese eine Verbindung. Das ist kein Geiz an der falschen Stelle: der
    Server haelt ohnehin nur eine Anfrage gleichzeitig, und eine dauerhaft offene
    TCP-Verbindung zu einem Nachbarcontainer waere mehr Zustand als Gewinn.
    """

    name = "wyoming"

    def __init__(self, host: str, port: int, voice: str = "", timeout: float = 20.0) -> None:
        self._host = host
        self._port = port
        self._voice = voice
        self._timeout = timeout

    async def synthesize(self, text: str) -> bytes:
        try:
            return await asyncio.wait_for(self._synthesize(text), timeout=self._timeout)
        except TimeoutError as exc:
            raise TtsError("Die Sprachausgabe hat zu lange gebraucht.") from exc
        except (OSError, asyncio.IncompleteReadError) as exc:
            logger.warning("Piper unter %s:%s nicht erreichbar: %s", self._host, self._port, exc)
            raise TtsError("Ich erreiche die Sprachausgabe gerade nicht.") from exc

    async def _synthesize(self, text: str) -> bytes:
        reader, writer = await asyncio.open_connection(self._host, self._port)
        try:
            data: dict[str, Any] = {"text": text}
            if self._voice:
                data["voice"] = {"name": self._voice}
            await write_event(writer, Event("synthesize", data))

            audio_format = FALLBACK_FORMAT
            chunks: list[bytes] = []
            while (event := await read_event(reader)) is not None:
                if event.type == "audio-start":
                    audio_format = _format_of(event.data, audio_format)
                elif event.type == "audio-chunk":
                    if not chunks:
                        # Manche Versionen schicken kein audio-start, das Format
                        # steht dann an jedem Block.
                        audio_format = _format_of(event.data, audio_format)
                    if event.payload:
                        chunks.append(event.payload)
                elif event.type == "audio-stop":
                    break
        finally:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()

        if not chunks:
            raise TtsError("Die Sprachausgabe hat nichts geliefert.")
        return to_wav(b"".join(chunks), *audio_format)

    async def aclose(self) -> None:
        return None


def _format_of(data: dict[str, Any], fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    rate, width, channels = fallback
    return (
        int(data.get("rate") or rate),
        int(data.get("width") or width),
        int(data.get("channels") or channels),
    )


def to_wav(pcm: bytes, rate: int, width: int, channels: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(width)
        out.setframerate(rate)
        out.writeframes(pcm)
    return buffer.getvalue()
