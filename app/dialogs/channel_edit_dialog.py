"""
Channel add/edit dialog (V0.46) — full, user-friendly channel configuration.

Lets the user create or edit a Meshtastic channel with every option the
firmware supports, in plain language:

  • Name (max 11 chars)
  • Role: PRIMARY or SECONDARY
  • Encryption (PSK): None / Default (AQ==) / Random AES-128 / Random AES-256
    / Custom (paste base64 or hex)
  • MQTT uplink / downlink
  • Position precision (friendly presets: Off → Precise)
  • Mute channel

Emits saveRequested(dict). LoRa radio settings (region, preset, bandwidth,
spread factor, coding rate, frequency) are device-wide — not per channel —
so the dialog points the user to Settings → Quick Device Config for those,
matching how the firmware actually stores them.
"""

from __future__ import annotations

import base64
import binascii
import logging
import os
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QComboBox, QCheckBox, QPushButton, QFrame, QSpinBox, QPlainTextEdit,
    QMessageBox, QWidget
)

from ..theme import Colors

log = logging.getLogger("meshlink.channels")


# Friendly position-precision presets → bits.
# (0 = no location; 32 = full GPS. Intermediate values approximate.)
POS_PRECISION_PRESETS = [
    ("Off — don't share location",   0),
    ("Approximate — ~23 km (city)",  11),
    ("Medium — ~2.9 km (district)",  13),
    ("Close — ~700 m (neighbourhood)", 15),
    ("Fine — ~350 m (street)",       16),
    ("Precise — exact GPS",          32),
]


def _decode_psk_input(text: str) -> Optional[bytes]:
    """Decode a user-entered PSK (base64 or hex). Returns bytes or None."""
    text = (text or "").strip()
    if not text:
        return b""
    # strip optional "base64:" / "0x" prefixes
    if text.lower().startswith("base64:"):
        text = text[7:].strip()
    # try base64 first
    try:
        raw = base64.b64decode(text, validate=True)
        if len(raw) in (1, 16, 32):
            return raw
    except (binascii.Error, ValueError):
        pass
    # try hex
    hx = text[2:] if text.lower().startswith("0x") else text
    hx = hx.replace(" ", "").replace(":", "")
    try:
        raw = bytes.fromhex(hx)
        if len(raw) in (1, 16, 32):
            return raw
    except ValueError:
        pass
    return None


def _encode_psk_display(raw: bytes) -> str:
    if not raw:
        return "(no encryption)"
    if raw == b"\x01":
        return "AQ==  (default key)"
    return base64.b64encode(raw).decode("ascii")


class ChannelEditDialog(QDialog):
    """Add or edit a channel. Emits saveRequested(dict) with keys:
        is_new, remove, index, name, role (1/2), psk (bytes),
        uplink_enabled, downlink_enabled, position_precision, is_muted
    """
    saveRequested = Signal(dict)

    def __init__(self, existing: Optional[dict] = None, parent=None,
                 region_hint: str = "EU_868", lora_config: Optional[dict] = None):
        super().__init__(parent)
        self.existing = existing or {}
        self.is_new = (existing is None)
        self.region_hint = region_hint
        self.lora_config = lora_config or {}
        self.is_primary = (not self.is_new
                           and existing.get("role") == "PRIMARY")
        self.setMinimumWidth(480)
        self._build_ui()
        self._populate_from_existing()

    # ------------------------------------------------------------------ UI --
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(12)

        self.lbl_title = QLabel(
            "➕  Add channel" if self.is_new else "✎  Edit channel")
        self.lbl_title.setStyleSheet(
            f"color:{Colors.TEXT_PRIMARY}; font-size:16px; font-weight:700;")
        root.addWidget(self.lbl_title)

        self.lbl_warn = QLabel()
        self.lbl_warn.setWordWrap(True)
        self.lbl_warn.setStyleSheet(
            f"color:{Colors.WARNING}; font-size:11px; padding:6px; "
            f"background:rgba(245,185,70,0.10); border-radius:4px;")
        self.lbl_warn.setVisible(False)
        root.addWidget(self.lbl_warn)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setSpacing(10)

        # NAME
        self.ed_name = QLineEdit()
        self.ed_name.setMaxLength(11)
        self.ed_name.setPlaceholderText("e.g. SFNarrow (max 11 chars)")
        form.addRow("Name:", self.ed_name)

        # ROLE
        self.cmb_role = QComboBox()
        self.cmb_role.addItem("Secondary (private group)", 2)
        self.cmb_role.addItem("Primary (main channel)", 1)
        self.cmb_role.currentIndexChanged.connect(self._on_role_changed)
        form.addRow("Role:", self.cmb_role)

        # ENCRYPTION
        self.cmb_enc = QComboBox()
        self.cmb_enc.addItem("Default key (AQ==)", "default")
        self.cmb_enc.addItem("None — no encryption", "none")
        self.cmb_enc.addItem("Random AES-128 (recommended)", "aes128")
        self.cmb_enc.addItem("Random AES-256 (strongest)", "aes256")
        self.cmb_enc.addItem("Custom — paste a key", "custom")
        self.cmb_enc.currentIndexChanged.connect(self._on_enc_changed)
        form.addRow("Encryption:", self.cmb_enc)

        # Custom PSK input (hidden unless "custom")
        self.ed_psk = QPlainTextEdit()
        self.ed_psk.setMaximumHeight(52)
        self.ed_psk.setPlaceholderText(
            "Paste base64 or hex — 16 bytes = AES-128, 32 bytes = AES-256")
        self.ed_psk.setVisible(False)
        form.addRow("Custom key:", self.ed_psk)

        # PSK preview (read-only with show/hide)
        psk_disp = QHBoxLayout()
        self.ed_psk_display = QLineEdit()
        self.ed_psk_display.setReadOnly(True)
        self.ed_psk_display.setStyleSheet(
            f"font-family:Consolas,monospace; background:{Colors.BG_INPUT}; "
            f"color:{Colors.TEXT_SECONDARY};")
        self.ed_psk_display.setEchoMode(QLineEdit.Password)
        self.btn_show_psk = QPushButton("👁")
        self.btn_show_psk.setFixedWidth(36)
        self.btn_show_psk.setCheckable(True)
        self.btn_show_psk.toggled.connect(self._toggle_show_psk)
        psk_disp.addWidget(self.ed_psk_display, 1)
        psk_disp.addWidget(self.btn_show_psk)
        form.addRow("Current key:", psk_disp)

        # POSITION PRECISION (friendly dropdown)
        self.cmb_pos = QComboBox()
        for label, bits in POS_PRECISION_PRESETS:
            self.cmb_pos.addItem(label, bits)
        self.cmb_pos.setToolTip(
            "How precisely your location is shared on this channel. "
            "Off shares nothing; Precise shares exact GPS.")
        form.addRow("Location sharing:", self.cmb_pos)

        # MQTT + MUTE
        self.cb_uplink   = QCheckBox("Uplink to MQTT (send mesh → internet)")
        self.cb_downlink = QCheckBox("Downlink from MQTT (internet → mesh)")
        self.cb_muted    = QCheckBox("Mute this channel (no notifications)")
        form.addRow("MQTT:", self.cb_uplink)
        form.addRow("", self.cb_downlink)
        form.addRow("Options:", self.cb_muted)

        root.addLayout(form)

        # ── Advanced: device LoRa radio config (collapsible) ──────────────
        self.cb_lora_enable = QCheckBox(
            "📻  Also configure device LoRa radio (custom BW / SF / CR / slot)")
        self.cb_lora_enable.setStyleSheet(
            f"color:{Colors.TEXT_PRIMARY}; font-weight:600;")
        self.cb_lora_enable.toggled.connect(self._on_lora_toggle)
        root.addWidget(self.cb_lora_enable)

        self.lora_box = QFrame()
        self.lora_box.setObjectName("Card")
        self.lora_box.setVisible(False)
        lora_form = QFormLayout(self.lora_box)
        lora_form.setContentsMargins(14, 12, 14, 12)
        lora_form.setSpacing(8)

        lora_warn = QLabel(
            "⚠  These are DEVICE-WIDE radio settings — they affect ALL "
            "channels, not just this one. Set them to match the exact "
            "configuration your group uses (e.g. a narrow-band test channel). "
            "The device reboots to apply.")
        lora_warn.setWordWrap(True)
        lora_warn.setStyleSheet(
            f"color:{Colors.WARNING}; font-size:10px; padding:4px;")
        lora_form.addRow(lora_warn)

        # Bandwidth
        self.cmb_bw = QComboBox()
        for b in ("31", "62", "125", "250", "500"):
            self.cmb_bw.addItem(f"{b} kHz", int(b))
        self.cmb_bw.setCurrentIndex(3)  # 250 default
        self.cmb_bw.currentIndexChanged.connect(self._update_freq_preview)
        lora_form.addRow("Bandwidth:", self.cmb_bw)

        # Spreading Factor
        self.sp_sf = QSpinBox()
        self.sp_sf.setRange(7, 12)
        self.sp_sf.setValue(7)
        self.sp_sf.setToolTip("7 = faster/shorter range, 12 = slower/longer range")
        self.sp_sf.valueChanged.connect(self._update_freq_preview)
        lora_form.addRow("Spreading Factor:", self.sp_sf)

        # Coding Rate
        self.sp_cr = QSpinBox()
        self.sp_cr.setRange(5, 8)
        self.sp_cr.setValue(5)
        self.sp_cr.setToolTip("4/5 .. 4/8 — higher = more error correction, slower")
        lora_form.addRow("Coding Rate (4/x):", self.sp_cr)

        # Frequency slot
        self.sp_slot = QSpinBox()
        self.sp_slot.setRange(0, 200)
        self.sp_slot.setValue(0)
        self.sp_slot.setToolTip("Channel slot within the region band (0 = auto)")
        self.sp_slot.valueChanged.connect(self._update_freq_preview)
        lora_form.addRow("Frequency slot:", self.sp_slot)

        # Frequency override
        self.ed_freq_override = QLineEdit()
        self.ed_freq_override.setPlaceholderText("e.g. 869.618 (leave empty for auto)")
        self.ed_freq_override.setToolTip(
            "Force an exact frequency in MHz, ignoring the slot calculation.")
        lora_form.addRow("Frequency override (MHz):", self.ed_freq_override)

        # Live frequency preview
        self.lbl_freq_preview = QLabel("")
        self.lbl_freq_preview.setStyleSheet(
            f"color:{Colors.PRIMARY}; font-size:11px; font-weight:600;")
        lora_form.addRow("Calculated frequency:", self.lbl_freq_preview)

        root.addWidget(self.lora_box)

        # LoRa note
        note = QLabel(
            "ℹ  Radio settings (region, preset, bandwidth, spread factor, "
            "coding rate, frequency) are device-wide — set them in "
            "Settings → Quick Device Config. The primary channel's name also "
            "determines the LoRa frequency slot.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-size:10px;")
        root.addWidget(note)

        # Buttons
        btn_row = QHBoxLayout()
        self.btn_remove = QPushButton("🗑  Remove")
        self.btn_remove.setStyleSheet(
            f"QPushButton {{ background:{Colors.DANGER}; color:white; "
            f"border:none; border-radius:6px; padding:8px 16px; "
            f"font-weight:600; }} QPushButton:hover {{ background:#d85060; }}")
        self.btn_remove.clicked.connect(self._on_remove)
        btn_row.addWidget(self.btn_remove)
        btn_row.addStretch(1)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_cancel)
        self.btn_save = QPushButton("Save")
        self.btn_save.setObjectName("PrimaryButton")
        self.btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(self.btn_save)
        root.addLayout(btn_row)

    def _populate_from_existing(self):
        ex = self.existing
        # Pre-fill LoRa controls from the device's current config (for both
        # new and existing channels) so custom radio settings are preserved
        # and editable.
        self._populate_lora()
        if self.is_new:
            self.cmb_role.setCurrentIndex(0)   # Secondary
            self.cmb_enc.setCurrentIndex(0)    # Default key
            self.ed_psk_display.setText(_encode_psk_display(b"\x01"))
            self.btn_remove.setVisible(False)
            return

        self.ed_name.setText(ex.get("name") or "")
        # role
        role = ex.get("role")
        self.cmb_role.setCurrentIndex(1 if role == "PRIMARY" else 0)
        # encryption
        psk = ex.get("psk") or b""
        if len(psk) in (16, 32):
            self.cmb_enc.setCurrentIndex(4)   # custom
            self.ed_psk.setVisible(True)
            self.ed_psk.setPlainText(base64.b64encode(psk).decode("ascii"))
        elif psk == b"":
            self.cmb_enc.setCurrentIndex(1)   # none
        else:
            self.cmb_enc.setCurrentIndex(0)   # default
        self.ed_psk_display.setText(_encode_psk_display(psk))
        self.cb_uplink.setChecked(bool(ex.get("uplink_enabled")))
        self.cb_downlink.setChecked(bool(ex.get("downlink_enabled")))
        self.cb_muted.setChecked(bool(ex.get("is_muted")))
        # position precision → nearest preset
        bits = int(ex.get("position_precision") or 0)
        self._set_pos_from_bits(bits)
        if self.is_primary:
            self.lbl_warn.setText(
                "⚠  This is the PRIMARY channel. Changing its name or key "
                "will disconnect you from anyone using the old settings, and "
                "the name sets your LoRa frequency slot.")
            self.lbl_warn.setVisible(True)
            self.btn_remove.setVisible(False)
        else:
            self.btn_remove.setVisible(True)

    def _set_pos_from_bits(self, bits: int):
        # pick the closest preset
        best_i = 0
        best_d = 999
        for i in range(self.cmb_pos.count()):
            d = abs(self.cmb_pos.itemData(i) - bits)
            if d < best_d:
                best_d, best_i = d, i
        self.cmb_pos.setCurrentIndex(best_i)

    def _populate_lora(self):
        """Pre-fill the custom LoRa controls from the device's current config.

        If the device is on a custom (non-preset) LoRa config, tick the
        checkbox and load BW/SF/CR/slot/override so the values are preserved
        and editable. Without this, re-opening a channel would lose the
        custom radio settings the user entered.
        """
        lc = self.lora_config or {}
        if not lc:
            return
        bw   = lc.get("bandwidth") or 0
        sf   = lc.get("spread_factor") or 0
        cr   = lc.get("coding_rate") or 0
        slot = lc.get("channel_num") or 0
        override = lc.get("override_frequency") or 0.0
        use_preset = lc.get("use_preset", True)

        # Set bandwidth dropdown to the matching entry (if any)
        if bw:
            idx = self.cmb_bw.findData(int(bw))
            if idx >= 0:
                self.cmb_bw.setCurrentIndex(idx)
        if 7 <= sf <= 12:
            self.sp_sf.setValue(int(sf))
        if 5 <= cr <= 8:
            self.sp_cr.setValue(int(cr))
        if slot:
            self.sp_slot.setValue(int(slot))
        if override and override > 0:
            self.ed_freq_override.setText(f"{override:.3f}".rstrip("0").rstrip("."))

        # Auto-enable the section if the device is using a custom config
        # (i.e. not a named preset, or any custom value is set).
        has_custom = (not use_preset) or bool(override) or (
            bw and self.cmb_bw.findData(int(bw)) >= 0 and not use_preset)
        if not use_preset or override:
            self.cb_lora_enable.setChecked(True)
            self._on_lora_toggle(True)
        self._update_freq_preview()

    # ----------------------------------------------------------- actions --
    def _on_role_changed(self, *_):
        is_primary = (self.cmb_role.currentData() == 1)
        if is_primary and self.is_new:
            self.lbl_warn.setText(
                "⚠  Setting a PRIMARY channel replaces your main channel "
                "identity and your LoRa frequency slot. Only do this if you "
                "know the exact name + key your group uses.")
            self.lbl_warn.setVisible(True)
        elif not self.is_primary:
            self.lbl_warn.setVisible(False)

    def _on_enc_changed(self, *_):
        mode = self.cmb_enc.currentData()
        self.ed_psk.setVisible(mode == "custom")
        # live-preview the resulting key
        preview = {
            "default": b"\x01", "none": b"",
            "aes128": b"\x00" * 16, "aes256": b"\x00" * 32,
        }.get(mode)
        if mode == "custom":
            self.ed_psk_display.setText("(enter a custom key above)")
        elif mode in ("aes128", "aes256"):
            self.ed_psk_display.setText(
                f"(a random {'128' if mode=='aes128' else '256'}-bit key "
                f"will be generated)")
        else:
            self.ed_psk_display.setText(_encode_psk_display(preview))

    def _toggle_show_psk(self, checked: bool):
        self.ed_psk_display.setEchoMode(
            QLineEdit.Normal if checked else QLineEdit.Password)
        self.btn_show_psk.setText("🙈" if checked else "👁")

    def _on_lora_toggle(self, checked: bool):
        self.lora_box.setVisible(checked)
        if checked:
            self._update_freq_preview()

    def _update_freq_preview(self, *_):
        """Live-calculate the operating frequency from BW + slot + region.

        EU_868 base: the formula is freq = freqStart + bw/2 + slot*bw.
        We use the region the device is currently on (passed via region_hint),
        defaulting to EU_868. The override field, if set, wins.
        """
        override = self.ed_freq_override.text().strip()
        if override:
            try:
                f = float(override)
                self.lbl_freq_preview.setText(f"{f:.3f} MHz (manual override)")
                return
            except ValueError:
                pass
        bw_khz = self.cmb_bw.currentData() or 250
        slot = self.sp_slot.value()
        # Region start frequencies (MHz) — default EU_868
        region_start = {
            "EU_868": 869.4, "US": 902.0, "EU_433": 433.0, "ANZ": 915.0,
            "CN": 470.0, "JP": 920.0, "KR": 920.0, "IN": 865.0,
        }.get(self.region_hint, 869.4)
        bw_mhz = bw_khz / 1000.0
        if slot == 0:
            self.lbl_freq_preview.setText(
                f"auto (slot 0) — base {region_start:.3f} MHz, BW {bw_khz} kHz")
        else:
            freq = region_start + bw_mhz / 2.0 + (slot - 1) * bw_mhz
            self.lbl_freq_preview.setText(
                f"≈ {freq:.3f} MHz  (slot {slot}, BW {bw_khz} kHz)")

    def _resolve_psk(self) -> Optional[bytes]:
        mode = self.cmb_enc.currentData()
        if mode == "default":
            return b"\x01"
        if mode == "none":
            return b""
        if mode == "aes128":
            return os.urandom(16)
        if mode == "aes256":
            return os.urandom(32)
        # custom
        decoded = _decode_psk_input(self.ed_psk.toPlainText())
        return decoded

    def _on_remove(self):
        ans = QMessageBox.question(
            self, "Confirm",
            f"Remove channel \"{self.existing.get('name','')}\"?",
            QMessageBox.Yes | QMessageBox.No)
        if ans != QMessageBox.Yes:
            return
        self.saveRequested.emit({
            "is_new": False, "remove": True,
            "index": self.existing.get("index"),
        })
        self.accept()

    def _on_save(self):
        name = self.ed_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Error", "Channel name can't be empty.")
            return
        psk = self._resolve_psk()
        if psk is None:
            QMessageBox.warning(
                self, "Invalid key",
                "The custom key must be valid base64 or hex and decode to "
                "16 bytes (AES-128) or 32 bytes (AES-256).")
            return
        role = int(self.cmb_role.currentData())

        # Warn on PRIMARY key/name change
        if (self.is_primary and not self.is_new
                and psk != (self.existing.get("psk") or b"")):
            ans = QMessageBox.warning(
                self, "Confirm",
                "Changing the PRIMARY channel's key will disconnect you from "
                "anyone using the old key. Continue?",
                QMessageBox.Yes | QMessageBox.No)
            if ans != QMessageBox.Yes:
                return

        payload = {
            "is_new":             self.is_new,
            "remove":             False,
            "index":              (None if self.is_new
                                   else self.existing.get("index")),
            "name":               name,
            "role":               role,
            "psk":                psk,
            "uplink_enabled":     self.cb_uplink.isChecked(),
            "downlink_enabled":   self.cb_downlink.isChecked(),
            "position_precision": int(self.cmb_pos.currentData()),
            "is_muted":           self.cb_muted.isChecked(),
        }
        # Optional device-wide LoRa radio config
        if self.cb_lora_enable.isChecked():
            override = self.ed_freq_override.text().strip()
            override_f = None
            if override:
                try:
                    override_f = float(override)
                except ValueError:
                    QMessageBox.warning(self, "Invalid frequency",
                        "Frequency override must be a number in MHz, "
                        "e.g. 869.618")
                    return
            payload["lora"] = {
                "use_preset":         False,
                "bandwidth":          self.cmb_bw.currentData(),
                "spread_factor":      self.sp_sf.value(),
                "coding_rate":        self.sp_cr.value(),
                "channel_num":        self.sp_slot.value(),
                "override_frequency": override_f,
            }
        self.saveRequested.emit(payload)
        self.accept()
