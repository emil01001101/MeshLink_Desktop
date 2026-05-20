"""
Signal quality report dialog.

Shown when the user right-clicks a received message and picks
"Signal report". Lets the user quickly compose and send back a
human-readable rating ("5/5", "3/5") plus hop count — typical
content for replying to "test" messages during mesh range testing.

5-bar quality is derived from SNR:
    SNR ≥ 10   → 5/5  ⭐⭐⭐⭐⭐  (excellent)
    SNR ≥  5   → 4/5  ⭐⭐⭐⭐    (very good)
    SNR ≥  0   → 3/5  ⭐⭐⭐      (fair)
    SNR ≥ -5   → 2/5  ⭐⭐        (weak)
    SNR ≥ -10  → 1/5  ⭐          (very weak)
    else       → 0/5             (barely detected)

Hops = hop_start − hop_limit  (number of relays the packet traversed).
"""

from __future__ import annotations

from typing import Optional, Dict, Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QPlainTextEdit, QComboBox, QApplication
)

from ..theme import Colors


def snr_to_stars(snr) -> int:
    """Convert SNR (dB) to a 0-5 quality score."""
    if snr is None:
        return 0
    try:
        s = float(snr)
    except Exception:
        return 0
    if s >= 10:  return 5
    if s >= 5:   return 4
    if s >= 0:   return 3
    if s >= -5:  return 2
    if s >= -10: return 1
    return 0


def stars_to_label(n: int) -> str:
    return {
        5: "Excellent",
        4: "Very good",
        3: "Fair",
        2: "Weak",
        1: "Very weak",
        0: "Barely detected",
    }.get(n, "Unknown")


class SignalReportDialog(QDialog):
    """Compose & send a signal quality reply."""

    sendRequested = Signal(str)   # text to send back

    def __init__(self, original_text: str, sender_name: str,
                 info: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Signal report")
        self.setMinimumSize(460, 380)
        self.resize(520, 420)
        self.info = info or {}
        self.sender_name = sender_name or "node"
        self.original_text = original_text or ""
        self._build_ui()
        self._update_reply_text()

    # -----------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # ── Header: original message + sender ──
        header = QFrame()
        header.setObjectName("Card")
        h = QVBoxLayout(header)
        h.setContentsMargins(14, 10, 14, 12)
        h.setSpacing(4)
        h1 = QLabel(f"📥  Message from {self.sender_name}")
        h1.setStyleSheet(
            f"color: {Colors.PRIMARY}; font-size: 11px; font-weight: 700;"
        )
        h.addWidget(h1)
        msg = QLabel(self.original_text or "(no text)")
        msg.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; font-size: 13px; padding: 4px 0;"
        )
        msg.setWordWrap(True)
        msg.setTextInteractionFlags(Qt.TextSelectableByMouse)
        h.addWidget(msg)
        root.addWidget(header)

        # ── Quality metrics ──
        metrics = QFrame()
        metrics.setObjectName("Card")
        ml = QVBoxLayout(metrics)
        ml.setContentsMargins(14, 12, 14, 12)
        ml.setSpacing(8)

        snr = self.info.get("snr")
        rssi = self.info.get("rssi")
        hop_s = self.info.get("hop_start")
        hop_l = self.info.get("hop_limit")
        if hop_s is not None and hop_l is not None:
            hops = max(0, int(hop_s) - int(hop_l))
        else:
            hops = None

        # Star rating
        self._stars = snr_to_stars(snr)
        stars_str = "⭐" * self._stars + "☆" * (5 - self._stars)
        rating_row = QHBoxLayout()
        big = QLabel(stars_str)
        big.setStyleSheet(
            f"color: {Colors.WARNING}; font-size: 26px;"
        )
        rating_row.addWidget(big)
        rating_lbl = QLabel(f"{self._stars}/5  ·  {stars_to_label(self._stars)}")
        rating_lbl.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; font-size: 14px; font-weight: 700; "
            f"padding-left: 12px;"
        )
        rating_row.addWidget(rating_lbl)
        rating_row.addStretch(1)
        ml.addLayout(rating_row)

        # Detailed numbers in a horizontal strip
        details = QHBoxLayout()
        details.setSpacing(20)
        details.addWidget(self._stat_widget(
            "SNR", f"{snr:.2f} dB" if snr is not None else "—"))
        details.addWidget(self._stat_widget(
            "RSSI", f"{rssi} dBm" if rssi is not None else "—"))
        details.addWidget(self._stat_widget(
            "Hops", f"{hops}" if hops is not None else "—"))
        details.addStretch(1)
        ml.addLayout(details)

        # Allow user to override the stars (e.g. they want to be polite)
        ovr = QHBoxLayout()
        ovr.addWidget(QLabel("Override rating:"))
        self.cmb_rating = QComboBox()
        for i in range(0, 6):
            self.cmb_rating.addItem(f"{i}/5  ·  {stars_to_label(i)}", i)
        self.cmb_rating.setCurrentIndex(self._stars)
        self.cmb_rating.currentIndexChanged.connect(self._update_reply_text)
        ovr.addWidget(self.cmb_rating)
        ovr.addStretch(1)
        ml.addLayout(ovr)
        root.addWidget(metrics)

        # ── Reply text editor (pre-filled) ──
        lbl = QLabel("Reply message (edit if you want):")
        lbl.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: 11px; font-weight: 600;"
        )
        root.addWidget(lbl)
        self.txt_reply = QPlainTextEdit()
        self.txt_reply.setStyleSheet(f"""
            QPlainTextEdit {{
                background: {Colors.BG_CONSOLE};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER}; border-radius: 8px;
                padding: 8px; font-size: 12px;
                font-family: Consolas, monospace;
            }}
        """)
        self.txt_reply.setMaximumHeight(90)
        root.addWidget(self.txt_reply)

        # ── Actions ──
        actions = QHBoxLayout()
        self.btn_copy = QPushButton("📋  Copy to clipboard")
        self.btn_copy.clicked.connect(self._do_copy)
        actions.addWidget(self.btn_copy)
        actions.addStretch(1)
        self.btn_send = QPushButton("📤  Send reply")
        self.btn_send.setObjectName("PrimaryButton")
        self.btn_send.clicked.connect(self._do_send)
        actions.addWidget(self.btn_send)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        actions.addWidget(self.btn_cancel)
        root.addLayout(actions)

    def _stat_widget(self, label: str, value: str) -> QFrame:
        f = QFrame()
        l = QVBoxLayout(f)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(0)
        v_lbl = QLabel(value)
        v_lbl.setStyleSheet(
            f"color: {Colors.PRIMARY}; font-size: 18px; font-weight: 700; "
            f"font-family: Consolas, monospace;"
        )
        l.addWidget(v_lbl)
        k_lbl = QLabel(label)
        k_lbl.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: 10px; font-weight: 700; "
            f"letter-spacing: 1px;"
        )
        l.addWidget(k_lbl)
        return f

    # -----------------------------------------------------------------------
    def _update_reply_text(self):
        """Re-generate the suggested reply based on current selections."""
        stars = self.cmb_rating.currentData()
        snr = self.info.get("snr")
        rssi = self.info.get("rssi")
        hop_s = self.info.get("hop_start")
        hop_l = self.info.get("hop_limit")
        hops = (int(hop_s) - int(hop_l)) if (hop_s is not None and hop_l is not None) else None

        parts = []
        bars = "⭐" * stars
        if bars:
            parts.append(f"{bars} {stars}/5")
        else:
            parts.append("0/5")
        if snr is not None:
            parts.append(f"SNR {snr:.1f} dB")
        if hops is not None:
            parts.append(f"{hops} hop" + ("s" if hops != 1 else ""))
        elif rssi is not None:
            parts.append(f"RSSI {rssi} dBm")

        # Compose: ack + rating + signal + hops + reasonable length cap
        msg = "RX: " + " · ".join(parts)
        # Cap to safe LoRa payload (~200 chars)
        if len(msg) > 200:
            msg = msg[:200]
        self.txt_reply.setPlainText(msg)

    # -----------------------------------------------------------------------
    def _do_copy(self):
        QApplication.clipboard().setText(self.txt_reply.toPlainText())
        self.btn_copy.setText("✓  Copied!")

    def _do_send(self):
        text = self.txt_reply.toPlainText().strip()
        if not text:
            return
        self.sendRequested.emit(text)
        self.accept()
