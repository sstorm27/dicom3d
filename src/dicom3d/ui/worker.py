"""Rularea operatiilor lungi pe un fir separat, ca interfata sa nu se blocheze."""

from __future__ import annotations

import traceback

from PySide6.QtCore import QObject, QRunnable, Signal


class WorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class Worker(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.signals = WorkerSignals()

    def run(self):
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as exc:  # noqa: BLE001 - orice eroare ajunge la utilizator
            traceback.print_exc()
            self._emit(self.signals.failed, str(exc) or type(exc).__name__)
        else:
            self._emit(self.signals.finished, result)

    def _emit(self, signal, value):
        try:
            signal.emit(value)
        except RuntimeError:
            pass  # fereastra a fost inchisa intre timp; rezultatul nu mai are destinatar
