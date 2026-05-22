"""
Scanner page — an intensive, on-demand RF activity scan with a trust report.

IMPORTANT — what a Meshtastic node can and cannot do:
A stock Meshtastic radio is NOT a spectrum analyser. It can only *hear* the
single band + modem-preset it is currently tuned to, and can only *decrypt*
channels whose PSK it has. There is no firmware/API command to sweep the
spectrum. So a "scan" here is an honest, intensive PASSIVE-LISTEN session:

  * Press "Start scan" -> the app pauses its own background chatter
    (script scheduler, telemetry polling) so the link is dedicated to
    capturing every received frame.
  * For the scan window we record EVERY frame with full metadata:
    sender, port/type, SNR, RSSI, hop count, channel index.
  * When you stop (or the timer ends) we compile a trust report combining
    every detection method available to a stock node.

For true wideband spectrum scanning you need separate SDR hardware
(e.g. an RTL-SDR with a LoRa sniffer) -- that's outside what a Meshtastic
node can self-report, and the report says so honestly.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QScrollArea,
    QPushButton, QGridLayout, QProgressBar, QSpinBox
)

from ..connection import MeshtasticManager
from ..theme import Colors

log = logging.getLogger("meshlink.scanner")


class _Verdict(QFrame):
    def __init__(self, question: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(12)
        self._q = QLabel(question)
        self._q.setWordWrap(True)
        self._q.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; font-size: 13px;")
        lay.addWidget(self._q, 1)
        self._a = QLabel("\u2014")
        self._a.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: 13px; font-weight: 700;")
        self._a.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self._a, 0)

    def set_answer(self, text: str, color: str):
        self._a.setText(text)
        self._a.setStyleSheet(
            f"color: {color}; font-size: 13px; font-weight: 700;")


class ScannerPage(QWidget):

    def __init__(self, manager: MeshtasticManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self._scan_duration = 60
        self._scheduler = None
        self._scan_timer = QTimer(self)
        self._scan_timer.setInterval(1000)
        self._scan_timer.timeout.connect(self._on_scan_tick)
        self._build_ui()
        self.manager.scanStateChanged.connect(self._on_scan_state)
        self.manager.scanFinished.connect(self._on_scan_finished)
        self.manager.stateChanged.connect(self._on_conn_state)
        self._on_conn_state(self.manager.state)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 20)
        root.setSpacing(12)

        title = QLabel("\U0001F4E1  RF Activity Scanner")
        title.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; font-size: 16px; font-weight: 700;")
        root.addWidget(title)

        intro = QLabel(
            "An intensive passive-listen scan. When you start it, the app "
            "pauses background tasks (scripts, telemetry polling) and "
            "dedicates the radio to capturing every frame it can hear on its "
            "current band + preset. A Meshtastic node isn't a spectrum "
            "analyser -- for full wideband scanning you'd need SDR hardware -- "
            "but this honestly characterises everything actually reaching you.")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 12px;")
        root.addWidget(intro)

        ctrl = QFrame(); ctrl.setObjectName("Card")
        cl = QHBoxLayout(ctrl)
        cl.setContentsMargins(14, 10, 14, 10)
        cl.setSpacing(10)
        cl.addWidget(QLabel("Duration:"))
        self.spin_duration = QSpinBox()
        self.spin_duration.setRange(10, 600)
        self.spin_duration.setValue(60)
        self.spin_duration.setSuffix(" s")
        self.spin_duration.setFixedWidth(90)
        cl.addWidget(self.spin_duration)
        self.btn_scan = QPushButton("\u25B6  Start scan")
        self.btn_scan.setObjectName("PrimaryButton")
        self.btn_scan.clicked.connect(self._toggle_scan)
        cl.addWidget(self.btn_scan)
        cl.addStretch(1)
        self.lbl_tuning = QLabel("")
        self.lbl_tuning.setStyleSheet(
            f"color: {Colors.PRIMARY}; font-size: 11px;")
        self.lbl_tuning.setWordWrap(True)
        cl.addWidget(self.lbl_tuning, 2)
        root.addWidget(ctrl)

        self.progress = QProgressBar()
        self.progress.setRange(0, 60)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        root.addWidget(self.progress)
        self.lbl_live = QLabel("")
        self.lbl_live.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; font-size: 12px;")
        self.lbl_live.setVisible(False)
        root.addWidget(self.lbl_live)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {Colors.BG_BASE}; border: none; }}")
        host = QWidget()
        col = QVBoxLayout(host)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(8)

        vt = QLabel("DETECTION VERDICTS")
        vt.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: 10px; font-weight: 700; "
            f"letter-spacing: 1px;")
        col.addWidget(vt)

        self.v_generic = _Verdict("Generic LoRa activity")
        self.v_mesh    = _Verdict("Meshtastic-compatible activity")
        self.v_decode  = _Verdict("Meshtastic packets decodable without a key")
        self.v_exact   = _Verdict("Exact messages on a channel without its PSK")
        self.v_known   = _Verdict("Exact channel if you know the PSK / name")
        self.v_neigh   = _Verdict("Direct neighbours (0-hop, in range)")
        for v in (self.v_generic, self.v_mesh, self.v_decode,
                  self.v_exact, self.v_known, self.v_neigh):
            col.addWidget(v)

        self.stats_card = QFrame(); self.stats_card.setObjectName("Card")
        sc = QVBoxLayout(self.stats_card)
        sc.setContentsMargins(14, 12, 14, 12); sc.setSpacing(6)
        sct = QLabel("SCAN STATISTICS")
        sct.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: 10px; font-weight: 700; "
            f"letter-spacing: 1px;")
        sc.addWidget(sct)
        self.stats_grid = QGridLayout()
        self.stats_grid.setHorizontalSpacing(16)
        self.stats_grid.setVerticalSpacing(4)
        sc.addLayout(self.stats_grid)
        col.addWidget(self.stats_card)

        self.senders_card = QFrame(); self.senders_card.setObjectName("Card")
        snd = QVBoxLayout(self.senders_card)
        snd.setContentsMargins(14, 12, 14, 12); snd.setSpacing(6)
        sndt = QLabel("NODES HEARD (top 10 by packet count)")
        sndt.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: 10px; font-weight: 700; "
            f"letter-spacing: 1px;")
        snd.addWidget(sndt)
        self.senders_grid = QGridLayout()
        self.senders_grid.setHorizontalSpacing(16)
        self.senders_grid.setVerticalSpacing(3)
        snd.addLayout(self.senders_grid)
        col.addWidget(self.senders_card)

        self.rec_card = QFrame(); self.rec_card.setObjectName("Card")
        rc = QVBoxLayout(self.rec_card)
        rc.setContentsMargins(14, 12, 14, 12); rc.setSpacing(4)
        rct = QLabel("\U0001F4A1  WHAT THIS MEANS")
        rct.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: 10px; font-weight: 700; "
            f"letter-spacing: 1px;")
        rc.addWidget(rct)
        self.lbl_rec = QLabel(
            "Press Start scan to characterise the radio activity around you.")
        self.lbl_rec.setWordWrap(True)
        self.lbl_rec.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; font-size: 12px; line-height: 1.5;")
        rc.addWidget(self.lbl_rec)
        col.addWidget(self.rec_card)

        col.addStretch(1)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)

    def set_scheduler(self, scheduler):
        self._scheduler = scheduler

    def _toggle_scan(self):
        if self.manager.is_scanning:
            self.manager.stop_scan()
        else:
            self._start_scan()

    def _start_scan(self):
        if not self.manager.is_connected:
            return
        self._scan_duration = self.spin_duration.value()
        self.progress.setRange(0, self._scan_duration)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.lbl_live.setVisible(True)
        self.lbl_live.setText("Starting scan\u2026")
        ok = self.manager.start_scan(pause_callback=self._pause_background)
        if ok:
            self._scan_timer.start()

    def _pause_background(self, pause: bool):
        try:
            if self._scheduler:
                self._scheduler.pause() if pause else self._scheduler.resume()
        except Exception:
            log.exception("scheduler pause/resume failed")

    def _on_scan_tick(self):
        self.manager.emit_scan_progress(self._scan_duration)
        elapsed = self.progress.value() + 1
        self.progress.setValue(elapsed)
        pkts = len(self.manager._scan_packets)
        senders = len({p[1] for p in self.manager._scan_packets})
        self.lbl_live.setText(
            f"Scanning\u2026 {elapsed}/{self._scan_duration}s  \u00b7  "
            f"{pkts} frames from {senders} node(s) so far")
        if elapsed >= self._scan_duration:
            self.manager.stop_scan()

    @Slot(bool)
    def _on_scan_state(self, scanning: bool):
        if scanning:
            self.btn_scan.setText("\u23F9  Stop scan")
            self.spin_duration.setEnabled(False)
        else:
            self.btn_scan.setText("\u25B6  Start scan")
            self.spin_duration.setEnabled(True)
            self._scan_timer.stop()
            self.progress.setVisible(False)
            self.lbl_live.setVisible(False)

    @Slot(dict)
    def _on_scan_finished(self, report: dict):
        self._render_report(report)

    @Slot(str)
    def _on_conn_state(self, state):
        connected = (state == "ready")
        self.btn_scan.setEnabled(connected)
        if connected:
            freq = self.manager.get_radio_frequency()
            if freq:
                self.lbl_tuning.setText(
                    f"Listening on {freq['frequency_mhz']} MHz \u00b7 "
                    f"{freq['region']} \u00b7 {freq['preset']}")
        else:
            self.lbl_tuning.setText("Connect a device to scan.")

    def _render_report(self, rep: dict):
        if not rep:
            return
        total = rep.get("total_packets", 0)
        senders = rep.get("unique_senders", 0)
        neigh = rep.get("direct_neighbours", 0)
        channels = rep.get("decryptable_channels", [])

        GREEN = Colors.SUCCESS; AMBER = Colors.WARNING
        RED = Colors.DANGER; BLUE = Colors.INFO

        self.v_generic.set_answer("YES" if total else "none heard",
                                  GREEN if total else AMBER)
        self.v_mesh.set_answer("YES" if total else "none yet",
                               GREEN if total else AMBER)
        self.v_decode.set_answer("LIMITED (headers only)" if total else "\u2014",
                                 BLUE if total else Colors.TEXT_DIM)
        self.v_exact.set_answer("NO (PSK required)", RED)
        self.v_known.set_answer(
            f"YES ({len(channels)} configured)" if channels
            else "add channel + PSK",
            GREEN if channels else AMBER)
        self.v_neigh.set_answer(
            f"{neigh} in range" if neigh else "none direct",
            GREEN if neigh else AMBER)

        self._clear_grid(self.stats_grid)
        rows = [
            ("Scan duration", f"{rep.get('duration', 0)} s"),
            ("Total frames heard", str(total)),
            ("Frames / minute", str(rep.get("packets_per_min", 0))),
            ("Unique senders", str(senders)),
            ("Direct (0-hop) neighbours", str(neigh)),
        ]
        snr = rep.get("snr_range", (None, None))
        if snr[0] is not None:
            rows.append(("SNR range", f"{snr[0]:.1f} \u2026 {snr[1]:.1f} dB"))
        rssi = rep.get("rssi_range", (None, None))
        if rssi[0] is not None:
            rows.append(("RSSI range", f"{rssi[0]:.0f} \u2026 {rssi[1]:.0f} dBm"))
        cu = rep.get("channel_util_avg")
        if cu is not None:
            rows.append(("Channel utilization (device)", f"{cu}%"))
        if channels:
            rows.append(("Channels you can read", ", ".join(channels)))
        hh = rep.get("hop_histogram", {})
        if hh:
            hh_str = ", ".join(f"{k}-hop: {v}" for k, v in sorted(hh.items()))
            rows.append(("Hop distribution", hh_str))
        for port, cnt in sorted(rep.get("by_port", {}).items(),
                                key=lambda x: -x[1]):
            label = port.replace("_APP", "").replace("_", " ").title()
            rows.append((f"  {label}", str(cnt)))
        for r, (k, val) in enumerate(rows):
            self._grid_row(self.stats_grid, r, k, val)

        self._clear_grid(self.senders_grid)
        sr = rep.get("senders", [])
        if sr:
            self._grid_row(self.senders_grid, 0, "Node", "Frames \u00b7 SNR \u00b7 RSSI",
                           header=True)
            for i, s in enumerate(sr, start=1):
                snr_s = f"{s['avg_snr']}dB" if s['avg_snr'] is not None else "\u2014"
                rssi_s = f"{s['avg_rssi']}dBm" if s['avg_rssi'] is not None else "\u2014"
                self._grid_row(self.senders_grid, i, s["id"],
                               f"{s['count']} \u00b7 {snr_s} \u00b7 {rssi_s}")
        else:
            self._grid_row(self.senders_grid, 0, "No nodes heard", "")

        self.lbl_rec.setText(self._build_recommendation(rep))

    def _build_recommendation(self, rep: dict) -> str:
        total = rep.get("total_packets", 0)
        senders = rep.get("unique_senders", 0)
        neigh = rep.get("direct_neighbours", 0)
        freq = rep.get("frequency")
        region = freq["region"] if freq else "your region"
        preset = freq["preset"] if freq else "current preset"

        if total == 0:
            return (
                f"No activity heard on {region} / {preset} during the scan. "
                f"This means either there's no Meshtastic traffic nearby on "
                f"this exact band + preset, your Region/Preset don't match the "
                f"local mesh, or you're out of range. If you expected to find "
                f"a mesh, confirm the Region and Modem preset match the group "
                f"you want to join (Settings -> Quick Device Config), then scan "
                f"again. Remember: a node only hears its own configuration -- "
                f"for true wideband scanning you'd need SDR hardware.")
        if senders <= 1:
            return (
                f"Light activity: {total} frame(s) from {senders} node on "
                f"{region} / {preset}. You're at the edge of a mesh or it's a "
                f"quiet area. To read message contents on a channel you need "
                f"its name + PSK -- add it under Channels (or import its share "
                f"link). Metadata (sender, signal, hops) is visible for all "
                f"traffic regardless of keys.")
        msg = (
            f"Active mesh detected: {total} frames from {senders} nodes on "
            f"{region} / {preset}")
        if neigh:
            msg += f", {neigh} of them direct (0-hop) neighbours in range"
        msg += (". You can read metadata for everything heard, but message "
                "contents only on channels whose PSK you've configured. To "
                "join a specific group, add its channel (name + PSK) under "
                "Channels.")
        return msg

    @staticmethod
    def _clear_grid(grid):
        while grid.count():
            it = grid.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()

    def _grid_row(self, grid, r, k, val, header=False):
        kl = QLabel(k)
        vl = QLabel(val)
        if header:
            for lbl in (kl, vl):
                lbl.setStyleSheet(
                    f"color: {Colors.TEXT_DIM}; font-size: 10px; "
                    f"font-weight: 700;")
        else:
            kl.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 12px;")
            vl.setStyleSheet(
                f"color: {Colors.TEXT_PRIMARY}; font-size: 12px; font-weight: 600;")
        grid.addWidget(kl, r, 0)
        grid.addWidget(vl, r, 1, Qt.AlignRight)
