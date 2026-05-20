"""
Grafic telemetrie cu pyqtgraph - Battery%, Voltage, ChUtil%, AirUtil%.

Suporta zoom (mouse wheel) si pan (drag).
Filtre time: 1H / 6H / 24H / All

Daca pyqtgraph nu este instalat, afiseaza un placeholder cu instructiuni.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import List

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QButtonGroup,
    QFrame, QSizePolicy
)

from ..theme import Colors
from ..i18n import t, i18n

log = logging.getLogger("meshlink.chart")

# Verificam disponibilitatea pyqtgraph - optional
HAS_PG = False
try:
    import pyqtgraph as pg
    HAS_PG = True
except Exception:
    log.info("pyqtgraph indisponibil; chart va folosi fallback")


# Chart colors (matched to the app palette)
CL_BATTERY = "#67EA94"   # verde - main accent
CL_VOLTAGE = "#F5B946"   # galben - voltage
CL_CHUTIL  = "#C77DFF"   # mov - channel utilization
CL_AIRUTIL = "#5BA9F5"   # albastru - air util tx

# Environment series colors (used in env mode)
CL_TEMP    = "#F26B7E"   # rosu - temperature (left axis, °C)
CL_HUMID   = "#5BA9F5"   # albastru - humidity (left axis, %)
CL_PRESS   = "#F5B946"   # galben - pressure (right axis, hPa)
CL_GAS     = "#C77DFF"   # mov - gas resistance (right axis, MΩ)


# ===========================================================================
# TelemetryChart - widget cu pyqtgraph
# ===========================================================================
class TelemetryChart(QWidget):
    """
    Chart 4 serii (Battery%, ChUtil%, AirUtil%, Voltage).

    Reading-urile primite via set_data() trebuie sa fie list[dict] cu cheile:
      timestamp (int unix)
      battery_level (0-100 sau >100 pentru USB)
      voltage (V)
      channel_utilization (%)
      air_util_tx (%)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._readings: List[dict] = []
        self._range_seconds: int = 86400   # default 24H
        self._mode: str = "device"   # "device" or "env"

        if not HAS_PG:
            self._build_placeholder()
        else:
            self._build_pg_chart()

        i18n.languageChanged.connect(self._retranslate)
        self._retranslate()

    # ----- pyqtgraph chart -----------------------------------------------
    def _build_pg_chart(self):
        # Stil global pyqtgraph (DARK theme)
        pg.setConfigOption("background", Colors.BG_SURFACE)
        pg.setConfigOption("foreground", Colors.TEXT_PRIMARY)
        pg.setConfigOption("antialias", True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        # ----- BARA FILTRE TIMP + MODE -----
        bar = QFrame()
        bar.setObjectName("Card")
        bar_l = QHBoxLayout(bar)
        bar_l.setContentsMargins(10, 6, 10, 6)
        bar_l.setSpacing(8)

        self.range_group = QButtonGroup(self)
        self.range_group.setExclusive(True)
        self.btn_1h  = self._mk_range_btn("1H",  3600)
        self.btn_6h  = self._mk_range_btn("6H",  6 * 3600)
        self.btn_24h = self._mk_range_btn("24H", 86400)
        self.btn_all = self._mk_range_btn("All", 0)
        # NOTE: don't setChecked yet — that fires toggled → _redraw which
        # would access self.curve_battery (not yet created). Set it at the end.
        for b in (self.btn_1h, self.btn_6h, self.btn_24h, self.btn_all):
            bar_l.addWidget(b)

        # Separator
        sep = QLabel("│")
        sep.setStyleSheet(f"color: {Colors.BORDER_HI};")
        bar_l.addWidget(sep)

        # Mode toggle: Device (battery/voltage/util) vs Environment (temp/hum/press)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.btn_mode_device = self._mk_mode_btn("📊  Device", "device")
        self.btn_mode_env    = self._mk_mode_btn("🌡  Environment", "env")
        bar_l.addWidget(self.btn_mode_device)
        bar_l.addWidget(self.btn_mode_env)

        bar_l.addStretch(1)

        # Legenda inline (rebuilt by _retranslate based on mode)
        self.lbl_legend = QLabel()
        self.lbl_legend.setStyleSheet("font-size: 11px;")
        bar_l.addWidget(self.lbl_legend)
        root.addWidget(bar)

        # ----- PLOT -----
        # Axa X = timp (DateAxisItem - format ora/data)
        self.plot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem()})
        self.plot.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.plot.setMinimumHeight(220)
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.plot.setLabel("left", "Battery / ChUtil / AirUtil  (%)",
                           color=Colors.TEXT_SECONDARY)
        self.plot.setMouseEnabled(x=True, y=True)
        # 0..110 - pana la 110 ca sa cuprinda "USB powered" (>100)
        self.plot.setYRange(0, 110, padding=0)

        # Axa Y dreapta (Voltage in device mode, Pressure in env mode)
        self.plot.showAxis("right")
        self.plot.getAxis("right").setLabel("Voltage (V)", color=Colors.TEXT_SECONDARY)
        self.right_vb = pg.ViewBox()
        self.plot.scene().addItem(self.right_vb)
        self.plot.getAxis("right").linkToView(self.right_vb)
        self.right_vb.setXLink(self.plot)
        self.right_vb.setYRange(2.8, 4.4, padding=0)
        # tine pozitia right_vb sincronizata cu plot-ul principal
        self.plot.getViewBox().sigResized.connect(self._sync_right_vb)

        # ----- 4 curbe DEVICE -----
        self.curve_battery = self.plot.plot(
            [], [], pen=pg.mkPen(CL_BATTERY, width=2),
            symbol="o", symbolSize=5, symbolBrush=CL_BATTERY,
            symbolPen=None,
        )
        self.curve_chutil = self.plot.plot(
            [], [], pen=pg.mkPen(CL_CHUTIL, width=2, style=Qt.DashLine),
            symbol="o", symbolSize=4, symbolBrush=CL_CHUTIL,
            symbolPen=None,
        )
        self.curve_air = self.plot.plot(
            [], [], pen=pg.mkPen(CL_AIRUTIL, width=2, style=Qt.DashLine),
            symbol="o", symbolSize=4, symbolBrush=CL_AIRUTIL,
            symbolPen=None,
        )
        # Voltage on the right ViewBox
        self.curve_voltage = pg.PlotCurveItem(
            x=[], y=[], pen=pg.mkPen(CL_VOLTAGE, width=2)
        )
        self.right_vb.addItem(self.curve_voltage)

        # ----- 4 curbe ENVIRONMENT (created but hidden in device mode) -----
        self.curve_temp = self.plot.plot(
            [], [], pen=pg.mkPen(CL_TEMP, width=2),
            symbol="o", symbolSize=5, symbolBrush=CL_TEMP, symbolPen=None,
        )
        self.curve_humid = self.plot.plot(
            [], [], pen=pg.mkPen(CL_HUMID, width=2, style=Qt.DashLine),
            symbol="o", symbolSize=4, symbolBrush=CL_HUMID, symbolPen=None,
        )
        # Pressure on the right axis (env mode)
        self.curve_press = pg.PlotCurveItem(
            x=[], y=[], pen=pg.mkPen(CL_PRESS, width=2)
        )
        self.right_vb.addItem(self.curve_press)
        # Gas resistance also on the right axis (its scale differs; we
        # let pyqtgraph auto-rescale when we set data)
        self.curve_gas = pg.PlotCurveItem(
            x=[], y=[], pen=pg.mkPen(CL_GAS, width=2, style=Qt.DashLine)
        )
        self.right_vb.addItem(self.curve_gas)

        # Start hidden in device mode
        self._apply_mode_visibility()

        root.addWidget(self.plot, 1)

        # NOW safe to set defaults (curves exist)
        self.btn_24h.setChecked(True)
        self.btn_mode_device.setChecked(True)

    def _mk_mode_btn(self, label: str, mode: str) -> QPushButton:
        b = QPushButton(label)
        b.setCheckable(True)
        b.setProperty("mode", mode)
        b.setStyleSheet(f"""
            QPushButton {{
                background: {Colors.BG_INPUT}; border: 1px solid {Colors.BORDER};
                border-radius: 6px; padding: 4px 10px; color: {Colors.TEXT_SECONDARY};
                font-weight: 500; font-size: 11px;
            }}
            QPushButton:hover {{ background: {Colors.BORDER_HI}; }}
            QPushButton:checked {{
                background: {Colors.PRIMARY}; color: {Colors.BG_BASE};
                border: 1px solid {Colors.PRIMARY_DARK}; font-weight: 700;
            }}
        """)
        self.mode_group.addButton(b)
        b.toggled.connect(self._on_mode_changed)
        return b

    def _on_mode_changed(self, checked: bool):
        if not checked:
            return
        btn = self.sender()
        if not btn:
            return
        self._mode = str(btn.property("mode") or "device")
        self._apply_mode_visibility()
        self._redraw()
        self._retranslate()

    def _apply_mode_visibility(self):
        """Show only the curves relevant for the current mode."""
        if not hasattr(self, "curve_battery"):
            return
        device = (self._mode == "device")
        # device curves
        for c in (self.curve_battery, self.curve_chutil, self.curve_air,
                  self.curve_voltage):
            c.setVisible(device)
        # env curves
        for c in (self.curve_temp, self.curve_humid,
                  self.curve_press, self.curve_gas):
            c.setVisible(not device)
        # Update axis labels + ranges to match the active mode
        if device:
            self.plot.setLabel("left", "Battery / ChUtil / AirUtil  (%)",
                               color=Colors.TEXT_SECONDARY)
            self.plot.getAxis("right").setLabel("Voltage (V)",
                                                color=Colors.TEXT_SECONDARY)
            self.plot.setYRange(0, 110, padding=0)
            self.right_vb.setYRange(2.8, 4.4, padding=0)
            self.right_vb.enableAutoRange(axis="y", enable=False)
        else:
            self.plot.setLabel("left", "Temperature (°C) / Humidity (%)",
                               color=Colors.TEXT_SECONDARY)
            self.plot.getAxis("right").setLabel("Pressure (hPa) / Gas (MΩ)",
                                                color=Colors.TEXT_SECONDARY)
            # Let temp/humid use a sensible range; humid can be 0-100, temp
            # can be -20..50. Show both: 0..100 with a bit of headroom.
            self.plot.enableAutoRange(axis="y", enable=True)
            self.right_vb.enableAutoRange(axis="y", enable=True)

    def _sync_right_vb(self):
        try:
            self.right_vb.setGeometry(self.plot.getViewBox().sceneBoundingRect())
            self.right_vb.linkedViewChanged(self.plot.getViewBox(), self.right_vb.XAxis)
        except Exception:
            pass

    def _mk_range_btn(self, label: str, seconds: int) -> QPushButton:
        b = QPushButton(label)
        b.setCheckable(True)
        b.setProperty("range_seconds", seconds)
        b.setStyleSheet(f"""
            QPushButton {{
                background: {Colors.BG_INPUT}; border: 1px solid {Colors.BORDER};
                border-radius: 6px; padding: 4px 12px; color: {Colors.TEXT_SECONDARY};
                font-weight: 500; font-size: 11px;
            }}
            QPushButton:hover {{ background: {Colors.BORDER_HI}; }}
            QPushButton:checked {{
                background: {Colors.PRIMARY}; color: {Colors.BG_BASE};
                border: 1px solid {Colors.PRIMARY_DARK}; font-weight: 700;
            }}
        """)
        self.range_group.addButton(b)
        b.toggled.connect(self._on_range_changed)
        return b

    def _on_range_changed(self, checked: bool):
        if not checked:
            return
        btn = self.sender()
        if btn:
            self._range_seconds = int(btn.property("range_seconds") or 0)
            self._redraw()

    # ----- fallback (no pyqtgraph) ---------------------------------------
    def _build_placeholder(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        self.lbl_placeholder = QLabel()
        self.lbl_placeholder.setAlignment(Qt.AlignCenter)
        self.lbl_placeholder.setWordWrap(True)
        self.lbl_placeholder.setStyleSheet(
            f"background-color: {Colors.BG_SURFACE}; border: 1px solid {Colors.BORDER}; "
            f"border-radius: 10px; padding: 30px; color: {Colors.TEXT_PRIMARY};"
            f"font-family: Consolas, monospace; line-height: 1.7;"
        )
        layout.addWidget(self.lbl_placeholder)

    # ----- API publica ---------------------------------------------------
    def set_data(self, readings: List[dict]):
        """Primeste o lista de citiri (ordonate cronologic ascendent)."""
        self._readings = list(readings or [])
        self._redraw()

    def _redraw(self):
        # Guard: curves may not exist yet during construction, or pyqtgraph
        # may not be available at all (placeholder mode).
        if not HAS_PG or not hasattr(self, "curve_battery"):
            return

        cutoff = 0
        if self._range_seconds > 0:
            cutoff = int(time.time()) - self._range_seconds

        # filter to range
        readings = [r for r in self._readings
                    if (r.get("timestamp") or 0) >= cutoff]

        if not readings:
            for c in (self.curve_battery, self.curve_chutil, self.curve_air,
                      self.curve_voltage,
                      self.curve_temp, self.curve_humid,
                      self.curve_press, self.curve_gas):
                c.setData([], [])
            return

        # ---- DEVICE MODE: rows that carry deviceMetrics ----
        # ---- ENV MODE:    rows that carry env metrics ----
        if self._mode == "device":
            rows = [r for r in readings
                    if (r.get("battery_level") is not None
                        or r.get("voltage") is not None
                        or r.get("channel_utilization") is not None
                        or r.get("air_util_tx") is not None)]
            if not rows:
                for c in (self.curve_battery, self.curve_chutil,
                          self.curve_air, self.curve_voltage):
                    c.setData([], [])
                return
            ts      = [r.get("timestamp") or 0 for r in rows]
            battery = [(r.get("battery_level") or 0) for r in rows]
            voltage = [(r.get("voltage") or 0)       for r in rows]
            chutil  = [(r.get("channel_utilization") or 0) for r in rows]
            airutil = [(r.get("air_util_tx") or 0)   for r in rows]
            self.curve_battery.setData(ts, battery)
            self.curve_chutil.setData(ts, chutil)
            self.curve_air.setData(ts, airutil)
            self.curve_voltage.setData(ts, voltage)
            if ts:
                self.plot.setXRange(min(ts), max(ts) + 1, padding=0.05)
        else:
            rows = [r for r in readings
                    if (r.get("temperature") is not None
                        or r.get("humidity") is not None
                        or r.get("pressure") is not None
                        or r.get("gas_resistance") is not None)]
            if not rows:
                for c in (self.curve_temp, self.curve_humid,
                          self.curve_press, self.curve_gas):
                    c.setData([], [])
                return
            # Build series independently — some rows may carry only some fields
            def series(field):
                xs, ys = [], []
                for r in rows:
                    v = r.get(field)
                    if v is None:
                        continue
                    xs.append(r.get("timestamp") or 0)
                    ys.append(v)
                return xs, ys
            tx, ty = series("temperature")
            hx, hy = series("humidity")
            px, py = series("pressure")
            gx, gy = series("gas_resistance")
            self.curve_temp.setData(tx, ty)
            self.curve_humid.setData(hx, hy)
            self.curve_press.setData(px, py)
            self.curve_gas.setData(gx, gy)
            all_ts = tx + hx + px + gx
            if all_ts:
                self.plot.setXRange(min(all_ts), max(all_ts) + 1, padding=0.05)

        self._sync_right_vb()

    def _retranslate(self, *_):
        if not HAS_PG:
            self.lbl_placeholder.setText(t("chart.no_pyqtgraph"))
            return
        # Apply axis labels based on mode (also done in _apply_mode_visibility,
        # but call here to refresh translation strings if available).
        if getattr(self, "_mode", "device") == "device":
            self.plot.setLabel("left", t("chart.left_axis"),
                               color=Colors.TEXT_SECONDARY)
            self.plot.getAxis("right").setLabel(t("chart.right_axis"),
                                                color=Colors.TEXT_SECONDARY)
            # device legend
            self.lbl_legend.setText(
                f"<span style='color:{CL_BATTERY}'>● {t('chart.legend.battery')}</span>&nbsp;&nbsp;"
                f"<span style='color:{CL_VOLTAGE}'>● {t('chart.legend.voltage')}</span>&nbsp;&nbsp;"
                f"<span style='color:{CL_CHUTIL}'>● {t('chart.legend.chutil')}</span>&nbsp;&nbsp;"
                f"<span style='color:{CL_AIRUTIL}'>● {t('chart.legend.airutil')}</span>"
            )
        else:
            self.plot.setLabel("left", t("chart.env_left_axis"),
                               color=Colors.TEXT_SECONDARY)
            self.plot.getAxis("right").setLabel(t("chart.env_right_axis"),
                                                color=Colors.TEXT_SECONDARY)
            self.lbl_legend.setText(
                f"<span style='color:{CL_TEMP}'>● {t('chart.legend.temp')}</span>&nbsp;&nbsp;"
                f"<span style='color:{CL_HUMID}'>● {t('chart.legend.humid')}</span>&nbsp;&nbsp;"
                f"<span style='color:{CL_PRESS}'>● {t('chart.legend.press')}</span>&nbsp;&nbsp;"
                f"<span style='color:{CL_GAS}'>● {t('chart.legend.gas')}</span>"
            )
