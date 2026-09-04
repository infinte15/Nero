"""HTTP-Client fuer die Everything App.

Zwei Eigenheiten der API sind hier gekapselt, damit sie sonst nirgends auftauchen:

1. Die API ist **zeitzonennaiv**. Saemtliche Zeitstempel sind ``LocalDateTime`` /
   ``LocalDate`` / ``LocalTime`` - kein ``Instant``, kein Offset. Auch
   ``spring.jackson.time-zone`` greift bei JSR-310-Typen nicht. Ein
   ``2026-09-04T14:30:00Z`` oder ``...+02:00`` bricht das Binding. Nero rechnet
   deshalb intern mit zonenbehafteter Zeit und legt sie erst hier ab.

2. ``CalendarController.getEvents`` parst seine Query-Parameter per
   ``LocalDateTime.parse()`` von Hand, ohne ``@DateTimeFormat``. Ein reines Datum
   wirft dort eine ``DateTimeParseException`` statt eines sauberen 400 - es muss
   immer die volle ISO-Local-DateTime gesendet werden.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from nero.errors import AppError


def to_app(dt: datetime) -> str:
    """Zonenbehaftete Zeit -> naive ISO-Local-DateTime, wie die API sie erwartet."""
    return dt.replace(tzinfo=None).isoformat(timespec="seconds")


def from_app(value: str | None) -> datetime | None:
    """Naive ISO-Local-DateTime der API -> naives ``datetime``. Unlesbares ergibt ``None``."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class EverythingClient:
    def __init__(self, base_url: str, token: str, timeout: float = 10.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={"Authorization": f"Bearer {token}"} if token else {},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, json: Any = None, params: dict[str, Any] | None = None) -> Any:
        return await self._request("POST", path, json=json, params=params)

    async def put(self, path: str, json: Any = None, params: dict[str, Any] | None = None) -> Any:
        return await self._request("PUT", path, json=json, params=params)

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx.RequestError as exc:
            raise AppError("Ich erreiche die App gerade nicht.") from exc

        if response.status_code == 403:
            raise AppError("Dafür fehlt mir die Berechtigung.")
        if response.status_code >= 400:
            raise AppError(_error_speech(response))

        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return None


def _error_speech(response: httpx.Response) -> str:
    """Der GlobalExceptionHandler liefert ``ErrorResponse`` mit deutscher ``message``.

    Die laesst sich direkt vorlesen. Nur wenn sie fehlt, wird auf den Status
    zurueckgefallen.
    """
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return f"Die App hat mit Fehler {response.status_code} geantwortet."
