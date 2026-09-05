"""Wer darf mit dem Brain sprechen.

Bis Phase 3 lief Nero hinter verschlossener Tuer: kein offener Port, nur der
Server selbst als Gegenueber. Mit dem Satelliten aus Phase 4 spricht zum ersten
Mal ein Geraet von aussen - und damit braucht es eine Schranke.

Ein Token pro Geraet, nicht eines fuer alle. Der Grund steht in Kapitel 5 des
Plans: ein einzelnes Geraet muss sich sperren lassen, ohne dass die uebrigen
neue Zugangsdaten brauchen. Der Name landet zudem im Log - man sieht also, wer
was ausgeloest hat.

Eine leere Liste laesst alles durch. Das ist der lokale Entwicklungsfall und das
Verhalten der Phasen 1 bis 3; sobald ein Port offen ist, gehoeren Tokens gesetzt.
"""

from __future__ import annotations

import logging
import secrets

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

OPEN = "offen"


def parse_clients(raw: str) -> dict[str, str]:
    """``"laptop:abc,spiegel:def"`` -> ``{"abc": "laptop", "def": "spiegel"}``.

    Der Token ist der Schluessel, weil genau danach nachgeschlagen wird. Eintraege
    ohne Doppelpunkt oder mit leerem Token werden verworfen - ein halb getipptes
    Token soll nicht versehentlich zu einem gueltigen werden.
    """
    clients: dict[str, str] = {}
    for entry in raw.split(","):
        name, _, token = entry.partition(":")
        name, token = name.strip(), token.strip()
        if name and token:
            clients[token] = name
        elif entry.strip():
            logger.warning("NERO_CLIENT_TOKENS: Eintrag ohne name:token wird übergangen.")
    return clients


def bearer_token(authorization: str | None) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


def require_client(request: Request) -> str:
    """FastAPI-Dependency. Gibt den Geraetenamen zurueck."""
    clients: dict[str, str] = request.app.state.clients
    if not clients:
        return OPEN

    token = bearer_token(request.headers.get("authorization"))
    # Vergleich in konstanter Zeit gegen jeden Eintrag: ein Woerterbuch-Lookup
    # wuerde ueber die Laufzeit verraten, wie weit ein geratenes Token stimmt.
    for known, name in clients.items():
        if secrets.compare_digest(token, known):
            return name

    raise HTTPException(
        status_code=401,
        detail="Kein gültiges Gerätetoken.",
        headers={"WWW-Authenticate": "Bearer"},
    )
