"""
Message delivery status dialog.

Shown when the user clicks on a sent message bubble. Displays:

  • The message text + send timestamp
  • Whether it was a DM (with destination) or a broadcast (channel)
  • Per-responder routing info:
      - For DMs (wantAck=True): the destination's ACK
      - For broadcasts: any relay router that forwarded the packet
  • For broadcasts: a note about flood-routing not providing per-recipient
    delivery confirmation, plus a list of nodes heard recently (likely
    candidates that received the packet).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, List, Dict, Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QScrollArea, QWidget, QGridLayout
)

from ..theme import Colors


def _fmt_time(ts) -> str:
    if not ts:
        return "?"
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%H:%M:%S")
    except Exception:
        return "?"


def _short_id(node_id: str) -> str:
    return node_id[-9:] if node_id and len(node_id) > 9 else (node_id or "?")


class MessageStatusDialog(QDialog):
    """Non-modal dialog showing delivery info for a sent message."""

    def __init__(self, status: Dict[str, Any], manager, parent=None):
        """
        status: dict from manager.get_message_status(packet_id) — has keys
                'meta' and 'responders'. If None/empty, dialog shows that
                no info is available for this message.
        manager: MeshtasticManager — for looking up node names.
        """
        super().__init__(parent)
        self.status = status or {}
        self.manager = manager
        self.setWindowFlag(Qt.Window)
        self.setWindowTitle("Message delivery info")
        self.resize(560, 520)
        self.setMinimumSize(420, 380)
        self._build_ui()

    # -----------------------------------------------------------------------
    def _node_name(self, node_id: str) -> str:
        if not node_id:
            return "unknown"
        try:
            iface = self.manager.interface
            if iface and getattr(iface, "nodes", None):
                node = iface.nodes.get(node_id) or {}
                user = node.get("user") or {}
                long_n = user.get("longName")
                short_n = user.get("shortName")
                if long_n:
                    return f"{long_n} ({short_n or _short_id(node_id)})"
        except Exception:
            pass
        return node_id

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        meta = self.status.get("meta") or {}
        responders = self.status.get("responders") or []

        # ── Header card with the message ──
        msg_card = QFrame()
        msg_card.setObjectName("Card")
        mc = QVBoxLayout(msg_card)
        mc.setContentsMargins(14, 12, 14, 12)
        mc.setSpacing(4)

        hdr = QLabel("Your message")
        hdr.setStyleSheet(
            f"color: {Colors.PRIMARY}; font-size: 11px; font-weight: 700;"
        )
        mc.addWidget(hdr)

        text = meta.get("text") or "(no text)"
        msg_lbl = QLabel(text)
        msg_lbl.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; font-size: 13px; padding: 6px 0;"
        )
        msg_lbl.setWordWrap(True)
        msg_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        mc.addWidget(msg_lbl)

        meta_line = QLabel(
            f"Sent at {_fmt_time(meta.get('sent_at'))} · "
            f"{'Broadcast' if meta.get('is_broadcast') else 'Direct message'}"
        )
        meta_line.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: 11px;"
        )
        mc.addWidget(meta_line)

        root.addWidget(msg_card)

        # ── Either DM destination or broadcast channel ──
        if meta.get("is_broadcast"):
            ch = meta.get("channel", 0)
            dest_card = self._make_info_card(
                "📡  BROADCAST",
                f"Channel index: {ch}",
                Colors.INFO
            )
        elif meta.get("destination"):
            dest_id = meta["destination"]
            name = self._node_name(dest_id)
            dest_card = self._make_info_card(
                "📨  DIRECT MESSAGE",
                f"To: {name}\n{dest_id}",
                Colors.PRIMARY
            )
        else:
            dest_card = self._make_info_card(
                "Unknown destination", "", Colors.WARNING
            )
        root.addWidget(dest_card)

        # ── Responders / delivery confirmation ──
        responders_card = QFrame()
        responders_card.setObjectName("Card")
        rc = QVBoxLayout(responders_card)
        rc.setContentsMargins(14, 12, 14, 12)
        rc.setSpacing(8)

        sec_title = QLabel(self._build_section_title(meta, responders))
        sec_title.setStyleSheet(
            f"color: {Colors.PRIMARY}; font-size: 11px; font-weight: 700;"
        )
        rc.addWidget(sec_title)

        if not self.status:
            # Unknown packet
            note = QLabel(
                "ℹ  No delivery information available for this message.\n"
                "    The packet ID is unknown — this can happen if the app\n"
                "    was restarted after the message was sent."
            )
            note.setStyleSheet(f"color: {Colors.TEXT_DIM}; font-size: 12px;")
            note.setWordWrap(True)
            rc.addWidget(note)
        elif responders:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setStyleSheet(
                f"QScrollArea {{ background: transparent; }}"
            )
            inner = QWidget()
            il = QVBoxLayout(inner)
            il.setContentsMargins(0, 0, 0, 0)
            il.setSpacing(6)
            for r in responders:
                il.addWidget(self._build_responder_row(r))
            il.addStretch(1)
            scroll.setWidget(inner)
            rc.addWidget(scroll, 1)
        else:
            # No responders yet
            if meta.get("is_broadcast"):
                note = QLabel(
                    "ℹ  Broadcast messages don't have per-recipient delivery\n"
                    "    confirmation. Meshtastic floods broadcasts through\n"
                    "    the mesh without explicit ACKs from each node.\n\n"
                    "    Some routers may emit routing-app responses when\n"
                    "    relaying — they will appear here as they arrive."
                )
            else:
                note = QLabel(
                    "⏳  Awaiting acknowledgement from the destination…\n"
                    "    The recipient's device sends a ROUTING_APP packet\n"
                    "    when it receives the message. Typical delay is\n"
                    "    a few seconds to a couple of minutes depending on\n"
                    "    mesh size and air time."
                )
            note.setStyleSheet(f"color: {Colors.TEXT_DIM}; font-size: 12px;")
            note.setWordWrap(True)
            rc.addWidget(note)

        root.addWidget(responders_card, 1)

        # ── For broadcasts only: show currently active nodes (heard recently) ──
        if meta.get("is_broadcast"):
            active_card = self._build_active_nodes_card(meta.get("sent_at"))
            root.addWidget(active_card)

        # ── Close button ──
        actions = QHBoxLayout()
        actions.addStretch(1)
        btn = QPushButton("Close")
        btn.setObjectName("PrimaryButton")
        btn.clicked.connect(self.close)
        actions.addWidget(btn)
        root.addLayout(actions)

    # -----------------------------------------------------------------------
    def _make_info_card(self, header: str, body: str, color: str) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        l = QVBoxLayout(card)
        l.setContentsMargins(14, 10, 14, 12)
        l.setSpacing(4)
        h = QLabel(header)
        h.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 700;")
        l.addWidget(h)
        if body:
            b = QLabel(body)
            b.setStyleSheet(
                f"color: {Colors.TEXT_PRIMARY}; font-size: 13px; "
                f"font-family: Consolas, monospace;"
            )
            b.setTextInteractionFlags(Qt.TextSelectableByMouse)
            b.setWordWrap(True)
            l.addWidget(b)
        return card

    def _build_section_title(self, meta: dict, responders: list) -> str:
        if meta.get("is_broadcast"):
            return f"📡  RELAYS THAT FORWARDED THIS MESSAGE ({len(responders)})"
        return f"📬  DELIVERY ACKNOWLEDGEMENTS ({len(responders)})"

    def _build_responder_row(self, r: dict) -> QFrame:
        """One responder = one node that sent us a ROUTING_APP for our msg."""
        row = QFrame()
        row.setObjectName("Card")
        row.setStyleSheet(f"""
            QFrame#Card {{
                background: {Colors.BG_SURFACE_HI};
                border: 1px solid {Colors.BORDER};
                border-radius: 8px;
            }}
        """)
        l = QHBoxLayout(row)
        l.setContentsMargins(12, 10, 12, 10)
        l.setSpacing(10)

        status = r.get("status", "?")
        icon = "✓✓" if status == "delivered" else "✗"
        color = Colors.SUCCESS if status == "delivered" else Colors.DANGER
        icon_lbl = QLabel(icon)
        icon_lbl.setFixedWidth(28)
        icon_lbl.setStyleSheet(
            f"color: {color}; font-size: 18px; font-weight: 700;"
        )
        l.addWidget(icon_lbl)

        info = QVBoxLayout()
        info.setSpacing(2)
        from_id = r.get("from_id", "?")
        name_lbl = QLabel(self._node_name(from_id))
        name_lbl.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; font-size: 13px; font-weight: 600;"
        )
        info.addWidget(name_lbl)

        snr = r.get("snr")
        rssi = r.get("rssi")
        err  = r.get("error", "")
        parts = []
        parts.append(f"at {_fmt_time(r.get('time'))}")
        if status == "delivered":
            parts.append("✓ ACK")
        else:
            parts.append(f"✗ {err}")
        if snr is not None:
            parts.append(f"SNR {snr:.1f} dB")
        if rssi is not None:
            parts.append(f"RSSI {rssi} dBm")
        sub = QLabel("  ·  ".join(parts))
        sub.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: 11px; "
            f"font-family: Consolas, monospace;"
        )
        info.addWidget(sub)
        l.addLayout(info, 1)
        return row

    def _build_active_nodes_card(self, sent_at) -> QFrame:
        """Show nodes heard in the ~10 minutes around send time."""
        import time as _t
        card = QFrame()
        card.setObjectName("Card")
        l = QVBoxLayout(card)
        l.setContentsMargins(14, 10, 14, 10)
        l.setSpacing(6)

        # Collect nodes heard within 10 minutes of send time
        active: List[Dict[str, Any]] = []
        try:
            iface = self.manager.interface
            if iface and getattr(iface, "nodes", None):
                ref = int(sent_at or _t.time())
                for nid, node in iface.nodes.items():
                    if nid == self.manager.my_node_id:
                        continue
                    lh = node.get("lastHeard") or node.get("last_heard")
                    if lh and abs(int(lh) - ref) <= 600:  # ±10 min
                        active.append((nid, node))
        except Exception:
            pass
        active.sort(key=lambda kv: kv[1].get("lastHeard") or 0, reverse=True)

        hdr = QLabel(
            f"🌐  LIKELY RECIPIENTS (active in mesh near send time: "
            f"{len(active)} nodes)"
        )
        hdr.setStyleSheet(
            f"color: {Colors.INFO}; font-size: 11px; font-weight: 700;"
        )
        l.addWidget(hdr)

        if not active:
            note = QLabel("No nodes heard in the ±10 minute window around send.")
            note.setStyleSheet(f"color: {Colors.TEXT_DIM}; font-size: 11px;")
            l.addWidget(note)
            return card

        # 2-column grid of node names
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(2)
        cols = 2
        for i, (nid, node) in enumerate(active[:20]):  # cap at 20
            user = node.get("user") or {}
            name = user.get("longName") or _short_id(nid)
            short = user.get("shortName") or "??"
            lbl = QLabel(f"• {name}  ({short})")
            lbl.setStyleSheet(
                f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;"
            )
            grid.addWidget(lbl, i // cols, i % cols)
        l.addLayout(grid)
        if len(active) > 20:
            more = QLabel(f"… and {len(active) - 20} more.")
            more.setStyleSheet(f"color: {Colors.TEXT_DIM}; font-size: 11px;")
            l.addWidget(more)
        return card
