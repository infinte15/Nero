"""Tools gegen eine nachgebaute Everything-App-API.

Die Antwortformen stammen aus den DTOs des Backends (CalendarEventDTO, TaskDTO,
HabitDTO, StudyGoalDTO, FlashcardDTO) - insbesondere die zeitzonenlosen
Zeitstempel.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from nero.errors import AppError, ToolError
from nero.schemas import ToolCall
from nero.tools.registry import dispatch
from tests.conftest import BASE_URL

EVENTS_URL = f"{BASE_URL}/api/calendar/events"


def event(title, start, **extra):
    return {"id": 1, "title": title, "startTime": start, "endTime": start, **extra}


# --------------------------------------------------------------------------- system


async def test_uhrzeit_ohne_api_aufruf(ctx):
    with respx.mock(assert_all_called=False) as mock:
        catch_all = mock.route(host="app.test")
        _tool, speech = await dispatch(ToolCall("system.time"), ctx)
    assert speech == "Es ist 9:30 Uhr."
    assert not catch_all.called, "system.time darf die App nicht anfassen"


async def test_datum(ctx):
    _tool, speech = await dispatch(ToolCall("system.date"), ctx)
    assert speech == "Heute ist Freitag, 4. September."


# --------------------------------------------------------------------------- agenda


@respx.mock
async def test_tagesagenda_zaehlt_und_liest_vor(ctx):
    respx.get(EVENTS_URL).mock(
        return_value=httpx.Response(
            200,
            json=[
                event("Analysis", "2026-09-04T09:00:00"),
                event("Mittagessen", "2026-09-04T12:00:00"),
                event("Sport", "2026-09-04T17:00:00"),
            ],
        )
    )
    _tool, speech = await dispatch(ToolCall("app.today_agenda"), ctx)
    assert speech == (
        "Heute hast du 3 Einträge: 9:00 Uhr Analysis, 12:00 Uhr Mittagessen "
        "und 17:00 Uhr Sport."
    )


@respx.mock
async def test_tagesagenda_sendet_naive_zeitstempel(ctx):
    route = respx.get(EVENTS_URL).mock(return_value=httpx.Response(200, json=[]))
    await dispatch(ToolCall("app.today_agenda"), ctx)

    params = route.calls.last.request.url.params
    assert params["startDate"] == "2026-09-04T00:00:00"
    assert params["endDate"] == "2026-09-04T23:59:59"
    # Ein Offset oder ein "Z" bricht LocalDateTime.parse() im Backend.
    assert "+" not in params["startDate"] and "Z" not in params["startDate"]


@respx.mock
async def test_tagesagenda_leer(ctx):
    respx.get(EVENTS_URL).mock(return_value=httpx.Response(200, json=[]))
    _tool, speech = await dispatch(ToolCall("app.today_agenda"), ctx)
    assert speech == "Heute steht nichts an."


@respx.mock
async def test_tagesagenda_kuerzt_lange_tage(ctx):
    respx.get(EVENTS_URL).mock(
        return_value=httpx.Response(
            200,
            json=[event(f"Block {i}", f"2026-09-04T{8 + i:02d}:00:00") for i in range(7)],
        )
    )
    _tool, speech = await dispatch(ToolCall("app.today_agenda"), ctx)
    assert speech.startswith("Heute hast du 7 Einträge:")
    assert speech.endswith(", und 2 weitere.")


@respx.mock
async def test_naechster_termin_ueberspringt_erledigtes_und_vergangenes(ctx):
    respx.get(EVENTS_URL).mock(
        return_value=httpx.Response(
            200,
            json=[
                event("Frühsport", "2026-09-04T07:00:00"),  # vorbei
                event("Erledigt", "2026-09-04T10:00:00", completedAt="2026-09-04T10:30:00"),
                event("Übersprungen", "2026-09-04T11:00:00", skippedAt="2026-09-04T11:00:00"),
                event("Analysis", "2026-09-04T14:00:00"),
            ],
        )
    )
    _tool, speech = await dispatch(ToolCall("app.next_event"), ctx)
    assert speech == "Als nächstes: Analysis heute um 14:00 Uhr."


@respx.mock
async def test_naechster_termin_an_einem_anderen_tag(ctx):
    respx.get(EVENTS_URL).mock(
        return_value=httpx.Response(200, json=[event("Zahnarzt", "2026-09-08T11:15:00")])
    )
    _tool, speech = await dispatch(ToolCall("app.next_event"), ctx)
    assert speech == "Als nächstes: Zahnarzt am Dienstag um 11:15 Uhr."


@respx.mock
async def test_naechster_termin_wenn_nichts_kommt(ctx):
    respx.get(EVENTS_URL).mock(return_value=httpx.Response(200, json=[]))
    _tool, speech = await dispatch(ToolCall("app.next_event"), ctx)
    assert speech == "In den nächsten sieben Tagen steht nichts an."


# --------------------------------------------------------------------------- tasks


@respx.mock
async def test_aufgabe_anlegen_mit_faelligkeit(ctx):
    route = respx.post(f"{BASE_URL}/api/tasks").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": 7,
                "title": "Analysis-Übungsblatt abgeben",
                "deadline": "2026-09-10T23:59:00",
            },
        )
    )
    call = ToolCall(
        "app.create_task", {"title": "Analysis-Übungsblatt abgeben", "due": "2026-09-10"}
    )
    _tool, speech = await dispatch(call, ctx)

    import json

    body = json.loads(route.calls.last.request.content)
    # Ein Datum wird zum Tagesende - "bis Donnerstag" heisst nicht "Donnerstag 0 Uhr".
    assert body == {"title": "Analysis-Übungsblatt abgeben", "deadline": "2026-09-10T23:59:00"}
    assert speech == "Aufgabe „Analysis-Übungsblatt abgeben“ angelegt. Fällig am Donnerstag."


@respx.mock
async def test_aufgabe_anlegen_nur_mit_titel(ctx):
    route = respx.post(f"{BASE_URL}/api/tasks").mock(
        return_value=httpx.Response(201, json={"id": 8, "title": "Milch kaufen"})
    )
    _tool, speech = await dispatch(ToolCall("app.create_task", {"title": "Milch kaufen"}), ctx)

    import json

    assert json.loads(route.calls.last.request.content) == {"title": "Milch kaufen"}
    assert speech == "Aufgabe „Milch kaufen“ angelegt."


async def test_aufgabe_anlegen_mit_unlesbarem_datum(ctx):
    with pytest.raises(ToolError, match="Fälligkeitsdatum"):
        await dispatch(ToolCall("app.create_task", {"title": "X", "due": "Donnerstag"}), ctx)


async def test_pflichtparameter_fehlt(ctx):
    with pytest.raises(ToolError, match="fehlt mir noch eine Angabe"):
        await dispatch(ToolCall("app.create_task", {}), ctx)


async def test_erfundene_parameter_werden_verworfen(ctx):
    """Ein Modell darf sich Argumente ausdenken, ohne dass das einen TypeError wirft."""
    with respx.mock:
        respx.post(f"{BASE_URL}/api/tasks").mock(
            return_value=httpx.Response(201, json={"id": 9, "title": "X"})
        )
        call = ToolCall("app.create_task", {"title": "X", "prioritaet": "hoch", "farbe": "rot"})
        _tool, speech = await dispatch(call, ctx)
    assert speech == "Aufgabe „X“ angelegt."


@respx.mock
async def test_offene_aufgaben(ctx):
    respx.get(f"{BASE_URL}/api/tasks/status/TODO").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": i, "title": t} for i, t in enumerate(["Milch", "Steuer", "Bad", "Auto"])],
        )
    )
    _tool, speech = await dispatch(ToolCall("app.open_tasks"), ctx)
    assert speech == "Du hast 4 offene Aufgaben: Milch, Steuer und Bad, und 1 weitere."


@respx.mock
async def test_aufgabe_abhaken_loest_titel_auf(ctx):
    respx.get(f"{BASE_URL}/api/tasks/status/TODO").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 3, "title": "Analysis-Übungsblatt abgeben"},
                {"id": 4, "title": "Milch kaufen"},
            ],
        )
    )
    complete = respx.put(f"{BASE_URL}/api/tasks/3/complete").mock(
        return_value=httpx.Response(200, json={})
    )
    _tool, speech = await dispatch(ToolCall("app.complete_task", {"title": "Analysis"}), ctx)
    assert complete.called
    assert speech == "Aufgabe „Analysis-Übungsblatt abgeben“ ist erledigt."


@respx.mock
async def test_aufgabe_abhaken_ohne_treffer_raet_nicht(ctx):
    respx.get(f"{BASE_URL}/api/tasks/status/TODO").mock(
        return_value=httpx.Response(200, json=[{"id": 3, "title": "Milch kaufen"}])
    )
    with pytest.raises(ToolError, match="finde keine Aufgabe"):
        await dispatch(ToolCall("app.complete_task", {"title": "Steuererklärung"}), ctx)


@respx.mock
async def test_aufgabe_abhaken_bei_mehrdeutigkeit_fragt_zurueck(ctx):
    respx.get(f"{BASE_URL}/api/tasks/status/TODO").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 1, "title": "Analysis Blatt 3"},
                {"id": 2, "title": "Analysis Blatt 4"},
            ],
        )
    )
    with pytest.raises(ToolError, match="mehrere Treffer"):
        await dispatch(ToolCall("app.complete_task", {"title": "Analysis"}), ctx)


# --------------------------------------------------------------------------- habits


@respx.mock
async def test_gewohnheiten_heute_filtert_nach_wochentag(ctx):
    # 4.9.2026 ist ein Freitag.
    respx.get(f"{BASE_URL}/api/habits").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 1, "name": "Lesen", "frequency": "DAILY", "completedDates": ["2026-09-04"]},
                {"id": 2, "name": "Joggen", "frequency": "WEEKLY", "friday": True,
                 "completedDates": []},
                {"id": 3, "name": "Yoga", "frequency": "WEEKLY", "monday": True,
                 "completedDates": []},
            ],
        )
    )
    _tool, speech = await dispatch(ToolCall("app.habits_today"), ctx)
    assert speech == "Offen: Joggen. Erledigt: Lesen."
    assert "Yoga" not in speech


@respx.mock
async def test_gewohnheiten_alle_erledigt(ctx):
    respx.get(f"{BASE_URL}/api/habits").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 1, "name": "Lesen", "frequency": "DAILY",
                   "completedDates": ["2026-09-04"]}],
        )
    )
    _tool, speech = await dispatch(ToolCall("app.habits_today"), ctx)
    assert speech == "Alle 1 Gewohnheiten für heute sind erledigt."


@respx.mock
async def test_gewohnheit_abhaken(ctx):
    respx.get(f"{BASE_URL}/api/habits").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": 5, "name": "Joggen", "frequency": "DAILY", "currentStreak": 11}],
        )
    )
    complete = respx.post(f"{BASE_URL}/api/habits/5/complete").mock(
        return_value=httpx.Response(200)
    )
    _tool, speech = await dispatch(ToolCall("app.complete_habit", {"name": "joggen"}), ctx)
    assert complete.called
    assert speech == "„Joggen“ für heute abgehakt. Das sind 12 Tage am Stück."


# --------------------------------------------------------------------------- study


@respx.mock
async def test_lernfortschritt_einzelnes_fach(ctx):
    respx.get(f"{BASE_URL}/api/study/goals").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 1, "courseName": "Analysis", "loggedHours": 3.5,
                 "weeklyGoalHours": 6.0, "remainingHours": 2.5},
                {"id": 2, "courseName": "Lineare Algebra", "loggedHours": 1.0,
                 "weeklyGoalHours": 4.0, "remainingHours": 3.0},
            ],
        )
    )
    call = ToolCall("app.study_progress", {"subject": "Analysis"})
    _tool, speech = await dispatch(call, ctx)
    assert speech == "In Analysis 3,5 von 6 Stunden geschafft. Es fehlen noch 2,5 Stunden."


@respx.mock
async def test_lernfortschritt_alle_faecher(ctx):
    respx.get(f"{BASE_URL}/api/study/goals").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 1, "courseName": "Analysis", "loggedHours": 3.5, "weeklyGoalHours": 6.0},
                {"id": 2, "courseName": "LinAlg", "loggedHours": 4.0, "weeklyGoalHours": 4.0},
            ],
        )
    )
    _tool, speech = await dispatch(ToolCall("app.study_progress"), ctx)
    assert speech == (
        "Diese Woche: Analysis 3,5 von 6 Stunden und LinAlg 4 von 4 Stunden."
    )


@respx.mock
async def test_faellige_karten(ctx):
    respx.get(f"{BASE_URL}/api/study/flashcards/due").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": i, "deckName": "Analysis" if i < 3 else "Physik"} for i in range(5)],
        )
    )
    _tool, speech = await dispatch(ToolCall("app.flashcards_due"), ctx)
    assert speech == "Es sind 5 Karten fällig, davon 3 in Analysis und 2 in Physik."


@respx.mock
async def test_keine_faelligen_karten(ctx):
    respx.get(f"{BASE_URL}/api/study/flashcards/due").mock(
        return_value=httpx.Response(200, json=[])
    )
    _tool, speech = await dispatch(ToolCall("app.flashcards_due"), ctx)
    assert speech == "Es sind keine Karteikarten fällig."


# --------------------------------------------------------------------------- Fehler


@respx.mock
async def test_deutsche_fehlermeldung_der_app_wird_durchgereicht(ctx):
    respx.post(f"{BASE_URL}/api/tasks").mock(
        return_value=httpx.Response(
            400,
            json={"message": "Titel darf nicht leer sein", "status": 400, "error": "Bad Request"},
        )
    )
    with pytest.raises(AppError, match="Titel darf nicht leer sein"):
        await dispatch(ToolCall("app.create_task", {"title": "X"}), ctx)


@respx.mock
async def test_403_meldet_fehlende_berechtigung(ctx):
    """Die Deny-List im Backend greift - das muss Nero sagen koennen."""
    respx.post(f"{BASE_URL}/api/tasks").mock(return_value=httpx.Response(403))
    with pytest.raises(AppError, match="Berechtigung"):
        await dispatch(ToolCall("app.create_task", {"title": "X"}), ctx)


@respx.mock
async def test_app_nicht_erreichbar(ctx):
    respx.get(EVENTS_URL).mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(AppError, match="erreiche die App"):
        await dispatch(ToolCall("app.today_agenda"), ctx)


@respx.mock
async def test_gewohnheit_die_heute_schon_abgehakt_war(ctx):
    """markHabitComplete tut dann nichts - der Streak darf nicht trotzdem hochgezählt werden."""
    respx.get(f"{BASE_URL}/api/habits").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 5,
                    "name": "Joggen",
                    "frequency": "DAILY",
                    "currentStreak": 11,
                    "completedDates": ["2026-09-04"],
                }
            ],
        )
    )
    respx.post(f"{BASE_URL}/api/habits/5/complete").mock(return_value=httpx.Response(200))
    _tool, speech = await dispatch(ToolCall("app.complete_habit", {"name": "Joggen"}), ctx)
    assert speech == "„Joggen“ war heute schon abgehakt. Das sind 11 Tage am Stück."
