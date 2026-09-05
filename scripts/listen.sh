#!/usr/bin/env bash
# ===========================================================================
# Abnahme fuer Phase 3 ohne Browser: eine Audiodatei an /listen schicken.
#
#   ./scripts/listen.sh aufnahme.webm
#   ./scripts/listen.sh http://server:8090 aufnahme.wav
#
# Selbst etwas aufnehmen (Strg-C beendet):
#   arecord -f cd -t wav /tmp/befehl.wav
#
# Der bequemere Weg ist die Testseite unter / - die braucht aber ein Mikrofon
# im Browser und damit https oder localhost.
# ===========================================================================
set -uo pipefail

BRAIN="http://localhost:8090"
if [[ "${1:-}" == http://* || "${1:-}" == https://* ]]; then
  BRAIN="$1"
  shift
fi

FILE="${1:-}"
if [[ -z "$FILE" || ! -f "$FILE" ]]; then
  echo "Aufruf: $0 [BRAIN_URL] <audiodatei>"
  exit 1
fi

if ! curl -sf "$BRAIN/health" >/dev/null; then
  echo "Kein Brain unter $BRAIN."
  exit 1
fi
echo "Brain: $(curl -sf "$BRAIN/health")"

RESPONSE=$(curl -s -w '\n%{http_code}' -X POST "$BRAIN/listen" -F "audio=@$FILE")
STATUS="${RESPONSE##*$'\n'}"
BODY="${RESPONSE%$'\n'*}"

if [[ "$STATUS" != "200" ]]; then
  echo "[!] /listen antwortete $STATUS: $BODY"
  exit 1
fi

BODY="$BODY" python3 - <<'PY'
import json, os

body = json.loads(os.environ["BODY"])
print(f'     gehört:   „{body.get("text") or "-"}“')
print(f'     Tool:     {body.get("tool") or "-"}  ({body.get("route")})')
print(f'     Antwort:  {body["speech"]}')
PY
