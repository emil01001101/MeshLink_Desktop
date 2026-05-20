"""
Reusable widgets.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QPainter, QColor, QBrush
from PySide6.QtWidgets import (
    QFrame, QLabel, QHBoxLayout, QVBoxLayout, QWidget,
    QPushButton, QGridLayout
)

from ..theme import Colors


# ===========================================================================
# Signal strength indicator
# ===========================================================================
class SignalIndicator(QWidget):

    BAR_COUNT = 4

    def __init__(self, snr: Optional[float] = None, is_own_node: bool = False,
                 parent=None):
        super().__init__(parent)
        self._snr = snr
        self._is_own_node = is_own_node
        self.setFixedSize(QSize(22, 16))
        self.setToolTip(self._tooltip_text())

    def set_snr(self, snr: Optional[float]):
        self._snr = snr
        self.setToolTip(self._tooltip_text())
        self.update()

    def set_own_node(self, own: bool):
        self._is_own_node = own
        self.setToolTip(self._tooltip_text())
        self.update()

    def _level(self) -> int:
        if self._snr is None or self._is_own_node:
            return 0
        if self._snr >= 5:    return 4
        if self._snr >= 0:    return 3
        if self._snr >= -7:   return 2
        if self._snr >= -15:  return 1
        return 0

    def _tooltip_text(self) -> str:
        from ..i18n import t  # import here to avoid circular at module load
        if self._is_own_node:
            return t("nodes.signal_own")
        if self._snr is None:
            return t("nodes.signal_unknown")
        return f"SNR: {self._snr:.1f} dB"

    def paintEvent(self, e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        level = self._level()
        w = self.width()
        h = self.height()
        bar_w, gap = 3, 2
        total = self.BAR_COUNT * bar_w + (self.BAR_COUNT - 1) * gap
        x0 = (w - total) // 2

        for i in range(self.BAR_COUNT):
            x = x0 + i * (bar_w + gap)
            bar_h = int(h * (0.30 + 0.22 * i))
            y = h - bar_h
            if self._is_own_node:
                # Bars shown in dimmed style — own node, no air reception
                color = QColor(Colors.BORDER_HI)
            else:
                color = QColor(Colors.PRIMARY if i < level else Colors.BORDER_HI)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(color))
            p.drawRoundedRect(x, y, bar_w, bar_h, 1, 1)
        p.end()


# ===========================================================================
# Avatar circular
# ===========================================================================
class ShortNameAvatar(QLabel):
    def __init__(self, short_name: str, is_me: bool = False,
                 size: int = 44, parent=None):
        super().__init__(parent)
        self.setObjectName("NodeShort")
        if is_me:
            self.setProperty("role", "me")
        self.setFixedSize(QSize(size, size))
        self.setAlignment(Qt.AlignCenter)
        self.set_text(short_name)

    def set_text(self, short_name: str):
        self.setText((short_name or "??")[:4].upper())


# ===========================================================================
# Message bubble
# ===========================================================================
class MessageBubble(QWidget):
    """Chat bubble with right-click context menu and delivery status icon.

    Signals (for action menu):
        requestCopy(str)        — copy message text to clipboard
        requestDM(str)          — start a DM conversation with the sender
        requestDetails(str)     — open node details popup for the sender
        requestReply(int,str,str) — user wants to reply to this msg
                                     (packet_id, sender_name, preview_text)
        requestReact(int,str)   — user wants to add a reaction
                                     (packet_id, sender_name)
        clicked()               — left-click on bubble (sent messages: opens
                                  delivery info dialog showing which nodes
                                  acknowledged / relayed the message)
    """

    # Signals for the right-click context menu
    requestSignalReport = Signal(str, dict)   # text, info_dict
    requestCopy    = Signal(str)
    requestDM      = Signal(str)
    requestDetails = Signal(str)
    requestReply   = Signal(int, str, str)   # packet_id, sender, preview
    requestReact   = Signal(int, str)        # packet_id, sender
    clicked        = Signal()

    # Delivery status icons
    STATUS_PENDING   = "⏳"   # waiting to be sent
    STATUS_SENT      = "✓"    # sent to mesh / accepted by device
    STATUS_DELIVERED = "✓✓"   # ACK received from recipient (DMs only)
    STATUS_FAILED    = "✗"    # error / no ACK in time

    def __init__(self, text: str, is_me: bool, sender_name: str = "",
                 timestamp: Optional[int] = None,
                 from_id: str = "",
                 packet_id: Optional[int] = None,
                 status: str = "sent",
                 snr: Optional[float] = None,
                 rssi: Optional[int] = None,
                 hop_start: Optional[int] = None,
                 hop_limit: Optional[int] = None,
                 reply_preview: Optional[str] = None,
                 reply_to_sender: str = "",
                 parent=None):
        super().__init__(parent)
        self._text = text
        self._is_me = is_me
        self._from_id = from_id
        self._packet_id = packet_id
        self._status = status
        self._sender_name = sender_name or ""
        # Signal quality info — relevant on RECEIVED messages so user can
        # quickly report it back during range tests.
        self._snr = snr
        self._rssi = rssi
        self._hop_start = hop_start
        self._hop_limit = hop_limit
        # Reply threading: when this message is a reply, show a small
        # preview of the message being replied to above the text.
        self._reply_preview = (reply_preview or "").strip()
        self._reply_to_sender = (reply_to_sender or "").strip()
        # Reactions: dict[emoji] -> set of from_id who reacted with that emoji
        self._reactions: dict = {}
        self._setup_ui(text, is_me, sender_name, timestamp)

    # public ------------------------------------------------------------
    @property
    def packet_id(self) -> Optional[int]:
        return self._packet_id

    @property
    def from_id(self) -> str:
        return self._from_id

    @property
    def text(self) -> str:
        return self._text

    def set_status(self, status: str):
        """Update delivery status: pending/sent/delivered/failed."""
        self._status = status
        if hasattr(self, "_meta_label"):
            self._meta_label.setText(self._build_meta_text())

    def add_reaction(self, emoji: str, from_id: str):
        """Add a reaction received from `from_id` with `emoji` to this bubble.

        Multiple distinct nodes can react with the same emoji and the chip
        will show a counter (e.g. '❤️ 3'). The same node reacting twice
        with the same emoji is deduped.
        """
        if not emoji:
            return
        s = self._reactions.setdefault(emoji, set())
        s.add(from_id or "?")
        self._rebuild_reactions_row()

    def get_reactions(self) -> dict:
        """Return current reactions as {emoji: [from_id, ...]}.

        Used by the parent page to persist them with the message in
        the SQLite history.
        """
        return {emoji: sorted(senders)
                for emoji, senders in self._reactions.items()}

    def set_reactions(self, reactions: dict):
        """Bulk-set reactions; replaces existing state."""
        self._reactions = {}
        for emoji, senders in (reactions or {}).items():
            if not emoji:
                continue
            self._reactions[emoji] = set(senders or [])
        self._rebuild_reactions_row()

    # internal ----------------------------------------------------------
    def _build_meta_text(self) -> str:
        ts_str = datetime.fromtimestamp(self._ts).strftime("%H:%M")
        if not self._is_me:
            return ts_str
        icon_map = {
            "pending":   self.STATUS_PENDING,
            "sent":      self.STATUS_SENT,
            "delivered": self.STATUS_DELIVERED,
            "failed":    self.STATUS_FAILED,
        }
        icon = icon_map.get(self._status, "")
        return f"{ts_str}  {icon}" if icon else ts_str

    def _setup_ui(self, text, is_me, sender_name, timestamp):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 2, 0, 2)
        outer.setSpacing(0)

        # Wrap bubble + reactions row in a vertical container so the row
        # appears tucked just under the bubble on the same side.
        side_wrap = QVBoxLayout()
        side_wrap.setContentsMargins(0, 0, 0, 0)
        side_wrap.setSpacing(2)

        self._bubble = QFrame()
        self._bubble.setObjectName("BubbleMe" if is_me else "BubbleOther")
        self._bubble.setMaximumWidth(560)
        # Custom context menu on the bubble itself (right-click)
        self._bubble.setContextMenuPolicy(Qt.CustomContextMenu)
        self._bubble.customContextMenuRequested.connect(self._show_menu)

        # For our OWN sent messages: clicking the bubble opens the delivery
        # info dialog (which nodes acked / relayed). Show pointing-hand cursor
        # on the bubble background to hint at this. Text remains selectable
        # because the QLabel inside accepts press events on text (so the
        # parent's mousePressEvent only fires for clicks on padding/meta).
        if is_me:
            self._bubble.setCursor(Qt.PointingHandCursor)
            self._bubble.setToolTip("Click for delivery info")
            self._bubble.mousePressEvent = self._bubble_mouse_press

        inner = QVBoxLayout(self._bubble)
        inner.setContentsMargins(12, 8, 12, 8)
        inner.setSpacing(2)

        if not is_me and sender_name:
            s = QLabel(sender_name)
            s.setObjectName("BubbleSender")
            inner.addWidget(s)

        # ---- Reply preview block (only when this message is a reply) ----
        if self._reply_preview:
            preview_frame = QFrame()
            preview_frame.setObjectName("BubbleReplyPreview")
            preview_frame.setStyleSheet(f"""
                QFrame#BubbleReplyPreview {{
                    background: rgba(255,255,255,0.06);
                    border-left: 3px solid {Colors.PRIMARY};
                    border-radius: 4px;
                }}
            """)
            pv = QVBoxLayout(preview_frame)
            pv.setContentsMargins(8, 4, 8, 4)
            pv.setSpacing(1)
            if self._reply_to_sender:
                rs = QLabel("↪  " + self._reply_to_sender)
                rs.setStyleSheet(f"color: {Colors.PRIMARY}; font-size: 10px; "
                                 f"font-weight: 600;")
                pv.addWidget(rs)
            preview_text = self._reply_preview
            if len(preview_text) > 80:
                preview_text = preview_text[:77] + "…"
            rt = QLabel(preview_text)
            rt.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 11px; "
                             f"font-style: italic;")
            rt.setWordWrap(True)
            pv.addWidget(rt)
            inner.addWidget(preview_frame)

        self._text_label = QLabel(text)
        self._text_label.setObjectName("BubbleText")
        self._text_label.setWordWrap(True)
        self._text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        # Right-click on the text label also opens menu
        self._text_label.setContextMenuPolicy(Qt.CustomContextMenu)
        self._text_label.customContextMenuRequested.connect(
            lambda p: self._show_menu(self._text_label.mapTo(self._bubble, p))
        )
        inner.addWidget(self._text_label)

        self._ts = timestamp or int(time.time())
        self._meta_label = QLabel(self._build_meta_text())
        self._meta_label.setObjectName("BubbleMeta")
        self._meta_label.setAlignment(Qt.AlignRight if is_me else Qt.AlignLeft)
        inner.addWidget(self._meta_label)

        # ---- Reactions chip row (under the bubble) ----
        self._reactions_row = QFrame()
        self._reactions_row_layout = QHBoxLayout(self._reactions_row)
        self._reactions_row_layout.setContentsMargins(6, 0, 6, 0)
        self._reactions_row_layout.setSpacing(4)
        self._reactions_row.setVisible(False)

        side_wrap.addWidget(self._bubble)
        side_wrap.addWidget(self._reactions_row)

        if is_me:
            outer.addStretch(1)
            outer.addLayout(side_wrap)
            self._reactions_row_layout.addStretch(1)   # chips right-aligned
        else:
            outer.addLayout(side_wrap)
            outer.addStretch(1)
            # chips left-aligned (default flow)

    def _bubble_mouse_press(self, e):
        """Left click on the bubble background (not text) emits clicked()."""
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        # don't accept — let event continue to default handling
        e.ignore()

    def _rebuild_reactions_row(self):
        """Re-render the reactions chip row from self._reactions."""
        if not hasattr(self, "_reactions_row_layout"):
            return
        # Clear existing chips (keep the trailing stretch for is_me case)
        while self._reactions_row_layout.count():
            item = self._reactions_row_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        if not self._reactions:
            self._reactions_row.setVisible(False)
            return
        # Insert one chip per emoji
        chip_style = (
            f"QLabel {{ background: {Colors.BG_SURFACE_HI}; "
            f"border: 1px solid {Colors.BORDER}; border-radius: 10px; "
            f"padding: 2px 7px; font-size: 11px; "
            f"font-family: 'Segoe UI Emoji', 'Segoe UI Symbol', "
            f"'Apple Color Emoji', 'Noto Color Emoji', sans-serif; "
            f"color: {Colors.TEXT_PRIMARY}; }}"
        )
        for emoji, senders in sorted(self._reactions.items()):
            n = len(senders)
            chip = QLabel(f"{emoji}  {n}" if n > 1 else emoji)
            chip.setStyleSheet(chip_style)
            chip.setToolTip(", ".join(sorted(senders)))
            self._reactions_row_layout.addWidget(chip)
        if self._is_me:
            self._reactions_row_layout.addStretch(1)
        else:
            # left-align: add stretch after chips
            self._reactions_row_layout.addStretch(1)
        self._reactions_row.setVisible(True)

    def _show_menu(self, pos):
        """Show right-click context menu on the bubble."""
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QAction
        menu = QMenu(self)
        a_copy = QAction("📋  Copy message", self)
        a_copy.triggered.connect(lambda: self.requestCopy.emit(self._text))
        menu.addAction(a_copy)

        # Reply + React: available on ANY message that has a known packet_id.
        # For our own sent messages we omit reply (would be replying to self),
        # but reactions to your own messages are fine — Meshtastic supports it.
        if self._packet_id:
            menu.addSeparator()
            if not self._is_me:
                a_reply = QAction("↩  Reply to this message", self)
                preview = self._text if len(self._text) <= 80 \
                          else self._text[:77] + "…"
                a_reply.triggered.connect(
                    lambda: self.requestReply.emit(
                        int(self._packet_id),
                        self._sender_name or self._from_id,
                        preview))
                menu.addAction(a_reply)
            a_react = QAction("😊  React with emoji…", self)
            a_react.triggered.connect(
                lambda: self.requestReact.emit(
                    int(self._packet_id),
                    self._sender_name or self._from_id))
            menu.addAction(a_react)

        # DM, details and Signal report only make sense for RECEIVED messages
        if not self._is_me and self._from_id:
            menu.addSeparator()
            # Signal-quality report — useful during range tests
            a_signal = QAction("📊  Signal report (reply with quality)…", self)
            info = {
                "snr":       self._snr,
                "rssi":      self._rssi,
                "hop_start": self._hop_start,
                "hop_limit": self._hop_limit,
                "from_id":   self._from_id,
                "sender":    "",   # filled by parent
            }
            a_signal.triggered.connect(
                lambda: self.requestSignalReport.emit(self._text, info))
            menu.addAction(a_signal)

            menu.addSeparator()
            a_dm = QAction("💬  Send private message", self)
            a_dm.triggered.connect(lambda: self.requestDM.emit(self._from_id))
            menu.addAction(a_dm)
            a_details = QAction("🔍  Show node details…", self)
            a_details.triggered.connect(lambda: self.requestDetails.emit(self._from_id))
            menu.addAction(a_details)
        menu.exec(self._bubble.mapToGlobal(pos))


# ===========================================================================
# Node card
# ===========================================================================
class NodeCard(QFrame):
    """
    Node card with expand/collapse details panel.

    Compact view (always visible): avatar, name, ID, position summary,
    SNR/RSSI bars, battery, last-seen.

    Expanded view (click chevron to toggle): grid with ALL available
    fields — long/short name, hw model, role, hop limit, hops away,
    channel utilization, air util, uptime, full position (alt, sats,
    precision, source, time), SNR/RSSI numeric, lastHeard exact time,
    public key, isLicensed (HAM), num.
    """

    expandToggled = Signal(str, bool)  # node_id, expanded

    def __init__(self, node_id: str, node_data: dict,
                 is_me: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("NodeCard")
        self.node_id = node_id
        self.is_me = is_me
        self._expanded = False
        self._last_node: dict = {}
        self._build_ui()
        self.update_data(node_data)

    def set_is_me(self, is_me: bool):
        """Update the "this is my own node" flag after construction.

        Required because `my_node_id` from the manager isn't always available
        when the first `nodeUpdated` signal fires for the local node — the
        card gets created with is_me=False and the SignalIndicator shows
        the generic "Signal: unknown" tooltip instead of "Own node — signal
        not measured". Calling this when my_node_id becomes known fixes
        the tooltip + avatar styling without re-creating the card.
        """
        if self.is_me == is_me:
            return
        self.is_me = is_me
        try:
            self.signal.set_own_node(is_me)
        except Exception:
            pass
        # Re-create the avatar with the new is_me flag so it gets the
        # proper "you" tinting.
        try:
            old = self.avatar
            short = old.text() if hasattr(old, "text") else "??"
            from .common import ShortNameAvatar
            parent_lay = old.parentWidget().layout()
            idx = parent_lay.indexOf(old)
            new_av = ShortNameAvatar(short, is_me=is_me, size=44)
            parent_lay.insertWidget(idx, new_av)
            old.deleteLater()
            self.avatar = new_av
        except Exception:
            pass

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── HEADER ROW ──
        header = QFrame()
        header.setObjectName("NodeCardHeader")
        h = QHBoxLayout(header)
        h.setContentsMargins(14, 12, 14, 12)
        h.setSpacing(12)

        self.avatar = ShortNameAvatar("??", is_me=self.is_me, size=44)
        h.addWidget(self.avatar)

        col = QVBoxLayout()
        col.setSpacing(2)
        col.setContentsMargins(0, 0, 0, 0)
        self.lbl_name = QLabel("Unknown")
        self.lbl_name.setObjectName("NodeName")
        self.lbl_id = QLabel("")
        self.lbl_id.setObjectName("NodeId")
        col.addWidget(self.lbl_name)
        col.addWidget(self.lbl_id)
        self.lbl_meta = QLabel("")
        self.lbl_meta.setObjectName("NodeStat")
        col.addWidget(self.lbl_meta)
        h.addLayout(col, 1)

        right = QVBoxLayout()
        right.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        right.setSpacing(4)
        self.signal = SignalIndicator(None, is_own_node=self.is_me)
        right.addWidget(self.signal, 0, Qt.AlignRight)
        self.lbl_battery = QLabel("")
        self.lbl_battery.setObjectName("NodeStat")
        self.lbl_battery.setAlignment(Qt.AlignRight)
        right.addWidget(self.lbl_battery)
        self.lbl_last = QLabel("")
        self.lbl_last.setObjectName("NodeStat")
        self.lbl_last.setAlignment(Qt.AlignRight)
        right.addWidget(self.lbl_last)
        h.addLayout(right)

        # Expand chevron
        self.btn_expand = QPushButton("▾")
        self.btn_expand.setFixedSize(28, 28)
        self.btn_expand.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {Colors.TEXT_DIM};
                border: 1px solid {Colors.BORDER}; border-radius: 14px;
                font-size: 14px;
            }}
            QPushButton:hover {{
                background: {Colors.BG_SURFACE_HI};
                color: {Colors.TEXT_PRIMARY};
            }}
        """)
        self.btn_expand.setToolTip("Show / hide all node details")
        self.btn_expand.clicked.connect(self._toggle_expand)
        h.addWidget(self.btn_expand)

        root.addWidget(header)

        # ── DETAILS PANEL (hidden by default) ──
        self.details = QFrame()
        self.details.setObjectName("NodeCardDetails")
        self.details.setStyleSheet(f"""
            QFrame#NodeCardDetails {{
                background: {Colors.BG_SURFACE_HI};
                border-top: 1px solid {Colors.BORDER};
            }}
        """)
        self.details_layout = QGridLayout(self.details)
        self.details_layout.setContentsMargins(20, 12, 20, 12)
        self.details_layout.setHorizontalSpacing(24)
        self.details_layout.setVerticalSpacing(6)
        self.details.setVisible(False)
        root.addWidget(self.details)

    def _toggle_expand(self):
        self._expanded = not self._expanded
        self.details.setVisible(self._expanded)
        self.btn_expand.setText("▴" if self._expanded else "▾")
        if self._expanded:
            self._rebuild_details(self._last_node)
        self.expandToggled.emit(self.node_id, self._expanded)

    def update_data(self, node: dict):
        self._last_node = node or {}
        user = node.get("user") or {}
        long_name  = user.get("longName")  or "Unknown node"
        short_name = user.get("shortName") or "??"
        hw         = user.get("hwModel")   or "?"

        self.lbl_name.setText(long_name + ("  (me)" if self.is_me else ""))
        self.lbl_id.setText(f"{self.node_id}  •  {hw}")
        self.avatar.set_text(short_name)

        bits = []
        pos = node.get("position") or {}
        lat = pos.get("latitude")
        lon = pos.get("longitude")
        if lat is None and pos.get("latitudeI") is not None:
            lat = pos["latitudeI"] / 1e7
            lon = pos.get("longitudeI", 0) / 1e7
        if lat is not None and lon is not None:
            bits.append(f"📍 {lat:.4f}, {lon:.4f}")
        role = user.get("role")
        if role and str(role) not in ("CLIENT", "0"):
            bits.append(f"⚙ {role}")
        hops = node.get("hopsAway")
        if hops is not None and hops != 0:
            bits.append(f"📡 {hops} hops")
        self.lbl_meta.setText("  ".join(bits))

        self.signal.set_snr(node.get("snr"))

        dm = node.get("deviceMetrics") or {}
        battery = dm.get("batteryLevel")
        voltage = dm.get("voltage")
        bat_parts = []
        if battery is not None:
            if battery > 100:
                bat_parts.append("🔌 USB")
            else:
                icon = "🔋" if battery > 20 else "🪫"
                bat_parts.append(f"{icon} {battery}%")
        if voltage is not None:
            bat_parts.append(f"{voltage:.2f}V")
        self.lbl_battery.setText("  ".join(bat_parts))

        last = node.get("lastHeard")
        self.lbl_last.setText(humanize_age(last) if last else "—")

        if self._expanded:
            self._rebuild_details(node)

    def _rebuild_details(self, node: dict):
        # clear existing
        while self.details_layout.count():
            item = self.details_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        rows = self._collect_detail_rows(node)
        # 2 columns of key/value (each row uses cols 0+1 / 2+3)
        per_col = (len(rows) + 1) // 2
        for i, (k, v) in enumerate(rows):
            r = i % per_col
            c = (i // per_col) * 2
            k_lbl = QLabel(f"{k}:")
            k_lbl.setStyleSheet(
                f"color: {Colors.TEXT_DIM}; font-size: 11px; "
                f"font-weight: 600; text-transform: uppercase; "
                f"letter-spacing: 0.5px;"
            )
            v_lbl = QLabel(str(v))
            v_lbl.setStyleSheet(
                f"color: {Colors.TEXT_PRIMARY}; font-size: 12px; "
                f"font-family: Consolas, monospace;"
            )
            v_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            v_lbl.setWordWrap(True)
            self.details_layout.addWidget(k_lbl, r, c)
            self.details_layout.addWidget(v_lbl, r, c + 1)
        self.details_layout.setColumnStretch(1, 1)
        self.details_layout.setColumnStretch(3, 1)

    @staticmethod
    def _collect_detail_rows(node: dict) -> list:
        """Build the list of (label, value) pairs to show in details grid."""
        rows: list = []
        user = node.get("user") or {}
        pos  = node.get("position") or {}
        dm   = node.get("deviceMetrics") or {}
        em   = node.get("environmentMetrics") or {}
        pm   = node.get("powerMetrics") or {}

        def add(label, val, fmt=None):
            if val is None or val == "":
                return
            if fmt:
                try: val = fmt(val)
                except Exception: pass
            rows.append((label, val))

        # Identity
        add("Long name",  user.get("longName"))
        add("Short name", user.get("shortName"))
        add("Node ID",    node.get("user", {}).get("id"))
        add("Node num",   node.get("num"))
        add("Hardware",   user.get("hwModel"))
        add("MAC",        user.get("macaddr"))
        add("Role",       user.get("role"))
        add("Licensed",   "Yes" if user.get("isLicensed") else None)
        pk = user.get("publicKey")
        if pk:
            pk_str = str(pk)
            if len(pk_str) > 40:
                pk_str = pk_str[:37] + "…"
            add("Public key", pk_str)

        # Position
        lat = pos.get("latitude")
        lon = pos.get("longitude")
        if lat is None and pos.get("latitudeI") is not None:
            lat = pos["latitudeI"] / 1e7
            lon = pos.get("longitudeI", 0) / 1e7
        if lat is not None:
            add("Latitude",  f"{lat:.6f}")
            add("Longitude", f"{lon:.6f}")
        add("Altitude",       pos.get("altitude"), fmt=lambda v: f"{v} m")
        add("Sats in view",   pos.get("satsInView"))
        add("Precision bits", pos.get("precisionBits"))
        add("Loc source",     pos.get("locationSource"))
        ptime = pos.get("time")
        if ptime:
            add("Pos time", datetime.fromtimestamp(ptime).strftime("%Y-%m-%d %H:%M:%S"))

        # Device telemetry
        bat = dm.get("batteryLevel")
        if bat is not None:
            add("Battery", "USB powered" if bat > 100 else f"{int(bat)}%")
        add("Voltage",        dm.get("voltage"),
            fmt=lambda v: f"{v:.3f} V")
        add("Channel util",   dm.get("channelUtilization"),
            fmt=lambda v: f"{v:.2f}%")
        add("Air util TX",    dm.get("airUtilTx"),
            fmt=lambda v: f"{v:.2f}%")
        add("Uptime",         dm.get("uptimeSeconds"),
            fmt=_format_uptime)

        # ── Environment sensors (if present) ──
        # All fields from EnvironmentMetrics protobuf, displayed when available
        add("🌡 Temperature",   em.get("temperature"),
            fmt=lambda v: f"{v:.1f} °C")
        add("💧 Humidity",      em.get("relativeHumidity"),
            fmt=lambda v: f"{v:.1f} %")
        add("📊 Pressure",      em.get("barometricPressure"),
            fmt=lambda v: f"{v:.1f} hPa")
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
        # Env voltage / current (e.g. for sensor power monitoring)
        if em.get("voltage") is not None and "voltage" not in dm:
            add("⚡ Env voltage", em.get("voltage"),
                fmt=lambda v: f"{v:.3f} V")
        if em.get("current") is not None:
            add("⚡ Env current", em.get("current"),
                fmt=lambda v: f"{v:.1f} mA")

        # ── Power sensors (INA series, 3 channels) ──
        for ch in (1, 2, 3):
            v_key = f"ch{ch}Voltage"
            i_key = f"ch{ch}Current"
            if pm.get(v_key) is not None:
                add(f"🔌 Ch{ch} voltage", pm[v_key],
                    fmt=lambda v: f"{v:.3f} V")
            if pm.get(i_key) is not None:
                add(f"🔌 Ch{ch} current", pm[i_key],
                    fmt=lambda v: f"{v:.1f} mA")

        # Signal
        add("SNR",            node.get("snr"),
            fmt=lambda v: f"{v:.2f} dB")
        add("RSSI",           node.get("rssi"),
            fmt=lambda v: f"{v} dBm")
        add("Hops away",      node.get("hopsAway"))
        add("Via MQTT",       "Yes" if node.get("viaMqtt") else None)

        # ── Direct radio neighbors (from NEIGHBORINFO_APP packets) ──
        neighbors = node.get("neighbors") or []
        if neighbors:
            # Compact summary: "5 (best: !abcd1234 8.5dB)"
            best = None
            best_snr = -999
            for n in neighbors:
                s = n.get("snr")
                if s is not None and s > best_snr:
                    best_snr = s
                    best = n
            summary = f"{len(neighbors)}"
            if best:
                summary += f"  (best: {best.get('node_id', '?')} "
                summary += f"{best_snr:+.1f} dB)"
            add("📡 Neighbors", summary)

        # Timestamps
        lh = node.get("lastHeard")
        if lh:
            add("Last heard",
                datetime.fromtimestamp(lh).strftime("%Y-%m-%d %H:%M:%S"))
        return rows


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


# ===========================================================================
# Utils
# ===========================================================================
def humanize_age(ts) -> str:
    if not ts:
        return "?"
    delta = int(time.time()) - int(ts)
    if delta < 0:     return "future"
    if delta < 60:    return "now"
    if delta < 3600:  return f"{delta // 60}m"
    if delta < 86400: return f"{delta // 3600}h"
    return f"{delta // 86400}d"


class HSeparator(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HSeparator")
        self.setFrameShape(QFrame.NoFrame)
        self.setFixedHeight(1)
