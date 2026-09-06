"""Der Satellit ohne Mikrofon.

Alles, was Hardware anfasst, steckt in ``satellite/audio.py`` und ``wake.py``.
Der Rest - wann eine Aufnahme endet, was danach passiert, was bei einem
ausgefallenen Brain geschieht - laeuft hier gegen Bloecke aus Bytes und ist
damit genau in den Faellen pruefbar, die man mit echter Hardware kaum
provoziert.
"""

from __future__ import annotations

import array
import io
import json
import wave
from collections.abc import AsyncIterator

import httpx
import pytest
import respx

from nero.satellite.client import BrainClient
from nero.satellite.config import FRAME_SAMPLES, SAMPLE_RATE, SatelliteSettings
from nero.satellite.endpoint import Endpointer, State, rms
from nero.satellite.runner import Satellite, ist_zustimmung, preroll_frames

BRAIN = "http://brain.test"
FRAME_SECONDS = FRAME_SAMPLES / SAMPLE_RATE  # 80 ms


def frame(amplitude: int) -> bytes:
    """Ein Block konstanter Lautstaerke - Inhalt egal, Pegel zaehlt."""
    return array.array("h", [amplitude] * FRAME_SAMPLES).tobytes()


STILL = frame(20)
LAUT = frame(4000)


def frames_for(seconds: float, block: bytes) -> list[bytes]:
    return [block] * round(seconds / FRAME_SECONDS)


async def stream(blocks: list[bytes]) -> AsyncIterator[bytes]:
    for block in blocks:
        yield block


# ---- Pegelmessung ----------------------------------------------------------


def test_rms_misst_die_lautstaerke():
    assert rms(frame(0)) == 0.0
    assert rms(frame(1000)) == pytest.approx(1000, rel=1e-6)
    assert rms(STILL) < rms(LAUT)


def test_ungerade_bytezahl_stuerzt_nicht_ab():
    """Ein abgeschnittener Block darf den Satelliten nicht beenden."""
    assert rms(b"\x01") == 0.0
    assert rms(LAUT[:-1]) > 0


# ---- Endpointer ------------------------------------------------------------


def make_endpointer(**kwargs) -> Endpointer:
    return Endpointer(**{"silence_seconds": 0.8, "noise_floor": 100.0, **kwargs})


def test_stille_nach_dem_sprechen_beendet_die_aufnahme():
    ep = make_endpointer()
    for block in frames_for(1.0, LAUT):
        assert ep.feed(block) is State.SPEECH

    # Kurze Pausen im Satz beenden noch nichts.
    for block in frames_for(0.4, STILL):
        assert ep.feed(block) is State.SPEECH

    assert ep.feed(LAUT) is State.SPEECH  # es ging weiter
    for block in frames_for(0.8, STILL):
        ep.feed(block)
    assert ep.state is State.DONE


def test_wer_nichts_sagt_bekommt_keine_aufnahme():
    """Wake Word gerufen, dann doch nichts gesagt."""
    ep = make_endpointer(max_lead_seconds=1.0)
    for block in frames_for(1.1, STILL):
        ep.feed(block)
    assert ep.state is State.EMPTY


def test_dauerreden_wird_nach_der_notbremse_beendet():
    """Fernseher oder Gespräch im Raum - irgendwann ist Schluss."""
    ep = make_endpointer(max_command_seconds=2.0)
    for block in frames_for(3.0, LAUT):
        ep.feed(block)
    assert ep.state is State.DONE


def test_schwelle_haengt_am_gemessenen_grundrauschen():
    leise = make_endpointer(noise_floor=100.0, silence_factor=2.5)
    laut = make_endpointer(noise_floor=800.0, silence_factor=2.5)
    assert leise.threshold == 250.0
    assert laut.threshold == 2000.0

    # Derselbe Block ist im leisen Raum Sprache und im lauten nur Rauschen.
    mittel = frame(500)
    assert leise.feed(mittel) is State.SPEECH
    assert laut.feed(mittel) is State.LEAD


def test_grundrauschen_lernt_den_raum_waehrend_des_wartens():
    ep = make_endpointer(noise_floor=1000.0, noise_floor_min=10.0, max_lead_seconds=99.0)
    for block in frames_for(3.0, frame(50)):
        ep.feed(block)
    # Der Raum ist leiser als angenommen - das faellt schnell auf.
    assert ep.noise_floor < 300.0


def test_grundrauschen_faellt_nie_unter_die_untergrenze():
    """Sonst zöge ein absolut stiller Raum die Schwelle auf null."""
    ep = make_endpointer(noise_floor=200.0, noise_floor_min=60.0, max_lead_seconds=99.0)
    for block in frames_for(5.0, frame(0)):
        ep.feed(block)
    assert ep.noise_floor == 60.0


def test_nach_dem_ende_aendert_sich_nichts_mehr():
    ep = make_endpointer(max_lead_seconds=0.1)
    ep.feed(STILL)
    ep.feed(STILL)
    assert ep.state is State.EMPTY
    assert ep.feed(LAUT) is State.EMPTY


# ---- Brain-Client ----------------------------------------------------------


@respx.mock
async def test_listen_schickt_ein_wav_mit_token():
    route = respx.post(f"{BRAIN}/listen").mock(
        return_value=httpx.Response(200, json={"speech": "Es ist 9 Uhr.", "text": "wie spät"})
    )
    client = BrainClient(BRAIN, token="geheim")
    try:
        assert (await client.listen(b"RIFFxxxx"))["speech"] == "Es ist 9 Uhr."
    finally:
        await client.aclose()

    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer geheim"
    assert b'filename="befehl.wav"' in request.content


@respx.mock
async def test_brain_weg_beendet_den_satelliten_nicht():
    respx.post(f"{BRAIN}/listen").mock(side_effect=httpx.ConnectError("weg"))
    client = BrainClient(BRAIN)
    try:
        assert (await client.listen(b"x"))["speech"] == "Ich erreiche das Brain gerade nicht."
    finally:
        await client.aclose()


@respx.mock
async def test_abgelehntes_token_wird_gesagt_statt_geworfen():
    respx.post(f"{BRAIN}/listen").mock(return_value=httpx.Response(401, json={"detail": "nein"}))
    client = BrainClient(BRAIN, token="falsch")
    try:
        assert (await client.listen(b"x"))["speech"] == "Das Brain kennt mein Token nicht."
    finally:
        await client.aclose()


@respx.mock
async def test_ohne_sprachausgabe_bleibt_es_stumm_statt_laut():
    respx.post(f"{BRAIN}/speak").mock(return_value=httpx.Response(503, json={"detail": "aus"}))
    client = BrainClient(BRAIN)
    try:
        assert await client.speak("Guten Morgen") is None
        assert await client.speak("") is None
    finally:
        await client.aclose()


# ---- Die Schleife ----------------------------------------------------------


class FakeWake:
    """Loest bei genau den angegebenen Blocknummern aus."""

    name = "fake"

    def __init__(self, bei: set[int]) -> None:
        self._bei = bei
        self.gesehen = 0
        self.resets = 0

    def heard(self, frame: bytes) -> bool:
        self.gesehen += 1
        return self.gesehen in self._bei

    def reset(self) -> None:
        self.resets += 1


class FakeMic:
    def __init__(self) -> None:
        self.drains = 0

    def drain(self) -> None:
        self.drains += 1


class FakeBrain:
    """Antwortet der Reihe nach mit den vorgegebenen Koerpern.

    ``antworten`` ist eine Liste von ``(text, body)``: was das Brain verstanden
    haben will und was es zurueckgibt. Die letzte Antwort gilt weiter, wenn mehr
    Befehle kommen als Antworten vorgesehen sind.
    """

    def __init__(self, speech: str = "Es ist 9 Uhr.", antworten: list[dict] | None = None) -> None:
        self.speech = speech
        self.antworten = antworten
        self.uploads: list[bytes] = []
        self.gesprochen: list[str] = []
        self.bestaetigt: list[str] = []

    async def listen(self, wav: bytes) -> dict:
        self.uploads.append(wav)
        if self.antworten:
            index = min(len(self.uploads) - 1, len(self.antworten) - 1)
            return {"text": "wie spät ist es", **self.antworten[index]}
        return {"speech": self.speech, "text": "wie spät ist es"}

    async def confirm(self, token: str) -> dict:
        self.bestaetigt.append(token)
        return {"speech": "Getippt.", "text": ""}

    async def speak(self, text: str) -> bytes:
        self.gesprochen.append(text)
        return b"WAV"


def make_satellite(wake, brain, **overrides):
    settings = SatelliteSettings(
        nero_silence_seconds=0.4,
        nero_max_lead_seconds=0.5,
        nero_max_command_seconds=5.0,
        nero_noise_floor_min=100.0,
        nero_silence_factor=2.5,
        **overrides,
    )
    mic = FakeMic()
    gespielt: list[bytes] = []

    async def play(wav: bytes) -> None:
        gespielt.append(wav)

    return Satellite(settings, mic, wake, brain, play), mic, gespielt


async def test_ein_kompletter_durchlauf():
    wake = FakeWake(bei={2})
    brain = FakeBrain()
    satellite, mic, gespielt = make_satellite(wake, brain)

    blocks = [STILL, STILL] + frames_for(1.0, LAUT) + frames_for(0.5, STILL)
    await satellite.run(stream(blocks))

    assert len(brain.uploads) == 1
    assert brain.gesprochen == ["Es ist 9 Uhr."]
    assert gespielt == [b"WAV"]
    # Nach dem Befehl wird aufgeraeumt, damit die eigene Stimme nichts ausloest.
    assert wake.resets == 1 and mic.drains == 1


async def test_der_upload_ist_ein_lesbares_wav():
    wake = FakeWake(bei={1})
    brain = FakeBrain()
    satellite, _, _ = make_satellite(wake, brain)

    await satellite.run(stream(frames_for(1.0, LAUT) + frames_for(0.5, STILL)))

    with wave.open(io.BytesIO(brain.uploads[0]), "rb") as wav:
        assert (wav.getframerate(), wav.getsampwidth(), wav.getnchannels()) == (SAMPLE_RATE, 2, 1)
        assert wav.getnframes() > 0


async def test_die_aufnahme_beginnt_vor_dem_wake_word():
    """Sonst fehlte bei „Hey Mycroft, was steht heute an" der Anfang."""
    laut = frames_for(1.0, LAUT)
    vorlauf = frames_for(2.0, STILL)
    # Das Wake Word faellt beim letzten stillen Block, direkt vor dem Sprechen -
    # so, wie jemand "Hey Mycroft, was steht heute an" in einem Zug spricht.
    wake = FakeWake(bei={len(vorlauf)})
    brain = FakeBrain()
    satellite, _, _ = make_satellite(wake, brain)

    await satellite.run(stream(vorlauf + laut + frames_for(0.5, STILL)))

    with wave.open(io.BytesIO(brain.uploads[0]), "rb") as wav:
        blocks = wav.getnframes() / FRAME_SAMPLES
    # Ohne Ringpuffer waeren es nur die lauten Blöcke plus die Stille am Ende.
    assert blocks >= preroll_frames() + len(laut)


async def test_wake_word_ohne_befehl_laedt_nichts_hoch():
    wake = FakeWake(bei={1})
    brain = FakeBrain()
    satellite, mic, _ = make_satellite(wake, brain)

    await satellite.run(stream(frames_for(2.0, STILL)))

    assert brain.uploads == []
    assert wake.resets == 1 and mic.drains == 1


async def test_zwei_befehle_nacheinander():
    wake = FakeWake(bei={1, 20})
    brain = FakeBrain()
    satellite, mic, _ = make_satellite(wake, brain)

    einer = frames_for(0.8, LAUT) + frames_for(0.5, STILL)
    await satellite.run(stream(einer + einer + frames_for(0.5, STILL)))

    assert len(brain.uploads) == 2
    assert mic.drains == 2


async def test_stumme_antwort_wird_nicht_abgespielt():
    wake = FakeWake(bei={1})
    brain = FakeBrain(speech="")
    satellite, _, gespielt = make_satellite(wake, brain)

    await satellite.run(stream(frames_for(0.8, LAUT) + frames_for(0.5, STILL)))

    assert len(brain.uploads) == 1
    assert brain.gesprochen == [] and gespielt == []


# ---- Die Rueckfrage --------------------------------------------------------


def test_zustimmung_ist_eine_geschlossene_liste():
    """Kein Modellaufruf: was zaehlt, steht in JA und sonst nirgends."""
    for satz in ("ja", "Ja.", "ja bitte", "mach das", "OK!", "bestätigt"):
        assert ist_zustimmung(satz)
    for satz in ("nein", "lieber nicht", "was steht heute an", "ja aber später", ""):
        assert not ist_zustimmung(satz)


RUECKFRAGE = {
    "speech": "Soll ich wirklich Text tippen (text: Hallo Welt)?",
    "needs_confirmation": True,
    "confirm_token": "abc123",
}

EIN_BEFEHL = frames_for(0.8, LAUT) + frames_for(0.5, STILL)


class WakeBeiJedemSatz:
    """Loest beim ersten lauten Block nach jedem ``reset()`` aus.

    Fuer Ablaeufe ueber mehrere Befehle hinweg handlicher als feste
    Blocknummern: wie viele Bloecke die Aufnahme schluckt, haengt am
    Endpointer und nicht am Test.
    """

    name = "fake"

    def __init__(self) -> None:
        self._scharf = True
        self.resets = 0

    def heard(self, frame: bytes) -> bool:
        if self._scharf and frame == LAUT:
            self._scharf = False
            return True
        return False

    def reset(self) -> None:
        self._scharf = True
        self.resets += 1


def befehle(anzahl: int) -> list[bytes]:
    return EIN_BEFEHL * anzahl + frames_for(0.5, STILL)


async def test_ja_auf_eine_rueckfrage_fuehrt_aus():
    brain = FakeBrain(antworten=[RUECKFRAGE, {"speech": "", "text": "ja"}])
    satellite, _, _ = make_satellite(WakeBeiJedemSatz(), brain)

    await satellite.run(stream(befehle(2)))

    assert brain.bestaetigt == ["abc123"]
    assert brain.gesprochen == [RUECKFRAGE["speech"], "Getippt."]


async def test_etwas_anderes_gesagt_zaehlt_als_nein():
    """Nur ein "ja" bestaetigt. Alles andere verwirft die Rueckfrage."""
    agenda = {"speech": "Heute hast du 3 Einträge.", "text": "was steht heute an"}
    brain = FakeBrain(antworten=[RUECKFRAGE, agenda])
    satellite, _, _ = make_satellite(WakeBeiJedemSatz(), brain)

    await satellite.run(stream(befehle(2)))

    assert brain.bestaetigt == []
    # Der zweite Befehl wird trotzdem beantwortet - er war ja einer.
    assert brain.gesprochen == [RUECKFRAGE["speech"], "Heute hast du 3 Einträge."]


async def test_ein_ja_ohne_offene_rueckfrage_bestaetigt_nichts():
    wake = FakeWake(bei={1})
    brain = FakeBrain(antworten=[{"speech": "Das habe ich nicht verstanden.", "text": "ja"}])
    satellite, _, _ = make_satellite(wake, brain)

    await satellite.run(stream(frames_for(0.8, LAUT) + frames_for(0.5, STILL)))

    assert brain.bestaetigt == []


async def test_eine_rueckfrage_gilt_nur_fuer_den_naechsten_befehl():
    """Sonst wuerde ein "ja" Minuten spaeter noch etwas ausloesen."""
    brain = FakeBrain(
        antworten=[
            RUECKFRAGE,
            {"speech": "Heute hast du 3 Einträge.", "text": "was steht heute an"},
            {"speech": "Das habe ich nicht verstanden.", "text": "ja"},
        ]
    )
    satellite, _, _ = make_satellite(WakeBeiJedemSatz(), brain)

    await satellite.run(stream(befehle(3)))

    assert len(brain.uploads) == 3
    assert brain.bestaetigt == []


@respx.mock
async def test_confirm_schickt_nur_das_token():
    route = respx.post(f"{BRAIN}/command").mock(
        return_value=httpx.Response(200, json={"speech": "Getippt.", "route": "confirm"})
    )
    client = BrainClient(BRAIN, token="geheim")
    try:
        assert (await client.confirm("abc123"))["speech"] == "Getippt."
    finally:
        await client.aclose()

    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer geheim"
    assert json.loads(request.content) == {"confirm_token": "abc123"}


@respx.mock
async def test_abgelaufene_rueckfrage_wird_gesagt_statt_geworfen():
    respx.post(f"{BRAIN}/command").mock(return_value=httpx.Response(410, json={"detail": "weg"}))
    client = BrainClient(BRAIN)
    try:
        assert (await client.confirm("alt"))["speech"] == "Die Rückfrage ist abgelaufen."
    finally:
        await client.aclose()


@respx.mock
async def test_brain_weg_beim_bestaetigen():
    respx.post(f"{BRAIN}/command").mock(side_effect=httpx.ConnectError("weg"))
    client = BrainClient(BRAIN)
    try:
        assert (await client.confirm("abc"))["speech"] == "Ich erreiche das Brain gerade nicht."
    finally:
        await client.aclose()
