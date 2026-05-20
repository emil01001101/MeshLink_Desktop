"""
Channel edit / add dialog.

Used by ChannelsPage for both creating new SECONDARY channels and editing
existing ones. Emits `saveRequested(dict)` on confirm — the page is
responsible for actually writing through MeshtasticManager.

Fields:
    name                 — 1..11 chars
    psk_mode             — "default" | "random" | "custom"
    psk_text             — base64 or hex (when mode == custom)
    uplink_enabled       — MQTT bridge inbound
    downlink_enabled     — MQTT bridge outbound
    position_precision   — 0..32 (0 = disabled, 32 = full lat/lon)

When opened in ADD mode (existing=None) the user gets:
    [ Name ] [ PSK mode: default/random/custom ] [ uplink/downlink ] [ position precision ]

When opened in EDIT mode (existing=dict from _publish_channels) all fields
are pre-filled. Editing the PRIMARY channel triggers a warning because
changing its name or key disconnects the device from the rest of the mesh.
"""

from __future__ import annotations

import os
import base64
import binascii
import logging
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QComboBox, QCheckBox, QPushButton, QFrame, QSpinBox, QRadioButton,
    QButtonGroup, QPlainTextEdit, QMessageBox
)

from ..theme import Colors
from ..i18n import t, i18n

log = logging.getLogger("meshlink.channel_edit")


# ===========================================================================
# Helpers
# ===========================================================================
def _decode_psk_input(text: str) -> Optional[bytes]:
    """Try to decode a user-provided PSK string as base64 or hex.

    Returns bytes on success, None if the input is unparseable or has a
    length other than 16 / 32 bytes.
    """
    text = (text or "").strip()
    if not text:
        return b""
    # Try base64 first (most common in channel URLs)
    for decoder in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            raw = decoder(text + "=" * (-len(text) % 4))
            if len(raw) in (16, 32):
                return raw
        except (binascii.Error, ValueError):
            pass
    # Try hex
    try:
        cleaned = text.replace(" ", "").replace(":", "").replace("-", "")
        raw = bytes.fromhex(cleaned)
        if len(raw) in (16, 32):
            return raw
    except ValueError:
        pass
    return None


def _encode_psk_display(raw: bytes) -> str:
    """Pretty base64 of bytes for the read-only field."""
    if not raw:
        return ""
    if len(raw) == 1 and raw[0] in (0, 1):
        return "(default key)"
    try:
        return base64.b64encode(raw).decode("ascii")
    except Exception:
        return raw.hex()


# ===========================================================================
# Dialog
# ===========================================================================
class ChannelEditDialog(QDialog):
    """Add or edit a channel.

    Emits `saveRequested(dict)` with the following keys:
        is_new:               bool       (True when adding a new channel)
        index:                int|None   (slot to write; None when adding)
        name:                 str
        psk:                  bytes      (b"" → use default; 16/32 = AES)
        uplink_enabled:       bool
        downlink_enabled:     bool
        position_precision:   int
    """

    saveRequested = Signal(dict)

    def __init__(self, existing: Optional[dict] = None, parent=None):
        super().__init__(parent)
        self.existing = existing or {}
        self.is_new = (existing is None)
        self.is_primary = (not self.is_new
                           and existing.get("role") == "PRIMARY")
        self.setMinimumWidth(440)
        self._build_ui()
        self._populate_from_existing()
        i18n.languageChanged.connect(self._retranslate)
        self._retranslate()

    # ------------------------------------------------------------------ UI --
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        self.lbl_title = QLabel()
        self.lbl_title.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; font-size: 16px; "
            f"font-weight: 700;")
        root.addWidget(self.lbl_title)

        self.lbl_warn = QLabel()
        self.lbl_warn.setWordWrap(True)
        self.lbl_warn.setStyleSheet(
            f"color: {Colors.WARNING}; font-size: 11px; padding: 6px;"
            f"background: rgba(245, 185, 70, 0.10); border-radius: 4px;")
        self.lbl_warn.setVisible(False)
        root.addWidget(self.lbl_warn)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setSpacing(10)

        # NAME
        self.lbl_name = QLabel()
        self.ed_name = QLineEdit()
        self.ed_name.setMaxLength(11)
        self.ed_name.setPlaceholderText("e.g. Iberia (max 11 chars)")
        form.addRow(self.lbl_name, self.ed_name)

        # PSK mode + value
        self.lbl_psk_mode = QLabel()
        psk_row = QHBoxLayout()
        self.psk_group = QButtonGroup(self)
        self.rb_psk_default = QRadioButton()
        self.rb_psk_random  = QRadioButton()
        self.rb_psk_custom  = QRadioButton()
        for rb in (self.rb_psk_default, self.rb_psk_random, self.rb_psk_custom):
            self.psk_group.addButton(rb)
            psk_row.addWidget(rb)
        psk_row.addStretch(1)
        form.addRow(self.lbl_psk_mode, psk_row)

        self.lbl_psk_val = QLabel()
        psk_v = QVBoxLayout()
        psk_v.setSpacing(4)
        self.ed_psk = QPlainTextEdit()
        self.ed_psk.setMaximumHeight(56)
        self.ed_psk.setPlaceholderText(
            "Paste base64 or hex (16 bytes = AES128, 32 bytes = AES256)")
        psk_v.addWidget(self.ed_psk)
        self.lbl_psk_hint = QLabel()
        self.lbl_psk_hint.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: 10px;")
        self.lbl_psk_hint.setWordWrap(True)
        psk_v.addWidget(self.lbl_psk_hint)

        # PSK display row (read-only, with show/hide toggle)
        psk_disp = QHBoxLayout()
        self.ed_psk_display = QLineEdit()
        self.ed_psk_display.setReadOnly(True)
        self.ed_psk_display.setStyleSheet(
            f"font-family: Consolas, monospace; "
            f"background: {Colors.BG_INPUT}; "
            f"color: {Colors.TEXT_SECONDARY};")
        self.ed_psk_display.setEchoMode(QLineEdit.Password)
        self.btn_show_psk = QPushButton("👁")
        self.btn_show_psk.setFixedWidth(34)
        self.btn_show_psk.setCheckable(True)
        self.btn_show_psk.toggled.connect(self._toggle_show_psk)
        psk_disp.addWidget(self.ed_psk_display, 1)
        psk_disp.addWidget(self.btn_show_psk)
        psk_v.addLayout(psk_disp)
        form.addRow(self.lbl_psk_val, psk_v)

        # MQTT uplink/downlink
        self.cb_uplink   = QCheckBox()
        self.cb_downlink = QCheckBox()
        form.addRow("", self.cb_uplink)
        form.addRow("", self.cb_downlink)

        # Position precision
        self.lbl_pos_prec = QLabel()
        self.sp_pos_prec = QSpinBox()
        self.sp_pos_prec.setRange(0, 32)
        self.sp_pos_prec.setSingleStep(1)
        self.sp_pos_prec.setSuffix(" bits")
        self.sp_pos_prec.setToolTip(
            "0 = position disabled, 32 = full GPS precision. "
            "Lower values approximate the location.")
        form.addRow(self.lbl_pos_prec, self.sp_pos_prec)

        root.addLayout(form)

        # ── Buttons ──
        btn_row = QHBoxLayout()
        self.btn_remove = QPushButton()
        self.btn_remove.setObjectName("DangerButton")
        self.btn_remove.setStyleSheet(f"""
            QPushButton#DangerButton {{
                background: {Colors.DANGER}; color: white;
                border: none; border-radius: 6px;
                padding: 8px 16px; font-weight: 600;
            }}
            QPushButton#DangerButton:hover {{ background: #d85060; }}
        """)
        self.btn_remove.clicked.connect(self._on_remove)
        btn_row.addWidget(self.btn_remove)
        btn_row.addStretch(1)
        self.btn_cancel = QPushButton()
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_cancel)
        self.btn_save = QPushButton()
        self.btn_save.setObjectName("PrimaryButton")
        self.btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(self.btn_save)
        root.addLayout(btn_row)

        # Wire mode radios
        for rb in (self.rb_psk_default, self.rb_psk_random, self.rb_psk_custom):
            rb.toggled.connect(self._on_psk_mode_changed)

    def _populate_from_existing(self):
        ex = self.existing
        if self.is_new:
            self.ed_name.setText("")
            self.rb_psk_default.setChecked(True)
            self.cb_uplink.setChecked(False)
            self.cb_downlink.setChecked(False)
            self.sp_pos_prec.setValue(0)
            self.ed_psk_display.setText("(will use default key)")
            self.btn_remove.setVisible(False)
            return

        self.ed_name.setText(ex.get("name") or "")
        psk = ex.get("psk") or b""
        if len(psk) in (16, 32):
            self.rb_psk_custom.setChecked(True)
            self.ed_psk.setPlainText(base64.b64encode(psk).decode("ascii"))
        else:
            self.rb_psk_default.setChecked(True)
        self.ed_psk_display.setText(_encode_psk_display(psk))
        self.cb_uplink.setChecked(bool(ex.get("uplink_enabled")))
        self.cb_downlink.setChecked(bool(ex.get("downlink_enabled")))
        self.sp_pos_prec.setValue(int(ex.get("position_precision") or 0))
        # PRIMARY channel — show warning, hide remove button (can't remove
        # PRIMARY; would brick the device).
        if self.is_primary:
            self.lbl_warn.setVisible(True)
            self.btn_remove.setVisible(False)
        else:
            self.btn_remove.setVisible(True)

    def _retranslate(self, *_):
        if self.is_new:
            self.setWindowTitle(t("channels.dlg_add_title"))
            self.lbl_title.setText("➕  " + t("channels.dlg_add_title"))
        elif self.is_primary:
            self.setWindowTitle(t("channels.dlg_edit_primary_title"))
            self.lbl_title.setText("✎  " + t("channels.dlg_edit_primary_title"))
            self.lbl_warn.setText("⚠  " + t("channels.warn_primary"))
        else:
            idx = self.existing.get("index", "?")
            self.setWindowTitle(t("channels.dlg_edit_title", idx))
            self.lbl_title.setText("✎  " + t("channels.dlg_edit_title", idx))

        self.lbl_name.setText(t("channels.field.name") + ":")
        self.lbl_psk_mode.setText(t("channels.field.psk_mode") + ":")
        self.rb_psk_default.setText(t("channels.psk.default"))
        self.rb_psk_random.setText(t("channels.psk.random"))
        self.rb_psk_custom.setText(t("channels.psk.custom"))
        self.lbl_psk_val.setText(t("channels.field.psk_value") + ":")
        self.lbl_psk_hint.setText(t("channels.psk_hint"))
        self.cb_uplink.setText(t("channels.field.uplink"))
        self.cb_downlink.setText(t("channels.field.downlink"))
        self.lbl_pos_prec.setText(t("channels.field.position_precision") + ":")
        self.btn_remove.setText("🗑  " + t("channels.remove"))
        self.btn_cancel.setText(t("common.cancel"))
        self.btn_save.setText(t("common.save"))

    # ----------------------------------------------------------- actions --
    def _on_psk_mode_changed(self, _checked: bool):
        if self.rb_psk_custom.isChecked():
            self.ed_psk.setEnabled(True)
            self.ed_psk.setFocus()
        else:
            self.ed_psk.setEnabled(False)
            self.ed_psk.clear()

    def _toggle_show_psk(self, checked: bool):
        self.ed_psk_display.setEchoMode(
            QLineEdit.Normal if checked else QLineEdit.Password)
        self.btn_show_psk.setText("🙈" if checked else "👁")

    def _on_remove(self):
        ans = QMessageBox.question(
            self, t("common.confirm"),
            t("channels.confirm_remove", self.existing.get("name", "")),
            QMessageBox.Yes | QMessageBox.No)
        if ans != QMessageBox.Yes:
            return
        payload = {
            "is_new":  False,
            "remove":  True,
            "index":   self.existing.get("index"),
        }
        self.saveRequested.emit(payload)
        self.accept()

    def _on_save(self):
        name = self.ed_name.text().strip()
        if not name:
            QMessageBox.warning(self, t("common.error"),
                                t("channels.err_name_empty"))
            return

        # Resolve PSK from mode
        if self.rb_psk_default.isChecked():
            psk = b""
        elif self.rb_psk_random.isChecked():
            psk = os.urandom(16)
            log.info("Generated random 16-byte PSK")
        else:   # custom
            txt = self.ed_psk.toPlainText().strip()
            decoded = _decode_psk_input(txt)
            if decoded is None:
                QMessageBox.warning(self, t("common.error"),
                                    t("channels.err_psk_format"))
                return
            psk = decoded

        # Extra warning when editing PRIMARY with a key change
        if (self.is_primary and not self.is_new
                and psk != (self.existing.get("psk") or b"")):
            ans = QMessageBox.warning(
                self, t("common.confirm"),
                t("channels.confirm_primary_psk"),
                QMessageBox.Yes | QMessageBox.No)
            if ans != QMessageBox.Yes:
                return

        payload = {
            "is_new":             self.is_new,
            "remove":             False,
            "index":              (None if self.is_new
                                   else self.existing.get("index")),
            "name":               name,
            "psk":                psk,
            "uplink_enabled":     self.cb_uplink.isChecked(),
            "downlink_enabled":   self.cb_downlink.isChecked(),
            "position_precision": int(self.sp_pos_prec.value()),
        }
        self.saveRequested.emit(payload)
        self.accept()
