"""
Modules page — manage moduleConfig sections (MQTT, Serial, Ext Notification,
Store & Forward, Range Test, Neighbor Info, Detection Sensor, Audio).

Architecture:
    ModulesPage  (QTabWidget host)
      └─ ModuleForm  (one per sub-tab)
           ├─ protobuf field introspection → widgets
           ├─ Reload from device
           └─ Save → writeConfig(<module_name>)

The Range Test sub-tab additionally renders a live statistics panel that
listens to manager.rangeTestPacket and tracks per-sender TX/RX counters,
SNR/RSSI min/max/avg and packet loss (from sequence number gaps).

Each form is generated AT RUNTIME from the protobuf descriptor — so when
the firmware adds new fields, no UI code changes are needed; they appear
automatically. We only special-case password masking and a few labels.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Optional, Dict, Any, List, Callable

from PySide6.QtCore import Qt, Slot, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QTabWidget, QScrollArea, QFormLayout, QCheckBox, QSpinBox, QLineEdit,
    QComboBox, QPlainTextEdit, QMessageBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QSizePolicy
)

from ..connection import MeshtasticManager
from ..i18n import t, i18n
from ..theme import Colors

log = logging.getLogger("meshlink.modules_page")


# ===========================================================================
# Field type helpers
# ===========================================================================
def _humanize_field_name(name: str) -> str:
    """snake_case → 'Title Case'."""
    return re.sub(r"_", " ", name).strip().title()


def _is_password_field(name: str) -> bool:
    return name in ("password",) or name.endswith("_password")


# ===========================================================================
# Generic module form
# ===========================================================================
class ModuleForm(QWidget):
    """Form for a single moduleConfig section.

    Args:
        manager: MeshtasticManager
        module_name: protobuf field name on ModuleConfig
                     (e.g. "mqtt", "serial", "range_test").
        description: short human-readable explanation shown at the top.
    """

    saved = Signal(str)   # emits module_name after successful save

    def __init__(self, manager: MeshtasticManager, module_name: str,
                 description: str = "", config_root: str = "moduleConfig",
                 parent=None):
        super().__init__(parent)
        self.manager = manager
        self.module_name = module_name
        # V20-turn15: which protobuf root holds this section. Most modules
        # live under localNode.moduleConfig, but WiFi/Network is under
        # localNode.localConfig. config_root selects which one.
        self.config_root = config_root
        self.description_text = description
        self._fields: Dict[str, Dict[str, Any]] = {}   # name -> {widget, descriptor}
        self._descriptors_loaded = False
        self._build_ui()
        self.manager.stateChanged.connect(self._on_state_changed)
        self._refresh_enabled_state()

    # -------------------------------------------------------------- UI --
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 16)
        root.setSpacing(10)

        # Description
        if self.description_text:
            self.lbl_desc = QLabel(self.description_text)
            self.lbl_desc.setWordWrap(True)
            self.lbl_desc.setStyleSheet(
                f"color: {Colors.TEXT_DIM}; font-size: 11px;")
            root.addWidget(self.lbl_desc)

        # Form (scrollable so long modules like external_notification fit)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.form_host = QWidget()
        self.form_layout = QFormLayout(self.form_host)
        self.form_layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.form_layout.setSpacing(10)
        self.form_layout.setContentsMargins(4, 4, 4, 4)
        self.scroll.setWidget(self.form_host)
        root.addWidget(self.scroll, 1)

        # Status line
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet(f"color: {Colors.TEXT_DIM}; font-size: 11px;")
        root.addWidget(self.lbl_status)

        # Buttons
        btn_row = QHBoxLayout()
        self.btn_reload = QPushButton("↻  " + t("modules.reload"))
        self.btn_reload.clicked.connect(self.reload_from_device)
        btn_row.addWidget(self.btn_reload)
        btn_row.addStretch(1)
        self.btn_save = QPushButton("💾  " + t("modules.save"))
        self.btn_save.setObjectName("PrimaryButton")
        self.btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(self.btn_save)
        root.addLayout(btn_row)

    # ------------------------------------------------------------ logic --
    def _proto_section(self):
        """Return the protobuf submessage for this module, or None."""
        if not self.manager.is_connected:
            return None
        try:
            root = getattr(self.manager.interface.localNode,
                           self.config_root, None)
            if root is None:
                return None
            return getattr(root, self.module_name, None)
        except Exception:
            return None

    def _build_fields_from_descriptor(self):
        """Inspect the protobuf descriptor and create one widget per field.

        Called the first time the device has been connected and we can see
        the descriptor. Lazy because building widgets up-front would need a
        stub proto, which is fine but this is cleaner.
        """
        section = self._proto_section()
        if section is None or self._descriptors_loaded:
            return
        # Clear any previous (stale) widgets
        while self.form_layout.rowCount() > 0:
            self.form_layout.removeRow(0)
        self._fields.clear()

        try:
            from google.protobuf.descriptor import FieldDescriptor
        except Exception:
            log.exception("protobuf descriptor import failed")
            return

        for fd in section.DESCRIPTOR.fields:
            # Skip nested messages — we don't try to render submessages like
            # mqtt.map_report_settings inline. They can still be tweaked via
            # the console.
            if fd.type == FieldDescriptor.TYPE_MESSAGE:
                continue
            # Skip repeated for now (rare in module config; would need a
            # list editor). The `label` attribute exists on the pure-Python
            # protobuf backend; the `_upb` (C++) backend exposes it
            # differently. Guard with getattr so we work on both.
            label = getattr(fd, "label", None)
            if label is not None and label == getattr(
                    FieldDescriptor, "LABEL_REPEATED", 3):
                continue
            if fd.type == FieldDescriptor.TYPE_BYTES:
                continue

            widget = self._make_widget_for_field(fd)
            if widget is None:
                continue
            label = _humanize_field_name(fd.name)
            # Add a small (key) hint after the label so users know the
            # exact name to use with `set <module>.<field>` in the console.
            self.form_layout.addRow(f"{label}", widget)
            self._fields[fd.name] = {"widget": widget, "descriptor": fd}

        self._descriptors_loaded = True
        log.info(f"ModuleForm[{self.module_name}]: rendered "
                 f"{len(self._fields)} fields")

    def _make_widget_for_field(self, fd) -> Optional[QWidget]:
        """Create the right input widget for one protobuf field."""
        from google.protobuf.descriptor import FieldDescriptor
        if fd.type == FieldDescriptor.TYPE_BOOL:
            w = QCheckBox()
            return w
        if fd.type == FieldDescriptor.TYPE_STRING:
            w = QLineEdit()
            if _is_password_field(fd.name):
                w.setEchoMode(QLineEdit.Password)
                # Visibility-toggle button is not embedded — kept simple.
            w.setMinimumWidth(220)
            return w
        if fd.type == FieldDescriptor.TYPE_ENUM:
            w = QComboBox()
            for v in fd.enum_type.values:
                w.addItem(v.name, v.number)
            return w
        if fd.type in (FieldDescriptor.TYPE_INT32, FieldDescriptor.TYPE_INT64,
                       FieldDescriptor.TYPE_SINT32, FieldDescriptor.TYPE_SINT64,
                       FieldDescriptor.TYPE_SFIXED32, FieldDescriptor.TYPE_SFIXED64):
            w = QSpinBox()
            w.setRange(-2**31, 2**31 - 1)
            return w
        if fd.type in (FieldDescriptor.TYPE_UINT32, FieldDescriptor.TYPE_UINT64,
                       FieldDescriptor.TYPE_FIXED32, FieldDescriptor.TYPE_FIXED64):
            w = QSpinBox()
            w.setRange(0, 2**31 - 1)
            return w
        if fd.type in (FieldDescriptor.TYPE_FLOAT, FieldDescriptor.TYPE_DOUBLE):
            from PySide6.QtWidgets import QDoubleSpinBox
            w = QDoubleSpinBox()
            w.setDecimals(4)
            w.setRange(-1e9, 1e9)
            return w
        return None

    # ------------------------------------------------------- reload/save --
    def reload_from_device(self):
        """Pull current values from the protobuf into the widgets."""
        section = self._proto_section()
        if section is None:
            self._set_status(t("modules.not_connected"), warning=True)
            return
        if not self._descriptors_loaded:
            self._build_fields_from_descriptor()
            if not self._fields:
                self._set_status(t("modules.no_fields"), warning=True)
                return
        for name, meta in self._fields.items():
            try:
                value = getattr(section, name)
                self._set_widget_value(meta["widget"], meta["descriptor"], value)
            except Exception:
                log.exception(f"reload: could not read {self.module_name}.{name}")
        self._set_status(t("modules.loaded"))

    @staticmethod
    def _set_widget_value(widget: QWidget, fd, value):
        if isinstance(widget, QCheckBox):
            widget.setChecked(bool(value))
        elif isinstance(widget, QSpinBox):
            try:
                widget.setValue(int(value))
            except Exception:
                widget.setValue(0)
        elif isinstance(widget, QComboBox):
            # value is the enum int — find item index whose data matches
            idx = widget.findData(int(value))
            if idx >= 0:
                widget.setCurrentIndex(idx)
        elif isinstance(widget, QLineEdit):
            widget.setText(str(value or ""))
        else:
            # QDoubleSpinBox
            try:
                widget.setValue(float(value))
            except Exception:
                pass

    @staticmethod
    def _read_widget_value(widget: QWidget):
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        if isinstance(widget, QSpinBox):
            return int(widget.value())
        if isinstance(widget, QComboBox):
            return int(widget.currentData())
        if isinstance(widget, QLineEdit):
            return widget.text()
        # double spinbox
        return float(widget.value())

    def _on_save(self):
        section = self._proto_section()
        if section is None:
            self._set_status(t("modules.not_connected"), warning=True)
            return
        # Confirm because writing config triggers a reboot
        ans = QMessageBox.question(
            self.window(),
            t("common.confirm"),
            t("modules.confirm_save", self.module_name),
            QMessageBox.Yes | QMessageBox.No)
        if ans != QMessageBox.Yes:
            return
        try:
            for name, meta in self._fields.items():
                value = self._read_widget_value(meta["widget"])
                try:
                    setattr(section, name, value)
                except Exception:
                    log.exception(f"save: could not set {self.module_name}.{name} "
                                  f"= {value!r}")
            log.info(f"writeConfig({self.module_name})")
            self.manager.interface.localNode.writeConfig(self.module_name)
            self._set_status(t("modules.saved"), success=True)
            self.saved.emit(self.module_name)
        except Exception as e:
            log.exception("save failed")
            self._set_status(t("modules.err_save", str(e)), warning=True)

    # ----------------------------------------------------- state hooks --
    @Slot(str)
    def _on_state_changed(self, state: str):
        self._refresh_enabled_state()
        if state == "ready":
            # Defer slightly so localNode.moduleConfig is fully populated
            QTimer.singleShot(800, self._first_load_when_ready)

    def _first_load_when_ready(self):
        if not self._descriptors_loaded:
            self._build_fields_from_descriptor()
        self.reload_from_device()

    def _refresh_enabled_state(self):
        enabled = self.manager.is_connected
        self.btn_save.setEnabled(enabled)
        self.btn_reload.setEnabled(enabled)
        self.form_host.setEnabled(enabled)

    def _set_status(self, text: str, success: bool = False,
                    warning: bool = False):
        color = (Colors.SUCCESS if success
                 else (Colors.WARNING if warning else Colors.TEXT_DIM))
        self.lbl_status.setStyleSheet(f"color: {color}; font-size: 11px;")
        self.lbl_status.setText(text)
        # auto-clear success/info messages
        if success:
            QTimer.singleShot(4000, lambda: self.lbl_status.setText(""))


# ===========================================================================
# Range-test live statistics
# ===========================================================================
class RangeTestStats(QWidget):
    """Tracks RANGE_TEST_APP packets per sender — count, SNR/RSSI stats, loss."""

    def __init__(self, manager: MeshtasticManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        # sender_id -> {count, first_seq, last_seq, gaps, snr_list, rssi_list}
        self._stats: Dict[str, Dict[str, Any]] = {}
        self._build_ui()
        manager.rangeTestPacket.connect(self._on_packet)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 8, 16, 12)
        root.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel("📊  " + t("modules.range_stats_title"))
        title.setProperty("role", "section")
        head.addWidget(title)
        head.addStretch(1)
        btn_clear = QPushButton("🗑  " + t("modules.range_clear"))
        btn_clear.clicked.connect(self._clear)
        head.addWidget(btn_clear)
        root.addLayout(head)

        self.lbl_summary = QLabel(t("modules.range_no_packets"))
        self.lbl_summary.setStyleSheet(f"color: {Colors.TEXT_DIM}; font-size: 11px;")
        root.addWidget(self.lbl_summary)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            t("modules.range_col_sender"),
            "RX",
            "SNR " + t("modules.range_col_last"),
            "SNR " + t("modules.range_col_avg"),
            "RSSI " + t("modules.range_col_last"),
            t("modules.range_col_lost"),
            t("modules.range_col_last_seen"),
        ])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        root.addWidget(self.table, 1)

    @Slot(dict)
    def _on_packet(self, pkt: dict):
        sender = pkt.get("fromId") or "?"
        # Try to parse seq=N from the text payload (range_test convention)
        seq: Optional[int] = None
        text = pkt.get("text") or ""
        m = re.search(r"seq[=:]\s*(\d+)", text)
        if m:
            try:
                seq = int(m.group(1))
            except Exception:
                seq = None

        s = self._stats.setdefault(sender, {
            "count": 0, "first_seq": None, "last_seq": None,
            "snr_list": [], "rssi_list": [], "lost": 0,
            "last_rx_time": int(time.time()),
        })
        s["count"] += 1
        s["last_rx_time"] = int(pkt.get("rxTime") or time.time())
        snr = pkt.get("rxSnr")
        if snr is not None:
            try: s["snr_list"].append(float(snr))
            except Exception: pass
        rssi = pkt.get("rxRssi")
        if rssi is not None:
            try: s["rssi_list"].append(int(rssi))
            except Exception: pass
        if seq is not None:
            if s["first_seq"] is None:
                s["first_seq"] = seq
            if s["last_seq"] is not None and seq > s["last_seq"] + 1:
                # Gap detected — count the missed packets
                s["lost"] += (seq - s["last_seq"] - 1)
            if s["last_seq"] is None or seq > s["last_seq"]:
                s["last_seq"] = seq

        self._rerender_table()

    def _rerender_table(self):
        self.table.setRowCount(0)
        total = sum(s["count"] for s in self._stats.values())
        senders = sorted(self._stats.items(),
                         key=lambda kv: kv[1]["last_rx_time"], reverse=True)
        for sender, s in senders:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(sender))
            self.table.setItem(row, 1, QTableWidgetItem(str(s["count"])))
            snr_last = (f"{s['snr_list'][-1]:+.2f}"
                        if s["snr_list"] else "—")
            snr_avg = (f"{sum(s['snr_list'])/len(s['snr_list']):+.2f}"
                       if s["snr_list"] else "—")
            rssi_last = (str(s["rssi_list"][-1])
                         if s["rssi_list"] else "—")
            self.table.setItem(row, 2, QTableWidgetItem(snr_last))
            self.table.setItem(row, 3, QTableWidgetItem(snr_avg))
            self.table.setItem(row, 4, QTableWidgetItem(rssi_last))
            self.table.setItem(row, 5, QTableWidgetItem(str(s["lost"])))
            age = int(time.time()) - s["last_rx_time"]
            if   age < 60:    age_s = f"{age}s ago"
            elif age < 3600:  age_s = f"{age // 60}m ago"
            else:             age_s = f"{age // 3600}h ago"
            self.table.setItem(row, 6, QTableWidgetItem(age_s))
        self.lbl_summary.setText(
            t("modules.range_summary", total, len(self._stats)))

    def _clear(self):
        self._stats.clear()
        self._rerender_table()


# ===========================================================================
# Main page
# ===========================================================================
class ModulesPage(QWidget):
    """Tabbed page for managing all module configurations."""

    # (proto field name, i18n key, description i18n key)
    # Sections that live under localConfig instead of moduleConfig
    LOCAL_CONFIG_SECTIONS = {"network"}

    MODULES = [
        ("network",              "modules.wifi",        "modules.wifi_desc"),
        ("mqtt",                 "modules.mqtt",        "modules.mqtt_desc"),
        ("serial",               "modules.serial",      "modules.serial_desc"),
        ("external_notification","modules.ext_notif",   "modules.ext_notif_desc"),
        ("store_forward",        "modules.sf",          "modules.sf_desc"),
        ("range_test",           "modules.range_test",  "modules.range_test_desc"),
        ("telemetry",            "modules.telemetry",   "modules.telemetry_desc"),
        ("neighbor_info",        "modules.neighbor",    "modules.neighbor_desc"),
        ("detection_sensor",     "modules.detection",   "modules.detection_desc"),
        ("audio",                "modules.audio",       "modules.audio_desc"),
        ("canned_message",       "modules.canned",      "modules.canned_desc"),
        ("remote_hardware",      "modules.remote_hw",   "modules.remote_hw_desc"),
        ("ambient_lighting",     "modules.ambient",     "modules.ambient_desc"),
        ("paxcounter",           "modules.paxcounter",  "modules.paxcounter_desc"),
    ]

    def __init__(self, manager: MeshtasticManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self._forms: Dict[str, ModuleForm] = {}
        self._build_ui()
        i18n.languageChanged.connect(self._retranslate)
        self._retranslate()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 20)
        root.setSpacing(10)

        self.lbl_intro = QLabel()
        self.lbl_intro.setWordWrap(True)
        self.lbl_intro.setProperty("role", "muted")
        root.addWidget(self.lbl_intro)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabPosition(QTabWidget.North)
        root.addWidget(self.tabs, 1)

        for module_name, _label_key, desc_key in self.MODULES:
            config_root = ("localConfig"
                           if module_name in self.LOCAL_CONFIG_SECTIONS
                           else "moduleConfig")
            form = ModuleForm(self.manager, module_name,
                              description=t(desc_key),
                              config_root=config_root)
            self._forms[module_name] = form
            if module_name == "range_test":
                # Range Test gets a special container: form + live stats panel.
                container = QWidget()
                cv = QVBoxLayout(container)
                cv.setContentsMargins(0, 0, 0, 0)
                cv.setSpacing(6)
                cv.addWidget(form, 0)
                cv.addWidget(RangeTestStats(self.manager), 1)
                self.tabs.addTab(container, "")
            else:
                self.tabs.addTab(form, "")

    def _retranslate(self, *_):
        self.lbl_intro.setText(t("modules.intro"))
        for i, (_name, label_key, desc_key) in enumerate(self.MODULES):
            self.tabs.setTabText(i, t(label_key))
            # Update description label on each form
            form = self._forms.get(_name)
            if form and hasattr(form, "lbl_desc"):
                form.lbl_desc.setText(t(desc_key))
