"""Was ein Agent auf seinem Rechner tun kann.

**Programme laufen ueber eine Positivliste, nicht ueber einen freien Namen.**
Der Entwurf im Plan macht ``subprocess.Popen([name])`` mit dem, was das Modell
geliefert hat - das ist Codeausfuehrung per Zuruf. Der Weg vom Mikrofon bis
hierher fuehrt durch eine Spracherkennung und ein Sprachmodell; beide koennen
irren, und ein Mensch in Hoerweite kann es absichtlich. Deshalb steht in
``NERO_APPS`` eine Zuordnung von gesprochenem Namen auf Befehl, und nur was dort
steht, laeuft:

    NERO_APPS=firefox=firefox,musik=spotify,code=code

Ohne Eintrag antwortet der Agent, dass er das Programm nicht kennt - eine
verstaendliche Absage statt eines Fehlversuchs.

Die Befehle selbst sind Systemwerkzeuge statt Python-Bibliotheken. Ein Agent
laeuft auf jedem Rechner; jede Abhaengigkeit dort ist eine, die man auf jedem
Rechner pflegen muss. ``pyautogui`` aus dem Plan zieht dafuer zu viel nach.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys

logger = logging.getLogger(__name__)

WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"


class CommandError(Exception):
    """Der Befehl liess sich nicht ausfuehren. Der Text geht zurueck ans Brain."""


def _run(argv: list[str], timeout: float = 10.0) -> str:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise CommandError(f"{argv[0]} ist auf diesem Rechner nicht installiert") from exc
    except subprocess.TimeoutExpired as exc:
        raise CommandError(f"{argv[0]} hat nicht geantwortet") from exc
    if done.returncode != 0:
        raise CommandError((done.stderr or done.stdout or "unbekannter Fehler").strip()[:200])
    return done.stdout.strip()


def _first_available(candidates: list[list[str]]) -> list[str]:
    for argv in candidates:
        if shutil.which(argv[0]):
            return argv
    raise CommandError("kein passendes Werkzeug gefunden (siehe README)")


def lock() -> str:
    if WINDOWS:
        _run(["rundll32.exe", "user32.dll,LockWorkStation"])
    elif MACOS:
        _run(["pmset", "displaysleepnow"])
    else:
        # loginctl kann es ohne Desktop-Umgebung, xdg-screensaver ist der Rueckfall.
        _run(_first_available([["loginctl", "lock-session"], ["xdg-screensaver", "lock"]]))
    return "Bildschirm gesperrt."


def open_app(app: str, apps: dict[str, str]) -> str:
    befehl = apps.get(app.strip().casefold())
    if not befehl:
        bekannt = ", ".join(sorted(apps)) or "keins"
        raise CommandError(f"{app} steht nicht auf meiner Liste. Ich kenne: {bekannt}")

    argv = befehl.split()
    if not shutil.which(argv[0]):
        raise CommandError(f"{argv[0]} ist auf diesem Rechner nicht installiert")

    # Bewusst kein warten: ein Programm laeuft weiter, wenn der Agent neu startet.
    subprocess.Popen(  # noqa: S603 - argv aus der Positivliste, keine Shell
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=not WINDOWS,
    )
    return f"{app} geöffnet."


def volume(level: int) -> str:
    level = max(0, min(100, int(level)))
    if WINDOWS:
        try:
            _windows_volume(level)
        except ImportError as exc:
            raise CommandError("für die Lautstärke fehlt hier pycaw") from exc
    elif MACOS:
        _run(["osascript", "-e", f"set volume output volume {level}"])
    else:
        _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"])
    return "Ton aus." if level == 0 else f"Lautstärke auf {level} Prozent."


def _windows_volume(level: int) -> None:  # pragma: no cover - nur auf Windows
    from ctypes import POINTER, cast

    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    speakers = AudioUtilities.GetSpeakers()
    interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    cast(interface, POINTER(IAudioEndpointVolume)).SetMasterVolumeLevelScalar(level / 100, None)


def type_text(text: str) -> str:
    if not text:
        raise CommandError("kein Text angegeben")
    if WINDOWS:  # pragma: no cover - nur auf Windows
        escaped = text.replace("{", "{{").replace("}", "}}").replace('"', '`"')
        _run([
            "powershell", "-NoProfile", "-Command",
            f'[void][Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms");'
            f'[System.Windows.Forms.SendKeys]::SendWait("{escaped}")',
        ])
    elif MACOS:  # pragma: no cover - nur auf macOS
        _run(["osascript", "-e", f'tell application "System Events" to keystroke {text!r}'])
    else:
        # "--" trennt Optionen vom Text: sonst wuerde ein Befehl, der mit "-"
        # anfaengt, als Schalter gelesen. wtype ist der Weg unter Wayland.
        werkzeug = _first_available([["xdotool"], ["wtype"]])[0]
        argv = [werkzeug, "type", "--delay", "12", "--", text] if werkzeug == "xdotool" else [
            werkzeug, text
        ]
        _run(argv)
    return "Getippt."


def dispatch(tool: str, args: dict, apps: dict[str, str]) -> str:
    if tool == "lock":
        return lock()
    if tool == "open_app":
        return open_app(str(args.get("app", "")), apps)
    if tool == "volume":
        return volume(int(args.get("level", 50)))
    if tool == "type_text":
        return type_text(str(args.get("text", "")))
    raise CommandError(f"unbekannter Befehl: {tool}")
