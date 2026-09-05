#!/usr/bin/env bash
# ===========================================================================
# Abnahme fuer Phase 2: einen Satz durch Piper schicken und anhoeren.
#
#   ./scripts/speak.sh                       # Beispielsatz aus Kapitel 4
#   ./scripts/speak.sh "Guten Morgen"
#   ./scripts/speak.sh http://server:8090 "Guten Morgen"
#
# Fertig ist Phase 2, wenn die erzeugte Datei ein Mensch versteht.
#
# Wie smoke.sh bewusst nur bash + curl + python3, kein jq: das Skript soll auf
# einem frischen Server laufen, ohne dass vorher etwas nachinstalliert wird.
# ===========================================================================
set -uo pipefail

BRAIN="http://localhost:8090"
if [[ "${1:-}" == http://* || "${1:-}" == https://* ]]; then
  BRAIN="$1"
  shift
fi

TEXT="${*:-Aufgabe Analysis-Übungsblatt abgeben angelegt, für Donnerstag.}"
OUT="${NERO_SPEAK_OUT:-/tmp/nero.wav}"

if ! curl -sf "$BRAIN/health" >/dev/null; then
  echo "Kein Brain unter $BRAIN. Starten mit:"
  echo "  .venv/bin/uvicorn nero.main:app --port 8090"
  exit 1
fi
echo "Brain: $(curl -sf "$BRAIN/health")"

BODY=$(TEXT="$TEXT" python3 -c 'import json, os; print(json.dumps({"text": os.environ["TEXT"]}))')

STATUS=$(curl -s -o "$OUT" -w '%{http_code}' -X POST "$BRAIN/speak" \
           -H 'Content-Type: application/json' -d "$BODY")

if [[ "$STATUS" != "200" ]]; then
  echo "[!] /speak antwortete $STATUS:"
  cat "$OUT"; echo
  rm -f "$OUT"
  [[ "$STATUS" == "503" ]] && echo "    (Sprachausgabe aus? NERO_TTS_PROVIDER / Piper-Container prüfen.)"
  exit 1
fi

# Kopf des WAV auslesen - das prueft gleich mit, dass die Datei wohlgeformt ist.
if ! python3 - "$OUT" "$TEXT" <<'PY'
import sys, wave

path, text = sys.argv[1], sys.argv[2]
with wave.open(path, "rb") as wav:
    seconds = wav.getnframes() / wav.getframerate()
    print(f'[OK] "{text}"')
    print(f"     {path}  {seconds:.1f} s  "
          f"{wav.getframerate()} Hz  {wav.getsampwidth() * 8} bit  "
          f"{'mono' if wav.getnchannels() == 1 else 'stereo'}")
PY
then
  echo "[!] $OUT ist kein lesbares WAV."
  exit 1
fi

if command -v aplay >/dev/null; then
  aplay -q "$OUT"
else
  echo "     (kein aplay - Datei selbst abspielen)"
fi
