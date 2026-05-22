"""
Channels page — full management UI with PSK display, add / edit / remove.

Layout:
    [ Intro card ]
    [ Section header ] ⮕ [ Add channel + ]
    [ Channel cards — expandable ] ⮕ shows full PSK, mqtt flags, pos precision
    [ Primary URL — share / copy ]
"""

from __future__ import annotations

import base64
import logging
from typing import List, Optional

from PySide6.QtCore import Qt, Slot, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QPlainTextEdit, QScrollArea, QApplication, QMessageBox, QLineEdit
)

from ..connection import MeshtasticManager
from ..i18n import t, i18n
from ..theme import Colors
from ..dialogs.channel_edit_dialog import ChannelEditDialog, _encode_psk_display

log = logging.getLogger("meshlink.channels_page")


# ===========================================================================
# Channel card (one per channel slot)
# ===========================================================================
class _ChannelCard(QFrame):
    """Expandable card showing one channel: name, role, hidden PSK,
    MQTT flags, position precision."""

    def __init__(self, channel: dict, on_edit, on_remove, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.channel = channel
        self._on_edit = on_edit
        self._on_remove = on_remove
        self._expanded = False
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header (always visible) ──
        header = QFrame()
        h = QHBoxLayout(header)
        h.setContentsMargins(14, 12, 14, 12)
        h.setSpacing(10)

        role = self.channel.get("role", "?")
        idx  = self.channel.get("index", "?")
        name = self.channel.get("name") or f"Channel {idx}"

        col = QVBoxLayout()
        col.setSpacing(2)
        col.setContentsMargins(0, 0, 0, 0)
        icon = "★" if role == "PRIMARY" else "#"
        title = QLabel(f"{icon}  {name}")
        title.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; font-size: 14px; "
            f"font-weight: 700;")
        col.addWidget(title)
        sub_bits = []
        if role == "PRIMARY":
            sub_bits.append(t("channels.primary"))
        else:
            sub_bits.append(t("channels.index", idx))
        if self.channel.get("uplink_enabled"):
            sub_bits.append("↑ MQTT")
        if self.channel.get("downlink_enabled"):
            sub_bits.append("↓ MQTT")
        sub = QLabel("  ·  ".join(sub_bits))
        sub.setStyleSheet(f"color: {Colors.TEXT_DIM}; font-size: 11px;")
        col.addWidget(sub)
        h.addLayout(col, 1)

        self.btn_edit = QPushButton("✎")
        self.btn_edit.setFixedSize(28, 28)
        self.btn_edit.setToolTip(t("channels.edit"))
        self.btn_edit.setStyleSheet(self._btn_circle_style())
        self.btn_edit.clicked.connect(lambda: self._on_edit(self.channel))
        h.addWidget(self.btn_edit)

        self.btn_expand = QPushButton("▾")
        self.btn_expand.setFixedSize(28, 28)
        self.btn_expand.setStyleSheet(self._btn_circle_style())
        self.btn_expand.clicked.connect(self._toggle_expand)
        h.addWidget(self.btn_expand)

        root.addWidget(header)

        # ── Details (collapsed by default) ──
        self.details = QFrame()
        self.details.setStyleSheet(f"""
            QFrame {{ background: {Colors.BG_SURFACE_HI};
                      border-top: 1px solid {Colors.BORDER}; }}
        """)
        d = QVBoxLayout(self.details)
        d.setContentsMargins(18, 12, 18, 14)
        d.setSpacing(8)

        # PSK row
        psk_row = QHBoxLayout()
        lbl = QLabel(t("channels.field.psk_value") + ":")
        lbl.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: 11px; font-weight: 600;")
        lbl.setFixedWidth(80)
        psk_row.addWidget(lbl)
        self.ed_psk = QLineEdit()
        self.ed_psk.setReadOnly(True)
        self.ed_psk.setEchoMode(QLineEdit.Password)
        self.ed_psk.setText(_encode_psk_display(self.channel.get("psk") or b""))
        self.ed_psk.setStyleSheet(
            f"font-family: Consolas, monospace; "
            f"background: {Colors.BG_INPUT}; "
            f"color: {Colors.TEXT_PRIMARY}; "
            f"border: 1px solid {Colors.BORDER}; padding: 4px;")
        psk_row.addWidget(self.ed_psk, 1)
        self.btn_show_psk = QPushButton("👁")
        self.btn_show_psk.setFixedWidth(34)
        self.btn_show_psk.setCheckable(True)
        self.btn_show_psk.toggled.connect(self._toggle_show_psk)
        psk_row.addWidget(self.btn_show_psk)
        self.btn_copy_psk = QPushButton("📋")
        self.btn_copy_psk.setFixedWidth(34)
        self.btn_copy_psk.setToolTip(t("common.copy"))
        self.btn_copy_psk.clicked.connect(self._copy_psk)
        psk_row.addWidget(self.btn_copy_psk)
        d.addLayout(psk_row)

        # Extra metadata grid
        meta = QHBoxLayout()
        meta.setSpacing(20)
        def _kv(k, v):
            box = QVBoxLayout()
            box.setSpacing(2)
            kl = QLabel(k)
            kl.setStyleSheet(
                f"color: {Colors.TEXT_DIM}; font-size: 10px; "
                f"font-weight: 600; text-transform: uppercase;")
            vl = QLabel(str(v))
            vl.setStyleSheet(
                f"color: {Colors.TEXT_PRIMARY}; font-size: 12px;")
            box.addWidget(kl)
            box.addWidget(vl)
            meta.addLayout(box)

        psk = self.channel.get("psk") or b""
        if not psk or (len(psk) == 1 and psk[0] in (0, 1)):
            psk_label = "Default"
        elif len(psk) == 16:
            psk_label = "AES-128"
        elif len(psk) == 32:
            psk_label = "AES-256"
        else:
            psk_label = f"{len(psk)} bytes"
        _kv("Encryption", psk_label)
        _kv(t("channels.field.uplink"),
            "✓" if self.channel.get("uplink_enabled") else "—")
        _kv(t("channels.field.downlink"),
            "✓" if self.channel.get("downlink_enabled") else "—")
        _kv(t("channels.field.position_precision"),
            self.channel.get("position_precision", 0))
        meta.addStretch(1)
        d.addLayout(meta)

        # Per-card actions row
        actions = QHBoxLayout()
        actions.addStretch(1)
        self.btn_edit2 = QPushButton("✎  " + t("channels.edit"))
        self.btn_edit2.clicked.connect(lambda: self._on_edit(self.channel))
        actions.addWidget(self.btn_edit2)
        if self.channel.get("role") != "PRIMARY":
            self.btn_remove = QPushButton("🗑  " + t("channels.remove"))
            self.btn_remove.setStyleSheet(f"""
                QPushButton {{ background: transparent;
                               color: {Colors.DANGER};
                               border: 1px solid {Colors.DANGER};
                               border-radius: 6px; padding: 6px 14px;
                               font-weight: 600; }}
                QPushButton:hover {{ background: rgba(242,107,126,0.10); }}
            """)
            self.btn_remove.clicked.connect(
                lambda: self._on_remove(self.channel))
            actions.addWidget(self.btn_remove)
        d.addLayout(actions)

        self.details.setVisible(False)
        root.addWidget(self.details)

    @staticmethod
    def _btn_circle_style() -> str:
        return f"""
            QPushButton {{
                background: transparent; color: {Colors.TEXT_DIM};
                border: 1px solid {Colors.BORDER}; border-radius: 14px;
                font-size: 14px;
            }}
            QPushButton:hover {{
                background: {Colors.BG_SURFACE_HI};
                color: {Colors.TEXT_PRIMARY};
            }}
        """

    def _toggle_expand(self):
        self._expanded = not self._expanded
        self.details.setVisible(self._expanded)
        self.btn_expand.setText("▴" if self._expanded else "▾")

    def _toggle_show_psk(self, checked: bool):
        self.ed_psk.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        self.btn_show_psk.setText("🙈" if checked else "👁")

    def _copy_psk(self):
        psk = self.channel.get("psk") or b""
        if not psk:
            return
        if len(psk) == 1 and psk[0] in (0, 1):
            return
        try:
            QApplication.clipboard().setText(
                base64.b64encode(psk).decode("ascii"))
            self.btn_copy_psk.setText("✓")
            QTimer.singleShot(1200,
                              lambda: self.btn_copy_psk.setText("📋"))
        except Exception:
            log.exception("Could not copy PSK")


# ===========================================================================
# Page
# ===========================================================================
class ChannelsPage(QWidget):

    def __init__(self, manager: MeshtasticManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.channels: List[dict] = []
        self._build_ui()
        self._connect_signals()
        i18n.languageChanged.connect(self._retranslate)
        self._retranslate()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 20)
        root.setSpacing(14)

        self.lbl_intro = QLabel()
        self.lbl_intro.setWordWrap(True)
        self.lbl_intro.setProperty("role", "muted")
        root.addWidget(self.lbl_intro)

        section_row = QHBoxLayout()
        self.lbl_section_active = QLabel()
        self.lbl_section_active.setProperty("role", "section")
        section_row.addWidget(self.lbl_section_active)
        section_row.addStretch(1)
        self.btn_add = QPushButton()
        self.btn_add.setObjectName("PrimaryButton")
        self.btn_add.clicked.connect(self._add_channel)
        self.btn_add.setEnabled(False)
        section_row.addWidget(self.btn_add)
        root.addLayout(section_row)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(8)
        self.cards_layout.addStretch(1)
        self.scroll.setWidget(self.cards_container)
        root.addWidget(self.scroll, 1)

        self.lbl_section_url = QLabel()
        self.lbl_section_url.setProperty("role", "section")
        root.addWidget(self.lbl_section_url)
        url_card = QFrame()
        url_card.setObjectName("Card")
        ul = QVBoxLayout(url_card)
        ul.setContentsMargins(14, 12, 14, 12)
        ul.setSpacing(8)
        self.url_box = QPlainTextEdit()
        self.url_box.setReadOnly(True)
        self.url_box.setMaximumHeight(72)
        ul.addWidget(self.url_box)
        btns = QHBoxLayout()
        self.copy_btn = QPushButton()
        self.copy_btn.setObjectName("PrimaryButton")
        self.copy_btn.setEnabled(False)
        self.copy_btn.clicked.connect(self._copy_url)
        btns.addWidget(self.copy_btn)
        btns.addStretch(1)
        ul.addLayout(btns)
        root.addWidget(url_card)

        # ---- Import channel from URL / QR link ----
        self.lbl_section_import = QLabel("📥  Import channels from URL / QR link")
        self.lbl_section_import.setProperty("role", "section")
        root.addWidget(self.lbl_section_import)
        import_card = QFrame()
        import_card.setObjectName("Card")
        il = QVBoxLayout(import_card)
        il.setContentsMargins(14, 12, 14, 12)
        il.setSpacing(8)
        self.lbl_import_hint = QLabel(
            "Paste a Meshtastic share link (https://meshtastic.org/e/#…) — "
            "the same link a QR code encodes. This replaces your channel set "
            "with the one in the link.")
        self.lbl_import_hint.setWordWrap(True)
        self.lbl_import_hint.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: 11px;")
        il.addWidget(self.lbl_import_hint)
        self.import_input = QPlainTextEdit()
        self.import_input.setMaximumHeight(60)
        self.import_input.setPlaceholderText(
            "https://meshtastic.org/e/#CgMSAQE...")
        il.addWidget(self.import_input)
        irow = QHBoxLayout()
        irow.addStretch(1)
        self.btn_import_url = QPushButton("📥  Import from link")
        self.btn_import_url.setObjectName("PrimaryButton")
        self.btn_import_url.setEnabled(False)
        self.btn_import_url.clicked.connect(self._import_from_url)
        irow.addWidget(self.btn_import_url)
        il.addLayout(irow)
        self.lbl_import_status = QLabel("")
        self.lbl_import_status.setWordWrap(True)
        self.lbl_import_status.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: 11px;")
        il.addWidget(self.lbl_import_status)
        root.addWidget(import_card)

    def _import_from_url(self):
        """Apply a Meshtastic channel-set URL (the QR-code payload)."""
        url = self.import_input.toPlainText().strip()
        if not url:
            return
        if "meshtastic.org/e/#" not in url and not url.startswith("http"):
            self.lbl_import_status.setText(
                "✗ That doesn't look like a Meshtastic share link "
                "(expected https://meshtastic.org/e/#…).")
            self.lbl_import_status.setStyleSheet(
                f"color: {Colors.DANGER}; font-size: 11px;")
            return
        from PySide6.QtWidgets import QMessageBox
        confirm = QMessageBox.question(
            self, "Import channels?",
            "This will replace your current channel configuration with the "
            "one encoded in the link. The device will reboot to apply it.\n\n"
            "Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        try:
            ln = self.manager.interface.localNode
            # meshtastic-python: setURL applies the channel set from the link
            ln.setURL(url)
            self.lbl_import_status.setText(
                "✓ Channels imported. The device is rebooting to apply them — "
                "it will reconnect automatically.")
            self.lbl_import_status.setStyleSheet(
                f"color: {Colors.SUCCESS}; font-size: 11px;")
            self.import_input.clear()
        except Exception as e:
            log.exception("setURL import failed")
            self.lbl_import_status.setText(f"✗ Import failed: {e}")
            self.lbl_import_status.setStyleSheet(
                f"color: {Colors.DANGER}; font-size: 11px;")

    def _retranslate(self, *_):
        self.lbl_intro.setText(t("channels.intro"))
        self.lbl_section_active.setText(t("channels.active"))
        self.lbl_section_url.setText(t("channels.url_title"))
        self.url_box.setPlaceholderText(t("channels.url_placeholder"))
        self.copy_btn.setText(t("channels.copy_url"))
        self.btn_add.setText("➕  " + t("channels.add"))
        self._refresh_list()

    def _connect_signals(self):
        self.manager.channelsUpdated.connect(self._on_channels)
        self.manager.stateChanged.connect(self._on_state)

    @Slot(str)
    def _on_state(self, state):
        is_ready = (state == "ready")
        self.btn_add.setEnabled(is_ready)
        self.btn_import_url.setEnabled(is_ready)
        if state == "idle":
            self.channels = []
            self._refresh_list()
            self.url_box.clear()
            self.copy_btn.setEnabled(False)

    @Slot(list)
    def _on_channels(self, channels: list):
        self.channels = channels
        self._refresh_list()
        self._refresh_url()

    def _refresh_list(self):
        while self.cards_layout.count() > 1:
            item = self.cards_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        active = [c for c in self.channels
                  if c.get("role") in ("PRIMARY", "SECONDARY")]
        active.sort(key=lambda c: (0 if c.get("role") == "PRIMARY" else 1,
                                   c.get("index", 99)))
        disabled = [c for c in self.channels
                    if c.get("role") == "DISABLED" and c.get("index", 0) > 0]

        for ch in active:
            card = _ChannelCard(ch,
                                on_edit=self._edit_channel,
                                on_remove=self._remove_channel)
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)

        if disabled:
            sep_lbl = QLabel(t("channels.free_slots", len(disabled)))
            sep_lbl.setStyleSheet(
                f"color: {Colors.TEXT_DIM}; font-size: 11px; "
                f"padding: 12px 4px 4px 4px;")
            self.cards_layout.insertWidget(
                self.cards_layout.count() - 1, sep_lbl)

        if self.channels and not disabled:
            self.btn_add.setEnabled(False)
            self.btn_add.setToolTip(t("channels.err_no_slot"))
        else:
            self.btn_add.setToolTip("")

    def _refresh_url(self):
        iface = self.manager.interface
        if not iface:
            return
        try:
            url = iface.localNode.getURL()
            if url:
                self.url_box.setPlainText(url)
                self.copy_btn.setEnabled(True)
        except Exception:
            self.url_box.setPlainText("(N/A)")
            self.copy_btn.setEnabled(False)

    def _copy_url(self):
        text = self.url_box.toPlainText().strip()
        if text:
            QApplication.clipboard().setText(text)
            self.copy_btn.setText(t("common.copied"))
            QTimer.singleShot(1500,
                              lambda: self.copy_btn.setText(t("channels.copy_url")))

    # ----- actions ----------------------------------------------------------
    def _add_channel(self):
        if not self.manager.is_connected:
            return
        dlg = ChannelEditDialog(existing=None, parent=self.window())
        dlg.saveRequested.connect(self._on_dialog_save)
        dlg.exec()

    def _edit_channel(self, channel: dict):
        if not self.manager.is_connected:
            return
        dlg = ChannelEditDialog(existing=channel, parent=self.window())
        dlg.saveRequested.connect(self._on_dialog_save)
        dlg.exec()

    def _remove_channel(self, channel: dict):
        idx = channel.get("index")
        if idx is None or int(idx) == 0:
            return
        ans = QMessageBox.question(
            self.window(), t("common.confirm"),
            t("channels.confirm_remove", channel.get("name", "")),
            QMessageBox.Yes | QMessageBox.No)
        if ans != QMessageBox.Yes:
            return
        ok = self.manager.remove_channel(int(idx))
        if ok:
            log.info(f"Channel {idx} removed")

    def _on_dialog_save(self, payload: dict):
        if payload.get("remove"):
            ok = self.manager.remove_channel(int(payload["index"]))
            log.info(f"remove via dialog: idx={payload['index']} ok={ok}")
            return
        if payload.get("is_new"):
            ok = self.manager.add_channel(
                name=payload["name"], psk=payload["psk"],
                uplink=payload["uplink_enabled"],
                downlink=payload["downlink_enabled"])
            log.info(f"add via dialog: name={payload['name']!r} ok={ok}")
            return
        idx = payload["index"]
        psk_to_send: Optional[bytes] = None
        existing_psk = b""
        for ch in self.channels:
            if ch.get("index") == idx:
                existing_psk = ch.get("psk") or b""
                break
        new_psk = payload["psk"]
        if new_psk != existing_psk:
            psk_to_send = new_psk
        ok = self.manager.update_channel(
            int(idx),
            name=payload["name"], psk=psk_to_send,
            uplink=payload["uplink_enabled"],
            downlink=payload["downlink_enabled"],
            position_precision=payload["position_precision"])
        log.info(f"edit via dialog: idx={idx} ok={ok}")
