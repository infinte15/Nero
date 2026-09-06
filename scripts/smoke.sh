#!/usr/bin/env bash
# ===========================================================================
# Abnahme fuer Phase 1: elf Befehle gegen ein laufendes Brain.
#
#   ./scripts/smoke.sh [BRAIN_URL]
#
# Sind Geraetetokens gesetzt, gehoert eines davon in die Umgebung:
#   NERO_DEVICE_TOKEN=... ./scripts/smoke.sh https://nero.deine-domain.de
#
# Fertig ist Phase 1, wenn alle elf die richtige Aktion ausloesen und die als
# [K] markierten ueber den Keyword-Router laufen - also ohne dass ein Paket das
# Haus verlaesst.
#
# Bewusst nur bash + python3, kein jq: das Skript soll auf einem frischen Server
# laufen, ohne dass vorher etwas nachinstalliert werden muss.
# ===========================================================================
set -uo pipefail

BRAIN="${1:-http://localhost:8090}"

if ! curl -sf "$BRAIN/health" >/dev/null; then
  echo "Kein Brain unter $BRAIN. Starten mit:"
  echo "  .venv/bin/uvicorn nero.main:app --port 8090"
  exit 1
fi
echo "Brain: $(curl -sf "$BRAIN/health")"
echo

exec python3 - "$BRAIN" "${NERO_DEVICE_TOKEN:-}" <<'PY'
import json
import sys
import urllib.error
import urllib.request

BRAIN, TOKEN = sys.argv[1], sys.argv[2]
HEADERS = {"Content-Type": "application/json"}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"

# Steht in /health nicht mehr drin: der Endpunkt ist ueber den Tunnel oeffentlich.
# Ohne Token laesst sich das nicht nachsehen - dann wird angenommen, dass Stufe 2
# laeuft, damit ein echter Fehlschlag nicht als "uebersprungen" durchgeht.
try:
    request = urllib.request.Request(f"{BRAIN}/status", headers=HEADERS)
    with urllib.request.urlopen(request, timeout=10) as response:
        LLM_ENABLED = json.load(response)["provider"] != "null"
except (urllib.error.URLError, TimeoutError, KeyError):
    print("/status nicht lesbar (NERO_DEVICE_TOKEN setzen) - Stufe 2 wird als aktiv angenommen.\n")
    LLM_ENABLED = True

COMMANDS = [
    "Wie spät ist es?",
    "Welcher Tag ist heute?",
    "Was steht heute an?",
    "Nächster Termin",
    "Neue Aufgabe: Analysis-Übungsblatt abgeben",
    "Was habe ich noch offen?",
    "Aufgabe Analysis-Übungsblatt abgeben ist erledigt",
    "Welche Gewohnheiten habe ich heute?",
    "Wie steht's mit dem Lernen?",
    "Wie viele Karten sind fällig?",
    # Das Beispiel aus Kapitel 4 des Plans - faellt bewusst durch auf Stufe 2.
    "Leg mir für Donnerstag eine Aufgabe an, Analysis-Übungsblatt abgeben",
]

# Genau ein Befehl braucht das Sprachmodell. Ohne GROQ_API_KEY ist Stufe 2 aus -
# das ist kein Fehlschlag, sondern das dokumentierte Offline-Verhalten.
NEEDS_LLM = {COMMANDS[-1]}

MARKS = {"keyword": "[K]", "llm": "[L]"}
failed = 0

for text in COMMANDS:
    request = urllib.request.Request(
        f"{BRAIN}/command",
        data=json.dumps({"text": text}).encode(),
        headers=HEADERS,
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.load(response)
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"[!] {text:<54} {exc}")
        failed = 1
        continue

    mark = MARKS.get(body["route"], "[!]")
    if mark == "[!]":
        if text in NEEDS_LLM and not LLM_ENABLED:
            mark = "[-]"
        else:
            failed = 1
    print(f'{mark} {text:<54} {body["tool"] or "-":<22} {body["speech"]}')

print()
print("[K] Keyword-Router, lokal   [L] Sprachmodell   [!] nicht erkannt")
if not LLM_ENABLED:
    print("[-] übersprungen: Stufe 2 ist aus (NERO_LLM_PROVIDER=null oder GROQ_API_KEY leer)")
sys.exit(failed)
PY
