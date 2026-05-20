"""
Node details popup — shows ALL available information about a node in a
separate window.

Layout:
  • Header with avatar, long name, short name, node ID
  • Grid with ALL fields (identity, position, telemetry, signal, timestamps)
  • Action buttons: Copy ID, Google Maps, OpenStreetMap, Request telemetry, Close
"""

from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QGridLayout, QScrollArea, QWidget, QApplication
)

from ..widgets.common import ShortNameAvatar, SignalIndicator
from ..theme import Colors


def _format_uptime(s) -> str:
    try: s = int(s)
    except Exception: return str(s)
    d, rem = divmod(s, 86400)
    h, rem = divmod(rem, 3600)
    m, sec = divmod(rem, 60)
    if d: return f"{d}d {h}h {m}m"
    if h: return f"{h}h {m}m"
    if m: return f"{m}m {sec}s"
    return f"{sec}s"


class NodeDetailsDialog(QDialog):
    """Non-modal dialog showing every available field for a node."""

    def __init__(self, node_id: str, node: dict, parent=None):
        super().__init__(parent)
        self.node_id = node_id
        self.node = node or {}
        self.setWindowFlag(Qt.Window)
        self.resize(620, 640)
        self.setMinimumSize(480, 420)

        user = self.node.get("user") or {}
        long_name = user.get("longName") or "Unknown node"
        self.setWindowTitle(f"Node — {long_name}")

        self._build_ui()
        self._populate()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # ── header ──
        header = QFrame()
        header.setObjectName("Card")
        h = QHBoxLayout(header)
        h.setContentsMargins(14, 12, 14, 12)
        h.setSpacing(12)

        user = self.node.get("user") or {}
        short = user.get("shortName") or "??"
        self.avatar = ShortNameAvatar(short, is_me=False, size=56)
        h.addWidget(self.avatar)

        col = QVBoxLayout()
        col.setSpacing(2)
        self.lbl_name = QLabel(user.get("longName") or "Unknown node")
        self.lbl_name.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; font-size: 18px; font-weight: 700;"
        )
        col.addWidget(self.lbl_name)
        self.lbl_subtitle = QLabel(
            f"{self.node_id}  •  {user.get('hwModel') or '-'}  •  {user.get('shortName') or '-'}"
        )
        self.lbl_subtitle.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: 11px; "
            f"font-family: Consolas, monospace;"
        )
        col.addWidget(self.lbl_subtitle)
        h.addLayout(col, 1)

        # Signal indicator on the right
        self.signal = SignalIndicator(self.node.get("snr"))
        h.addWidget(self.signal)

        root.addWidget(header)

        # ── scroll area with details grid ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"QScrollArea {{ background: {Colors.BG_BASE}; }}")
        inner = QWidget()
        self.grid = QGridLayout(inner)
        self.grid.setContentsMargins(0, 4, 0, 4)
        self.grid.setHorizontalSpacing(20)
        self.grid.setVerticalSpacing(4)
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        # ── actions ──
        actions = QHBoxLayout()
        actions.setSpacing(8)

        self.btn_copy = QPushButton("📋  Copy ID")
        self.btn_copy.clicked.connect(self._copy_id)
        actions.addWidget(self.btn_copy)

        self.btn_gmaps = QPushButton("🗺  Google Maps")
        self.btn_gmaps.clicked.connect(self._open_gmaps)
        actions.addWidget(self.btn_gmaps)

        self.btn_osm = QPushButton("🌐  OpenStreetMap")
        self.btn_osm.clicked.connect(self._open_osm)
        actions.addWidget(self.btn_osm)

        actions.addStretch(1)
        self.btn_close = QPushButton("Close")
        self.btn_close.setObjectName("PrimaryButton")
        self.btn_close.clicked.connect(self.close)
        actions.addWidget(self.btn_close)
        root.addLayout(actions)

        # Enable map buttons only when position is known
        if not self._get_latlon():
            self.btn_gmaps.setEnabled(False)
            self.btn_osm.setEnabled(False)

    # ----- data formatting ----------------------------------------------
    def _populate(self):
        rows = self._collect_rows()
        # 2-column grid: section header, key, value alternating
        per_col = (len(rows) + 1) // 2
        for i, item in enumerate(rows):
            r = i % per_col
            c = (i // per_col) * 2
            if isinstance(item, tuple) and len(item) == 2 and item[0].startswith("__"):
                # Section header (key starts with __)
                title = item[0][2:]
                hdr = QLabel(title)
                hdr.setStyleSheet(
                    f"color: {Colors.PRIMARY}; font-size: 11px; "
                    f"font-weight: 700; padding-top: 12px;"
                )
                self.grid.addWidget(hdr, r, c, 1, 2)
                continue
            k, v = item
            k_lbl = QLabel(f"{k}:")
            k_lbl.setStyleSheet(
                f"color: {Colors.TEXT_DIM}; font-size: 11px; "
                f"font-weight: 600;"
            )
            v_lbl = QLabel(str(v))
            v_lbl.setStyleSheet(
                f"color: {Colors.TEXT_PRIMARY}; font-size: 12px; "
                f"font-family: Consolas, monospace;"
            )
            v_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            v_lbl.setWordWrap(True)
            self.grid.addWidget(k_lbl, r, c)
            self.grid.addWidget(v_lbl, r, c + 1)
        self.grid.setColumnStretch(1, 1)
        self.grid.setColumnStretch(3, 1)
        self.grid.setRowStretch(per_col, 1)

    def _collect_rows(self) -> list:
        user = self.node.get("user") or {}
        pos  = self.node.get("position") or {}
        dm   = self.node.get("deviceMetrics") or {}
        em   = self.node.get("environmentMetrics") or {}
        pm   = self.node.get("powerMetrics") or {}
        rows: list = []

        def add(label, val, fmt=None):
            if val is None or val == "":
                return
            if fmt:
                try: val = fmt(val)
                except Exception: pass
            rows.append((label, val))

        rows.append(("__IDENTITY", ""))
        add("Long name",   user.get("longName"))
        add("Short name",  user.get("shortName"))
        add("Node ID",     user.get("id") or self.node_id)
        add("Node num",    self.node.get("num"))
        add("Hardware",    user.get("hwModel"))
        add("MAC address", user.get("macaddr"))
        add("Role",        user.get("role"))
        add("Licensed",    "Yes (HAM)" if user.get("isLicensed") else None)
        pk = user.get("publicKey")
        if pk:
            pk_s = str(pk)
            if len(pk_s) > 50: pk_s = pk_s[:47] + "…"
            add("Public key", pk_s)

        rows.append(("__POSITION", ""))
        lat = pos.get("latitude")
        lon = pos.get("longitude")
        if lat is None and pos.get("latitudeI") is not None:
            lat = pos["latitudeI"] / 1e7
            lon = pos.get("longitudeI", 0) / 1e7
        if lat is not None:
            add("Latitude",  f"{lat:.6f}")
            add("Longitude", f"{lon:.6f}")
        else:
            add("Position", "no GPS data")
        add("Altitude",      pos.get("altitude"), fmt=lambda v: f"{v} m")
        add("Sats in view",  pos.get("satsInView"))
        add("Precision bits",pos.get("precisionBits"))
        add("Source",        pos.get("locationSource"))
        if pos.get("time"):
            add("Pos time", datetime.fromtimestamp(pos["time"])
                .strftime("%Y-%m-%d %H:%M:%S"))

        rows.append(("__DEVICE TELEMETRY", ""))
        bat = dm.get("batteryLevel")
        if bat is not None:
            add("Battery", "USB powered (>100%)" if bat > 100 else f"{int(bat)}%")
        add("Voltage",       dm.get("voltage"),
            fmt=lambda v: f"{v:.3f} V")
        add("Channel util",  dm.get("channelUtilization"),
            fmt=lambda v: f"{v:.2f}%")
        add("Air util TX",   dm.get("airUtilTx"),
            fmt=lambda v: f"{v:.2f}%")
        add("Uptime",        dm.get("uptimeSeconds"),
            fmt=_format_uptime)

        # Environment sensors — only show section header if any data present
        env_fields_present = any(em.get(k) is not None for k in (
            "temperature","relativeHumidity","barometricPressure","gasResistance",
            "iaq","lux","whiteLux","irLux","uvLux","windDirection","windSpeed",
            "windGust","windLull","rainfall1h","rainfall24h","distance","weight",
            "radiation","soilMoisture","soilTemperature","voltage","current"))
        if env_fields_present:
            rows.append(("__ENVIRONMENT SENSORS", ""))
            add("🌡 Temperature",   em.get("temperature"),
                fmt=lambda v: f"{v:.1f} °C")
            add("💧 Humidity",      em.get("relativeHumidity"),
                fmt=lambda v: f"{v:.1f} %")
            add("📊 Pressure",      em.get("barometricPressure"),
                fmt=lambda v: f"{v:.2f} hPa")
            add("🌫 Gas resistance",em.get("gasResistance"),
                fmt=lambda v: f"{v:.2f} MΩ")
            add("🧪 IAQ",           em.get("iaq"))
            add("☀ Lux",            em.get("lux"),
                fmt=lambda v: f"{v:.0f} lx")
            add("⚪ White lux",     em.get("whiteLux"),
                fmt=lambda v: f"{v:.0f} lx")
            add("🟣 UV lux",        em.get("uvLux"),
                fmt=lambda v: f"{v:.2f} lx")
            add("🔴 IR lux",        em.get("irLux"),
                fmt=lambda v: f"{v:.0f} lx")
            add("🌬 Wind dir",      em.get("windDirection"),
                fmt=lambda v: f"{int(v)}°")
            add("💨 Wind speed",    em.get("windSpeed"),
                fmt=lambda v: f"{v:.1f} m/s")
            add("💨 Wind gust",     em.get("windGust"),
                fmt=lambda v: f"{v:.1f} m/s")
            add("💨 Wind lull",     em.get("windLull"),
                fmt=lambda v: f"{v:.1f} m/s")
            add("🌧 Rainfall 1h",   em.get("rainfall1h"),
                fmt=lambda v: f"{v:.1f} mm")
            add("🌧 Rainfall 24h",  em.get("rainfall24h"),
                fmt=lambda v: f"{v:.1f} mm")
            add("📏 Distance",      em.get("distance"),
                fmt=lambda v: f"{v:.0f} mm")
            add("⚖ Weight",         em.get("weight"),
                fmt=lambda v: f"{v:.2f} kg")
            add("☢ Radiation",      em.get("radiation"),
                fmt=lambda v: f"{v:.2f} µR/h")
            add("🌱 Soil moisture", em.get("soilMoisture"),
                fmt=lambda v: f"{v} %")
            add("🌱 Soil temp",     em.get("soilTemperature"),
                fmt=lambda v: f"{v:.1f} °C")
            if em.get("voltage") is not None and dm.get("voltage") is None:
                add("⚡ Env voltage", em.get("voltage"),
                    fmt=lambda v: f"{v:.3f} V")
            if em.get("current") is not None:
                add("⚡ Env current", em.get("current"),
                    fmt=lambda v: f"{v:.1f} mA")

        # Power sensors (INA series, multi-channel)
        pwr_present = any(pm.get(f"ch{ch}{k}") is not None
                          for ch in (1, 2, 3)
                          for k in ("Voltage", "Current"))
        if pwr_present:
            rows.append(("__POWER SENSORS", ""))
            for ch in (1, 2, 3):
                if pm.get(f"ch{ch}Voltage") is not None:
                    add(f"🔌 Ch{ch} voltage", pm[f"ch{ch}Voltage"],
                        fmt=lambda v: f"{v:.3f} V")
                if pm.get(f"ch{ch}Current") is not None:
                    add(f"🔌 Ch{ch} current", pm[f"ch{ch}Current"],
                        fmt=lambda v: f"{v:.1f} mA")

        rows.append(("__SIGNAL", ""))
        add("SNR",        self.node.get("snr"),
            fmt=lambda v: f"{v:.2f} dB")
        add("RSSI",       self.node.get("rssi"),
            fmt=lambda v: f"{v} dBm")
        add("Hops away",  self.node.get("hopsAway"))
        add("Via MQTT",   "Yes" if self.node.get("viaMqtt") else None)

        # ── Direct radio neighbors (from NEIGHBORINFO_APP) ──
        neighbors = self.node.get("neighbors") or []
        if neighbors:
            rows.append(("__NEIGHBORS", ""))
            # Sort by SNR descending (best first)
            sorted_n = sorted(
                neighbors,
                key=lambda x: x.get("snr") if x.get("snr") is not None else -999,
                reverse=True)
            for n in sorted_n:
                nid = n.get("node_id") or "?"
                snr = n.get("snr")
                if snr is not None:
                    val = f"{snr:+.2f} dB"
                else:
                    val = "(no SNR)"
                last_rx = n.get("last_rx_time")
                if last_rx:
                    try:
                        age = int(time.time()) - int(last_rx)
                        if age < 60:    val += f"   {age}s ago"
                        elif age < 3600: val += f"   {age // 60}m ago"
                        else:            val += f"   {age // 3600}h ago"
                    except Exception:
                        pass
                rows.append((f"📡 {nid}", val))
            ts_rx = self.node.get("neighborsRxTime")
            if ts_rx:
                rows.append((
                    "  Last update",
                    datetime.fromtimestamp(int(ts_rx)).strftime(
                        "%Y-%m-%d %H:%M:%S")))

        rows.append(("__TIMESTAMPS", ""))
        lh = self.node.get("lastHeard")
        if lh:
            add("Last heard",
                datetime.fromtimestamp(lh).strftime("%Y-%m-%d %H:%M:%S"))
        ls = self.node.get("lastSent")
        if ls:
            add("Last sent",
                datetime.fromtimestamp(ls).strftime("%Y-%m-%d %H:%M:%S"))
        return rows

    # ----- actions ------------------------------------------------------
    def _copy_id(self):
        QApplication.clipboard().setText(self.node_id)
        self.btn_copy.setText("✓  Copied!")
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1500, lambda: self.btn_copy.setText("📋  Copy ID"))

    def _get_latlon(self):
        pos = self.node.get("position") or {}
        lat = pos.get("latitude")
        lon = pos.get("longitude")
        if lat is None and pos.get("latitudeI") is not None:
            lat = pos["latitudeI"] / 1e7
            lon = pos.get("longitudeI", 0) / 1e7
        return (lat, lon) if lat is not None else None

    def _open_gmaps(self):
        ll = self._get_latlon()
        if ll:
            QDesktopServices.openUrl(
                QUrl(f"https://www.google.com/maps?q={ll[0]},{ll[1]}"))

    def _open_osm(self):
        ll = self._get_latlon()
        if ll:
            QDesktopServices.openUrl(
                QUrl(f"https://www.openstreetmap.org/?mlat={ll[0]}&mlon={ll[1]}&zoom=15"))
