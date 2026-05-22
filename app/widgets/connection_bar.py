"""
Connection bar with i18n + language selector.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QVBoxLayout, QLabel, QRadioButton, QButtonGroup,
    QStackedWidget, QWidget, QLineEdit, QSpinBox, QComboBox, QPushButton,
    QToolButton, QMenu
)
from PySide6.QtGui import QAction

from ..theme import Colors
from ..i18n import t, i18n, LANGUAGE_NAMES


class ConnectionBar(QFrame):

    connectRequested      = Signal(str, str)
    disconnectRequested   = Signal()
    refreshPortsRequested = Signal()
    languageChangeRequested = Signal(str)
    muteToggled           = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AppHeader")
        self.setFixedHeight(68)
        self._state = "idle"
        self._build_ui()
        i18n.languageChanged.connect(self._retranslate)
        self._retranslate()

    # -----------------------------------------------------------------
    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(14, 8, 14, 8)
        root.setSpacing(12)

        # ---- LOGO ----
        logo_col = QVBoxLayout()
        logo_col.setSpacing(0)
        self.lbl_title = QLabel("◈  MeshLink")
        self.lbl_title.setObjectName("AppTitle")
        self.lbl_subtitle = QLabel()
        self.lbl_subtitle.setObjectName("AppSubtitle")
        logo_col.addWidget(self.lbl_title)
        logo_col.addWidget(self.lbl_subtitle)
        root.addLayout(logo_col)

        root.addWidget(self._vsep())

        # ---- RADIO BUTTONS ----
        self.btn_group = QButtonGroup(self)
        self.rb_serial = QRadioButton()
        self.rb_ble    = QRadioButton()
        self.rb_wifi   = QRadioButton()
        self.btn_group.addButton(self.rb_serial, 0)
        self.btn_group.addButton(self.rb_ble,    1)
        self.btn_group.addButton(self.rb_wifi,   2)
        self.rb_serial.setChecked(True)
        self.btn_group.buttonClicked.connect(self._on_type_changed)
        for rb in (self.rb_serial, self.rb_ble, self.rb_wifi):
            rb.setStyleSheet(f"""
                QRadioButton {{
                    color: {Colors.TEXT_SECONDARY};
                    padding: 4px 2px; font-weight: 500;
                }}
                QRadioButton:checked {{ color: {Colors.PRIMARY}; font-weight: 600; }}
                QRadioButton::indicator {{
                    width: 14px; height: 14px; border-radius: 8px;
                    border: 2px solid {Colors.BORDER_HI}; background: {Colors.BG_INPUT};
                }}
                QRadioButton::indicator:checked {{
                    background-color: {Colors.PRIMARY};
                    border: 2px solid {Colors.PRIMARY};
                }}
            """)
            root.addWidget(rb)

        root.addWidget(self._vsep())

        # ---- INPUT STACK ----
        self.stack = QStackedWidget()
        # V20-turn10: lowered from 340 to 240 so the connection bar
        # still fits on narrow windows (e.g. 760px wide) without truncation.
        self.stack.setMinimumWidth(240)

        # Serial: port combo
        serial_w = QWidget()
        sl = QHBoxLayout(serial_w)
        sl.setContentsMargins(0, 0, 0, 0); sl.setSpacing(6)
        self.lbl_port = QLabel()
        sl.addWidget(self.lbl_port)
        self.port_combo = QComboBox()
        self.port_combo.setEditable(True)
        self.port_combo.setMinimumWidth(130)
        sl.addWidget(self.port_combo, 1)
        self.btn_refresh = QPushButton("⟳")
        self.btn_refresh.setMaximumWidth(34)
        self.btn_refresh.setToolTip("Refresh COM port list (quick)")
        self.btn_refresh.clicked.connect(self.refreshPortsRequested)
        sl.addWidget(self.btn_refresh)
        # V20-turn12: rich serial picker (parallel to BLE 🔍)
        self.btn_serial_scan = QPushButton("🔍  Scan")
        self.btn_serial_scan.setMaximumWidth(80)
        self.btn_serial_scan.setToolTip(
            "Scan and identify connected Meshtastic devices")
        self.btn_serial_scan.clicked.connect(self._open_serial_picker)
        sl.addWidget(self.btn_serial_scan)
        self.stack.addWidget(serial_w)

        # BLE
        ble_w = QWidget()
        bl = QHBoxLayout(ble_w)
        bl.setContentsMargins(0, 0, 0, 0); bl.setSpacing(6)
        self.lbl_addr = QLabel()
        bl.addWidget(self.lbl_addr)
        self.ble_addr = QLineEdit()
        bl.addWidget(self.ble_addr, 1)
        # V20-turn9: Scan button — opens a picker that scans BLE devices
        # via bleak and lets the user pick one. meshtastic-python 2.5+
        # removed auto-scan from BLEInterface, so the address field
        # can't be left blank anymore.
        self.btn_ble_scan = QPushButton("🔍  Scan")
        self.btn_ble_scan.setToolTip("Scan for nearby BLE Meshtastic devices")
        self.btn_ble_scan.setFixedWidth(80)
        self.btn_ble_scan.clicked.connect(self._open_ble_picker)
        bl.addWidget(self.btn_ble_scan)
        self.stack.addWidget(ble_w)

        # WiFi
        wifi_w = QWidget()
        wl = QHBoxLayout(wifi_w)
        wl.setContentsMargins(0, 0, 0, 0); wl.setSpacing(6)
        self.lbl_host = QLabel()
        wl.addWidget(self.lbl_host)
        self.wifi_host = QLineEdit()
        self.wifi_host.setText("meshtastic.local")
        wl.addWidget(self.wifi_host, 1)
        self.lbl_wport = QLabel()
        wl.addWidget(self.lbl_wport)
        self.wifi_port = QSpinBox()
        self.wifi_port.setRange(1, 65535)
        self.wifi_port.setValue(4403)
        self.wifi_port.setFixedWidth(80)
        wl.addWidget(self.wifi_port)
        # V20-turn13: scan the local network for Meshtastic TCP devices
        self.btn_wifi_scan = QPushButton("🔍  Scan")
        self.btn_wifi_scan.setMaximumWidth(80)
        self.btn_wifi_scan.setToolTip(
            "Scan the local network for Meshtastic devices (port 4403)")
        self.btn_wifi_scan.clicked.connect(self._open_network_scanner)
        wl.addWidget(self.btn_wifi_scan)
        self.stack.addWidget(wifi_w)

        root.addWidget(self.stack, 1)

        # ---- CONNECT BUTTON ----
        self.btn_connect = QPushButton()
        self.btn_connect.setObjectName("PrimaryButton")
        self.btn_connect.setMinimumWidth(130)
        self.btn_connect.setMinimumHeight(36)
        self.btn_connect.clicked.connect(self._on_connect_clicked)
        root.addWidget(self.btn_connect)

        # ---- LANGUAGE PICKER ----
        self.btn_lang = QToolButton()
        self.btn_lang.setText("🌐")
        self.btn_lang.setToolTip(t("common.language"))
        self.btn_lang.setPopupMode(QToolButton.InstantPopup)
        self.btn_lang.setStyleSheet(f"""
            QToolButton {{
                background: {Colors.BG_SURFACE_HI}; border: 1px solid {Colors.BORDER};
                border-radius: 8px; padding: 6px 10px; color: {Colors.TEXT_PRIMARY};
                font-size: 13px;
            }}
            QToolButton:hover {{ background: {Colors.BORDER_HI}; }}
            QToolButton::menu-indicator {{ image: none; }}
        """)
        lang_menu = QMenu(self.btn_lang)
        for code, label in LANGUAGE_NAMES.items():
            a = QAction(label, self.btn_lang)
            a.triggered.connect(lambda _checked, c=code: self.languageChangeRequested.emit(c))
            lang_menu.addAction(a)
        self.btn_lang.setMenu(lang_menu)
        root.addWidget(self.btn_lang)

        # ---- MUTE BUTTON ----
        self.btn_mute = QToolButton()
        self.btn_mute.setText("🔔")
        self.btn_mute.setCheckable(True)
        self.btn_mute.setStyleSheet(f"""
            QToolButton {{
                background: {Colors.BG_SURFACE_HI}; border: 1px solid {Colors.BORDER};
                border-radius: 8px; padding: 6px 10px; color: {Colors.TEXT_PRIMARY};
                font-size: 13px;
            }}
            QToolButton:hover {{ background: {Colors.BORDER_HI}; }}
            QToolButton:checked {{
                background: {Colors.BG_SURFACE};
                color: {Colors.TEXT_DIM};
            }}
        """)
        self.btn_mute.toggled.connect(self._on_mute_clicked)
        root.addWidget(self.btn_mute)

        # ---- STATUS DOT + label ----
        st_col = QVBoxLayout()
        st_col.setSpacing(2)
        st_top = QHBoxLayout()
        st_top.setSpacing(6)
        self.dot = QLabel()
        self.dot.setObjectName("StatusDot")
        self.dot.setProperty("state", "offline")
        st_top.addWidget(self.dot)
        self.lbl_state = QLabel()
        self.lbl_state.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; font-size: 12px; font-weight: 500;")
        st_top.addWidget(self.lbl_state)
        st_col.addLayout(st_top)
        self.lbl_progress = QLabel("")
        self.lbl_progress.setStyleSheet(f"color: {Colors.TEXT_DIM}; font-size: 10px;")
        self.lbl_progress.setMaximumWidth(220)
        st_col.addWidget(self.lbl_progress)
        root.addLayout(st_col)

    def _vsep(self) -> QFrame:
        s = QFrame()
        s.setFixedWidth(1)
        s.setStyleSheet(f"background: {Colors.BORDER};")
        return s

    # -----------------------------------------------------------------
    def _retranslate(self, *_):
        self.lbl_subtitle.setText(t("app.subtitle"))
        self.rb_serial.setText(f"🔌  {t('conn.serial')}")
        self.rb_ble.setText(f"📶  {t('conn.bluetooth')}")
        self.rb_wifi.setText(f"🌐  {t('conn.wifi')}")
        self.lbl_port.setText(t("conn.port"))
        self.lbl_addr.setText(t("conn.address"))
        self.lbl_host.setText(t("conn.host"))
        self.lbl_wport.setText(t("conn.port"))
        self.btn_refresh.setToolTip(t("common.refresh"))
        self.btn_lang.setToolTip(t("common.language"))
        self.ble_addr.setPlaceholderText(t("conn.ble_placeholder"))
        self.wifi_host.setPlaceholderText(t("conn.host_placeholder"))
        # repopulam auto-detect text
        if self.port_combo.count() and self.port_combo.itemText(0).startswith("("):
            self.port_combo.setItemText(0, t("conn.auto"))
        # connect button
        self.update_state(self._state, *self._labels_for_state(self._state))

    def _labels_for_state(self, state: str):
        labels = {
            "ready":          (t("state.ready"),    "online"),
            "opening":        (t("state.opening"),  "connecting"),
            "waiting_config": (t("state.waiting"),  "connecting"),
            "loading":        (t("state.loading"),  "connecting"),
            "failed":         (t("state.failed"),   "offline"),
            "idle":           (t("state.idle"),     "offline"),
        }
        return labels.get(state, (state, "offline")) + ("",)

    # -----------------------------------------------------------------
    # API
    # -----------------------------------------------------------------
    def populate_serial_ports(self, ports: list[dict]):
        cur = self.port_combo.currentText()
        self.port_combo.clear()
        self.port_combo.addItem(t("conn.auto"))
        for p in ports:
            self.port_combo.addItem(f"{p['device']} — {p.get('description','')}")
        if cur and not cur.startswith("("):
            idx = self.port_combo.findText(cur, Qt.MatchStartsWith)
            if idx >= 0:
                self.port_combo.setCurrentIndex(idx)

    def set_initial(self, conn_type: str, serial_port: str = "",
                    ble_addr: str = "", wifi_host: str = "", wifi_port: int = 4403):
        if conn_type == "ble":
            self.rb_ble.setChecked(True)
        elif conn_type == "tcp":
            self.rb_wifi.setChecked(True)
        else:
            self.rb_serial.setChecked(True)
        self._on_type_changed()
        if serial_port:
            idx = self.port_combo.findText(serial_port, Qt.MatchStartsWith)
            if idx >= 0: self.port_combo.setCurrentIndex(idx)
            else:        self.port_combo.setEditText(serial_port)
        if ble_addr:
            self.ble_addr.setText(ble_addr)
        if wifi_host:
            self.wifi_host.setText(wifi_host)
        if wifi_port:
            self.wifi_port.setValue(wifi_port)

    def get_current_target(self) -> tuple[str, str]:
        """Return (conn_type, target_string) for persisting in settings."""
        idx = self.btn_group.checkedId()
        if idx == 0:
            target = self.port_combo.currentText().strip()
            if target.startswith("(") or " — " in target:
                target = target.split(" — ", 1)[0].strip() if " — " in target else ""
            return "serial", target
        if idx == 1:
            return "ble", self.ble_addr.text().strip()
        return "tcp", f"{self.wifi_host.text().strip()}:{self.wifi_port.value()}"

    def update_state(self, state: str, label: str, dot_state: str, progress: str = ""):
        self._state = state
        self.lbl_state.setText(label)
        self.lbl_progress.setText(progress)
        self.dot.setProperty("state", dot_state)
        self.dot.style().unpolish(self.dot); self.dot.style().polish(self.dot)

        if state == "ready":
            self.btn_connect.setText(t("conn.disconnect"))
            self.btn_connect.setEnabled(True)
            self._lock_inputs(True)
        elif state in ("opening", "waiting_config", "loading"):
            self.btn_connect.setText(t("conn.cancel"))
            self.btn_connect.setEnabled(True)
            self._lock_inputs(True)
        else:
            self.btn_connect.setText(t("conn.connect"))
            self.btn_connect.setEnabled(True)
            self._lock_inputs(False)

    def _lock_inputs(self, locked: bool):
        for w in (self.rb_serial, self.rb_ble, self.rb_wifi,
                  self.port_combo, self.btn_refresh,
                  self.ble_addr, self.wifi_host, self.wifi_port):
            w.setDisabled(locked)

    def _on_type_changed(self, _btn=None):
        idx = self.btn_group.checkedId()
        self.stack.setCurrentIndex(idx)

    def _on_mute_clicked(self, checked: bool):
        self.btn_mute.setText("🔕" if checked else "🔔")
        self.btn_mute.setToolTip(t("sound.mute") if checked else t("sound.active"))
        self.muteToggled.emit(checked)

    def set_muted(self, muted: bool):
        """Setare programatica (din settings la pornire) - nu emite muteToggled."""
        self.btn_mute.blockSignals(True)
        self.btn_mute.setChecked(muted)
        self.btn_mute.setText("🔕" if muted else "🔔")
        self.btn_mute.setToolTip(t("sound.mute") if muted else t("sound.active"))
        self.btn_mute.blockSignals(False)

    def _on_connect_clicked(self):
        if self._state in ("ready", "opening", "waiting_config", "loading"):
            self.disconnectRequested.emit()
            return

        idx = self.btn_group.checkedId()
        if idx == 0:
            target = self.port_combo.currentText().strip()
            if target.startswith("("):
                target = ""
            elif " — " in target:
                target = target.split(" — ", 1)[0].strip()
            self.connectRequested.emit("serial", target)
        elif idx == 1:
            self.connectRequested.emit("ble", self.ble_addr.text().strip())
        else:
            host = self.wifi_host.text().strip() or "meshtastic.local"
            port = self.wifi_port.value()
            self.connectRequested.emit("tcp", f"{host}:{port}")

    # ------------------------------------------------------------------
    # V20-turn9: BLE scan picker
    # ------------------------------------------------------------------
    def _open_ble_picker(self):
        """Open a modal dialog that scans BLE devices and lets the user
        pick one. Selecting a device fills `self.ble_addr` with its MAC.

        The scan itself runs on a background QThread so the UI stays
        responsive during the ~5s discovery window.
        """
        dlg = _BLEPickerDialog(self)
        if dlg.exec() == _BLEPickerDialog.Accepted and dlg.selected_address:
            self.ble_addr.setText(dlg.selected_address)


# ===========================================================================
# BLE picker dialog
# ===========================================================================
from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QDialog, QListWidget, QListWidgetItem, QDialogButtonBox, QProgressBar
)


class _BLEScanWorker(QThread):
    """Runs BLEInterface.scan() off the Qt thread to avoid freezing UI."""
    finished_with_results = Signal(list)
    failed = Signal(str)

    def run(self):
        try:
            from ..connection import MeshtasticManager
            devices = MeshtasticManager.scan_ble_devices(timeout=5.0)
            self.finished_with_results.emit(devices)
        except Exception as e:
            self.failed.emit(str(e))


class _BLEPickerDialog(QDialog):
    """Modal dialog: lists BLE devices, lets user pick one.

    Filters by name prefix "MeshLink" by default but shows all devices
    if no matches are found, so first-time setup with a renamed node
    still works.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Scan BLE — Meshtastic devices")
        self.setMinimumSize(480, 360)
        self.selected_address: str = ""

        root = QVBoxLayout(self)
        root.setSpacing(10)

        info = QLabel(
            "Scanning for nearby Bluetooth devices…  "
            "Make sure your radio is powered on and within range.")
        info.setWordWrap(True)
        root.addWidget(info)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)   # indeterminate
        root.addWidget(self.progress)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(
            lambda _: self.accept_with_selection())
        root.addWidget(self.list_widget, 1)

        self.status = QLabel("")
        self.status.setStyleSheet(f"color: {Colors.TEXT_DIM}; font-size: 11px;")
        root.addWidget(self.status)

        btn_row = QHBoxLayout()
        self.btn_rescan = QPushButton("🔄  Rescan")
        self.btn_rescan.clicked.connect(self.start_scan)
        btn_row.addWidget(self.btn_rescan)
        btn_row.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept_with_selection)
        bb.rejected.connect(self.reject)
        self.btn_ok = bb.button(QDialogButtonBox.Ok)
        self.btn_ok.setEnabled(False)
        btn_row.addWidget(bb)
        root.addLayout(btn_row)

        self.list_widget.currentItemChanged.connect(
            lambda cur, _prev: self.btn_ok.setEnabled(cur is not None))

        self.worker = None
        self.start_scan()

    def start_scan(self):
        self.list_widget.clear()
        self.btn_ok.setEnabled(False)
        self.btn_rescan.setEnabled(False)
        self.progress.setRange(0, 0)
        self.progress.setVisible(True)
        self.status.setText("Scanning…")
        self.worker = _BLEScanWorker(self)
        self.worker.finished_with_results.connect(self._on_results)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_results(self, devices: list):
        self.progress.setVisible(False)
        self.btn_rescan.setEnabled(True)
        # Prefer Meshtastic-named ones at the top
        meshtastic_devs = [d for d in devices
                           if "meshtastic" in (d["name"] or "").lower()]
        other_devs     = [d for d in devices
                          if "meshtastic" not in (d["name"] or "").lower()]
        ordered = meshtastic_devs + other_devs
        if not ordered:
            self.status.setText(
                "No Bluetooth devices found.  Make sure the radio is on, "
                "BLE is enabled in its config, and it's in range. "
                "On Windows, also check that Bluetooth is turned on in "
                "Settings → Devices.")
            return
        for d in ordered:
            label = d["name"]
            if "meshtastic" in label.lower():
                label = f"📡  {label}"
            else:
                label = f"     {label}"
            rssi = d.get("rssi")
            rssi_str = f"   {rssi} dBm" if rssi is not None else ""
            text = f"{label}\n     {d['address']}{rssi_str}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, d["address"])
            self.list_widget.addItem(item)
        self.status.setText(
            f"Found {len(meshtastic_devs)} Meshtastic device(s), "
            f"{len(other_devs)} other BLE device(s) nearby.")
        # Auto-select the strongest Meshtastic device, if any
        if meshtastic_devs:
            self.list_widget.setCurrentRow(0)

    def _on_failed(self, err: str):
        self.progress.setVisible(False)
        self.btn_rescan.setEnabled(True)
        self.status.setText(f"Scan failed: {err}")

    def accept_with_selection(self):
        item = self.list_widget.currentItem()
        if item is None:
            return
        self.selected_address = item.data(Qt.UserRole) or ""
        self.accept()


# ===========================================================================
# V20-turn12: Serial port picker — modeled after the BLE picker but simpler
# (no async scan needed, serial enumeration is instant)
# ===========================================================================
def _open_serial_picker_for_bar(bar: ConnectionBar):
    """Open the serial picker dialog. Sets the chosen device into the combo."""
    dlg = _SerialPickerDialog(bar)
    if dlg.exec() == _SerialPickerDialog.Accepted and dlg.selected_device:
        # Try to find the device in the combo; if missing, set as text
        idx = bar.port_combo.findText(dlg.selected_device, Qt.MatchStartsWith)
        if idx >= 0:
            bar.port_combo.setCurrentIndex(idx)
        else:
            bar.port_combo.setEditText(dlg.selected_device)


# Wire the method onto the class so the click handler we registered earlier
# can find it.
ConnectionBar._open_serial_picker = _open_serial_picker_for_bar


class _SerialPickerDialog(QDialog):
    """Modal dialog: enumerates COM ports, highlights Meshtastic-likely ones.

    Sorting:
      • Ports whose USB chip matches a known Meshtastic USB-UART chip
        (CP210x, CH340, FT232, etc.) appear first with a 📡 icon and
        a "likely Meshtastic" subtitle.
      • Everything else is listed below as generic devices.

    The user can:
      • Double-click an item to accept it
      • Single-click + OK
      • Re-scan with the 🔄 button
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Scan COM ports — Meshtastic devices")
        self.setMinimumSize(520, 360)
        self.selected_device: str = ""

        root = QVBoxLayout(self)
        root.setSpacing(10)

        info = QLabel(
            "Scanning serial ports.  📡 indicates USB chips commonly used "
            "by Meshtastic-compatible boards (CP210x, CH340, FT232, etc.). "
            "If your device isn't listed, install its USB driver and "
            "re-scan.")
        info.setWordWrap(True)
        root.addWidget(info)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(
            lambda _: self.accept_with_selection())
        root.addWidget(self.list_widget, 1)

        self.status = QLabel("")
        self.status.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: 11px;")
        root.addWidget(self.status)

        btn_row = QHBoxLayout()
        self.btn_rescan = QPushButton("🔄  Rescan")
        self.btn_rescan.clicked.connect(self.scan_now)
        btn_row.addWidget(self.btn_rescan)
        btn_row.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept_with_selection)
        bb.rejected.connect(self.reject)
        self.btn_ok = bb.button(QDialogButtonBox.Ok)
        self.btn_ok.setEnabled(False)
        btn_row.addWidget(bb)
        root.addLayout(btn_row)

        self.list_widget.currentItemChanged.connect(
            lambda cur, _prev: self.btn_ok.setEnabled(cur is not None))

        self.scan_now()

    def scan_now(self):
        """Re-enumerate and repopulate the list."""
        self.list_widget.clear()
        self.btn_ok.setEnabled(False)
        self.status.setText("Scanning…")
        from ..connection import MeshtasticManager
        ports = MeshtasticManager.list_serial_ports() or []

        if not ports:
            self.status.setText(
                "No COM ports detected.  Plug in your Meshtastic device "
                "via USB and click 🔄 Rescan. On Windows, also check "
                "Device Manager → Ports (COM & LPT).")
            return

        meshtastic_count = 0
        for p in ports:
            device = p["device"]
            desc   = p.get("description") or ""
            mfr    = p.get("manufacturer") or ""
            vid    = p.get("vid")
            pid    = p.get("pid")
            likely = bool(p.get("likely_meshtastic"))

            if likely:
                meshtastic_count += 1
                line1 = f"📡  {device}"
                tag = "  ← likely Meshtastic"
            else:
                line1 = f"     {device}"
                tag = ""

            # Build a compact details line
            details_parts = []
            if desc:
                details_parts.append(desc)
            if mfr and mfr.lower() not in desc.lower():
                details_parts.append(mfr)
            if vid is not None and pid is not None:
                details_parts.append(f"VID:PID = {vid:04X}:{pid:04X}")
            details = "  ·  ".join(details_parts) if details_parts else \
                       "(no driver info)"

            text = f"{line1}{tag}\n     {details}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, device)
            self.list_widget.addItem(item)

        # Status line
        other = len(ports) - meshtastic_count
        self.status.setText(
            f"Found {meshtastic_count} likely Meshtastic device(s) "
            f"and {other} other serial port(s).")

        # Auto-select the first Meshtastic-likely device, if any
        if meshtastic_count >= 1:
            self.list_widget.setCurrentRow(0)

    def accept_with_selection(self):
        item = self.list_widget.currentItem()
        if item is None:
            return
        self.selected_device = item.data(Qt.UserRole) or ""
        self.accept()


# ===========================================================================
# V20-turn13: Network scanner — find Meshtastic TCP devices on the LAN
# ===========================================================================
def _open_network_scanner_for_bar(bar: ConnectionBar):
    dlg = _NetworkScanDialog(bar)
    if dlg.exec() == _NetworkScanDialog.Accepted and dlg.selected_ip:
        bar.wifi_host.setText(dlg.selected_ip)


ConnectionBar._open_network_scanner = _open_network_scanner_for_bar


class _NetworkScanWorker(QThread):
    """Scans the /24 subnet for open :4403 in a background thread."""
    progress = Signal(int, int)
    finished_with_results = Signal(list)

    def run(self):
        from ..connection import MeshtasticManager
        results = MeshtasticManager.scan_network_for_devices(
            timeout=0.3, progress_cb=lambda d, t: self.progress.emit(d, t))
        self.finished_with_results.emit(results)


class _NetworkScanDialog(QDialog):
    """Modal dialog: scans the LAN and lists Meshtastic devices on :4403."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Scan network — Meshtastic devices")
        self.setMinimumSize(480, 360)
        self.selected_ip = ""
        self._worker = None

        root = QVBoxLayout(self)
        root.setSpacing(10)
        info = QLabel(
            "Scanning your local network for devices with the Meshtastic "
            "TCP API open (port 4403). This probes every address on your "
            "subnet and takes a few seconds.")
        info.setWordWrap(True)
        root.addWidget(info)

        self.progress = QProgressBar()
        self.progress.setRange(0, 254)
        root.addWidget(self.progress)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(
            lambda _: self.accept_with_selection())
        root.addWidget(self.list_widget, 1)

        self.status = QLabel("")
        self.status.setStyleSheet(f"color: {Colors.TEXT_DIM}; font-size: 11px;")
        root.addWidget(self.status)

        btn_row = QHBoxLayout()
        self.btn_rescan = QPushButton("🔄  Rescan")
        self.btn_rescan.clicked.connect(self.scan_now)
        btn_row.addWidget(self.btn_rescan)
        btn_row.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept_with_selection)
        bb.rejected.connect(self.reject)
        self.btn_ok = bb.button(QDialogButtonBox.Ok)
        self.btn_ok.setEnabled(False)
        btn_row.addWidget(bb)
        root.addLayout(btn_row)

        self.list_widget.currentItemChanged.connect(
            lambda cur, _p: self.btn_ok.setEnabled(cur is not None))

        self.scan_now()

    def scan_now(self):
        self.list_widget.clear()
        self.btn_ok.setEnabled(False)
        self.btn_rescan.setEnabled(False)
        self.progress.setValue(0)
        self.status.setText("Scanning… this can take a few seconds.")
        self._worker = _NetworkScanWorker(self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_with_results.connect(self._on_results)
        self._worker.start()

    def _on_progress(self, done, total):
        self.progress.setMaximum(total)
        self.progress.setValue(done)

    def _on_results(self, results):
        self.btn_rescan.setEnabled(True)
        self.progress.setValue(self.progress.maximum())
        if not results:
            self.status.setText(
                "No Meshtastic devices found on the network. Make sure the "
                "device is powered on, connected to the same Wi-Fi/LAN, and "
                "has Wi-Fi enabled in its config.")
            return
        for r in results:
            ip = r["ip"]
            host = r.get("hostname") or ""
            label = f"📡  {ip}"
            if host:
                label += f"\n     {host}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, ip)
            self.list_widget.addItem(item)
        self.status.setText(
            f"Found {len(results)} device(s) listening on port 4403.")
        self.list_widget.setCurrentRow(0)

    def accept_with_selection(self):
        item = self.list_widget.currentItem()
        if item is None:
            return
        self.selected_ip = item.data(Qt.UserRole) or ""
        self.accept()
