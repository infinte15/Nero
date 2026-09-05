"""Fehler, die Nero dem Nutzer vorlesen kann."""

from __future__ import annotations


class NeroError(Exception):
    """Basis. Die Meldung ist bereits so formuliert, dass sie vorgelesen werden kann."""

    def __init__(self, speech: str) -> None:
        super().__init__(speech)
        self.speech = speech


class AppError(NeroError):
    """Die Everything App hat mit einem Fehler geantwortet."""


class ToolError(NeroError):
    """Der Befehl war verstaendlich, liess sich aber nicht ausfuehren.

    Etwa: kein Treffer bei der Namensaufloesung, oder mehrere gleich gute.
    """


class BudgetExceeded(NeroError):
    """Das Tagesbudget fuer LLM-Aufrufe ist aufgebraucht."""


class TtsError(NeroError):
    """Die Sprachausgabe hat nicht geliefert.

    Anders als bei den uebrigen Fehlern hilft die ``speech`` hier nur dem Client
    auf dem Bildschirm - vorlesen laesst sie sich gerade nicht.
    """


class SttError(NeroError):
    """Die Spracherkennung hat nicht geliefert."""
