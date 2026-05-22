"""
Games page (V0.44) — Tic-Tac-Toe over the mesh.

A tiny, fun, bandwidth-friendly two-player game. Each move is a single short
DM (e.g. "MLTTT:M4" = I played cell 4), so a whole game costs only a handful
of tiny packets. Perfect for testing connectivity between two nodes in a way
anyone understands.

Protocol (all sent as DMs to the opponent, prefix MLTTT:):
  MLTTT:NEW       — I want to start a new game; I am X, you are O
  MLTTT:M<0-8>    — I played this cell (0..8, left→right, top→bottom)
  MLTTT:RESET     — clear the board

Bandwidth: ~8 bytes per move. A full game ≈ 5–9 tiny messages.
"""

from __future__ import annotations

import logging
from typing import Optional, List

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QComboBox, QGridLayout, QSizePolicy
)

from ..connection import MeshtasticManager
from ..theme import Colors

log = logging.getLogger("meshlink.games")

PREFIX = "MLTTT:"
WIN_LINES = [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]


class GamesPage(QWidget):

    def __init__(self, manager: MeshtasticManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self._opponent: Optional[str] = None
        self._my_mark = "X"      # I'm X if I start, O if invited
        self._their_mark = "O"
        self._turn = "X"          # whose turn it is
        self._board: List[str] = [""] * 9
        self._game_over = False
        self._build_ui()
        self.manager.textMessageReceived.connect(self._on_text)
        self.manager.stateChanged.connect(lambda *_: self._refresh_opponents())
        self._refresh_opponents()

    # ------------------------------------------------------------- UI
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 20)
        root.setSpacing(12)

        title = QLabel("🎮  Tic-Tac-Toe over the mesh")
        title.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; font-size: 16px; font-weight: 700;")
        root.addWidget(title)

        intro = QLabel(
            "A friendly two-player game that uses almost no bandwidth — each "
            "move is one tiny message. Pick an opponent node, start a game, "
            "and take turns. Great fun way to confirm a solid link with "
            "another operator!")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 12px;")
        root.addWidget(intro)

        # Opponent picker + controls
        ctrl = QFrame(); ctrl.setObjectName("Card")
        cl = QHBoxLayout(ctrl); cl.setContentsMargins(14, 10, 14, 10); cl.setSpacing(10)
        cl.addWidget(QLabel("Opponent:"))
        self.cmb_opponent = QComboBox()
        self.cmb_opponent.setMinimumWidth(220)
        cl.addWidget(self.cmb_opponent, 1)
        self.btn_new = QPushButton("▶  New game")
        self.btn_new.setObjectName("PrimaryButton")
        self.btn_new.clicked.connect(self._start_new_game)
        cl.addWidget(self.btn_new)
        self.btn_reset = QPushButton("↺  Reset")
        self.btn_reset.clicked.connect(self._reset_game)
        cl.addWidget(self.btn_reset)
        root.addWidget(ctrl)

        # Status
        self.lbl_status = QLabel("Pick an opponent and press New game.")
        self.lbl_status.setStyleSheet(
            f"color: {Colors.PRIMARY}; font-size: 13px; font-weight: 600; "
            f"padding: 4px 0;")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        root.addWidget(self.lbl_status)

        # Board 3x3
        board_wrap = QHBoxLayout()
        board_wrap.addStretch(1)
        board_frame = QFrame()
        board_frame.setObjectName("Card")
        bg = QGridLayout(board_frame)
        bg.setContentsMargins(12, 12, 12, 12)
        bg.setSpacing(6)
        self.cells: List[QPushButton] = []
        for i in range(9):
            b = QPushButton("")
            b.setFixedSize(90, 90)
            b.setStyleSheet(self._cell_style())
            b.clicked.connect(lambda _=False, idx=i: self._play(idx))
            self.cells.append(b)
            bg.addWidget(b, i // 3, i % 3)
        board_wrap.addWidget(board_frame)
        board_wrap.addStretch(1)
        root.addLayout(board_wrap)
        root.addStretch(1)
        self._update_board_ui()

    def _cell_style(self, win=False):
        bg = Colors.SUCCESS if win else Colors.BG_INPUT
        fg = Colors.BG_BASE if win else Colors.TEXT_PRIMARY
        return (f"QPushButton {{ background: {bg}; color: {fg}; "
                f"border: 1px solid {Colors.BORDER}; border-radius: 10px; "
                f"font-size: 38px; font-weight: 700; }} "
                f"QPushButton:hover {{ background: {Colors.BORDER_HI}; }} "
                f"QPushButton:disabled {{ color: {fg}; }}")

    # ------------------------------------------------------- opponents
    def _refresh_opponents(self):
        cur = self.cmb_opponent.currentData()
        self.cmb_opponent.clear()
        try:
            nodes = getattr(self.manager.interface, "nodes", {}) or {}
        except Exception:
            nodes = {}
        my = self.manager.my_node_id
        for nid, info in nodes.items():
            if nid == my:
                continue
            user = info.get("user", {}) if isinstance(info, dict) else {}
            name = user.get("longName") or user.get("shortName") or nid
            self.cmb_opponent.addItem(f"{name}  ({nid})", nid)
        if cur:
            idx = self.cmb_opponent.findData(cur)
            if idx >= 0:
                self.cmb_opponent.setCurrentIndex(idx)
        self.btn_new.setEnabled(self.manager.is_connected
                                and self.cmb_opponent.count() > 0)

    # ----------------------------------------------------------- send
    def _send(self, payload: str):
        if not self._opponent:
            return
        try:
            self.manager.send_text(PREFIX + payload, destination_id=self._opponent)
        except Exception:
            log.exception("game send failed")

    def _start_new_game(self):
        nid = self.cmb_opponent.currentData()
        if not nid:
            return
        self._opponent = nid
        self._my_mark = "X"      # initiator is X and moves first
        self._their_mark = "O"
        self._turn = "X"
        self._board = [""] * 9
        self._game_over = False
        self._send("NEW")
        self._update_board_ui()
        self.lbl_status.setText("New game! You are ✗ — your move.")

    def _reset_game(self):
        self._board = [""] * 9
        self._game_over = False
        self._turn = "X"
        self._send("RESET")
        self._update_board_ui()
        self.lbl_status.setText("Board reset.")

    def _play(self, idx: int):
        if self._game_over or not self._opponent:
            return
        if self._board[idx]:
            return
        if self._turn != self._my_mark:
            self.lbl_status.setText("Not your turn — waiting for opponent.")
            return
        self._board[idx] = self._my_mark
        self._send(f"M{idx}")
        self._turn = self._their_mark
        self._post_move()

    # -------------------------------------------------------- receive
    @Slot(dict)
    def _on_text(self, msg: dict):
        text = (msg.get("text") or "")
        if not text.startswith(PREFIX):
            return
        from_id = msg.get("fromId")
        payload = text[len(PREFIX):]

        # Auto-bind opponent if we get a NEW from someone
        if payload == "NEW":
            self._opponent = from_id
            self._my_mark = "O"      # invitee is O
            self._their_mark = "X"
            self._turn = "X"          # X (the inviter) moves first
            self._board = [""] * 9
            self._game_over = False
            # select them in the dropdown if present
            idx = self.cmb_opponent.findData(from_id)
            if idx >= 0:
                self.cmb_opponent.setCurrentIndex(idx)
            self._update_board_ui()
            self.lbl_status.setText(
                f"{self._name(from_id)} invited you! You are ◯ — their move first.")
            return

        # Only accept moves from our current opponent
        if from_id != self._opponent:
            return

        if payload == "RESET":
            self._board = [""] * 9
            self._game_over = False
            self._turn = "X"
            self._update_board_ui()
            self.lbl_status.setText("Opponent reset the board.")
            return

        if payload.startswith("M"):
            try:
                cell = int(payload[1:])
            except ValueError:
                return
            if 0 <= cell <= 8 and not self._board[cell]:
                self._board[cell] = self._their_mark
                self._turn = self._my_mark
                self._post_move(opponent_moved=True)

    # ---------------------------------------------------------- logic
    def _post_move(self, opponent_moved=False):
        winner = self._winner()
        self._update_board_ui()
        if winner:
            self._game_over = True
            if winner == "draw":
                self.lbl_status.setText("It's a draw! 🤝")
            elif winner == self._my_mark:
                self.lbl_status.setText("You win! 🎉")
            else:
                self.lbl_status.setText("You lost — better luck next time!")
            return
        if self._turn == self._my_mark:
            self.lbl_status.setText("Your move.")
        else:
            self.lbl_status.setText(f"Waiting for {self._name(self._opponent)}…")

    def _winner(self) -> Optional[str]:
        for a, b, c in WIN_LINES:
            if self._board[a] and self._board[a] == self._board[b] == self._board[c]:
                self._win_line = (a, b, c)
                return self._board[a]
        if all(self._board):
            return "draw"
        return None

    def _update_board_ui(self):
        win_cells = set()
        w = self._winner()
        if w and w != "draw" and hasattr(self, "_win_line"):
            win_cells = set(self._win_line)
        for i, b in enumerate(self.cells):
            mark = self._board[i]
            b.setText("✗" if mark == "X" else ("◯" if mark == "O" else ""))
            b.setStyleSheet(self._cell_style(win=(i in win_cells)))
            # enabled only if: game active, my turn, empty cell, have opponent
            b.setEnabled(bool(self._opponent) and not self._game_over
                         and not mark and self._turn == self._my_mark)

    def _name(self, nid: Optional[str]) -> str:
        if not nid:
            return "opponent"
        try:
            nodes = getattr(self.manager.interface, "nodes", {}) or {}
            user = nodes.get(nid, {}).get("user", {})
            return user.get("longName") or user.get("shortName") or nid
        except Exception:
            return nid
