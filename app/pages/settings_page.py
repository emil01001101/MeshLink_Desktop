"""
Settings page — app preferences (language, auto-reconnect, notifications,
istoric) + actiuni device (owner, reboot, reset NodeDB). Cu i18n.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFrame, QMessageBox, QGridLayout, QComboBox, QCheckBox
)

from ..connection import MeshtasticManager
from ..settings_store import Settings
from ..theme import Colors
from ..i18n import t, i18n, LANGUAGE_NAMES

log = logging.getLogger("meshlink.settings")


class SettingsPage(QWidget):

    preferenceChanged = Signal(str, object)   # (key, value)

    def __init__(self, manager: MeshtasticManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self._build_ui()
        self._load_preferences()
        self._connect_signals()
        i18n.languageChanged.connect(self._retranslate)
        self._retranslate()

    def _build_ui(self):
        # Wrap everything in a scroll area — the page now has a lot of
        # content (preferences + owner + quick device config + actions).
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        from PySide6.QtWidgets import QScrollArea
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {Colors.BG_BASE}; border: none; }}")
        host = QWidget()
        scroll.setWidget(host)
        outer.addWidget(scroll)

        root = QVBoxLayout(host)
        root.setContentsMargins(20, 16, 20, 20)
        root.setSpacing(16)

        # info / hint
        hint = QFrame()
        hint.setObjectName("Card")
        hl = QHBoxLayout(hint)
        hl.setContentsMargins(16, 12, 16, 12)
        ic = QLabel("ℹ")
        ic.setStyleSheet(f"color: {Colors.PRIMARY}; font-size: 18px;")
        hl.addWidget(ic)
        self.lbl_hint = QLabel()
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        hl.addWidget(self.lbl_hint, 1)
        root.addWidget(hint)

        # ============== Application preferences ==============
        prefs = QFrame()
        prefs.setObjectName("Card")
        pl = QVBoxLayout(prefs)
        pl.setContentsMargins(18, 16, 18, 16)
        pl.setSpacing(10)
        self.lbl_section_prefs = QLabel()
        self.lbl_section_prefs.setProperty("role", "section")
        pl.addWidget(self.lbl_section_prefs)

        # limba
        lang_row = QHBoxLayout()
        self.lbl_lang = QLabel()
        lang_row.addWidget(self.lbl_lang)
        self.lang_combo = QComboBox()
        for code, label in LANGUAGE_NAMES.items():
            self.lang_combo.addItem(label, code)
        lang_row.addWidget(self.lang_combo, 1)
        pl.addLayout(lang_row)

        self.cb_auto_reconnect = QCheckBox()
        pl.addWidget(self.cb_auto_reconnect)
        self.cb_notifications = QCheckBox()
        pl.addWidget(self.cb_notifications)
        self.cb_save_history = QCheckBox()
        pl.addWidget(self.cb_save_history)

        root.addWidget(prefs)

        # ============== Owner ==============
        owner = QFrame()
        owner.setObjectName("Card")
        ol = QVBoxLayout(owner)
        ol.setContentsMargins(18, 16, 18, 16)
        ol.setSpacing(10)
        self.lbl_section_owner = QLabel()
        self.lbl_section_owner.setProperty("role", "section")
        ol.addWidget(self.lbl_section_owner)
        self.lbl_owner_hint = QLabel()
        self.lbl_owner_hint.setWordWrap(True)
        ol.addWidget(self.lbl_owner_hint)

        og = QGridLayout()
        og.setHorizontalSpacing(10)
        og.setVerticalSpacing(8)
        og.setColumnStretch(1, 1)
        self.lbl_long_name = QLabel()
        og.addWidget(self.lbl_long_name, 0, 0)
        self.long_name_input = QLineEdit()
        self.long_name_input.setMaxLength(40)
        og.addWidget(self.long_name_input, 0, 1)
        self.lbl_short_name = QLabel()
        og.addWidget(self.lbl_short_name, 1, 0)
        self.short_name_input = QLineEdit()
        self.short_name_input.setMaxLength(4)
        og.addWidget(self.short_name_input, 1, 1)
        ol.addLayout(og)

        obtns = QHBoxLayout()
        obtns.addStretch(1)
        self.save_owner_btn = QPushButton()
        self.save_owner_btn.setObjectName("PrimaryButton")
        self.save_owner_btn.setEnabled(False)
        self.save_owner_btn.clicked.connect(self._save_owner)
        obtns.addWidget(self.save_owner_btn)
        ol.addLayout(obtns)
        root.addWidget(owner)

        # ============== Quick Device Config ==============
        self._build_quick_config(root)

        # ============== Watchlist / Alerts ==============
        self._build_watchlist(root)

        # ============== Actions ==============
        actions = QFrame()
        actions.setObjectName("Card")
        al = QVBoxLayout(actions)
        al.setContentsMargins(18, 16, 18, 16)
        al.setSpacing(10)
        self.lbl_section_actions = QLabel()
        self.lbl_section_actions.setProperty("role", "section")
        al.addWidget(self.lbl_section_actions)
        self.lbl_actions_warn = QLabel()
        self.lbl_actions_warn.setWordWrap(True)
        self.lbl_actions_warn.setStyleSheet(f"color: {Colors.WARNING}; font-size: 11px;")
        al.addWidget(self.lbl_actions_warn)

        ar = QHBoxLayout()
        self.reboot_btn = QPushButton()
        self.reboot_btn.setEnabled(False)
        self.reboot_btn.clicked.connect(self._reboot_confirm)
        ar.addWidget(self.reboot_btn)
        self.reset_db_btn = QPushButton()
        self.reset_db_btn.setObjectName("DangerButton")
        self.reset_db_btn.setEnabled(False)
        self.reset_db_btn.clicked.connect(self._reset_db_confirm)
        ar.addWidget(self.reset_db_btn)
        ar.addStretch(1)
        al.addLayout(ar)
        root.addWidget(actions)

        # ============== About ==============
        about = QFrame()
        about.setObjectName("Card")
        abl = QVBoxLayout(about)
        abl.setContentsMargins(18, 16, 18, 16)
        abl.setSpacing(6)
        self.lbl_section_about = QLabel()
        self.lbl_section_about.setProperty("role", "section")
        abl.addWidget(self.lbl_section_about)
        self.lbl_about_text = QLabel()
        abl.addWidget(self.lbl_about_text)
        self.lbl_about_inspired = QLabel()
        self.lbl_about_inspired.setStyleSheet(f"color: {Colors.TEXT_DIM}; font-size: 11px;")
        self.lbl_about_inspired.setWordWrap(True)
        abl.addWidget(self.lbl_about_inspired)
        self.lbl_log_hint = QLabel()
        self.lbl_log_hint.setStyleSheet(f"color: {Colors.TEXT_DIM}; font-size: 11px;")
        abl.addWidget(self.lbl_log_hint)
        root.addWidget(about)
        root.addStretch(1)

    def _build_watchlist(self, root):
        """🔔 Watchlist / Alerts — notify when a watched node comes online or
        a watched keyword appears in a message. Good for fixed base stations."""
        from ..watchlist import Watchlist
        from PySide6.QtWidgets import QListWidget, QListWidgetItem
        wl = Watchlist.get()

        card = QFrame(); card.setObjectName("Card")
        v = QVBoxLayout(card); v.setContentsMargins(18, 16, 18, 16); v.setSpacing(10)
        title = QLabel("🔔  Watchlist & Alerts")
        title.setProperty("role", "section")
        v.addWidget(title)
        hint = QLabel(
            "Get a desktop notification + sound when a watched node comes "
            "back online, or when a message contains a keyword (e.g. SOS, "
            "your name). Ideal for an always-on station.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")
        v.addWidget(hint)

        self.wl_enabled = QCheckBox("Enable watchlist alerts")
        self.wl_enabled.setChecked(wl.enabled)
        self.wl_enabled.toggled.connect(lambda c: setattr(Watchlist.get(), "enabled", c))
        v.addWidget(self.wl_enabled)

        # Nodes
        cols = QHBoxLayout()
        # --- nodes column ---
        ncol = QVBoxLayout()
        ncol.addWidget(QLabel("Watched nodes (by ID):"))
        self.wl_node_list = QListWidget()
        self.wl_node_list.setMaximumHeight(90)
        for n in wl.nodes:
            self.wl_node_list.addItem(n)
        ncol.addWidget(self.wl_node_list)
        nrow = QHBoxLayout()
        self.wl_node_input = QLineEdit()
        self.wl_node_input.setPlaceholderText("!a1b2c3d4")
        nrow.addWidget(self.wl_node_input, 1)
        btn_add_node = QPushButton("Add")
        btn_add_node.clicked.connect(self._wl_add_node)
        nrow.addWidget(btn_add_node)
        btn_del_node = QPushButton("Remove")
        btn_del_node.clicked.connect(self._wl_remove_node)
        nrow.addWidget(btn_del_node)
        ncol.addLayout(nrow)
        cols.addLayout(ncol)

        # --- keywords column ---
        kcol = QVBoxLayout()
        kcol.addWidget(QLabel("Watched keywords:"))
        self.wl_kw_list = QListWidget()
        self.wl_kw_list.setMaximumHeight(90)
        for k in wl.keywords:
            self.wl_kw_list.addItem(k)
        kcol.addWidget(self.wl_kw_list)
        krow = QHBoxLayout()
        self.wl_kw_input = QLineEdit()
        self.wl_kw_input.setPlaceholderText("SOS, urgent, my name…")
        krow.addWidget(self.wl_kw_input, 1)
        btn_add_kw = QPushButton("Add")
        btn_add_kw.clicked.connect(self._wl_add_kw)
        krow.addWidget(btn_add_kw)
        btn_del_kw = QPushButton("Remove")
        btn_del_kw.clicked.connect(self._wl_remove_kw)
        krow.addWidget(btn_del_kw)
        kcol.addLayout(krow)
        cols.addLayout(kcol)

        v.addLayout(cols)
        root.addWidget(card)

    def _wl_add_node(self):
        from ..watchlist import Watchlist
        nid = self.wl_node_input.text().strip()
        if nid:
            Watchlist.get().add_node(nid)
            self.wl_node_list.addItem(nid)
            self.wl_node_input.clear()

    def _wl_remove_node(self):
        from ..watchlist import Watchlist
        it = self.wl_node_list.currentItem()
        if it:
            Watchlist.get().remove_node(it.text())
            self.wl_node_list.takeItem(self.wl_node_list.row(it))

    def _wl_add_kw(self):
        from ..watchlist import Watchlist
        kw = self.wl_kw_input.text().strip()
        if kw:
            Watchlist.get().add_keyword(kw)
            self.wl_kw_list.addItem(kw)
            self.wl_kw_input.clear()

    def _wl_remove_kw(self):
        from ..watchlist import Watchlist
        it = self.wl_kw_list.currentItem()
        if it:
            Watchlist.get().remove_keyword(it.text())
            self.wl_kw_list.takeItem(self.wl_kw_list.row(it))

    def _build_quick_config(self, root):
        """A compact panel to configure the most common device settings
        without using the Console. Each control writes to the device when
        the user clicks the per-row Apply button (or the global Save).

        Grouped: Identity, Radio, Position, Broadcast intervals, Display,
        Power saving.
        """
        from PySide6.QtWidgets import QSpinBox, QDoubleSpinBox

        card = QFrame()
        card.setObjectName("Card")
        v = QVBoxLayout(card)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)

        self.lbl_section_quick = QLabel("⚡  Quick device configuration")
        self.lbl_section_quick.setProperty("role", "section")
        v.addWidget(self.lbl_section_quick)

        self.lbl_quick_hint = QLabel(
            "Configure common device settings directly. Each change is "
            "written to the radio and may trigger a brief reboot "
            "(auto-reconnect handles it). Requires an active connection.")
        self.lbl_quick_hint.setWordWrap(True)
        self.lbl_quick_hint.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")
        v.addWidget(self.lbl_quick_hint)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)
        self._qc_widgets = {}   # field_key -> (widget, getter)
        r = 0

        def add_label_row(text):
            nonlocal r
            lbl = QLabel(text)
            lbl.setStyleSheet(
                f"color: {Colors.PRIMARY}; font-size: 11px; "
                f"font-weight: 700; padding-top: 6px;")
            grid.addWidget(lbl, r, 0, 1, 3)
            r += 1

        def add_field(label, widget, key, getter, hint=""):
            nonlocal r
            cap = QLabel(label)
            grid.addWidget(cap, r, 0)
            grid.addWidget(widget, r, 1)
            if hint:
                widget.setToolTip(hint)
            self._qc_widgets[key] = (widget, getter)
            r += 1

        # ----- Identity -----
        add_label_row("IDENTITY")
        self.qc_long = QLineEdit(); self.qc_long.setMaxLength(40)
        self.qc_long.setPlaceholderText("e.g. My Base Station")
        add_field("Long name", self.qc_long, "owner_long",
                  lambda: self.qc_long.text().strip())
        self.qc_short = QLineEdit(); self.qc_short.setMaxLength(4)
        self.qc_short.setPlaceholderText("e.g. BASE (max 4)")
        add_field("Short name", self.qc_short, "owner_short",
                  lambda: self.qc_short.text().strip())

        # ----- Radio -----
        add_label_row("RADIO (LoRa)")
        self.qc_region = QComboBox()
        REGIONS = ["UNSET","US","EU_433","EU_868","CN","JP","ANZ","KR","TW",
                   "RU","IN","NZ_865","TH","LORA_24","UA_433","UA_868",
                   "MY_433","MY_919","SG_923"]
        self.qc_region.addItems(REGIONS)
        add_field("Region", self.qc_region, "region",
                  lambda: self.qc_region.currentText(),
                  "Your country's LoRa band — MUST match your local mesh.")
        self.qc_preset = QComboBox()
        PRESETS = ["LONG_FAST","LONG_SLOW","VERY_LONG_SLOW","MEDIUM_SLOW",
                   "MEDIUM_FAST","SHORT_SLOW","SHORT_FAST","LONG_MODERATE",
                   "SHORT_TURBO","LONG_TURBO"]
        self.qc_preset.addItems(PRESETS)
        add_field("Modem preset", self.qc_preset, "preset",
                  lambda: self.qc_preset.currentText(),
                  "Named LoRa profile. For a fully custom config (e.g. a "
                  "narrow-band channel like BW 62.5/SF7/CR5), tick "
                  "'Use custom LoRa' below instead.")
        self.qc_hop = QSpinBox(); self.qc_hop.setRange(1, 7); self.qc_hop.setValue(3)
        add_field("Hop limit", self.qc_hop, "hop_limit",
                  lambda: self.qc_hop.value(),
                  "Max relays a packet can take (1–7). 3 is typical.")
        self.qc_txpow = QSpinBox(); self.qc_txpow.setRange(0, 30); self.qc_txpow.setValue(0)
        add_field("TX power (dBm, 0=max legal)", self.qc_txpow, "tx_power",
                  lambda: self.qc_txpow.value(),
                  "0 lets the firmware pick the max legal power for your region.")

        # ----- Custom LoRa (advanced) -----
        add_label_row("CUSTOM LoRa (advanced — overrides preset)")
        self.qc_use_custom = QCheckBox(
            "Use custom LoRa parameters instead of a named preset")
        add_field("", self.qc_use_custom, "use_custom_lora",
                  lambda: self.qc_use_custom.isChecked(),
                  "Enable to set bandwidth / spread factor / coding rate "
                  "manually — for narrow-band channels (e.g. 'SFNarrow').")
        self.qc_bw = QComboBox(); self.qc_bw.setEditable(True)
        for b in ["31","62","125","250","500"]:
            self.qc_bw.addItem(b)
        self.qc_bw.setCurrentText("250")
        add_field("Bandwidth (kHz)", self.qc_bw, "bandwidth",
                  lambda: self._parse_leading_int(self.qc_bw.currentText(), 250),
                  "Lower = longer range, slower. SFNarrow uses 62 kHz.")
        self.qc_sf = QSpinBox(); self.qc_sf.setRange(7, 12); self.qc_sf.setValue(7)
        add_field("Spread factor (SF)", self.qc_sf, "spread_factor",
                  lambda: self.qc_sf.value(),
                  "7–12. Higher = longer range, much slower. SFNarrow uses SF7.")
        self.qc_cr = QSpinBox(); self.qc_cr.setRange(5, 8); self.qc_cr.setValue(5)
        add_field("Coding rate (CR 4/x)", self.qc_cr, "coding_rate",
                  lambda: self.qc_cr.value(),
                  "5–8 (i.e. 4/5..4/8). SFNarrow uses CR5.")
        self.qc_freq_slot = QSpinBox(); self.qc_freq_slot.setRange(0, 200)
        add_field("Frequency slot (0=auto)", self.qc_freq_slot, "channel_num",
                  lambda: self.qc_freq_slot.value(),
                  "Channel slot within the region band. 0 = auto from channel name.")

        # ----- Position -----
        add_label_row("POSITION (fixed)")
        from PySide6.QtWidgets import QDoubleSpinBox
        self.qc_lat = QDoubleSpinBox(); self.qc_lat.setRange(-90, 90)
        self.qc_lat.setDecimals(6); self.qc_lat.setSingleStep(0.0001)
        add_field("Latitude", self.qc_lat, "lat", lambda: self.qc_lat.value())
        self.qc_lon = QDoubleSpinBox(); self.qc_lon.setRange(-180, 180)
        self.qc_lon.setDecimals(6); self.qc_lon.setSingleStep(0.0001)
        add_field("Longitude", self.qc_lon, "lon", lambda: self.qc_lon.value())
        self.qc_alt = QSpinBox(); self.qc_alt.setRange(-500, 9000)
        add_field("Altitude (m)", self.qc_alt, "alt", lambda: self.qc_alt.value())

        # ----- Broadcast intervals -----
        add_label_row("BROADCAST INTERVALS")
        self.qc_nodeinfo = QComboBox()
        self.qc_nodeinfo.setEditable(True)
        for v_ in ["900","1800","3600","10800","21600"]:
            self.qc_nodeinfo.addItem(v_)
        add_field("Node-info broadcast (s)", self.qc_nodeinfo, "nodeinfo_secs",
                  lambda: int(self.qc_nodeinfo.currentText() or 900),
                  "How often the device announces itself. 900s = 15min.")
        self.qc_posbcast = QComboBox()
        self.qc_posbcast.setEditable(True)
        for v_ in ["900","1800","3600","10800","43200"]:
            self.qc_posbcast.addItem(v_)
        add_field("Position broadcast (s)", self.qc_posbcast, "pos_secs",
                  lambda: int(self.qc_posbcast.currentText() or 900),
                  "How often the device shares its position. 3600s = 1h.")

        # ----- Display -----
        add_label_row("DISPLAY")
        self.qc_screen = QComboBox()
        self.qc_screen.setEditable(True)
        for v_ in ["0 (always on)","10","30","60","120","300","600"]:
            self.qc_screen.addItem(v_)
        add_field("Screen timeout (s)", self.qc_screen, "screen_secs",
                  lambda: self._parse_leading_int(self.qc_screen.currentText(), 60),
                  "Seconds before the OLED turns off. 0 = always on.")
        self.qc_carousel = QSpinBox(); self.qc_carousel.setRange(0, 600)
        add_field("Auto screen carousel (s)", self.qc_carousel, "carousel_secs",
                  lambda: self.qc_carousel.value(),
                  "Auto-cycle screens every N seconds. 0 = disabled.")
        self.qc_wake_tap = QCheckBox("Wake screen on tap / motion")
        add_field("", self.qc_wake_tap, "wake_on_tap",
                  lambda: self.qc_wake_tap.isChecked())
        self.qc_12h = QCheckBox("Use 12-hour clock")
        add_field("", self.qc_12h, "use_12h",
                  lambda: self.qc_12h.isChecked())

        # ----- Buttons / LED -----
        add_label_row("BUTTONS & LED")
        self.qc_led_off = QCheckBox("Disable LED heartbeat (blinking)")
        add_field("", self.qc_led_off, "led_heartbeat_disabled",
                  lambda: self.qc_led_off.isChecked(),
                  "Stops the periodic status LED blink (saves a little power).")
        self.qc_buzzer = QComboBox()
        self.qc_buzzer.addItems(["DEFAULT","ALL_ENABLED","DISABLED",
                                 "NOTIFICATIONS_ONLY","SYSTEM_ONLY"])
        add_field("Buzzer mode", self.qc_buzzer, "buzzer_mode",
                  lambda: self.qc_buzzer.currentText())
        self.qc_double_tap = QCheckBox("Double-tap acts as button press")
        add_field("", self.qc_double_tap, "double_tap",
                  lambda: self.qc_double_tap.isChecked())

        # ----- Power saving -----
        add_label_row("POWER SAVING")
        self.qc_power_saving = QCheckBox("Enable power-saving mode")
        add_field("", self.qc_power_saving, "is_power_saving",
                  lambda: self.qc_power_saving.isChecked(),
                  "Aggressively sleeps between activity. Best for battery nodes.")
        self.qc_shutdown = QSpinBox(); self.qc_shutdown.setRange(0, 100000)
        add_field("Shutdown on battery after (s)", self.qc_shutdown, "shutdown_secs",
                  lambda: self.qc_shutdown.value(),
                  "Power off N seconds after losing USB power. 0 = never.")
        self.qc_wait_bt = QSpinBox(); self.qc_wait_bt.setRange(0, 3600)
        add_field("Wait for Bluetooth (s)", self.qc_wait_bt, "wait_bt_secs",
                  lambda: self.qc_wait_bt.value(),
                  "How long to stay awake waiting for a BLE client.")
        self.qc_min_wake = QSpinBox(); self.qc_min_wake.setRange(0, 3600)
        add_field("Min wake time (s)", self.qc_min_wake, "min_wake_secs",
                  lambda: self.qc_min_wake.value())

        v.addLayout(grid)

        # Save button
        brow = QHBoxLayout()
        brow.addStretch(1)
        self.qc_apply_btn = QPushButton("💾  Apply to device")
        self.qc_apply_btn.setObjectName("PrimaryButton")
        self.qc_apply_btn.setEnabled(False)
        self.qc_apply_btn.clicked.connect(self._apply_quick_config)
        brow.addWidget(self.qc_apply_btn)
        v.addLayout(brow)

        self.qc_status = QLabel("")
        self.qc_status.setWordWrap(True)
        self.qc_status.setStyleSheet(f"color: {Colors.TEXT_DIM}; font-size: 11px;")
        v.addWidget(self.qc_status)

        root.addWidget(card)

    @staticmethod
    def _parse_leading_int(text: str, default: int) -> int:
        try:
            return int(str(text).strip().split()[0])
        except Exception:
            return default

    def _load_quick_config_from_device(self):
        """Populate the quick-config widgets from the device's current config."""
        if not self.manager.is_connected:
            return
        try:
            ln = self.manager.interface.localNode
            lc = ln.localConfig
            # Identity
            nodes = getattr(self.manager.interface, "nodes", {}) or {}
            me = nodes.get(self.manager.my_node_id, {})
            user = me.get("user", {}) if isinstance(me, dict) else {}
            self.qc_long.setText(user.get("longName", "") or "")
            self.qc_short.setText(user.get("shortName", "") or "")
            # Radio
            from meshtastic.protobuf.config_pb2 import Config
            try:
                self.qc_region.setCurrentText(
                    Config.LoRaConfig.RegionCode.Name(int(lc.lora.region)))
            except Exception: pass
            try:
                self.qc_preset.setCurrentText(
                    Config.LoRaConfig.ModemPreset.Name(int(lc.lora.modem_preset)))
            except Exception: pass
            self.qc_hop.setValue(int(getattr(lc.lora, "hop_limit", 3) or 3))
            self.qc_txpow.setValue(int(getattr(lc.lora, "tx_power", 0) or 0))
            # Position
            pos = me.get("position", {}) if isinstance(me, dict) else {}
            if pos.get("latitude") is not None:
                self.qc_lat.setValue(float(pos["latitude"]))
            if pos.get("longitude") is not None:
                self.qc_lon.setValue(float(pos["longitude"]))
            if pos.get("altitude") is not None:
                self.qc_alt.setValue(int(pos["altitude"]))
            # Intervals
            self.qc_nodeinfo.setCurrentText(
                str(getattr(lc.device, "node_info_broadcast_secs", 900) or 900))
            self.qc_posbcast.setCurrentText(
                str(getattr(lc.position, "position_broadcast_secs", 900) or 900))
            # Display
            self.qc_screen.setCurrentText(
                str(getattr(lc.display, "screen_on_secs", 60) or 60))
            self.qc_carousel.setValue(
                int(getattr(lc.display, "auto_screen_carousel_secs", 0) or 0))
            self.qc_wake_tap.setChecked(
                bool(getattr(lc.display, "wake_on_tap_or_motion", False)))
            self.qc_12h.setChecked(bool(getattr(lc.display, "use_12h_clock", False)))
            # Buttons/LED
            self.qc_led_off.setChecked(
                bool(getattr(lc.device, "led_heartbeat_disabled", False)))
            self.qc_double_tap.setChecked(
                bool(getattr(lc.device, "double_tap_as_button_press", False)))
            # Power
            self.qc_power_saving.setChecked(
                bool(getattr(lc.power, "is_power_saving", False)))
            self.qc_shutdown.setValue(
                int(getattr(lc.power, "on_battery_shutdown_after_secs", 0) or 0))
            self.qc_wait_bt.setValue(
                int(getattr(lc.power, "wait_bluetooth_secs", 0) or 0))
            self.qc_min_wake.setValue(
                int(getattr(lc.power, "min_wake_secs", 0) or 0))
            self.qc_status.setText("Loaded current device configuration.")
        except Exception as e:
            log.debug(f"Could not load quick config: {e}", exc_info=True)

    def _apply_quick_config(self):
        """Write all quick-config values to the device."""
        if not self.manager.is_connected:
            QMessageBox.warning(self, "Not connected",
                                "Connect to a device first.")
            return
        try:
            ln = self.manager.interface.localNode
            lc = ln.localConfig
            from meshtastic.protobuf.config_pb2 import Config
            applied = []

            # Identity (via setOwner)
            long_n = self.qc_long.text().strip()
            short_n = self.qc_short.text().strip()
            if long_n or short_n:
                try:
                    ln.setOwner(long_name=long_n or None,
                                short_name=short_n or None)
                    applied.append("owner")
                except Exception as e:
                    log.warning(f"setOwner failed: {e}")

            # Radio
            try:
                lc.lora.region = Config.LoRaConfig.RegionCode.Value(
                    self.qc_region.currentText())
                lc.lora.hop_limit = self.qc_hop.value()
                lc.lora.tx_power = self.qc_txpow.value()
                if self.qc_use_custom.isChecked():
                    # Custom LoRa: set BW/SF/CR, disable preset usage
                    lc.lora.use_preset = False
                    lc.lora.bandwidth = self._parse_leading_int(
                        self.qc_bw.currentText(), 250)
                    lc.lora.spread_factor = self.qc_sf.value()
                    lc.lora.coding_rate = self.qc_cr.value()
                else:
                    lc.lora.use_preset = True
                    lc.lora.modem_preset = Config.LoRaConfig.ModemPreset.Value(
                        self.qc_preset.currentText())
                slot = self.qc_freq_slot.value()
                if slot > 0:
                    lc.lora.channel_num = slot
                ln.writeConfig("lora")
                applied.append("lora")
            except Exception as e:
                log.warning(f"lora write failed: {e}")

            # Position interval + device node-info
            try:
                lc.device.node_info_broadcast_secs = int(
                    self.qc_nodeinfo.currentText() or 900)
                lc.device.led_heartbeat_disabled = self.qc_led_off.isChecked()
                lc.device.double_tap_as_button_press = self.qc_double_tap.isChecked()
                try:
                    lc.device.buzzer_mode = lc.device.BuzzerMode.Value(
                        self.qc_buzzer.currentText())
                except Exception: pass
                ln.writeConfig("device")
                applied.append("device")
            except Exception as e:
                log.warning(f"device write failed: {e}")

            try:
                lc.position.position_broadcast_secs = int(
                    self.qc_posbcast.currentText() or 900)
                ln.writeConfig("position")
                applied.append("position")
            except Exception as e:
                log.warning(f"position write failed: {e}")

            # Display
            try:
                lc.display.screen_on_secs = self._parse_leading_int(
                    self.qc_screen.currentText(), 60)
                lc.display.auto_screen_carousel_secs = self.qc_carousel.value()
                lc.display.wake_on_tap_or_motion = self.qc_wake_tap.isChecked()
                lc.display.use_12h_clock = self.qc_12h.isChecked()
                ln.writeConfig("display")
                applied.append("display")
            except Exception as e:
                log.warning(f"display write failed: {e}")

            # Power
            try:
                lc.power.is_power_saving = self.qc_power_saving.isChecked()
                lc.power.on_battery_shutdown_after_secs = self.qc_shutdown.value()
                lc.power.wait_bluetooth_secs = self.qc_wait_bt.value()
                lc.power.min_wake_secs = self.qc_min_wake.value()
                ln.writeConfig("power")
                applied.append("power")
            except Exception as e:
                log.warning(f"power write failed: {e}")

            # Fixed position (set-position) — only if lat/lon non-zero
            lat = self.qc_lat.value(); lon = self.qc_lon.value()
            if abs(lat) > 0.0001 or abs(lon) > 0.0001:
                try:
                    ln.setFixedPosition(lat, lon, int(self.qc_alt.value()))
                    applied.append("position(fixed)")
                except Exception as e:
                    log.warning(f"setFixedPosition failed: {e}")

            self.qc_status.setText(
                f"✓ Applied: {', '.join(applied)}. The device may reboot "
                "briefly to apply changes — it will reconnect automatically.")
            self.qc_status.setStyleSheet(
                f"color: {Colors.SUCCESS}; font-size: 11px;")
        except Exception as e:
            log.exception("apply_quick_config failed")
            self.qc_status.setText(f"✗ Error: {e}")
            self.qc_status.setStyleSheet(
                f"color: {Colors.DANGER}; font-size: 11px;")

    def _load_preferences(self):
        s = Settings.get()
        # limba
        idx = self.lang_combo.findData(s.language)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)
        self.cb_auto_reconnect.setChecked(s.auto_reconnect)
        self.cb_notifications.setChecked(s.notifications)
        self.cb_save_history.setChecked(s.save_history)

    def _connect_signals(self):
        self.manager.stateChanged.connect(self._on_state)
        self.manager.deviceInfoReady.connect(self._on_device_info)
        self.manager.errorMessage.connect(self._on_error)
        self.lang_combo.currentIndexChanged.connect(self._on_lang_changed)
        self.cb_auto_reconnect.toggled.connect(
            lambda v: self._on_pref("auto_reconnect", v))
        self.cb_notifications.toggled.connect(
            lambda v: self._on_pref("notifications", v))
        self.cb_save_history.toggled.connect(
            lambda v: self._on_pref("save_history", v))

    def _retranslate(self, *_):
        self.lbl_hint.setText(t("settings.connection_hint"))
        self.lbl_section_prefs.setText(t("settings.preferences"))
        self.lbl_lang.setText(t("settings.language"))
        self.cb_auto_reconnect.setText(t("settings.auto_reconnect"))
        self.cb_notifications.setText(t("settings.notifications"))
        self.cb_save_history.setText(t("settings.save_history"))
        self.lbl_section_owner.setText(t("settings.owner"))
        self.lbl_owner_hint.setText(t("settings.owner_hint"))
        self.lbl_long_name.setText(t("settings.long_name"))
        self.lbl_short_name.setText(t("settings.short_name"))
        self.long_name_input.setPlaceholderText(t("settings.long_name_placeholder"))
        self.short_name_input.setPlaceholderText(t("settings.short_name_placeholder"))
        self.save_owner_btn.setText(t("settings.save_name"))
        self.lbl_section_actions.setText(t("settings.actions"))
        self.lbl_actions_warn.setText(t("settings.actions_warn"))
        self.reboot_btn.setText(t("settings.reboot"))
        self.reset_db_btn.setText(t("settings.reset_db"))
        self.lbl_section_about.setText(t("settings.about"))
        self.lbl_about_text.setText(t("settings.about_text"))
        self.lbl_about_inspired.setText(t("settings.about_inspired"))
        self.lbl_log_hint.setText(t("settings.log_hint"))

    def _on_state(self, state):
        is_ready = (state == "ready")
        self.save_owner_btn.setEnabled(is_ready)
        self.reboot_btn.setEnabled(is_ready)
        self.reset_db_btn.setEnabled(is_ready)
        self.qc_apply_btn.setEnabled(is_ready)
        if is_ready:
            # Populate the quick-config panel from the device, a moment after
            # connect so localConfig has arrived.
            QTimer.singleShot(1500, self._load_quick_config_from_device)
        if state == "idle":
            self.long_name_input.clear()
            self.short_name_input.clear()

    def _on_device_info(self, info: dict):
        if info.get("longName"):
            self.long_name_input.setText(info["longName"])
        if info.get("shortName"):
            self.short_name_input.setText(info["shortName"])

    def _on_error(self, err: str):
        QMessageBox.warning(self, t("common.error"), err)

    def _on_lang_changed(self):
        code = self.lang_combo.currentData()
        if code:
            i18n.set_language(code)
            Settings.get().language = code

    def _on_pref(self, key: str, val: bool):
        s = Settings.get()
        setattr(s, key, val)
        self.preferenceChanged.emit(key, val)

    def _save_owner(self):
        ln = self.long_name_input.text().strip()
        sn = self.short_name_input.text().strip()
        if not ln or not sn:
            QMessageBox.information(self, t("settings.incomplete"),
                                    t("settings.incomplete_msg"))
            return
        self.manager.set_owner(ln, sn)
        self.save_owner_btn.setText(t("common.saved"))
        QTimer.singleShot(1500, lambda: self.save_owner_btn.setText(t("settings.save_name")))

    def _reboot_confirm(self):
        r = QMessageBox.question(self, t("common.confirm"), t("settings.reboot_confirm"))
        if r == QMessageBox.Yes:
            self.manager.reboot()

    def _reset_db_confirm(self):
        r = QMessageBox.question(self, t("common.confirm"), t("settings.reset_db_confirm"))
        if r == QMessageBox.Yes:
            try:
                self.manager.interface.localNode.resetNodeDb()
            except Exception as e:
                QMessageBox.warning(self, t("common.error"), str(e))
