"""
Pagina Mesaje - FIX bug afisare + bara actiuni DM (Position/Telemetry/Traceroute).

Schimbari fata de versiunea precedenta:
  • Detectare DM/broadcast mai robusta (accepta to_id "" / None ca broadcast)
  • Logging detaliat pentru CADERE - vezi in Console tab daca un mesaj NU apare
  • DB merge (NU overwrite) - nu mai pierdem mesajele primite in primele 500ms
  • Bara de actiuni in headerul DM: Position / Telemetry / Traceroute / Google Maps
  • Anti-duplicate on DB save
"""

from __future__ import annotations

import time
import logging
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal, Slot, QSize, QTimer, QUrl
from PySide6.QtGui import QKeyEvent, QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QFrame, QPushButton, QPlainTextEdit, QScrollArea, QInputDialog
)

from ..connection import MeshtasticManager
from ..widgets.common import MessageBubble
from ..theme import Colors
from ..i18n import t, i18n
from ..message_db import MessageDB
from ..settings_store import Settings

log = logging.getLogger("meshlink.messages")
BROADCAST_IDS = ("^all", "!ffffffff", "", None)


class _MessageInput(QPlainTextEdit):
    sendRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMaximumHeight(96)

    def keyPressEvent(self, e: QKeyEvent):  # noqa: N802
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and not (e.modifiers() & Qt.ShiftModifier):
            self.sendRequested.emit()
            return
        super().keyPressEvent(e)


class MessagesPage(QWidget):

    newMessageReceived = Signal(str, str, str)  # convo_id, sender_name, text
    # BUG 21 (V20-turn2): right-clicking a message and choosing "Send DM"
    # invoked self.requestStartDM.emit(from_id) but the signal was never
    # declared on the class, raising AttributeError every time. We just
    # add it here — the page handles the "switch to DM convo" path itself
    # via _switch_to_convo, but a signal lets main_window or future
    # consumers also hook into the action.
    requestStartDM = Signal(str)   # node_id

    def __init__(self, manager: MeshtasticManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.conversations: Dict[str, List[dict]] = {}
        self.channels: List[dict] = []
        self.node_names: Dict[str, str] = {}
        self.current_convo: Optional[str] = None
        self._history_loaded = False
        # Track bubbles for sent messages so we can update their delivery
        # status when ROUTING_APP ACKs arrive: {packet_id: MessageBubble}
        self._sent_bubbles: Dict[int, "MessageBubble"] = {}
        # Index of ALL currently-rendered bubbles by packet_id, used to
        # apply incoming reactions to the right bubble (sent OR received).
        # Rebuilt every time the conversation is re-rendered.
        self._bubbles_by_packet_id: Dict[int, "MessageBubble"] = {}
        # When the user clicks "Reply" on a bubble, we stage the parent
        # packet so the next send carries replyId. Dict so the banner can
        # show preview + sender; None when no reply is staged.
        self._pending_reply: Optional[dict] = None

        self._build_ui()
        self._connect_signals()
        i18n.languageChanged.connect(self._retranslate)
        self._retranslate()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ============== LEFT: lista conversatii ==============
        left = QFrame()
        left.setFixedWidth(280)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(16, 16, 8, 16)
        ll.setSpacing(10)

        self.lbl_section = QLabel()
        self.lbl_section.setProperty("role", "section")
        ll.addWidget(self.lbl_section)

        self.btn_new_dm = QPushButton()
        self.btn_new_dm.clicked.connect(self._new_dm)
        ll.addWidget(self.btn_new_dm)

        self.convo_list = QListWidget()
        self.convo_list.setSpacing(2)
        # V0.44: right-click a conversation to delete it
        self.convo_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.convo_list.customContextMenuRequested.connect(
            self._show_convo_context_menu)
        ll.addWidget(self.convo_list, 1)

        # ============== RIGHT: chat ==============
        right = QFrame()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(16, 16, 16, 16)
        rl.setSpacing(10)

        # header cu titlu + bara actiuni
        self.convo_header = QFrame()
        self.convo_header.setObjectName("Card")
        ch_l = QVBoxLayout(self.convo_header)
        ch_l.setContentsMargins(16, 12, 16, 12)
        ch_l.setSpacing(8)

        title_row = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        self.convo_title = QLabel()
        self.convo_title.setProperty("role", "title")
        self.convo_subtitle = QLabel()
        self.convo_subtitle.setProperty("role", "muted")
        title_col.addWidget(self.convo_title)
        title_col.addWidget(self.convo_subtitle)
        title_row.addLayout(title_col, 1)
        # V0.44: delete-conversation button (works for DM and channel).
        # Use a text label ("Delete") rather than an emoji-only glyph, which
        # doesn't render reliably inside a styled QPushButton on Windows.
        self.btn_clear_convo = QPushButton("🗑  Delete")
        self.btn_clear_convo.setCursor(Qt.PointingHandCursor)
        self.btn_clear_convo.setToolTip("Delete this conversation's history")
        self.btn_clear_convo.setStyleSheet(
            f"QPushButton {{ background: {Colors.BG_INPUT}; "
            f"color: {Colors.TEXT_SECONDARY}; "
            f"border: 1px solid {Colors.BORDER}; border-radius: 8px; "
            f"padding: 6px 12px; font-size: 12px; }} "
            f"QPushButton:hover {{ background: {Colors.DANGER}; "
            f"color: white; border-color: {Colors.DANGER}; }}")
        self.btn_clear_convo.clicked.connect(self._delete_current_conversation)
        title_row.addWidget(self.btn_clear_convo)
        ch_l.addLayout(title_row)

        # bara actiuni (vizibila doar la DM)
        self.action_bar = QFrame()
        ab_l = QHBoxLayout(self.action_bar)
        ab_l.setContentsMargins(0, 0, 0, 0)
        ab_l.setSpacing(8)
        self.btn_act_pos = QPushButton()
        self.btn_act_pos.clicked.connect(self._dm_request_position)
        ab_l.addWidget(self.btn_act_pos)
        self.btn_act_telem = QPushButton()
        self.btn_act_telem.clicked.connect(self._dm_request_telemetry)
        ab_l.addWidget(self.btn_act_telem)
        self.btn_act_trace = QPushButton()
        self.btn_act_trace.clicked.connect(self._dm_traceroute)
        ab_l.addWidget(self.btn_act_trace)
        self.btn_act_gmaps = QPushButton()
        self.btn_act_gmaps.clicked.connect(self._dm_gmaps)
        ab_l.addWidget(self.btn_act_gmaps)
        ab_l.addStretch(1)
        self.lbl_action_feedback = QLabel("")
        self.lbl_action_feedback.setStyleSheet(f"color: {Colors.SUCCESS}; font-size: 11px;")
        ab_l.addWidget(self.lbl_action_feedback)
        ch_l.addWidget(self.action_bar)
        self.action_bar.hide()

        rl.addWidget(self.convo_header)

        # zona bubbles
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setStyleSheet(f"QScrollArea {{ background: {Colors.BG_BASE}; border: none; }}")
        self.bubbles_container = QWidget()
        self.bubbles_layout = QVBoxLayout(self.bubbles_container)
        self.bubbles_layout.setContentsMargins(4, 4, 4, 4)
        self.bubbles_layout.setSpacing(2)
        self.bubbles_layout.addStretch(1)
        self.scroll.setWidget(self.bubbles_container)
        rl.addWidget(self.scroll, 1)

        self.empty_state = QLabel()
        self.empty_state.setAlignment(Qt.AlignCenter)
        self.empty_state.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: 14px; line-height: 1.6;"
        )
        rl.replaceWidget(self.scroll, self.empty_state)
        self.scroll.hide()

        # ── Reply banner (visible only when a reply is staged) ──
        self.reply_banner = QFrame()
        self.reply_banner.setObjectName("ReplyBanner")
        self.reply_banner.setStyleSheet(f"""
            QFrame#ReplyBanner {{
                background: {Colors.BG_SURFACE_HI};
                border-left: 3px solid {Colors.PRIMARY};
                border-radius: 4px;
            }}
        """)
        rb_l = QHBoxLayout(self.reply_banner)
        rb_l.setContentsMargins(10, 6, 10, 6)
        rb_l.setSpacing(8)
        self.lbl_reply_to = QLabel("↩")
        self.lbl_reply_to.setStyleSheet(
            f"color: {Colors.PRIMARY}; font-weight: 600; font-size: 12px;")
        rb_l.addWidget(self.lbl_reply_to)
        self.lbl_reply_preview = QLabel("")
        self.lbl_reply_preview.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; font-style: italic;")
        self.lbl_reply_preview.setWordWrap(False)
        rb_l.addWidget(self.lbl_reply_preview, 1)
        self.btn_cancel_reply = QPushButton("✗")
        self.btn_cancel_reply.setFixedSize(22, 22)
        self.btn_cancel_reply.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {Colors.TEXT_DIM};
                border: none; font-size: 13px; font-weight: 700;
            }}
            QPushButton:hover {{ color: {Colors.DANGER}; }}
        """)
        self.btn_cancel_reply.setToolTip("Cancel reply")
        self.btn_cancel_reply.clicked.connect(self._cancel_reply)
        rb_l.addWidget(self.btn_cancel_reply)
        self.reply_banner.setVisible(False)
        rl.addWidget(self.reply_banner)

        # input bar
        input_card = QFrame()
        input_card.setObjectName("Card")
        ic = QHBoxLayout(input_card)
        ic.setContentsMargins(12, 10, 12, 10)
        ic.setSpacing(8)

        # emoji picker button
        # IMPORTANT: We use CSS stylesheet font-family (NOT setFont) because
        # QPushButton on Windows uses the native widget style which bypasses
        # Qt's color glyph rendering when font is set via setFont(). The CSS
        # font-family path engages Qt's text engine which correctly renders
        # color emoji from Segoe UI Emoji.
        from ..dialogs.emoji_picker import _emoji_font_css
        self.btn_emoji = QPushButton("😀")
        self.btn_emoji.setFixedSize(40, 40)
        self.btn_emoji.setToolTip("Insert emoji")
        self.btn_emoji.setStyleSheet(f"""
            QPushButton {{
                background: {Colors.BG_SURFACE_HI};
                border: 1px solid {Colors.BORDER};
                border-radius: 8px;
                font-family: {_emoji_font_css()};
                font-size: 18px;
            }}
            QPushButton:hover {{
                background: {Colors.BORDER_HI};
                border: 1px solid {Colors.PRIMARY_DARK};
            }}
            QPushButton:disabled {{ color: {Colors.TEXT_DIM}; }}
        """)
        self.btn_emoji.setEnabled(False)
        self.btn_emoji.clicked.connect(self._open_emoji_picker)
        ic.addWidget(self.btn_emoji)

        self.input = _MessageInput()
        self.input.setEnabled(False)
        ic.addWidget(self.input, 1)
        self.send_btn = QPushButton()
        self.send_btn.setObjectName("PrimaryButton")
        self.send_btn.setMinimumWidth(100)
        self.send_btn.setEnabled(False)
        ic.addWidget(self.send_btn)
        rl.addWidget(input_card)

        root.addWidget(left)
        sep = QFrame()
        sep.setFixedWidth(1)
        sep.setStyleSheet(f"background: {Colors.BORDER};")
        root.addWidget(sep)
        root.addWidget(right, 1)

    def _connect_signals(self):
        self.manager.stateChanged.connect(self._on_state_changed)
        self.manager.channelsUpdated.connect(self._on_channels_updated)
        self.manager.textMessageReceived.connect(self._on_text_received)
        self.manager.nodeUpdated.connect(self._on_node_updated)
        self.manager.messageAckReceived.connect(self._on_message_ack)
        self.manager.reactionReceived.connect(self._on_reaction_received)
        # V20-turn7: render bubbles for messages the manager just sent,
        # regardless of source (UI input, scripts, console). One source of
        # truth — see comment in MeshtasticManager.messageSent declaration.
        self.manager.messageSent.connect(self._on_message_sent)
        self.convo_list.currentItemChanged.connect(self._on_convo_changed)
        self.send_btn.clicked.connect(self._send_current)
        self.input.sendRequested.connect(self._send_current)

    @Slot(dict)
    def _on_message_ack(self, info: dict):
        """Update the delivery status icon on the matching sent bubble.

        BUG 20 (V20-turn2): the previous Signal(int, str) form repeatedly
        triggered "Slot 'MessagesPage::_on_message_ack(int,QString)' not
        found" in PySide6 6.11.0 cross-thread dispatch, despite an
        @Slot(int, str) decoration. Switching to Signal(dict) (the same
        pattern that textMessageReceived uses successfully) routes through
        PyObject marshaling and avoids the QString metaobject lookup.

        BUG 25 (V20-turn7): the stored message dict must be updated even
        when no bubble is currently rendered (e.g. user is viewing channel 0
        but a script just sent a DM to a node) — otherwise switching to
        that convo afterwards would show the bubble stuck at 'pending'.
        We now always update the dict; the bubble update is conditional.
        """
        try:
            packet_id = int(info.get("packet_id") or 0)
        except Exception:
            packet_id = 0
        status = info.get("status") or ""
        if not packet_id:
            return
        log.info(f"ACK for packet #{packet_id}: {status}")
        # Update the stored message dict in ANY conversation that has it;
        # this is what gets read when the bubble is (re)rendered later.
        for msgs in self.conversations.values():
            for m in msgs:
                if m.get("packetId") == packet_id:
                    m["ackStatus"] = status
        # Also update the live bubble if one is currently on screen
        bubble = self._sent_bubbles.get(packet_id)
        if bubble is not None:
            bubble.set_status(status)

    def _retranslate(self, *_):
        self.lbl_section.setText(t("msg.conversations").upper())
        self.btn_new_dm.setText("➕  " + t("msg.new_dm"))
        self.send_btn.setText(t("msg.send"))
        self.input.setPlaceholderText(t("msg.input_placeholder"))
        self.btn_act_pos.setText(t("msg.action.position"))
        self.btn_act_telem.setText(t("msg.action.telemetry"))
        self.btn_act_trace.setText(t("msg.action.traceroute"))
        self.btn_act_gmaps.setText(t("msg.action.gmaps"))
        if not self.current_convo:
            self.convo_title.setText(t("msg.select_convo"))
            self.empty_state.setText(t("msg.empty_hint"))
        self._rebuild_convo_list()

    @Slot(str)
    def _on_state_changed(self, state: str):
        online = (state == "ready")
        self._set_input_enabled(online and self.current_convo is not None)
        self.btn_new_dm.setEnabled(online)
        if state == "ready" and not self._history_loaded and Settings.get().save_history:
            QTimer.singleShot(800, self._load_history_from_db)
        elif state == "idle":
            self._history_loaded = False   # reload on next connection

    @Slot(list)
    def _on_channels_updated(self, channels: list):
        log.info(f"Channels received: {[c.get('name') for c in channels]}")
        self.channels = channels
        self._rebuild_convo_list()
        if not self.current_convo and channels:
            QTimer.singleShot(50, lambda: self.convo_list.setCurrentRow(0))

    @Slot(str, dict)
    def _on_node_updated(self, node_id: str, node: dict):
        user = node.get("user") or {}
        name = user.get("longName") or user.get("shortName") or node_id
        if self.node_names.get(node_id) != name:
            self.node_names[node_id] = name
            self._rebuild_convo_list()
            if self.current_convo == f"dm:{node_id}":
                self._render_current_convo()

    # ====================================================================
    # RECEIVE MESSAGE - cu logging detaliat
    # ====================================================================
    @Slot(dict)
    def _on_text_received(self, msg: dict):
        from_id = msg.get("fromId") or "?"
        to_id   = msg.get("toId") or ""
        channel = msg.get("channel", 0)
        text    = msg.get("text") or ""

        if not text:
            log.warning(f"Text gol primit, IGNOR: {msg}")
            return

        # V0.45: game protocol messages are routed to the Games tab — keep
        # them out of the normal chat view. (MLGAME: covers all 5 games;
        # MLTTT: kept for backward-compat with older clients.)
        if text.startswith("MLGAME:") or text.startswith("MLTTT:"):
            return

        my_id = self.manager.my_node_id or ""
        is_me = bool(my_id) and (from_id == my_id)
        is_broadcast = to_id in BROADCAST_IDS

        if is_broadcast:
            convo_id = f"ch:{channel}"
        else:
            other = to_id if is_me else from_id
            convo_id = f"dm:{other}"

        log.info(
            f"[CHAT] {'TX' if is_me else 'RX'} "
            f"{convo_id}  from={from_id} to={to_id} ch={channel} "
            f"text={text[:80]!r}"
        )

        msg_record = {**msg, "isMe": is_me, "sender": from_id}
        self.conversations.setdefault(convo_id, []).append(msg_record)

        # persistenta DB (cu protectie de duplicate prin verificare rxTime+text+from)
        if Settings.get().save_history:
            try:
                MessageDB.get().add_message(
                    from_id=from_id, to_id=to_id, channel=channel,
                    text=text, rx_time=msg.get("rxTime", int(time.time())),
                    is_me=is_me,
                    packet_id=(msg.get("id") or msg.get("packetId")),
                    reply_id=msg.get("replyId"),
                )
            except Exception:
                log.exception("Error saving message to DB")

        self._rebuild_convo_list()

        if self.current_convo == convo_id:
            self._append_bubble(msg_record, is_me)
            self._scroll_to_bottom()
            log.debug(f"  -> bubble adaugat in UI (convo curent)")
        else:
            log.debug(f"  -> stored but not displayed (current convo: {self.current_convo})")

        if not is_me:
            sender = self.node_names.get(from_id, from_id or "?")
            self.newMessageReceived.emit(convo_id, sender, text)

    # ====================================================================
    # SELECTIE CONVO
    # ====================================================================
    def _on_convo_changed(self, current: Optional[QListWidgetItem], _previous):
        if not current or not current.flags() & Qt.ItemIsSelectable:
            self.current_convo = None
            self._show_empty()
            self.action_bar.hide()
            return
        self.current_convo = current.data(Qt.UserRole)
        self._render_current_convo()
        self._set_input_enabled(self.manager.is_connected)
        self.input.setFocus()
        # bara actiuni doar pentru DM
        self.action_bar.setVisible(self.current_convo.startswith("dm:") if self.current_convo else False)
        self.lbl_action_feedback.setText("")

    def _new_dm(self):
        nodes = []
        for nid, name in sorted(self.node_names.items(), key=lambda kv: kv[1].lower()):
            if nid != self.manager.my_node_id:
                nodes.append(f"{name}  —  {nid}")
        if not nodes:
            return
        choice, ok = QInputDialog.getItem(
            self, t("msg.new_dm_title"), t("msg.new_dm_prompt"), nodes, 0, False
        )
        if not ok or not choice:
            return
        node_id = choice.split("—")[-1].strip()
        self.start_dm_with(node_id)

    def start_dm_with(self, node_id: str):
        convo_id = f"dm:{node_id}"
        self.conversations.setdefault(convo_id, [])
        self._rebuild_convo_list()
        for i in range(self.convo_list.count()):
            it = self.convo_list.item(i)
            if it and it.data(Qt.UserRole) == convo_id:
                self.convo_list.setCurrentRow(i)
                return

    # ====================================================================
    # ACTIUNI in bara DM
    # ====================================================================
    def _show_convo_context_menu(self, pos):
        """Right-click on a conversation → Delete option."""
        item = self.convo_list.itemAt(pos)
        if item is None:
            return
        convo_id = item.data(Qt.UserRole)
        if not convo_id:
            return
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        act_del = menu.addAction("🗑  Delete conversation")
        chosen = menu.exec(self.convo_list.mapToGlobal(pos))
        if chosen == act_del:
            self._delete_conversation(convo_id)

    def _delete_current_conversation(self):
        """Delete the currently-open conversation (toolbar button)."""
        if self.current_convo:
            self._delete_conversation(self.current_convo)

    def _delete_conversation(self, convo_id: str):
        """Delete a conversation (DM or channel) from history, by id."""
        if not convo_id:
            return
        from PySide6.QtWidgets import QMessageBox
        is_dm = convo_id.startswith("dm:")
        # friendly name for the confirm dialog
        if is_dm:
            nid = convo_id.split(":", 1)[1]
            title = self.node_names.get(nid, nid)
        else:
            idx = convo_id.split(":", 1)[1]
            ch = next((c for c in self.channels if str(c["index"]) == idx), None)
            title = ch["name"] if ch else f"Channel {idx}"
        confirm = QMessageBox.question(
            self, "Delete conversation?",
            f"Delete all messages in \"{title}\"?\n\n"
            f"This only clears your local history in MeshLink Desktop — it "
            f"does not affect other nodes or the device. This can't be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        try:
            from ..message_db import MessageDB
            db = MessageDB.get()
            if is_dm:
                partner = convo_id.split(":", 1)[1]
                my = self.manager.my_node_id or ""
                n = db.clear_dm(my, partner)
            else:
                ch_idx = int(convo_id.split(":", 1)[1])
                n = db.clear_channel(ch_idx)
            # Clear in-memory cache
            self.conversations[convo_id] = []
            # Refresh the sidebar (count badges) and the chat view
            self._rebuild_convo_list()
            if self.current_convo == convo_id:
                self._render_current_convo()
            self._feedback(f"Deleted {n} message(s)")
            log.info(f"Cleared conversation {convo_id}: {n} messages")
        except Exception:
            log.exception("delete conversation failed")
            QMessageBox.warning(self, "Delete failed",
                                "Could not delete the conversation. See logs.")
        if self.current_convo and self.current_convo.startswith("dm:"):
            return self.current_convo.split(":", 1)[1]
        return None

    def _feedback(self, text: str):
        self.lbl_action_feedback.setText(text)
        QTimer.singleShot(2500, lambda: self.lbl_action_feedback.setText(""))

    def _current_dm_partner(self) -> Optional[str]:
        """Return the node ID of the current DM conversation, or None.

        The current conversation key is formatted as "dm:<node_id>" for
        direct messages and "ch:<index>" for channels. The DM action buttons
        (request position/telemetry, traceroute, open in maps) only apply to
        DM conversations.
        """
        convo = self.current_convo
        if convo and convo.startswith("dm:"):
            return convo[3:]
        return None

    def _dm_request_position(self):
        partner = self._current_dm_partner()
        if partner and self.manager.request_position(partner):
            self._feedback(t("msg.action.sent"))

    def _dm_request_telemetry(self):
        partner = self._current_dm_partner()
        if partner and self.manager.request_telemetry_with_popup(partner):
            self._feedback(t("msg.action.sent"))

    def _dm_traceroute(self):
        partner = self._current_dm_partner()
        if partner and self.manager.traceroute(partner):
            self._feedback(t("msg.action.sent"))

    def _dm_gmaps(self):
        partner = self._current_dm_partner()
        if not partner:
            return
        iface = self.manager.interface
        if not iface or not iface.nodes or partner not in iface.nodes:
            return
        pos = (iface.nodes[partner].get("position") or {})
        lat = pos.get("latitude")
        lon = pos.get("longitude")
        if lat is None and pos.get("latitudeI") is not None:
            lat = pos["latitudeI"] / 1e7
            lon = pos.get("longitudeI", 0) / 1e7
        if lat is not None and lon is not None:
            QDesktopServices.openUrl(QUrl(f"https://www.google.com/maps?q={lat},{lon}"))

    # ====================================================================
    # SEND
    # ====================================================================
    def _send_current(self):
        """Send whatever's in the input box on the active conversation.

        V20-turn7: this no longer renders the bubble or writes to the DB
        directly — the manager emits messageSent on a successful send and
        _on_message_sent does all of that. Without this unification,
        script-sent messages bypassed the UI and vanished from history.
        """
        if not self.current_convo:
            return
        text = self.input.toPlainText().strip()
        if not text:
            return

        ch_idx = 0
        dest = None
        if self.current_convo.startswith("ch:"):
            ch_idx = int(self.current_convo.split(":", 1)[1])
        elif self.current_convo.startswith("dm:"):
            dest = self.current_convo.split(":", 1)[1]

        # Reply threading: if a reply is staged, pass replyId to the device.
        reply_id = None
        if self._pending_reply:
            reply_id = self._pending_reply.get("packet_id")

        log.info(f"[CHAT-SEND] convo={self.current_convo} ch={ch_idx} dest={dest} "
                 f"reply_id={reply_id} text={text[:80]!r}")
        result = self.manager.send_text(
            text, channel_index=ch_idx,
            destination_id=dest, reply_id=reply_id)
        # On success the manager fires messageSent → _on_message_sent
        # handles the convo append, persistence, bubble render. Here we
        # only need the input-box cleanup.
        if result:
            self.input.clear()
            if reply_id:
                self._cancel_reply()

    @Slot(dict)
    def _on_message_sent(self, msg: dict):
        """The manager just sent a text message — render it locally.

        Triggered for every outbound message regardless of source:
          • Messages-tab input (_send_current above)
          • Scripts/automation (ScriptAPI.send_text → manager.send_text)
          • Console sendtext / send commands
          • Reply buttons on incoming bubbles

        Resolves the convo from to_id + channel, persists if history is on,
        and renders a bubble only when the user is currently viewing that
        conversation (otherwise it'll appear when they switch to it).
        """
        try:
            to_id = msg.get("toId") or "^all"
            channel = int(msg.get("channel") or 0)
            text = msg.get("text") or ""
            if not text:
                return

            # Build a complete message dict so the bubble renderer has
            # everything it needs (isMe, sender, packetId, ackStatus, etc.)
            full = {
                "text":      text,
                "fromId":    msg.get("fromId") or self.manager.my_node_id or "",
                "toId":      to_id,
                "channel":   channel,
                "rxTime":    int(msg.get("rxTime") or time.time()),
                "isMe":      True,
                "sender":    msg.get("fromId") or self.manager.my_node_id or "",
                "packetId":  msg.get("packetId"),
                "replyId":   msg.get("replyId"),
                "ackStatus": msg.get("ackStatus") or "sent",
            }

            # Resolve target conversation
            if to_id in ("^all", "!ffffffff", ""):
                convo_id = f"ch:{channel}"
            else:
                convo_id = f"dm:{to_id}"

            # Append to in-memory conversation list (creates if missing)
            self.conversations.setdefault(convo_id, []).append(full)

            # Persist to history DB (skip if user turned that off)
            try:
                if Settings.get().save_history:
                    MessageDB.get().add_message(
                        from_id=full["fromId"], to_id=full["toId"],
                        channel=channel, text=text,
                        rx_time=full["rxTime"], is_me=True,
                        packet_id=full["packetId"],
                        reply_id=full["replyId"],
                    )
            except Exception:
                log.exception("Error saving sent message to DB")

            # Render the bubble immediately ONLY if the user is currently
            # viewing this conversation. Otherwise the bubble will be drawn
            # when they switch — _load_messages_for_convo iterates the
            # same self.conversations list.
            if self.current_convo == convo_id:
                self._append_bubble(full, is_me=True)
                self._scroll_to_bottom()

            # Keep the left-side conversation list counts/preview fresh
            try:
                self._rebuild_convo_list()
            except Exception:
                log.exception("convo list rebuild failed")

            log.info(f"[CHAT-RX-SELF] convo={convo_id} ch={channel} "
                     f"dest={to_id} packet_id={full.get('packetId')} "
                     f"len={len(text)}")
        except Exception:
            log.exception("_on_message_sent crashed")

    # ====================================================================
    # HISTORY: MERGE in loc de OVERWRITE
    # ====================================================================
    def _load_history_from_db(self):
        if self._history_loaded:
            return
        log.info("Loading message history from DB…")
        my_id = self.manager.my_node_id or ""

        loaded_count = 0
        # channels
        for ch in self.channels:
            ch_id = f"ch:{ch['index']}"
            try:
                rows = MessageDB.get().get_channel_messages(ch['index'], limit=200)
                db_msgs = [
                    {
                        "fromId": r["from_id"], "toId": r["to_id"],
                        "channel": r["channel"], "text": r["text"],
                        "rxTime": r["rx_time"], "isMe": bool(r["is_me"]),
                        "sender": r["from_id"],
                        "packetId":  r.get("packet_id"),
                        "replyId":   r.get("reply_id"),
                        "reactions": r.get("reactions") or {},
                    }
                    for r in rows
                ]
                self.conversations[ch_id] = self._merge_msgs(
                    db_msgs, self.conversations.get(ch_id, []))
                loaded_count += len(db_msgs)
            except Exception:
                log.exception(f"Error loading channel history {ch}")

        # DM-uri
        if my_id:
            try:
                partners = MessageDB.get().get_dm_partners(my_id)
                for p in partners:
                    rows = MessageDB.get().get_dm_messages(my_id, p, limit=200)
                    if rows:
                        db_msgs = [
                            {
                                "fromId": r["from_id"], "toId": r["to_id"],
                                "channel": r["channel"], "text": r["text"],
                                "rxTime": r["rx_time"], "isMe": bool(r["is_me"]),
                                "sender": r["from_id"],
                                "packetId":  r.get("packet_id"),
                                "replyId":   r.get("reply_id"),
                                "reactions": r.get("reactions") or {},
                            }
                            for r in rows
                        ]
                        cid = f"dm:{p}"
                        self.conversations[cid] = self._merge_msgs(
                            db_msgs, self.conversations.get(cid, []))
                        loaded_count += len(db_msgs)
            except Exception:
                log.exception("Error loading DM history")

        log.info(f"Istoric: {loaded_count} mesaje incarcate din DB")
        self._history_loaded = True
        self._rebuild_convo_list()
        if self.current_convo:
            self._render_current_convo()

    @staticmethod
    def _merge_msgs(db_msgs: list, session_msgs: list) -> list:
        """Combina db + session ordonate dupa rxTime, fara duplicate."""
        seen = set()
        out = []
        for m in db_msgs + session_msgs:
            key = (m.get("rxTime"), m.get("fromId"), (m.get("text") or "")[:50])
            if key not in seen:
                seen.add(key)
                out.append(m)
        out.sort(key=lambda x: x.get("rxTime") or 0)
        return out

    # ====================================================================
    # RENDER
    # ====================================================================
    def _rebuild_convo_list(self):
        prev_id = self.current_convo
        self.convo_list.blockSignals(True)
        self.convo_list.clear()

        for ch in self.channels:
            # V20: _publish_channels now emits ALL slots incl. DISABLED so
            # the channel management UI can see them. Skip DISABLED here.
            if ch.get("role") == "DISABLED":
                continue
            convo_id = f"ch:{ch['index']}"
            count = len(self.conversations.get(convo_id, []))
            label = f"#  {ch['name']}"
            if count:
                label += f"   ({count})"
            sub = t("msg.primary_channel") if ch["role"] == "PRIMARY" else \
                  f"{t('msg.secondary_channel')} {ch['index']}"
            self.convo_list.addItem(self._make_list_item(convo_id, label, sub))

        dm_ids = [k for k in self.conversations.keys() if k.startswith("dm:")]
        if dm_ids:
            sep_item = QListWidgetItem(t("msg.dms_section"))
            sep_item.setFlags(Qt.NoItemFlags)
            sep_item.setForeground(Qt.gray)
            self.convo_list.addItem(sep_item)
        for cid in dm_ids:
            node_id = cid.split(":", 1)[1]
            name = self.node_names.get(node_id, node_id)
            count = len(self.conversations.get(cid, []))
            label = f"@  {name}"
            if count:
                label += f"   ({count})"
            self.convo_list.addItem(self._make_list_item(cid, label, node_id))

        if prev_id:
            for i in range(self.convo_list.count()):
                it = self.convo_list.item(i)
                if it and it.data(Qt.UserRole) == prev_id:
                    self.convo_list.setCurrentRow(i)
                    break
        self.convo_list.blockSignals(False)

    def _make_list_item(self, convo_id: str, title: str, subtitle: str) -> QListWidgetItem:
        item = QListWidgetItem()
        item.setData(Qt.UserRole, convo_id)
        item.setText(f"{title}\n{subtitle}")
        item.setSizeHint(QSize(0, 52))
        return item

    def _render_current_convo(self):
        parent = self.scroll.parentWidget()
        if parent and self.scroll.isHidden():
            layout = parent.layout()
            idx = layout.indexOf(self.empty_state)
            if idx >= 0:
                layout.replaceWidget(self.empty_state, self.scroll)
                self.empty_state.hide()
                self.scroll.show()

        if self.current_convo.startswith("ch:"):
            idx = int(self.current_convo.split(":", 1)[1])
            ch = next((c for c in self.channels if c["index"] == idx), None)
            name = ch["name"] if ch else f"Channel {idx}"
            self.convo_title.setText(f"#  {name}")
            self.convo_subtitle.setText(
                t("msg.broadcast") if idx == 0 else f"{t('msg.secondary_channel')} {idx}"
            )
        elif self.current_convo.startswith("dm:"):
            node_id = self.current_convo.split(":", 1)[1]
            name = self.node_names.get(node_id, node_id)
            self.convo_title.setText(f"@  {name}")
            self.convo_subtitle.setText(node_id)

        self._clear_bubbles()
        for msg in self.conversations.get(self.current_convo, []):
            self._append_bubble(msg, msg.get("isMe", False))
        self._scroll_to_bottom()

    def _clear_bubbles(self):
        while self.bubbles_layout.count() > 1:
            child = self.bubbles_layout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()
        # Drop the packet-id index — bubbles are gone, the dict's entries
        # would all point to dangling C++ objects.
        self._bubbles_by_packet_id.clear()

    def _append_bubble(self, msg: dict, is_me: bool):
        sender_name = ""
        from_id = msg.get("fromId") or ""
        if not is_me:
            sender_name = self.node_names.get(from_id, from_id)
        # Build reply preview by looking up the parent message in this
        # conversation by its packet_id; degrade gracefully if not found
        # (the parent may have been before history loaded).
        reply_to_pkt = msg.get("replyId")
        reply_preview = ""
        reply_to_sender = ""
        if reply_to_pkt:
            parent = self._find_msg_by_packet_id(int(reply_to_pkt))
            if parent:
                reply_preview = parent.get("text") or ""
                p_from = parent.get("fromId") or ""
                reply_to_sender = (
                    "You" if parent.get("isMe")
                    else (self.node_names.get(p_from) or p_from))
            else:
                reply_preview = f"(message #{reply_to_pkt})"
        bubble = MessageBubble(
            text=msg.get("text", ""),
            is_me=is_me, sender_name=sender_name,
            timestamp=msg.get("rxTime"),
            from_id=from_id,
            packet_id=msg.get("packetId") or msg.get("id"),
            status=msg.get("ackStatus", "sent" if is_me else ""),
            snr=msg.get("rxSnr"),
            rssi=msg.get("rxRssi"),
            hop_start=msg.get("hopStart"),
            hop_limit=msg.get("hopLimit"),
            reply_preview=reply_preview,
            reply_to_sender=reply_to_sender,
        )
        # Restore reactions if present in the stored message
        rxn = msg.get("reactions") or {}
        if rxn:
            bubble.set_reactions(rxn)
        # Wire right-click context menu signals
        bubble.requestCopy.connect(self._on_bubble_copy)
        bubble.requestDM.connect(self._on_bubble_dm)
        bubble.requestDetails.connect(self._on_bubble_details)
        bubble.requestReply.connect(self._on_bubble_reply)
        bubble.requestReact.connect(self._on_bubble_react)
        bubble.requestSignalReport.connect(
            lambda txt, info, _from=from_id:
                self._on_bubble_signal_report(txt, info, _from))
        # Left-click on OUR bubbles → open delivery status dialog
        if is_me:
            bubble.clicked.connect(
                lambda pkt=msg.get("packetId"): self._on_bubble_clicked(pkt))
        # Track sent bubbles by packet_id so we can update status on ACK
        if is_me and bubble.packet_id:
            self._sent_bubbles[bubble.packet_id] = bubble
            # Cap the dict size — keep most recent 200
            if len(self._sent_bubbles) > 200:
                # Drop oldest (lowest IDs are usually oldest)
                drop_keys = sorted(self._sent_bubbles.keys())[:-200]
                for k in drop_keys:
                    self._sent_bubbles.pop(k, None)
        # Track ALL bubbles by packet_id for reaction lookup
        if bubble.packet_id:
            self._bubbles_by_packet_id[int(bubble.packet_id)] = bubble
        self.bubbles_layout.insertWidget(self.bubbles_layout.count() - 1, bubble)

    def _find_msg_by_packet_id(self, packet_id: int) -> Optional[dict]:
        """Scan the current conversation for the message with packet_id."""
        if not self.current_convo:
            return None
        for m in self.conversations.get(self.current_convo, []):
            pid = m.get("packetId") or m.get("id")
            try:
                if pid and int(pid) == int(packet_id):
                    return m
            except Exception:
                continue
        return None

    # ---- Right-click context menu handlers ---------------------------------
    def _on_bubble_copy(self, text: str):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)
        log.info(f"Copied {len(text)} chars to clipboard")

    def _on_bubble_dm(self, from_id: str):
        """Switch to (or start) a DM conversation with this sender."""
        if not from_id:
            return
        log.info(f"Starting DM with {from_id}")
        # Notify listeners (e.g. main_window could focus this tab)
        try:
            self.requestStartDM.emit(from_id)
        except Exception:
            log.exception("requestStartDM emit failed")
        # Ensure the DM convo exists, then switch to it. If we already
        # have messages with this node, _rebuild_convo_list will pick it
        # up; otherwise we create an empty entry first.
        convo_id = f"dm:{from_id}"
        self.conversations.setdefault(convo_id, [])
        self._switch_to_convo(convo_id)

    def _on_bubble_details(self, node_id: str):
        """Open node details popup for the sender of this message."""
        if not node_id:
            return
        try:
            from ..dialogs.node_details_dialog import NodeDetailsDialog
            iface = self.manager.interface
            node = (iface.nodes or {}).get(node_id, {}) if iface else {}
            dlg = NodeDetailsDialog(node_id, node, self.window())
            dlg.setAttribute(Qt.WA_DeleteOnClose, True)
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
        except Exception:
            log.exception("Could not open node details from bubble")

    def _on_bubble_clicked(self, packet_id):
        """Left-click on a sent bubble → open delivery status dialog showing
        which nodes acknowledged / relayed the message."""
        if not packet_id:
            packet_id = None
        try:
            status = self.manager.get_message_status(packet_id) if packet_id else None
            from ..dialogs.message_status_dialog import MessageStatusDialog
            dlg = MessageStatusDialog(status, self.manager, self.window())
            dlg.setAttribute(Qt.WA_DeleteOnClose, True)
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
        except Exception:
            log.exception("Could not open message status dialog")

    def _on_bubble_signal_report(self, original_text: str, info: dict,
                                  from_id: str):
        """Open the Signal Report dialog with quality + hops info.

        On user confirmation, sends the reply back as a DM to the sender.
        """
        try:
            sender_name = self.node_names.get(from_id, from_id) or "node"
            from ..dialogs.signal_report_dialog import SignalReportDialog
            dlg = SignalReportDialog(original_text, sender_name, info,
                                     self.window())

            def _do_send(text: str):
                # Send back as a DM to the original sender (so they get it
                # privately rather than spamming the channel).
                # V20-turn7: bubble + persistence happen via the manager's
                # messageSent signal — no manual append needed here.
                if not from_id:
                    return
                result = self.manager.send_text(
                    text, channel_index=0, destination_id=from_id
                )
                if result:
                    # Switch view to that DM conversation so user sees it
                    convo_id = f"dm:{from_id}"
                    self._switch_to_convo(convo_id)
                    log.info(f"Signal report sent to {from_id}: {text!r}")

            dlg.sendRequested.connect(_do_send)
            dlg.setAttribute(Qt.WA_DeleteOnClose, True)
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
        except Exception:
            log.exception("Could not open signal report dialog")

    # ====================================================================
    # REPLIES + REACTIONS
    # ====================================================================
    def _on_bubble_reply(self, packet_id: int, sender: str, preview: str):
        """User clicked 'Reply' on a bubble → stage the reply.

        We just remember the parent packet_id; the actual replyId will be
        attached on the next send_text() call.
        """
        if not packet_id:
            return
        self._pending_reply = {
            "packet_id": int(packet_id),
            "sender":    sender or "?",
            "preview":   preview or "",
        }
        prev = preview if len(preview) <= 80 else preview[:77] + "…"
        self.lbl_reply_to.setText(f"↩  {sender}")
        self.lbl_reply_preview.setText(prev)
        self.reply_banner.setVisible(True)
        # Focus the input so the user can start typing immediately
        self.input.setFocus()

    def _cancel_reply(self):
        self._pending_reply = None
        self.reply_banner.setVisible(False)

    def _on_bubble_react(self, packet_id: int, sender: str):
        """User picked 'React with emoji…' → open emoji picker, send reaction."""
        if not packet_id:
            return
        try:
            from ..dialogs.emoji_picker import EmojiPicker
            picker = EmojiPicker(self.window())

            def _do_send(emoji: str):
                self._send_reaction_for(int(packet_id), emoji)

            picker.emojiPicked.connect(_do_send)
            picker.adjustSize()
            # Center on the main window
            geo = self.window().geometry()
            picker.move(
                geo.x() + (geo.width()  - picker.width())  // 2,
                geo.y() + (geo.height() - picker.height()) // 2,
            )
            picker.show()
            picker.raise_()
            picker.activateWindow()
        except Exception:
            log.exception("Could not open emoji picker for reaction")

    def _send_reaction_for(self, packet_id: int, emoji: str):
        """Actually send a reaction on packet_id with emoji, then echo it
        locally so the user sees their own chip immediately.
        """
        if not emoji or not packet_id:
            return
        # Determine channel + destination from the current convo
        ch_idx = 0
        dest = None
        if self.current_convo and self.current_convo.startswith("ch:"):
            ch_idx = int(self.current_convo.split(":", 1)[1])
        elif self.current_convo and self.current_convo.startswith("dm:"):
            dest = self.current_convo.split(":", 1)[1]
        ok = self.manager.send_reaction(
            emoji=emoji, reply_id=packet_id,
            channel_index=ch_idx, destination_id=dest)
        if ok:
            # Optimistic local echo on the bubble + persisted state
            my_id = self.manager.my_node_id or "me"
            bubble = self._bubbles_by_packet_id.get(int(packet_id))
            if bubble:
                bubble.add_reaction(emoji, my_id)
            parent = self._find_msg_by_packet_id(int(packet_id))
            if parent is not None:
                rxn = parent.setdefault("reactions", {})
                lst = rxn.setdefault(emoji, [])
                if my_id not in lst:
                    lst.append(my_id)
                if Settings.get().save_history:
                    try:
                        MessageDB.get().update_reactions(
                            int(packet_id), parent.get("reactions") or {})
                    except Exception:
                        log.exception("update_reactions failed")

    @Slot(dict)
    def _on_reaction_received(self, reaction: dict):
        """Incoming EMOJI_APP packet — apply it to the matching bubble."""
        try:
            pkt_id = int(reaction.get("replyId") or 0)
        except Exception:
            pkt_id = 0
        emoji = reaction.get("emoji") or ""
        from_id = reaction.get("fromId") or ""
        if not pkt_id or not emoji:
            return
        # Update the rendered bubble (if any) immediately
        bubble = self._bubbles_by_packet_id.get(pkt_id)
        if bubble:
            bubble.add_reaction(emoji, from_id)
        # And persist to the message dict + DB so it survives a reload
        for msgs in self.conversations.values():
            for m in msgs:
                p = m.get("packetId") or m.get("id")
                if p and int(p) == pkt_id:
                    rxn = m.setdefault("reactions", {})
                    lst = rxn.setdefault(emoji, [])
                    if from_id and from_id not in lst:
                        lst.append(from_id)
                    if Settings.get().save_history:
                        try:
                            MessageDB.get().update_reactions(
                                pkt_id, m.get("reactions") or {})
                        except Exception:
                            log.exception("update_reactions failed")
                    return

    def _switch_to_convo(self, convo_id: str):
        """Programmatically switch to a conversation by ID."""
        try:
            self._rebuild_convo_list()
            for i in range(self.convo_list.count()):
                item = self.convo_list.item(i)
                if item.data(Qt.UserRole) == convo_id:
                    self.convo_list.setCurrentItem(item)
                    return
        except Exception:
            log.exception("Could not switch to convo")

    def _scroll_to_bottom(self):
        bar = self.scroll.verticalScrollBar()
        QTimer.singleShot(30, lambda: bar.setValue(bar.maximum()))

    def _show_empty(self):
        parent = self.empty_state.parentWidget()
        if parent and self.empty_state.isHidden():
            layout = parent.layout()
            idx = layout.indexOf(self.scroll)
            if idx >= 0:
                layout.replaceWidget(self.scroll, self.empty_state)
                self.scroll.hide()
                self.empty_state.show()

    def _set_input_enabled(self, enabled: bool):
        self.input.setEnabled(enabled)
        self.send_btn.setEnabled(enabled)
        self.btn_emoji.setEnabled(enabled)

    def _open_emoji_picker(self):
        """Open the emoji popup positioned just above the emoji button."""
        from ..dialogs.emoji_picker import EmojiPicker
        picker = EmojiPicker(self.window())
        picker.emojiPicked.connect(self._insert_emoji)
        # Force size BEFORE position calculation
        picker.adjustSize()
        btn_pos = self.btn_emoji.mapToGlobal(self.btn_emoji.rect().topLeft())
        x = max(20, btn_pos.x())
        y = max(20, btn_pos.y() - picker.height() - 6)
        picker.move(x, y)
        picker.show()
        picker.raise_()
        picker.activateWindow()

    def _insert_emoji(self, emoji: str):
        """Insert emoji at the current cursor position of the message input."""
        cursor = self.input.textCursor()
        cursor.insertText(emoji)
        self.input.setFocus()
