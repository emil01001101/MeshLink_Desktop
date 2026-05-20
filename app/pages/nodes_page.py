"""
Nodes page — list with context menu (DM, position, traceroute, Google Maps).
"""

from __future__ import annotations

import logging
from typing import Dict

from PySide6.QtCore import Qt, QTimer, Signal, QUrl
from PySide6.QtGui import QAction, QContextMenuEvent, QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QScrollArea, QFrame, QPushButton, QMenu, QApplication
)

from ..connection import MeshtasticManager
from ..widgets.common import NodeCard
from ..theme import Colors
from ..i18n import t, i18n

log = logging.getLogger("meshlink.nodes")


class _ClickableNodeCard(NodeCard):
    requestDM         = Signal(str)
    requestPosition   = Signal(str)
    requestTraceroute = Signal(str)
    requestTelemetry  = Signal(str)
    requestCopyId     = Signal(str)
    requestGoogleMaps = Signal(str)
    requestDetails    = Signal(str)   # NEW: open full details popup

    def contextMenuEvent(self, event: QContextMenuEvent):  # noqa: N802
        menu = QMenu(self)
        a_details = QAction("🔍  Show details…", self)
        a_dm    = QAction(t("nodes.context.dm"), self)
        a_pos   = QAction(t("nodes.context.position"), self)
        a_trace = QAction(t("nodes.context.traceroute"), self)
        a_telem = QAction(t("nodes.context.telemetry"), self)
        a_gmaps = QAction(t("nodes.context.gmaps"), self)
        a_copy  = QAction(t("nodes.context.copy"), self)
        a_details.triggered.connect(lambda: self.requestDetails.emit(self.node_id))
        a_dm.triggered.connect(lambda:    self.requestDM.emit(self.node_id))
        a_pos.triggered.connect(lambda:   self.requestPosition.emit(self.node_id))
        a_trace.triggered.connect(lambda: self.requestTraceroute.emit(self.node_id))
        a_telem.triggered.connect(lambda: self.requestTelemetry.emit(self.node_id))
        a_gmaps.triggered.connect(lambda: self.requestGoogleMaps.emit(self.node_id))
        a_copy.triggered.connect(lambda:  self.requestCopyId.emit(self.node_id))
        if self.is_me:
            a_dm.setEnabled(False)
            a_pos.setEnabled(False)
            a_trace.setEnabled(False)
            a_telem.setEnabled(False)
        menu.addAction(a_details)
        menu.addSeparator()
        menu.addAction(a_dm)
        menu.addSeparator()
        menu.addAction(a_pos)
        menu.addAction(a_telem)
        menu.addAction(a_trace)
        menu.addSeparator()
        menu.addAction(a_gmaps)
        menu.addAction(a_copy)
        menu.exec(event.globalPos())

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        """Double-click anywhere on the card opens the details popup."""
        super().mouseDoubleClickEvent(event)
        self.requestDetails.emit(self.node_id)


class NodesPage(QWidget):

    requestStartDM = Signal(str)

    def __init__(self, manager: MeshtasticManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.cards: Dict[str, _ClickableNodeCard] = {}
        self.node_data: Dict[str, dict] = {}

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(30_000)
        self._refresh_timer.timeout.connect(self._refresh_all)
        self._refresh_timer.start()

        self._build_ui()
        self._connect_signals()
        i18n.languageChanged.connect(self._retranslate)
        self._retranslate()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 20)
        root.setSpacing(14)

        ctrl = QHBoxLayout()
        ctrl.setSpacing(10)
        self.search = QLineEdit()
        self.search.textChanged.connect(self._apply_filter)
        ctrl.addWidget(self.search, 1)
        self.sort_by = QComboBox()
        self.sort_by.addItem("")
        self.sort_by.addItem("")
        self.sort_by.addItem("")
        self.sort_by.currentIndexChanged.connect(self._apply_filter)
        ctrl.addWidget(self.sort_by)
        self.refresh_btn = QPushButton()
        self.refresh_btn.clicked.connect(self._refresh_all)
        ctrl.addWidget(self.refresh_btn)
        root.addLayout(ctrl)

        self.lbl_count = QLabel()
        self.lbl_count.setProperty("role", "muted")
        root.addWidget(self.lbl_count)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setStyleSheet(f"QScrollArea {{ background: {Colors.BG_BASE}; border: none; }}")
        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(8)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(self.list_container)
        root.addWidget(self.scroll, 1)

    def _retranslate(self, *_):
        self.search.setPlaceholderText(t("nodes.search_placeholder"))
        self.sort_by.setItemText(0, t("nodes.sort.recent"))
        self.sort_by.setItemText(1, t("nodes.sort.name"))
        self.sort_by.setItemText(2, t("nodes.sort.signal"))
        self.refresh_btn.setText("⟳ " + t("common.refresh"))
        self._update_count()

    def _connect_signals(self):
        self.manager.nodeUpdated.connect(self._on_node_updated)
        self.manager.nodeRemoved.connect(self._on_node_removed)
        self.manager.stateChanged.connect(self._on_state_changed)

    def _on_state_changed(self, state):
        if state == "idle":
            for cid in list(self.cards.keys()):
                self._remove_card(cid)
            self.node_data.clear()
            self._update_count()

    def _on_node_updated(self, node_id: str, node: dict):
        # MERGE cu datele existente (update-urile partiale - ex doar position -
        # nu trebuie sa stearga restul info)
        existing = self.node_data.get(node_id) or {}
        merged = dict(existing)
        for k, v in node.items():
            if isinstance(v, dict) and isinstance(existing.get(k), dict):
                merged[k] = {**existing[k], **v}
            else:
                merged[k] = v
        self.node_data[node_id] = merged

        is_me = bool(self.manager.my_node_id) and (
            node_id == self.manager.my_node_id)
        if node_id in self.cards:
            # Re-check is_me on every update: when the local node update
            # arrives before my_node_id is known, the card is initially
            # built with is_me=False — fix that as soon as we can.
            card = self.cards[node_id]
            if card.is_me != is_me:
                log.info(f"Refreshing is_me for {node_id}: "
                         f"{card.is_me} -> {is_me}")
                card.set_is_me(is_me)
            card.update_data(merged)
        else:
            card = _ClickableNodeCard(node_id, merged, is_me=is_me)
            card.requestDM.connect(self.requestStartDM)
            card.requestPosition.connect(self._do_request_position)
            card.requestTraceroute.connect(self._do_traceroute)
            card.requestTelemetry.connect(self._do_request_telemetry)
            card.requestCopyId.connect(self._do_copy_id)
            card.requestGoogleMaps.connect(self._do_open_gmaps)
            card.requestDetails.connect(self._do_show_details)
            self.cards[node_id] = card
            self.list_layout.insertWidget(self.list_layout.count() - 1, card)
        # Belt-and-braces: also recheck is_me across ALL cards. Cheap loop
        # and covers the case where my_node_id only becomes available after
        # several other nodes have already been added.
        my_id = self.manager.my_node_id
        if my_id:
            for nid, c in self.cards.items():
                expected = (nid == my_id)
                if c.is_me != expected:
                    log.info(f"Sweep correcting is_me for {nid}: "
                             f"{c.is_me} -> {expected}")
                    c.set_is_me(expected)
        self._update_count()
        self._apply_filter()

    def _on_node_removed(self, node_id: str):
        self._remove_card(node_id)
        self.node_data.pop(node_id, None)
        self._update_count()

    def _remove_card(self, node_id: str):
        if node_id in self.cards:
            self.cards[node_id].deleteLater()
            del self.cards[node_id]

    def _do_request_position(self, node_id):
        if self.manager.request_position(node_id):
            self.lbl_count.setText(t("nodes.position_sent", node_id))
            QTimer.singleShot(2500, self._update_count)

    def _do_traceroute(self, node_id):
        if self.manager.traceroute(node_id):
            self.lbl_count.setText(t("nodes.trace_sent", node_id))
            QTimer.singleShot(2500, self._update_count)

    def _do_request_telemetry(self, node_id):
        if self.manager.request_telemetry_with_popup(node_id):
            self.lbl_count.setText(t("nodes.telemetry_sent", node_id))
            QTimer.singleShot(2500, self._update_count)

    def _do_copy_id(self, node_id):
        QApplication.clipboard().setText(node_id)
        self.lbl_count.setText(t("nodes.id_copied", node_id))
        QTimer.singleShot(2000, self._update_count)

    def _do_open_gmaps(self, node_id):
        node = self.node_data.get(node_id) or {}
        pos = node.get("position") or {}
        lat = pos.get("latitude")
        lon = pos.get("longitude")
        if lat is None and pos.get("latitudeI") is not None:
            lat = pos["latitudeI"] / 1e7
            lon = pos.get("longitudeI", 0) / 1e7
        if lat is not None and lon is not None:
            QDesktopServices.openUrl(QUrl(f"https://www.google.com/maps?q={lat},{lon}"))

    def _do_show_details(self, node_id):
        """Open a popup dialog with all available info about the node."""
        node = self.node_data.get(node_id) or {}
        try:
            from ..dialogs.node_details_dialog import NodeDetailsDialog
            dlg = NodeDetailsDialog(node_id, node, self.window())
            dlg.setAttribute(Qt.WA_DeleteOnClose, True)
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
        except Exception:
            log.exception("Could not open node details dialog")

    def _apply_filter(self):
        needle = self.search.text().strip().lower()
        sort_mode = self.sort_by.currentIndex()
        items = [(nid, self.node_data.get(nid, {}), self.cards[nid])
                 for nid in self.cards.keys()]

        my_id = self.manager.my_node_id
        def is_me(it): return it[0] == my_id

        if sort_mode == 1:
            items.sort(key=lambda x: ((x[1].get("user") or {}).get("longName") or x[0]).lower())
        elif sort_mode == 2:
            items.sort(key=lambda x: -(x[1].get("snr") or -999))
        else:
            items.sort(key=lambda x: -(x[1].get("lastHeard") or 0))
        items.sort(key=lambda x: 0 if is_me(x) else 1)

        for idx, (_, _, card) in enumerate(items):
            self.list_layout.removeWidget(card)
            self.list_layout.insertWidget(idx, card)

        visible = 0
        for nid, data, card in items:
            user = data.get("user") or {}
            haystack = " ".join([nid, user.get("longName") or "",
                                 user.get("shortName") or ""]).lower()
            show = (not needle) or (needle in haystack)
            card.setVisible(show)
            if show: visible += 1
        if needle:
            self.lbl_count.setText(t("nodes.count_filtered", visible, len(items)))
        else:
            self._update_count()

    def _refresh_all(self):
        for nid, card in self.cards.items():
            card.update_data(self.node_data.get(nid, {}))

    def _update_count(self):
        n = len(self.cards)
        self.lbl_count.setText(t("nodes.count_many", n) if n != 1 else t("nodes.count_one"))
