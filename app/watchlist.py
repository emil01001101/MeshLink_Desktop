"""
Watchlist / Alerts store (V0.44).

Lets the user mark nodes or keywords to watch. The main window checks
incoming messages and node updates against this list and fires a desktop
notification + sound when:
  • a watched node comes back online after being offline, or
  • an incoming message contains a watched keyword (case-insensitive).

Persisted via QSettings so it survives restarts. Designed for fixed base
stations left running all day.
"""

from __future__ import annotations

import logging
from typing import List

from PySide6.QtCore import QObject, Signal, QSettings

log = logging.getLogger("meshlink.watchlist")

ORG = "MeshLinkDesktop"
APP = "MeshLinkDesktop"


class Watchlist(QObject):
    changed = Signal()

    _instance = None

    @classmethod
    def get(cls) -> "Watchlist":
        if cls._instance is None:
            cls._instance = Watchlist()
        return cls._instance

    def __init__(self):
        super().__init__()
        self._settings = QSettings(ORG, APP)
        self._nodes: List[str] = self._load_list("watchlist/nodes")
        self._keywords: List[str] = self._load_list("watchlist/keywords")
        self._enabled: bool = self._settings.value(
            "watchlist/enabled", True, type=bool)
        # runtime: which watched nodes we currently believe are online
        self._online_state: dict = {}

    # ---- persistence ----
    def _load_list(self, key) -> List[str]:
        raw = self._settings.value(key, "", type=str)
        return [s.strip() for s in raw.split("\n") if s.strip()] if raw else []

    def _save_list(self, key, items):
        self._settings.setValue(key, "\n".join(items))

    # ---- nodes ----
    @property
    def nodes(self) -> List[str]:
        return list(self._nodes)

    def add_node(self, node_id: str):
        node_id = node_id.strip()
        if node_id and node_id not in self._nodes:
            self._nodes.append(node_id)
            self._save_list("watchlist/nodes", self._nodes)
            self.changed.emit()

    def remove_node(self, node_id: str):
        if node_id in self._nodes:
            self._nodes.remove(node_id)
            self._save_list("watchlist/nodes", self._nodes)
            self.changed.emit()

    def is_watched_node(self, node_id: str) -> bool:
        return node_id in self._nodes

    # ---- keywords ----
    @property
    def keywords(self) -> List[str]:
        return list(self._keywords)

    def add_keyword(self, kw: str):
        kw = kw.strip()
        if kw and kw.lower() not in [k.lower() for k in self._keywords]:
            self._keywords.append(kw)
            self._save_list("watchlist/keywords", self._keywords)
            self.changed.emit()

    def remove_keyword(self, kw: str):
        self._keywords = [k for k in self._keywords if k.lower() != kw.lower()]
        self._save_list("watchlist/keywords", self._keywords)
        self.changed.emit()

    def match_keywords(self, text: str) -> List[str]:
        """Return the watched keywords found in a message (case-insensitive)."""
        if not text or not self._enabled:
            return []
        low = text.lower()
        return [k for k in self._keywords if k.lower() in low]

    # ---- enabled ----
    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, val: bool):
        self._enabled = bool(val)
        self._settings.setValue("watchlist/enabled", self._enabled)
        self.changed.emit()

    # ---- online-transition detection ----
    def note_node_seen(self, node_id: str) -> bool:
        """Record that a node was just heard. Returns True if this is a
        watched node that just came back ONLINE (was offline/unknown before).
        """
        if not self._enabled or node_id not in self._nodes:
            self._online_state[node_id] = True
            return False
        was_online = self._online_state.get(node_id, False)
        self._online_state[node_id] = True
        return not was_online   # True only on the offline→online edge

    def mark_node_offline(self, node_id: str):
        self._online_state[node_id] = False
