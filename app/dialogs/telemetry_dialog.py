"""
Non-modal popup with telemetry received on explicit request.

Layout:
  Header: Latest values (Battery, Voltage, ChUtil, AirUtil, Uptime, PWR)
  Chart 24h
  Lista log entries (10-30 ultimele citiri)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QScrollArea, QWidget, QGridLayout, QSizePolicy
)

from ..telemetry_db import TelemetryDB
from ..widgets.telemetry_chart import TelemetryChart
from ..theme import Colors
from ..i18n import t, i18n

log = logging.getLogger("meshlink.tel_dialog")


def _humanize_uptime(s) -> str:
    if s is None:
        return "—"
    try:
        s = int(s)
    except Exception:
        return str(s)
    d, rem = divmod(s, 86400)
    h, rem = divmod(rem, 3600)
    m, sec = divmod(rem, 60)
    if d:    return f"{d}d {h}h {m}m {sec}s"
    if h:    return f"{h}h {m}m {sec}s"
    if m:    return f"{m}m {sec}s"
    return f"{sec}s"


class _MetricChip(QFrame):
    """Card mic cu icon + valoare pentru header-ul popup-ului."""

    def __init__(self, icon: str, label: str, color: str = None, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._icon = icon
        self._color = color or Colors.PRIMARY
        l = QVBoxLayout(self)
        l.setContentsMargins(12, 8, 12, 8)
        l.setSpacing(2)
        self.lbl_label = QLabel(label)
        self.lbl_label.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: 10px; "
            f"text-transform: uppercase; letter-spacing: 1px;"
        )
        l.addWidget(self.lbl_label)
        self.lbl_value = QLabel("—")
        self.lbl_value.setStyleSheet(
            f"color: {self._color}; font-size: 18px; font-weight: 700;"
        )
        l.addWidget(self.lbl_value)

    def set_value(self, v: str):
        self.lbl_value.setText(f"{self._icon}  {v}" if self._icon else v)

    def set_label(self, lbl: str):
        self.lbl_label.setText(lbl)


# ===========================================================================
# TelemetryDialog
# ===========================================================================
class TelemetryDialog(QDialog):

    def __init__(self, node_id: str, node_name: str, parent=None):
        super().__init__(parent)
        self.node_id = node_id
        self.node_name = node_name
        self.setWindowTitle(f"Telemetry — {node_name}")
        self.setWindowFlag(Qt.Window)  # ferestra separata, nu modal
        self.resize(820, 640)
        self.setMinimumSize(560, 420)

        self._build_ui()
        i18n.languageChanged.connect(self._retranslate)
        self._retranslate()
        self.refresh()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # === Header ===
        self.lbl_title = QLabel()
        self.lbl_title.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; font-size: 18px; font-weight: 700;"
        )
        root.addWidget(self.lbl_title)
        self.lbl_subtitle = QLabel()
        self.lbl_subtitle.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: 11px;"
        )
        root.addWidget(self.lbl_subtitle)

        # === Cards latest values ===
        chips = QHBoxLayout()
        chips.setSpacing(10)
        self.chip_battery = _MetricChip("🔋", "Battery", "#67EA94")
        self.chip_voltage = _MetricChip("⚡", "Voltage", "#F5B946")
        self.chip_chutil  = _MetricChip("📊", "Ch Util", "#C77DFF")
        self.chip_airutil = _MetricChip("📤", "Air Util", "#5BA9F5")
        self.chip_uptime  = _MetricChip("⏱", "Uptime")
        for c in (self.chip_battery, self.chip_voltage, self.chip_chutil,
                  self.chip_airutil, self.chip_uptime):
            chips.addWidget(c, 1)
        root.addLayout(chips)

        # === Chart ===
        chart_wrap = QFrame()
        chart_wrap.setObjectName("Card")
        cw_l = QVBoxLayout(chart_wrap)
        cw_l.setContentsMargins(8, 8, 8, 8)
        self.chart = TelemetryChart()
        cw_l.addWidget(self.chart, 1)
        root.addWidget(chart_wrap, 1)

        # === Lista log entries (scroll) ===
        logs_label = QLabel()
        logs_label.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: 10px; "
            f"text-transform: uppercase; letter-spacing: 1px;"
        )
        self.logs_label = logs_label
        root.addWidget(logs_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setMaximumHeight(180)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {Colors.BG_BASE}; border: none; }}"
        )
        inner = QWidget()
        self.logs_layout = QVBoxLayout(inner)
        self.logs_layout.setContentsMargins(0, 0, 0, 0)
        self.logs_layout.setSpacing(4)
        self.logs_layout.addStretch(1)
        scroll.setWidget(inner)
        root.addWidget(scroll)

        # === Buttons ===
        btns = QHBoxLayout()
        btns.addStretch(1)
        self.btn_refresh = QPushButton()
        self.btn_refresh.clicked.connect(self.refresh)
        btns.addWidget(self.btn_refresh)
        self.btn_close = QPushButton()
        self.btn_close.setObjectName("PrimaryButton")
        self.btn_close.clicked.connect(self.close)
        btns.addWidget(self.btn_close)
        root.addLayout(btns)

    def _retranslate(self, *_):
        self.lbl_title.setText(f"{self.node_name}")
        self.chip_battery.set_label(t("info.battery"))
        self.chip_voltage.set_label(t("info.voltage"))
        self.chip_chutil.set_label(t("info.chan_util"))
        self.chip_airutil.set_label(t("info.air_util"))
        self.chip_uptime.set_label(t("info.uptime"))
        self.logs_label.setText(t("telem_dialog.logs"))
        self.btn_refresh.setText("⟳ " + t("common.refresh"))
        self.btn_close.setText(t("common.close"))

    # ----- refresh -------------------------------------------------------
    def refresh(self):
        """Reciteste tot din DB pentru node_id si reafiseaza."""
        try:
            history = TelemetryDB.get().get_history(self.node_id, since_seconds=86400)
            recent  = TelemetryDB.get().get_recent(self.node_id, limit=20)
            count   = TelemetryDB.get().count(self.node_id)
        except Exception:
            log.exception("Telemetry dialog refresh failed")
            return

        self.setWindowTitle(f"Telemetry — {self.node_name} ({count} {t('telem_dialog.logs')})")
        self.lbl_subtitle.setText(
            f"{self.node_id}  •  {count} {t('telem_dialog.logs_short')}"
        )

        # Chart
        self.chart.set_data(history)

        # Latest values
        if history:
            latest = history[-1]
            bat = latest.get("battery_level")
            if bat is not None:
                if bat > 100:
                    self.chip_battery.set_value(t("info.usb_powered"))
                else:
                    self.chip_battery.set_value(f"{int(bat)}%")
            v = latest.get("voltage")
            self.chip_voltage.set_value(f"{v:.3f} V" if v is not None else "—")
            cu = latest.get("channel_utilization")
            self.chip_chutil.set_value(f"{cu:.1f}%" if cu is not None else "—")
            au = latest.get("air_util_tx")
            self.chip_airutil.set_value(f"{au:.1f}%" if au is not None else "—")
            up = latest.get("uptime_seconds")
            self.chip_uptime.set_value(_humanize_uptime(up))
        else:
            for c in (self.chip_battery, self.chip_voltage, self.chip_chutil,
                      self.chip_airutil, self.chip_uptime):
                c.set_value("—")

        # Logs list
        self._populate_logs(recent)

    def _populate_logs(self, recent):
        # clear
        while self.logs_layout.count() > 1:
            child = self.logs_layout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()

        for r in recent:
            ts = r.get("timestamp") or 0
            ts_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            bat = r.get("battery_level")
            v = r.get("voltage")
            cu = r.get("channel_utilization")
            au = r.get("air_util_tx")
            up = r.get("uptime_seconds")

            entry = QFrame()
            entry.setObjectName("Card")
            el = QHBoxLayout(entry)
            el.setContentsMargins(10, 6, 10, 6)
            el.setSpacing(12)

            time_lbl = QLabel(ts_str)
            time_lbl.setStyleSheet(
                f"color: {Colors.TEXT_PRIMARY}; font-family: Consolas, monospace; "
                f"font-size: 11px; font-weight: 500;"
            )
            el.addWidget(time_lbl)

            details = []
            if bat is not None:
                icon = "🔌" if bat > 100 else "🔋"
                details.append(f"{icon} {int(bat) if bat <= 100 else 'USB'}{'%' if bat <= 100 else ''}")
            if v is not None:
                details.append(f"⚡ {v:.3f}V")
            if cu is not None:
                details.append(f"Ch: {cu:.1f}%")
            if au is not None:
                details.append(f"Air: {au:.1f}%")
            if up is not None:
                details.append(f"⏱ {_humanize_uptime(up)}")

            det_lbl = QLabel("  ·  ".join(details))
            det_lbl.setStyleSheet(
                f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;"
            )
            det_lbl.setWordWrap(True)
            el.addWidget(det_lbl, 1)

            self.logs_layout.insertWidget(self.logs_layout.count() - 1, entry)
