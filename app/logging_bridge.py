"""
Bridge intre Python logging si Qt signals.

Toate log-urile (din modulele noastre + din biblioteca meshtastic) sunt
captate aici si emise ca semnal Qt astfel incat sa apara live in Debug tab.

Permite si redirect catre un fisier de log persistent.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QObject, Signal


# ---------------------------------------------------------------------------
# Singleton: bus de log Qt
# ---------------------------------------------------------------------------
class LogBus(QObject):
    """Emite fiecare LogRecord ca semnal Qt thread-safe."""

    logMessage = Signal(str, str, str)  # (level, name, message)

    _instance: Optional["LogBus"] = None

    def __init__(self):
        super().__init__()

    @classmethod
    def instance(cls) -> "LogBus":
        if cls._instance is None:
            cls._instance = LogBus()
        return cls._instance


# ---------------------------------------------------------------------------
# Handler logging -> Qt
# ---------------------------------------------------------------------------
class QtSignalHandler(logging.Handler):
    """Logging Handler care emite prin LogBus.logMessage."""

    def __init__(self, level=logging.NOTSET):
        super().__init__(level)

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            LogBus.instance().logMessage.emit(record.levelname, record.name, msg)
        except Exception:  # don't let a log error break the app
            self.handleError(record)


# ---------------------------------------------------------------------------
# Setup global
# ---------------------------------------------------------------------------
def setup_logging(log_dir: Optional[str] = None,
                  verbose: bool = False) -> str:
    """
    Configureaza root logger:
      • handler catre fisier (rotativ-zilnic in log_dir)
      • handler catre LogBus (pentru Debug tab)
      • handler catre stderr (pentru cand se ruleaza din cmd)

    Returneaza calea catre fisierul de log curent (sau '' daca log_dir e None).
    """
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)

    # curatare handlere existente (la re-setup)
    for h in list(root.handlers):
        root.removeHandler(h)

    fmt = "%(asctime)s | %(levelname)-7s | %(name)-30s | %(message)s"
    formatter = logging.Formatter(fmt, datefmt="%H:%M:%S")

    # 1) Qt signal handler
    qt_h = QtSignalHandler(level=logging.DEBUG)
    qt_h.setFormatter(formatter)
    root.addHandler(qt_h)

    # 2) Console / stderr handler (pentru rulare din cmd)
    import sys
    stderr_h = logging.StreamHandler(sys.stderr)
    stderr_h.setLevel(logging.INFO)
    stderr_h.setFormatter(formatter)
    root.addHandler(stderr_h)

    # 3) Fisier log
    log_path = ""
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = os.path.join(log_dir, f"meshlink_desktop_{ts}.log")
        try:
            file_h = logging.FileHandler(log_path, encoding="utf-8")
            file_h.setLevel(logging.DEBUG)
            file_h.setFormatter(formatter)
            root.addHandler(file_h)
        except Exception:
            pass

    # micsoram zgomotul de la biblioteci foarte verbose
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("bleak").setLevel(logging.INFO)

    return log_path
