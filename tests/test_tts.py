"""Sprachausgabe: das Wyoming-Protokoll, der Endpunkt, die Textaufbereitung.

Fuer Wyoming gibt es kein respx-Aequivalent, also laeuft hier ein echter kleiner
Server auf 127.0.0.1 - eine Loopback-Verbindung, die das Framing in beide
Richtungen prueft. Nach draussen geht weiterhin kein Paket.
"""

from __future__ import annotations

import asyncio
import io
import json
import wave

import pytest
from fastapi.testclient import TestClient

from nero.config import get_settings
from nero.errors import TtsError
from nero.speech import join_de, normalize_for_speech, quote
from nero.tts.null import NullTts
from nero.tts.wyoming import Event, WyomingTts, read_event, to_wav, write_event
from tests.conftest import BASE_URL

RATE, WIDTH, CHANNELS = 22050, 2, 1
CHUNKS = [b"\x01\x02" * 512, b"\x03\x04" * 512]


class FakePiper:
    """Ein Wyoming-Server, der auf "synthesize" mit zwei Bloecken antwortet."""

    def __init__(self, *, inline_data: bool = False, chunks: list[bytes] | None = None) -> None:
        self.inline_data = inline_data
        self.chunks = CHUNKS if chunks is None else chunks
        self.seen: list[Event] = []
        self._server: asyncio.Server | None = None

    async def __aenter__(self) -> FakePiper:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc: object) -> None:
        assert self._server is not None
        self._server.close()
        await self._server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        event = await read_event(reader)
        if event is None:
            return
        self.seen.append(event)

        fmt = {"rate": RATE, "width": WIDTH, "channels": CHANNELS}
        await self._send(writer, Event("audio-start", fmt))
        for chunk in self.chunks:
            await self._send(writer, Event("audio-chunk", fmt, payload=chunk))
        await self._send(writer, Event("audio-stop", {"timestamp": 1}))
        writer.close()

    async def _send(self, writer: asyncio.StreamWriter, event: Event) -> None:
        if not self.inline_data:
            await write_event(writer, event)
            return
        # Die andere zulaessige Form: data steht in der Kopfzeile statt dahinter.
        header: dict[str, object] = {"type": event.type, "data": event.data}
        if event.payload is not None:
            header["payload_length"] = len(event.payload)
        writer.write(json.dumps(header).encode() + b"\n")
        if event.payload is not None:
            writer.write(event.payload)
        await writer.drain()


def read_wav(data: bytes) -> tuple[tuple[int, int, int], bytes]:
    with wave.open(io.BytesIO(data), "rb") as wav:
        params = (wav.getframerate(), wav.getsampwidth(), wav.getnchannels())
        return params, wav.readframes(wav.getnframes())


# ---- Protokoll ------------------------------------------------------------


async def test_synthese_liefert_ein_lesbares_wav():
    async with FakePiper() as piper:
        tts = WyomingTts("127.0.0.1", piper.port)
        wav = await tts.synthesize("Heute hast du drei Termine.")

    params, frames = read_wav(wav)
    assert params == (RATE, WIDTH, CHANNELS)
    assert frames == b"".join(CHUNKS)


async def test_der_gesendete_befehl_ist_ein_synthesize_event():
    async with FakePiper() as piper:
        await WyomingTts("127.0.0.1", piper.port).synthesize("Guten Morgen")

    assert len(piper.seen) == 1
    assert piper.seen[0].type == "synthesize"
    assert piper.seen[0].data["text"] == "Guten Morgen"


async def test_data_inline_in_der_kopfzeile_wird_auch_gelesen():
    """wyoming-piper schreibt je nach Version die eine oder die andere Form."""
    async with FakePiper(inline_data=True) as piper:
        wav = await WyomingTts("127.0.0.1", piper.port).synthesize("Test")

    assert read_wav(wav) == ((RATE, WIDTH, CHANNELS), b"".join(CHUNKS))


async def test_stimme_wird_nur_mitgeschickt_wenn_konfiguriert():
    async with FakePiper() as piper:
        await WyomingTts("127.0.0.1", piper.port).synthesize("Test")
        assert "voice" not in piper.seen[0].data

        await WyomingTts("127.0.0.1", piper.port, voice="de_DE-thorsten-high").synthesize("Test")
        assert piper.seen[1].data["voice"] == {"name": "de_DE-thorsten-high"}


async def test_umlaute_ueberleben_das_framing():
    """data_length zaehlt Bytes, nicht Zeichen - ein klassischer Patzer."""
    text = "Nächster Termin: Analysis-Übungsblatt abgeben, um 9:30 Uhr"
    async with FakePiper() as piper:
        await WyomingTts("127.0.0.1", piper.port).synthesize(text)
    assert piper.seen[0].data["text"] == text


async def test_piper_nicht_erreichbar_wird_zu_einer_vorlesbaren_meldung():
    async with FakePiper() as piper:
        port = piper.port  # Server ist nach dem Block zu.

    with pytest.raises(TtsError) as exc:
        await WyomingTts("127.0.0.1", port).synthesize("Test")
    assert exc.value.speech == "Ich erreiche die Sprachausgabe gerade nicht."


async def test_antwort_ohne_audio_ist_ein_fehler_kein_leeres_wav():
    async with FakePiper(chunks=[]) as piper:
        with pytest.raises(TtsError):
            await WyomingTts("127.0.0.1", piper.port).synthesize("Test")


async def test_zeitueberschreitung_wird_zu_einer_vorlesbaren_meldung():
    # Der Handler haengt an einem Event statt an einem sleep und schliesst am
    # Ende seinen Writer: ab Python 3.12 wartet Server.wait_closed() sowohl auf
    # die laufenden Handler als auch auf deren offene Verbindungen.
    release = asyncio.Event()

    async def never_answer(reader, writer):
        try:
            await release.wait()
        finally:
            writer.close()

    server = await asyncio.start_server(never_answer, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        with pytest.raises(TtsError) as exc:
            await WyomingTts("127.0.0.1", port, timeout=0.2).synthesize("Test")
        assert exc.value.speech == "Die Sprachausgabe hat zu lange gebraucht."
    finally:
        release.set()
        server.close()
        await server.wait_closed()


def test_to_wav_haengt_nur_einen_header_an():
    wav = to_wav(b"\x00\x01" * 100, RATE, WIDTH, CHANNELS)
    assert wav[:4] == b"RIFF"
    assert read_wav(wav)[1] == b"\x00\x01" * 100


async def test_null_backend_spricht_nicht():
    with pytest.raises(TtsError):
        await NullTts().synthesize("Test")


# ---- Textaufbereitung -----------------------------------------------------


def test_anfuehrungszeichen_verschwinden_vor_der_synthese():
    satz = f"Aufgabe {quote('Analysis-Übungsblatt abgeben')} angelegt."
    assert normalize_for_speech(satz) == "Aufgabe Analysis-Übungsblatt abgeben angelegt."


def test_umbrueche_werden_zu_leerzeichen():
    assert normalize_for_speech("Heute:\n  drei Termine\n") == "Heute: drei Termine"


def test_uhrzeiten_und_zahlen_bleiben_unangetastet():
    satz = join_de(["9:30 Uhr Analysis", "14:00 Uhr Sport"])
    assert normalize_for_speech(satz) == "9:30 Uhr Analysis und 14:00 Uhr Sport"


def test_nur_anfuehrungszeichen_ergibt_leeren_text():
    assert normalize_for_speech(' „“ \n ') == ""


# ---- Endpunkt -------------------------------------------------------------


class StubTts:
    name = "stub"

    def __init__(self) -> None:
        self.wav = to_wav(b"\x07\x08" * 64, RATE, WIDTH, CHANNELS)
        self.seen: list[str] = []

    async def synthesize(self, text: str) -> bytes:
        self.seen.append(text)
        return self.wav

    async def aclose(self) -> None:
        return None


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_API_URL", BASE_URL)
    monkeypatch.setenv("NERO_APP_TOKEN", "test-token")
    monkeypatch.setenv("NERO_LLM_PROVIDER", "null")
    monkeypatch.setenv("NERO_TTS_PROVIDER", "null")
    monkeypatch.setenv("USAGE_FILE", str(tmp_path / "usage.json"))
    get_settings.cache_clear()

    from nero.main import app

    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def test_speak_liefert_ein_wav(api):
    from nero.main import app

    app.state.tts = stub = StubTts()
    response = api.post("/speak", json={"text": "Heute hast du drei Termine."})

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content == stub.wav


def test_speak_normalisiert_vor_der_synthese(api):
    from nero.main import app

    app.state.tts = stub = StubTts()
    api.post("/speak", json={"text": "Aufgabe „Analysis“\n angelegt."})
    assert stub.seen == ["Aufgabe Analysis angelegt."]


def test_speak_ohne_sprachausgabe_ist_503(api):
    body = api.post("/speak", json={"text": "Test"})
    assert body.status_code == 503
    assert body.json()["detail"] == "Sprachausgabe ist nicht eingerichtet."


def test_speak_ohne_text_ist_400(api):
    assert api.post("/speak", json={"text": "  \n "}).status_code == 400
    assert api.post("/speak", json={}).status_code == 422
    assert api.post("/speak", json={"text": "a" * 1001}).status_code == 422


def test_health_meldet_die_sprachausgabe(api):
    assert api.get("/health").json()["tts"] == "null"
