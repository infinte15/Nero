"""WebDAV-Client fuer Nextcloud.

Zwei Aufrufe, mehr braucht das Vorlesen nicht:

* ``PROPFIND`` auf den Notizordner - welche Notizen es gibt.
* ``GET`` auf eine davon - was drinsteht.

**Der Pfad wird nie von aussen gesetzt.** Gesucht wird immer erst die Liste, und
gelesen wird nur ein Eintrag daraus - aufgeloest lokal ueber ``tools/match.py``,
so wie bei Aufgaben und Gewohnheiten. Kaeme der Pfad aus einem Sprachmodell oder
aus einer Spracherkennung, waere ``../../.ssh/id_rsa`` ein Satz, den man
aussprechen kann.

Angemeldet wird sich mit einem **App-Passwort**, nicht mit dem Hauptpasswort:
Nextcloud kann ein einzelnes App-Passwort widerrufen, ohne dass alles andere
neue Zugangsdaten braucht - dieselbe Idee wie ein Token je Geraet.

Fuer die Anmeldung reicht Basic Auth ueber https. Nextcloud erwartet es so; ein
OAuth-Tanz waere fuer einen Dienst, der im selben Haus laeuft, nur eine weitere
Stelle, an der ein Token ablaufen kann.
"""

from __future__ import annotations

import logging
import posixpath
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

import httpx

from nero.errors import AppError

logger = logging.getLogger(__name__)

DAV = "{DAV:}"

# Nur was sich vorlesen laesst. Ein PDF oder ein Bild ist keine Notiz.
READABLE_SUFFIXES = (".md", ".txt", ".markdown", ".org")

# Eine Notiz ist Text. Alles darueber ist keine mehr, und der Speicher des Brains
# ist nicht der Ort, an dem sich das herausstellen soll.
MAX_NOTE_BYTES = 1024 * 1024

PROPFIND_BODY = """<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:">
  <d:prop>
    <d:displayname/>
    <d:getcontenttype/>
    <d:resourcetype/>
  </d:prop>
</d:propfind>
"""


class NextcloudClient:
    def __init__(
        self,
        base_url: str,
        user: str,
        app_password: str,
        notes_path: str = "Notes",
        timeout: float = 15.0,
        max_depth: int = 2,
    ) -> None:
        self._root = f"/remote.php/dav/files/{user.strip('/')}"
        self._notes_path = notes_path.strip("/")
        self._max_depth = max_depth
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            auth=(user, app_password),
            headers={"OCS-APIRequest": "true"},
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def notes(self) -> list[dict[str, str]]:
        """Alle vorlesbaren Dateien im Notizordner - ``{"title", "path"}``.

        ``Depth: infinity`` lehnen die meisten WebDAV-Server ab, deshalb wird
        Ebene fuer Ebene gegangen und bei ``max_depth`` Schluss gemacht. Ein
        Notizordner ist flach; wer dort einen Baum anlegt, will ihn nicht
        vorgelesen bekommen.
        """
        gefunden: list[dict[str, str]] = []
        offen = [(self._notes_path, 0)]

        while offen:
            pfad, tiefe = offen.pop(0)
            for eintrag in await self._propfind(pfad):
                if eintrag["collection"]:
                    if tiefe + 1 < self._max_depth:
                        offen.append((eintrag["path"], tiefe + 1))
                elif eintrag["path"].lower().endswith(READABLE_SUFFIXES):
                    gefunden.append({"title": eintrag["title"], "path": eintrag["path"]})
        return gefunden

    async def read(self, path: str) -> str:
        """Inhalt einer Notiz. ``path`` stammt immer aus ``notes()``, nie von aussen."""
        response = await self._request("GET", self._url(path))
        if len(response.content) > MAX_NOTE_BYTES:
            raise AppError("Diese Notiz ist zu lang zum Vorlesen.")
        return response.text

    async def _propfind(self, path: str) -> list[dict]:
        response = await self._request(
            "PROPFIND",
            self._url(path),
            headers={"Depth": "1", "Content-Type": "application/xml"},
            content=PROPFIND_BODY,
        )
        return self._parse(response.text, path)

    def _url(self, path: str) -> str:
        # posixpath.normpath entfernt "." und ".." bevor daraus eine Adresse wird.
        sauber = posixpath.normpath(f"{self._root}/{path.strip('/')}")
        if not sauber.startswith(self._root):
            raise AppError("Diese Notiz finde ich nicht.")
        return sauber

    def _parse(self, xml: str, parent: str) -> list[dict]:
        try:
            baum = ElementTree.fromstring(xml)
        except ElementTree.ParseError as exc:
            raise AppError("Nextcloud hat unverständlich geantwortet.") from exc

        eigener = self._url(parent).rstrip("/")
        eintraege = []
        for response in baum.findall(f"{DAV}response"):
            href = (response.findtext(f"{DAV}href") or "").strip()
            pfad = unquote(urlsplit(href).path).rstrip("/")
            if not pfad or pfad == eigener:
                continue  # der Ordner selbst steht als erster in der Antwort

            name = response.findtext(f".//{DAV}displayname") or posixpath.basename(pfad)
            eintraege.append(
                {
                    "title": _ohne_endung(name),
                    "path": pfad[len(self._root) :].lstrip("/"),
                    "collection": response.find(f".//{DAV}collection") is not None,
                }
            )
        return eintraege

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        try:
            response = await self._client.request(method, url, **kwargs)
        except httpx.RequestError as exc:
            logger.warning("Nextcloud nicht erreichbar: %s", exc)
            raise AppError("Ich erreiche Nextcloud gerade nicht.") from exc

        if response.status_code in (401, 403):
            raise AppError("Nextcloud nimmt mein App-Passwort nicht an.")
        if response.status_code == 404:
            raise AppError("Diese Notiz finde ich nicht.")
        if response.status_code >= 400:
            raise AppError(f"Nextcloud hat mit Fehler {response.status_code} geantwortet.")
        return response


def _ohne_endung(name: str) -> str:
    stamm, punkt, endung = name.rpartition(".")
    return stamm if punkt and f".{endung.lower()}" in READABLE_SUFFIXES else name
