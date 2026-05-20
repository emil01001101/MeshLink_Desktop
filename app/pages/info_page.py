"""
Tab Info - statistici complete cu suport i18n.
"""

from __future__ import annotations

import time
import logging
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, QUrl, QSize
from PySide6.QtGui import QPainter, QColor, QBrush, QDesktopServices, QPen, QPainterPath
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFrame,
    QScrollArea, QPushButton, QSizePolicy
)

log = logging.getLogger("meshlink.info")

from ..connection import MeshtasticManager
from ..theme import Colors
from ..i18n import t, i18n


class _MetricBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0.0
        self._reversed = False
        self.setFixedHeight(8)

    def set_value(self, v: float, reverse_scale: bool = False):
        self._value = max(0, min(100, v))
        self._reversed = reverse_scale
        self.update()

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(Colors.BG_INPUT)))
        p.drawRoundedRect(0, 0, self.width(), self.height(), 4, 4)
        w = int(self.width() * self._value / 100)
        if self._reversed:
            if self._value < 30:   color = Colors.SUCCESS
            elif self._value < 70: color = Colors.WARNING
            else:                  color = Colors.DANGER
        else:
            if self._value > 60:   color = Colors.SUCCESS
            elif self._value > 25: color = Colors.WARNING
            else:                  color = Colors.DANGER
        p.setBrush(QBrush(QColor(color)))
        if w > 0:
            p.drawRoundedRect(0, 0, w, self.height(), 4, 4)
        p.end()


class _Sparkline(QWidget):
    """Small inline line chart for channel-utilization history.

    Plots up to the last `max_points` samples (default 60) as a smooth
    line over a transparent background. Colour shifts from green at low
    utilisation to red at high — matching what users intuitively expect.
    """
    def __init__(self, parent=None, max_points: int = 60):
        super().__init__(parent)
        self._samples: list[float] = []
        self._max_points = max_points
        self.setMinimumHeight(40)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_samples(self, values: list[float]):
        self._samples = list(values[-self._max_points:])
        self.update()

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        # Background grid line at 25/50/75% (visual reference)
        p.setPen(QPen(QColor(Colors.BORDER), 1, Qt.DotLine))
        for pct in (0.25, 0.5, 0.75):
            y = int(h * (1 - pct))
            p.drawLine(0, y, w, y)
        if len(self._samples) < 2:
            p.setPen(QPen(QColor(Colors.TEXT_DIM)))
            p.drawText(0, 0, w, h, Qt.AlignCenter,
                       "Collecting samples…")
            p.end()
            return
        # Scale: clamp values to [0, max(40%, observed_max)] so spikes
        # are visible but a steady 5% channel doesn't look like a wall
        peak = max(40.0, max(self._samples) * 1.1)
        path = QPainterPath()
        n = len(self._samples)
        for i, v in enumerate(self._samples):
            x = (i / (n - 1)) * (w - 2) + 1
            y = h - (v / peak) * (h - 4) - 2
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        # Pick line colour from the most recent value
        last = self._samples[-1]
        if   last < 5:   stroke = Colors.SUCCESS
        elif last < 15:  stroke = Colors.WARNING
        else:            stroke = Colors.DANGER
        p.setPen(QPen(QColor(stroke), 2))
        p.drawPath(path)
        # Last-value dot
        last_x = w - 2
        last_y = h - (last / peak) * (h - 4) - 2
        p.setBrush(QBrush(QColor(stroke)))
        p.setPen(Qt.NoPen)
        p.drawEllipse(int(last_x - 3), int(last_y - 3), 6, 6)
        p.end()


class _MeshHealthCard(QFrame):
    """Live mesh-health panel for the Info tab.

    Shows the same data as the `mesh-health` console command, plus a
    sparkline of channel-utilization history. Refreshed by the parent
    InfoPage's QTimer every second.
    """

    def __init__(self, manager: MeshtasticManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.setObjectName("Card")
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 16)
        root.setSpacing(10)

        # ── Header + diagnostic badge ───────────────────────────────────
        head = QHBoxLayout()
        self.lbl_section = QLabel()  # title set in retranslate
        self.lbl_section.setProperty("role", "section")
        head.addWidget(self.lbl_section)
        head.addStretch(1)
        # Status pill (colour shifts based on diagnostic)
        self.lbl_badge = QLabel("●  …")
        self.lbl_badge.setStyleSheet(
            f"background: {Colors.BG_INPUT}; "
            f"color: {Colors.TEXT_DIM}; "
            f"padding: 4px 10px; border-radius: 10px; "
            f"font-size: 11px; font-weight: 600;")
        head.addWidget(self.lbl_badge)
        root.addLayout(head)

        # ── Diagnostic explanation (full sentence) ──────────────────────
        self.lbl_diag = QLabel("")
        self.lbl_diag.setWordWrap(True)
        self.lbl_diag.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; "
            f"font-size: 12px; line-height: 1.4; "
            f"padding: 8px 10px; "
            f"background: {Colors.BG_INPUT}; "
            f"border-radius: 6px;")
        root.addWidget(self.lbl_diag)

        # ── Two side-by-side columns: channel util + activity ──────────
        cols = QHBoxLayout()
        cols.setSpacing(12)

        # Left: channel utilization + sparkline
        cu_box = QFrame()
        cu_box.setStyleSheet(
            f"background: {Colors.BG_INPUT}; border-radius: 6px;")
        cu_lay = QVBoxLayout(cu_box)
        cu_lay.setContentsMargins(12, 10, 12, 12)
        cu_lay.setSpacing(6)
        self.lbl_cu_title = QLabel()
        self.lbl_cu_title.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: 10px; "
            f"letter-spacing: 1px; font-weight: 700;")
        cu_lay.addWidget(self.lbl_cu_title)
        # 3 numbers in a row: last / avg / max
        nums_row = QHBoxLayout()
        nums_row.setSpacing(16)
        self.lbl_cu_last = _NumberWithCaption("—", "Last")
        self.lbl_cu_avg  = _NumberWithCaption("—", "Avg")
        self.lbl_cu_max  = _NumberWithCaption("—", "Max")
        nums_row.addWidget(self.lbl_cu_last)
        nums_row.addWidget(self.lbl_cu_avg)
        nums_row.addWidget(self.lbl_cu_max)
        nums_row.addStretch(1)
        cu_lay.addLayout(nums_row)
        self.sparkline = _Sparkline()
        cu_lay.addWidget(self.sparkline)
        cols.addWidget(cu_box, 1)

        # Right: activity summary
        act_box = QFrame()
        act_box.setStyleSheet(
            f"background: {Colors.BG_INPUT}; border-radius: 6px;")
        act_lay = QVBoxLayout(act_box)
        act_lay.setContentsMargins(12, 10, 12, 12)
        act_lay.setSpacing(6)
        self.lbl_act_title = QLabel()
        self.lbl_act_title.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: 10px; "
            f"letter-spacing: 1px; font-weight: 700;")
        act_lay.addWidget(self.lbl_act_title)
        act_grid = QGridLayout()
        act_grid.setHorizontalSpacing(16)
        act_grid.setVerticalSpacing(4)
        self._act_labels: dict = {}
        rows = [
            ("tx_total",        "TX (session)"),
            ("tx_1h",           "TX (last hour)"),
            ("text_1h",         "Text RX (1h)"),
            ("nodes_1h",        "Neighbours (1h)"),
            ("last_text",       "Last text"),
            ("last_packet",     "Last packet"),
        ]
        for i, (key, caption) in enumerate(rows):
            k = QLabel(caption + ":")
            k.setStyleSheet(f"color: {Colors.TEXT_DIM}; font-size: 11px;")
            v = QLabel("—")
            v.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; font-weight: 500;")
            act_grid.addWidget(k, i, 0)
            act_grid.addWidget(v, i, 1)
            self._act_labels[key] = v
        act_lay.addLayout(act_grid)
        act_lay.addStretch(1)
        cols.addWidget(act_box, 1)
        root.addLayout(cols)

        # ── RX by port breakdown (compact table) ────────────────────────
        port_box = QFrame()
        port_box.setStyleSheet(
            f"background: {Colors.BG_INPUT}; border-radius: 6px;")
        port_lay = QVBoxLayout(port_box)
        port_lay.setContentsMargins(12, 10, 12, 12)
        port_lay.setSpacing(4)
        self.lbl_port_title = QLabel()
        self.lbl_port_title.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: 10px; "
            f"letter-spacing: 1px; font-weight: 700;")
        port_lay.addWidget(self.lbl_port_title)

        port_grid = QGridLayout()
        port_grid.setHorizontalSpacing(20)
        port_grid.setVerticalSpacing(2)
        # Header row
        for col, text in enumerate(("Type", "Total", "1h", "24h")):
            hdr = QLabel(text)
            hdr.setStyleSheet(
                f"color: {Colors.TEXT_DIM}; font-size: 10px; "
                f"font-weight: 700; letter-spacing: 0.5px;")
            port_grid.addWidget(hdr, 0, col)
        # Data rows for each tracked port
        self._port_rows: dict = {}
        port_keys = [
            ("TEXT_MESSAGE_APP", "Text"),
            ("POSITION_APP",     "Position"),
            ("TELEMETRY_APP",    "Telemetry"),
            ("NODEINFO_APP",     "Node info"),
            ("ROUTING_APP",      "Routing/ACK"),
            ("OTHER",            "Other"),
        ]
        for r, (key, label) in enumerate(port_keys, start=1):
            cells = []
            for c in range(4):
                lbl = QLabel(label if c == 0 else "0")
                lbl.setStyleSheet(
                    f"color: {Colors.TEXT_PRIMARY}; "
                    f"font-family: 'Consolas','Courier New',monospace; "
                    f"font-size: 11px;")
                port_grid.addWidget(lbl, r, c)
                cells.append(lbl)
            self._port_rows[key] = cells
        port_lay.addLayout(port_grid)
        root.addWidget(port_box)

    # ------------------------------------------------------------------
    # Live refresh — called by InfoPage._refresh_dynamic every second
    # ------------------------------------------------------------------
    def refresh(self):
        if not self.manager.is_connected:
            self._show_offline()
            return
        try:
            h = self.manager.get_mesh_health()
        except Exception:
            log.exception("get_mesh_health failed")
            return

        # Diagnostic badge
        diag = h.get("diagnostic") or ""
        if "⚠" in diag or "interference" in diag.lower() \
                or "PSK mismatch" in diag:
            badge_bg, badge_fg, icon = Colors.WARNING, "#000", "⚠"
        elif diag.startswith("✓"):
            badge_bg, badge_fg, icon = Colors.SUCCESS, "#000", "✓"
        elif "silent" in diag.lower():
            badge_bg, badge_fg, icon = Colors.TEXT_DIM, "#FFF", "💤"
        else:
            badge_bg, badge_fg, icon = Colors.BG_SURFACE_HI, Colors.TEXT_PRIMARY, "●"
        # Short pill label (first 30 chars or so)
        short = diag.lstrip("⚠✓💤 ").split(" — ")[0].split(".")[0]
        if len(short) > 36:
            short = short[:34] + "…"
        self.lbl_badge.setText(f"{icon}  {short}")
        self.lbl_badge.setStyleSheet(
            f"background: {badge_bg}; color: {badge_fg}; "
            f"padding: 4px 10px; border-radius: 10px; "
            f"font-size: 11px; font-weight: 600;")
        self.lbl_diag.setText(diag.lstrip("⚠✓💤 "))

        # Channel utilization numbers + sparkline
        cu_last = h.get("channel_util_last", -1)
        cu_avg  = h.get("channel_util_avg",  -1)
        cu_max  = h.get("channel_util_max",  -1)
        self.lbl_cu_last.set_value(f"{cu_last:.1f}%" if cu_last >= 0 else "—")
        self.lbl_cu_avg.set_value (f"{cu_avg:.1f}%"  if cu_avg  >= 0 else "—")
        self.lbl_cu_max.set_value (f"{cu_max:.1f}%"  if cu_max  >= 0 else "—")
        # Pass raw samples to the sparkline
        try:
            samples = [v for _, v in self.manager._channel_util_log]
            self.sparkline.set_samples(samples)
        except Exception:
            pass

        # Activity panel
        rx_by = h["rx_by_port"]
        text_1h = rx_by.get("TEXT_MESSAGE_APP", {}).get("1h", 0)
        self._act_labels["tx_total"].setText(str(h["tx_total"]))
        self._act_labels["tx_1h"].setText(str(h["tx_last_hour"]))
        self._act_labels["text_1h"].setText(str(text_1h))
        self._act_labels["nodes_1h"].setText(str(h["rx_unique_nodes_1h"]))
        # "Last text" / "Last packet" ages
        self._act_labels["last_text"].setText(
            _format_age(h["rx_last_text_age"]) + " ago"
            if h["rx_last_text_age"] >= 0 else "—")
        self._act_labels["last_packet"].setText(
            _format_age(h["rx_last_packet_age"]) + " ago"
            if h["rx_last_packet_age"] >= 0 else "—")

        # RX-per-port table
        for key, cells in self._port_rows.items():
            stat = rx_by.get(key, {"total": 0, "1h": 0, "24h": 0})
            cells[1].setText(str(stat["total"]))
            cells[2].setText(str(stat["1h"]))
            cells[3].setText(str(stat["24h"]))

    def _show_offline(self):
        self.lbl_badge.setText("●  offline")
        self.lbl_badge.setStyleSheet(
            f"background: {Colors.BG_INPUT}; color: {Colors.TEXT_DIM}; "
            f"padding: 4px 10px; border-radius: 10px; "
            f"font-size: 11px; font-weight: 600;")
        self.lbl_diag.setText(
            "Not connected — connect to a device to start collecting "
            "mesh-health data.")
        self.lbl_cu_last.set_value("—")
        self.lbl_cu_avg.set_value("—")
        self.lbl_cu_max.set_value("—")
        for cells in self._port_rows.values():
            for c in cells[1:]:
                c.setText("0")
        for v in self._act_labels.values():
            v.setText("—")

    def retranslate(self):
        self.lbl_section.setText("🩺  " + t("info.mesh_health"))
        self.lbl_cu_title.setText(t("info.mh_channel_util"))
        self.lbl_act_title.setText(t("info.mh_activity"))
        self.lbl_port_title.setText(t("info.mh_rx_by_type"))


class _NumberWithCaption(QFrame):
    """A vertical pair: a big number on top, a small caption below."""
    def __init__(self, value: str, caption: str, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.lbl_value = QLabel(value)
        self.lbl_value.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; font-size: 17px; font-weight: 700;")
        self.lbl_cap = QLabel(caption)
        self.lbl_cap.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: 10px; "
            f"letter-spacing: 0.5px;")
        lay.addWidget(self.lbl_value)
        lay.addWidget(self.lbl_cap)

    def set_value(self, v: str):
        self.lbl_value.setText(v)


def _format_age(seconds: int) -> str:
    """Compact 'time since' duration."""
    seconds = max(0, int(seconds))
    if seconds < 60:    return f"{seconds}s"
    if seconds < 3600:  return f"{seconds // 60}m"
    if seconds < 86400: return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


class _MetricCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        l = QVBoxLayout(self)
        l.setContentsMargins(16, 14, 16, 14)
        l.setSpacing(4)
        self.lbl_title = QLabel("")
        self.lbl_title.setProperty("role", "section")
        l.addWidget(self.lbl_title)
        self.lbl_value = QLabel("—")
        self.lbl_value.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; font-size: 22px; font-weight: 700;"
        )
        l.addWidget(self.lbl_value)
        self.lbl_sub = QLabel("")
        self.lbl_sub.setStyleSheet(f"color: {Colors.TEXT_DIM}; font-size: 11px;")
        l.addWidget(self.lbl_sub)
        self.bar = _MetricBar()
        self.bar.hide()
        l.addWidget(self.bar)

    def set_title(self, icon: str, title: str):
        self.lbl_title.setText(f"{icon}  {title}")

    def set_value(self, value: str, sub: str = "",
                  bar_pct: float = None, bar_reversed: bool = False):
        self.lbl_value.setText(value)
        self.lbl_sub.setText(sub)
        if bar_pct is not None:
            self.bar.set_value(bar_pct, bar_reversed)
            self.bar.show()
        else:
            self.bar.hide()


class InfoPage(QWidget):

    def __init__(self, manager: MeshtasticManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self._device_info = {}
        self._my_metrics = {}
        self._my_metrics_ts = 0
        self._my_env_metrics: dict = {}
        self._my_power_metrics: dict = {}
        self._my_position = {}

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(1000)
        self._refresh_timer.timeout.connect(self._refresh_dynamic)
        self._refresh_timer.start()

        self._build_ui()
        self._connect_signals()
        i18n.languageChanged.connect(self._retranslate)
        self._retranslate()
        self._refresh_dynamic()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"QScrollArea {{ background: {Colors.BG_BASE}; border: none; }}")
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(14)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        self.c_battery   = _MetricCard()
        self.c_voltage   = _MetricCard()
        self.c_uptime    = _MetricCard()
        self.c_lastpkt   = _MetricCard()
        self.c_chan_util = _MetricCard()
        self.c_air_util  = _MetricCard()
        grid.addWidget(self.c_battery,   0, 0)
        grid.addWidget(self.c_voltage,   0, 1)
        grid.addWidget(self.c_uptime,    0, 2)
        grid.addWidget(self.c_lastpkt,   1, 0)
        grid.addWidget(self.c_chan_util, 1, 1)
        grid.addWidget(self.c_air_util,  1, 2)
        for col in range(3):
            grid.setColumnStretch(col, 1)
        layout.addLayout(grid)

        hw_card = QFrame()
        hw_card.setObjectName("Card")
        hwl = QVBoxLayout(hw_card)
        hwl.setContentsMargins(18, 14, 18, 16)
        hwl.setSpacing(8)
        self.lbl_hw_section = QLabel()
        self.lbl_hw_section.setProperty("role", "section")
        hwl.addWidget(self.lbl_hw_section)

        self.hw_grid = QGridLayout()
        self.hw_grid.setHorizontalSpacing(20)
        self.hw_grid.setVerticalSpacing(8)
        self.hw_grid.setColumnStretch(1, 1)
        self.hw_grid.setColumnStretch(3, 1)
        self._hw_labels = {}
        self._hw_keys = [
            ("info.field.id",         "id"),
            ("info.field.long_name",  "longName"),
            ("info.field.short_name", "shortName"),
            ("info.field.hw",         "hwModel"),
            ("info.field.firmware",   "firmwareVersion"),
            ("info.field.region",     "region"),
            ("info.field.preset",     "modemPreset"),
            ("info.field.hops",       "hopLimit"),
            ("info.field.reboots",    "rebootCount"),
            ("info.field.min_app",    "minAppVersion"),
        ]
        for i, (key_t, key) in enumerate(self._hw_keys):
            row = i // 2
            col = (i % 2) * 2
            k = QLabel()
            k.setProperty("role", "muted")
            v = QLabel("—")
            v.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; font-weight: 500;")
            v.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.hw_grid.addWidget(k, row, col)
            self.hw_grid.addWidget(v, row, col + 1)
            self._hw_labels[key] = (k, v, key_t)
        hwl.addLayout(self.hw_grid)
        layout.addWidget(hw_card)

        # V20-turn8: Mesh-Health panel — live diagnostic of RX/TX rates
        # and channel utilization, so users can tell apart "mesh quiet"
        # from "RF noise / PSK mismatch". Refreshed by _refresh_dynamic
        # alongside the other metric cards.
        self.mesh_health = _MeshHealthCard(self.manager)
        layout.addWidget(self.mesh_health)

        # V20-turn11: Self-test launcher — a single button that runs ~23
        # diagnostic checks against the device + this app's environment.
        self_test_row = QHBoxLayout()
        self_test_row.setContentsMargins(0, 0, 0, 0)
        self_test_row.addStretch(1)
        self.btn_self_test = QPushButton("🩺  Run device self-test")
        self.btn_self_test.setObjectName("PrimaryButton")
        self.btn_self_test.setToolTip(
            "Run ~23 hardware + software diagnostic checks "
            "(safe, doesn't transmit anything).")
        self.btn_self_test.clicked.connect(self._open_self_test)
        self_test_row.addWidget(self.btn_self_test)
        self_test_row.addStretch(1)
        layout.addLayout(self_test_row)

        pos_card = QFrame()
        pos_card.setObjectName("Card")
        pl = QVBoxLayout(pos_card)
        pl.setContentsMargins(18, 14, 18, 16)
        pl.setSpacing(8)
        self.lbl_pos_section = QLabel()
        self.lbl_pos_section.setProperty("role", "section")
        pl.addWidget(self.lbl_pos_section)
        self.lbl_pos = QLabel()
        self.lbl_pos.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; font-size: 13px; line-height: 1.5;"
        )
        self.lbl_pos.setTextInteractionFlags(Qt.TextSelectableByMouse)
        pl.addWidget(self.lbl_pos)

        pos_btns = QHBoxLayout()
        self.btn_gmaps = QPushButton("🗺  Google Maps")
        self.btn_gmaps.setEnabled(False)
        self.btn_gmaps.clicked.connect(self._open_gmaps)
        pos_btns.addWidget(self.btn_gmaps)
        self.btn_osm = QPushButton("🌐  OpenStreetMap")
        self.btn_osm.setEnabled(False)
        self.btn_osm.clicked.connect(self._open_osm)
        pos_btns.addWidget(self.btn_osm)
        pos_btns.addStretch(1)
        pl.addLayout(pos_btns)
        layout.addWidget(pos_card)

        # === CHART TELEMETRIE 24H ===
        chart_card = QFrame()
        chart_card.setObjectName("Card")
        cc_l = QVBoxLayout(chart_card)
        cc_l.setContentsMargins(18, 14, 18, 16)
        cc_l.setSpacing(8)
        self.lbl_chart_section = QLabel()
        self.lbl_chart_section.setProperty("role", "section")
        cc_l.addWidget(self.lbl_chart_section)
        from ..widgets.telemetry_chart import TelemetryChart
        self.chart = TelemetryChart()
        cc_l.addWidget(self.chart, 1)
        layout.addWidget(chart_card)

        # === ENVIRONMENT / POWER SENSORS PANEL ===
        # Hidden by default; populated dynamically when the local device
        # actually reports any environmental sensor reading.
        self.sensors_card = QFrame()
        self.sensors_card.setObjectName("Card")
        sc_l = QVBoxLayout(self.sensors_card)
        sc_l.setContentsMargins(18, 14, 18, 16)
        sc_l.setSpacing(8)
        self.lbl_sensors_section = QLabel("🌡  Environment Sensors")
        self.lbl_sensors_section.setProperty("role", "section")
        sc_l.addWidget(self.lbl_sensors_section)
        self.sensors_grid = QGridLayout()
        self.sensors_grid.setHorizontalSpacing(20)
        self.sensors_grid.setVerticalSpacing(6)
        sc_l.addLayout(self.sensors_grid)
        self.sensors_card.setVisible(False)
        layout.addWidget(self.sensors_card)

        layout.addStretch(1)
        scroll.setWidget(inner)
        root.addWidget(scroll)

    def _retranslate(self, *_):
        self.c_battery.set_title("🔋",   t("info.battery"))
        self.c_voltage.set_title("⚡",   t("info.voltage"))
        self.c_uptime.set_title("⏱",    t("info.uptime"))
        self.c_lastpkt.set_title("📡",   t("info.last_packet"))
        self.c_chan_util.set_title("📊", t("info.chan_util"))
        self.c_air_util.set_title("📤",  t("info.air_util"))
        self.lbl_hw_section.setText("📦  " + t("info.about_device"))
        self.lbl_pos_section.setText("📍  " + t("info.position"))
        self.lbl_chart_section.setText("📈  " + t("info.chart_24h"))
        for key, (k_lbl, _, key_t) in self._hw_labels.items():
            k_lbl.setText(t(key_t))
        try:
            self.mesh_health.retranslate()
        except Exception:
            pass
        self._refresh_dynamic()
        self._refresh_position_display()

    def _connect_signals(self):
        self.manager.stateChanged.connect(self._on_state)
        self.manager.deviceInfoReady.connect(self._on_device_info)
        self.manager.nodeUpdated.connect(self._on_node_updated)
        self.manager.telemetryReceived.connect(self._on_telemetry)
        self.manager.positionReceived.connect(self._on_position)

    def _open_self_test(self):
        """Open the self-test dialog and run the checks."""
        try:
            from ..dialogs.self_test_dialog import SelfTestDialog
            dlg = SelfTestDialog(self.manager, self)
            dlg.exec()
        except Exception:
            log.exception("Failed to open self-test dialog")

    def _on_state(self, state: str):
        if state == "idle":
            self._device_info = {}
            self._my_metrics = {}
            self._my_metrics_ts = 0
            self._my_position = {}
            for _, (_, v_lbl, _) in self._hw_labels.items():
                v_lbl.setText("—")
            self._refresh_position_display()
            self.chart.set_data([])
        elif state == "ready":
            self._try_pull_local_metrics()
            QTimer.singleShot(800, self._refresh_chart)

    def _on_device_info(self, info: dict):
        self._device_info = info
        for key, (_, v_lbl, _) in self._hw_labels.items():
            v = info.get(key)
            v_lbl.setText(str(v) if v not in (None, "") else "—")
        self._try_pull_local_metrics()
        QTimer.singleShot(500, self._refresh_chart)

    def _on_node_updated(self, node_id: str, node: dict):
        if node_id == self.manager.my_node_id:
            dm = node.get("deviceMetrics") or {}
            if dm:
                self._my_metrics.update(dm)
                self._my_metrics_ts = int(time.time())
            em = node.get("environmentMetrics") or {}
            if em:
                self._my_env_metrics.update(em)
            pm = node.get("powerMetrics") or {}
            if pm:
                self._my_power_metrics.update(pm)
            pos = node.get("position") or {}
            if pos:
                self._my_position = pos
                self._refresh_position_display()
            self._refresh_dynamic()
            self._refresh_sensors_panel()

    def _on_telemetry(self, node_id: str, telemetry: dict):
        if node_id == self.manager.my_node_id:
            dm = telemetry.get("deviceMetrics") or {}
            if dm:
                self._my_metrics.update(dm)
                self._my_metrics_ts = int(time.time())
                self._refresh_dynamic()
                self._refresh_chart()
            em = telemetry.get("environmentMetrics") or {}
            if em:
                self._my_env_metrics.update(em)
                self._refresh_sensors_panel()
            pm = telemetry.get("powerMetrics") or {}
            if pm:
                self._my_power_metrics.update(pm)
                self._refresh_sensors_panel()

    def _on_position(self, node_id: str, pos: dict):
        if node_id == self.manager.my_node_id:
            self._my_position = pos
            self._refresh_position_display()

    def _refresh_chart(self):
        """Reload the chart with telemetry history for the local node."""
        my_id = self.manager.my_node_id
        if not my_id:
            self.chart.set_data([])
            return
        try:
            from ..telemetry_db import TelemetryDB
            history = TelemetryDB.get().get_history(my_id, since_seconds=86400)
            self.chart.set_data(history)
        except Exception:
            log.exception("Error refreshing chart")

    def _refresh_sensors_panel(self):
        """Populate the environment sensors grid with current readings.

        Only fields with actual data are shown. Card stays hidden if no
        environment or power sensor data is available yet.
        """
        em = self._my_env_metrics or {}
        pm = self._my_power_metrics or {}

        # Build the list of (icon+label, value_str) pairs
        rows: list = []
        def add(label, val, fmt=None, unit=""):
            if val is None or val == "":
                return
            try:
                if fmt:
                    val = fmt(val)
                else:
                    val = f"{val}{unit}"
            except Exception:
                val = str(val)
            rows.append((label, val))

        add("🌡  Temperature",    em.get("temperature"),
            fmt=lambda v: f"{v:.1f} °C")
        add("💧  Humidity",       em.get("relativeHumidity"),
            fmt=lambda v: f"{v:.1f} %")
        add("📊  Pressure",       em.get("barometricPressure"),
            fmt=lambda v: f"{v:.2f} hPa")
        add("🌫  Gas resistance", em.get("gasResistance"),
            fmt=lambda v: f"{v:.2f} MΩ")
        add("🧪  IAQ",            em.get("iaq"))
        add("☀  Lux",             em.get("lux"),
            fmt=lambda v: f"{v:.0f} lx")
        add("⚪  White lux",      em.get("whiteLux"),
            fmt=lambda v: f"{v:.0f} lx")
        add("🟣  UV lux",         em.get("uvLux"),
            fmt=lambda v: f"{v:.2f} lx")
        add("🔴  IR lux",         em.get("irLux"),
            fmt=lambda v: f"{v:.0f} lx")
        add("🌬  Wind direction", em.get("windDirection"),
            fmt=lambda v: f"{int(v)}°")
        add("💨  Wind speed",     em.get("windSpeed"),
            fmt=lambda v: f"{v:.1f} m/s")
        add("💨  Wind gust",      em.get("windGust"),
            fmt=lambda v: f"{v:.1f} m/s")
        add("💨  Wind lull",      em.get("windLull"),
            fmt=lambda v: f"{v:.1f} m/s")
        add("🌧  Rainfall 1h",    em.get("rainfall1h"),
            fmt=lambda v: f"{v:.1f} mm")
        add("🌧  Rainfall 24h",   em.get("rainfall24h"),
            fmt=lambda v: f"{v:.1f} mm")
        add("📏  Distance",       em.get("distance"),
            fmt=lambda v: f"{v:.0f} mm")
        add("⚖  Weight",          em.get("weight"),
            fmt=lambda v: f"{v:.2f} kg")
        add("☢  Radiation",       em.get("radiation"),
            fmt=lambda v: f"{v:.2f} µR/h")
        add("🌱  Soil moisture",  em.get("soilMoisture"),
            fmt=lambda v: f"{v} %")
        add("🌱  Soil temp",      em.get("soilTemperature"),
            fmt=lambda v: f"{v:.1f} °C")
        # Env voltage/current — only if not the same as device voltage
        if em.get("voltage") and not self._my_metrics.get("voltage"):
            add("⚡  Env voltage", em.get("voltage"),
                fmt=lambda v: f"{v:.3f} V")
        if em.get("current") is not None:
            add("⚡  Env current", em.get("current"),
                fmt=lambda v: f"{v:.1f} mA")

        # Power sensors (multi-channel)
        for ch in (1, 2, 3):
            v = pm.get(f"ch{ch}Voltage")
            i = pm.get(f"ch{ch}Current")
            if v is not None:
                add(f"🔌  Ch{ch} voltage", v,
                    fmt=lambda x: f"{x:.3f} V")
            if i is not None:
                add(f"🔌  Ch{ch} current", i,
                    fmt=lambda x: f"{x:.1f} mA")

        # Clear current widgets
        while self.sensors_grid.count():
            item = self.sensors_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not rows:
            self.sensors_card.setVisible(False)
            return

        # 2-column layout (4 grid columns: label/value, label/value)
        per_col = (len(rows) + 1) // 2
        for i, (label, value) in enumerate(rows):
            r = i % per_col
            c = (i // per_col) * 2
            lbl = QLabel(label)
            lbl.setStyleSheet(
                f"color: {Colors.TEXT_DIM}; font-size: 11px; font-weight: 600;"
            )
            val = QLabel(value)
            val.setStyleSheet(
                f"color: {Colors.TEXT_PRIMARY}; font-size: 13px; "
                f"font-family: Consolas, monospace; font-weight: 700;"
            )
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.sensors_grid.addWidget(lbl, r, c)
            self.sensors_grid.addWidget(val, r, c + 1)
        self.sensors_grid.setColumnStretch(1, 1)
        self.sensors_grid.setColumnStretch(3, 1)
        self.sensors_card.setVisible(True)

    def _try_pull_local_metrics(self):
        iface = self.manager.interface
        my_id = self.manager.my_node_id
        if not iface or not my_id or not iface.nodes:
            return
        me = iface.nodes.get(my_id)
        if not me:
            return
        dm = me.get("deviceMetrics") or {}
        if dm:
            self._my_metrics.update(dm)
            self._my_metrics_ts = int(time.time())
        pos = me.get("position") or {}
        if pos:
            self._my_position = pos
            self._refresh_position_display()

    def _refresh_dynamic(self):
        # V20-turn8: keep the mesh-health card live
        try:
            self.mesh_health.refresh()
        except Exception:
            log.exception("mesh_health refresh failed")

        dm = self._my_metrics
        bat = dm.get("batteryLevel")
        if bat is not None:
            if bat > 100:
                self.c_battery.set_value("USB", t("info.usb_powered"), bar_pct=100)
            else:
                self.c_battery.set_value(f"{bat}%", self._battery_label(bat), bar_pct=bat)
        else:
            self.c_battery.set_value("—", t("info.waiting_telem"))

        v = dm.get("voltage")
        if v is not None:
            self.c_voltage.set_value(f"{v:.2f} V", self._voltage_label(v))
        else:
            self.c_voltage.set_value("—", "")

        up = dm.get("uptimeSeconds")
        if up is not None:
            elapsed = max(0, int(time.time()) - self._my_metrics_ts)
            self.c_uptime.set_value(
                self._humanize_uptime(up + elapsed),
                t("info.telem_age", self._humanize_age(self._my_metrics_ts))
                if self._my_metrics_ts else ""
            )
        else:
            self.c_uptime.set_value("—", t("info.waiting_telem"))

        if self._my_metrics_ts:
            age = self._humanize_age(self._my_metrics_ts)
            self.c_lastpkt.set_value(
                age, datetime.fromtimestamp(self._my_metrics_ts).strftime("%H:%M:%S"))
        else:
            self.c_lastpkt.set_value("—", "")

        cu = dm.get("channelUtilization")
        if cu is not None:
            self.c_chan_util.set_value(f"{cu:.1f}%", self._util_label(cu),
                                       bar_pct=cu, bar_reversed=True)
        else:
            self.c_chan_util.set_value("—", "")

        au = dm.get("airUtilTx")
        if au is not None:
            self.c_air_util.set_value(f"{au:.1f}%", self._util_label(au),
                                      bar_pct=au, bar_reversed=True)
        else:
            self.c_air_util.set_value("—", "")

    def _refresh_position_display(self):
        pos = self._my_position
        if not pos:
            self.lbl_pos.setText(t("info.no_position"))
            self.btn_gmaps.setEnabled(False)
            self.btn_osm.setEnabled(False)
            return
        lat = pos.get("latitude")
        lon = pos.get("longitude")
        if lat is None and pos.get("latitudeI") is not None:
            lat = pos["latitudeI"] / 1e7
            lon = pos.get("longitudeI", 0) / 1e7
        alt = pos.get("altitude")
        bits = []
        if lat is not None and lon is not None:
            bits.append(f"📍  {lat:.6f}, {lon:.6f}")
            self._cached_pos = (lat, lon)
            self.btn_gmaps.setEnabled(True)
            self.btn_osm.setEnabled(True)
        if alt is not None:
            bits.append(f"⛰  {t('info.altitude')}: {alt} m")
        sats = pos.get("satsInView") or pos.get("sats_in_view")
        if sats is not None:
            bits.append(f"🛰  {t('info.sats')}: {sats}")
        self.lbl_pos.setText("\n".join(bits) if bits else t("info.no_position"))

    def _open_gmaps(self):
        if hasattr(self, "_cached_pos"):
            lat, lon = self._cached_pos
            QDesktopServices.openUrl(QUrl(f"https://www.google.com/maps?q={lat},{lon}"))

    def _open_osm(self):
        if hasattr(self, "_cached_pos"):
            lat, lon = self._cached_pos
            QDesktopServices.openUrl(QUrl(
                f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}&zoom=15"))

    @staticmethod
    def _humanize_uptime(seconds: int) -> str:
        seconds = int(seconds)
        d, rem = divmod(seconds, 86400)
        h, rem = divmod(rem, 3600)
        m, s   = divmod(rem, 60)
        if d:    return f"{d}d {h}h {m}m"
        if h:    return f"{h}h {m}m {s}s"
        if m:    return f"{m}m {s}s"
        return f"{s}s"

    @staticmethod
    def _humanize_age(ts: int) -> str:
        if not ts: return "?"
        delta = int(time.time()) - ts
        if delta < 5:     return "now"
        if delta < 60:    return f"{delta}s"
        if delta < 3600:  return f"{delta // 60}m"
        if delta < 86400: return f"{delta // 3600}h"
        return f"{delta // 86400}d"

    @staticmethod
    def _battery_label(pct: int) -> str:
        if pct > 75:  return t("info.battery.full")
        if pct > 40:  return t("info.battery.good")
        if pct > 20:  return t("info.battery.warn")
        return t("info.battery.crit")

    @staticmethod
    def _voltage_label(v: float) -> str:
        if v > 4.0:   return t("info.voltage.full")
        if v > 3.7:   return t("info.voltage.normal")
        if v > 3.4:   return t("info.voltage.low")
        return t("info.voltage.crit")

    @staticmethod
    def _util_label(pct: float) -> str:
        if pct < 10:  return t("info.util.light")
        if pct < 25:  return t("info.util.normal")
        if pct < 50:  return t("info.util.busy")
        return t("info.util.heavy")
