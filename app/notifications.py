"""
System tray + sound notifications (all English).
"""

from __future__ import annotations

import sys
import logging
from typing import Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QIcon, QPainter, QPixmap, QColor, QAction
from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QApplication

from .theme import Colors

log = logging.getLogger("meshlink.notif")


def make_app_icon(size: int = 64) -> QIcon:
    """Generate an in-memory app icon: green circle with a center dot."""
    pm = QPixmap(size, size)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setBrush(QColor(Colors.PRIMARY))
    p.setPen(QColor(Colors.PRIMARY_DARK))
    p.drawEllipse(2, 2, size - 4, size - 4)
    p.setBrush(QColor(Colors.BG_BASE))
    cx = size // 2
    cy = size // 2
    r = size // 6
    p.drawEllipse(cx - r, cy - r, 2 * r, 2 * r)
    p.end()
    return QIcon(pm)


class SoundPlayer(QObject):
    """Plays a short beep when a new message arrives. Supports mute toggle."""

    mutedChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._muted: bool = False

    @property
    def muted(self) -> bool:
        return self._muted

    def set_muted(self, muted: bool):
        new_val = bool(muted)
        if new_val != self._muted:
            self._muted = new_val
            self.mutedChanged.emit(self._muted)
            log.info(f"Sound: {'MUTED' if self._muted else 'ACTIVE'}")

    def play_message(self):
        if self._muted:
            return
        try:
            if sys.platform == "win32":
                import winsound
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
                return
        except Exception:
            log.debug("winsound.MessageBeep failed", exc_info=True)
        try:
            QApplication.beep()
        except Exception:
            log.debug("QApplication.beep failed", exc_info=True)


class NotificationManager(QObject):
    """Manages system tray icon + balloon notifications."""

    tray_show_request = Signal()
    tray_quit_request = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._enabled: bool = True
        self._tray: Optional[QSystemTrayIcon] = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._setup_tray()
        else:
            log.warning("System tray not available on this system")

    def _setup_tray(self):
        icon = make_app_icon(64)
        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip("MeshLink Desktop")

        menu = QMenu()
        a_show = QAction("Open", self)
        a_show.triggered.connect(self.tray_show_request)
        menu.addAction(a_show)
        menu.addSeparator()
        a_quit = QAction("Quit", self)
        a_quit.triggered.connect(self.tray_quit_request)
        menu.addAction(a_quit)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.DoubleClick, QSystemTrayIcon.Trigger):
            self.tray_show_request.emit()

    def set_enabled(self, on: bool):
        self._enabled = on

    def notify(self, title: str, body: str, ms: int = 4000):
        if not self._enabled or not self._tray:
            return
        try:
            self._tray.showMessage(title, body,
                                   QSystemTrayIcon.Information, ms)
        except Exception:
            log.exception("Notification failed")

    def set_tooltip(self, text: str):
        if self._tray:
            self._tray.setToolTip(text)

    def hide(self):
        if self._tray:
            self._tray.hide()
