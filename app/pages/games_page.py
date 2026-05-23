"""
Games page (V0.45) — five tiny two-player games over the mesh.

Pick a game from the dropdown and an opponent node, then play. Every move is
one short DM ("MLGAME:<code>:<payload>"), so a whole game costs only a handful
of tiny packets. A fun, bandwidth-friendly way to confirm a solid link with
another operator.

Games: Tic-Tac-Toe, Connect 4, Rock-Paper-Scissors, Battleship, Nim (21).

The page is a thin shell over the engines in app/game_engines.py — it handles
the dropdowns, networking and a per-game board renderer; the engines hold all
the rules.
"""

from __future__ import annotations

import logging
from typing import Optional, List

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QComboBox, QGridLayout
)

from ..connection import MeshtasticManager
from ..theme import Colors
from ..game_engines import GAME_CLASSES, GAME_BY_CODE

log = logging.getLogger("meshlink.games")

PREFIX = "MLGAME:"   # wire prefix; format MLGAME:<code>:<payload>


class GamesPage(QWidget):

    def __init__(self, manager: MeshtasticManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.engine = None
        self._opponent: Optional[str] = None
        self._build_ui()
        self.manager.textMessageReceived.connect(self._on_text)
        self.manager.stateChanged.connect(lambda *_: self._refresh_opponents())
        self._refresh_opponents()

    # ------------------------------------------------------------- UI
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 20)
        root.setSpacing(12)

        title = QLabel("🎮  Mesh Games")
        title.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; font-size: 16px; font-weight: 700;")
        root.addWidget(title)

        intro = QLabel(
            "Two-player games that use almost no bandwidth — each move is one "
            "tiny message. Pick a game and an opponent node, then play. A fun "
            "way to confirm a solid link with another operator!")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 12px;")
        root.addWidget(intro)

        # Controls: game + opponent + new/reset
        ctrl = QFrame(); ctrl.setObjectName("Card")
        cl = QHBoxLayout(ctrl); cl.setContentsMargins(14, 10, 14, 10); cl.setSpacing(10)
        cl.addWidget(QLabel("Game:"))
        self.cmb_game = QComboBox()
        for g in GAME_CLASSES:
            self.cmb_game.addItem(g.name, g.code)
        self.cmb_game.currentIndexChanged.connect(self._on_game_changed)
        cl.addWidget(self.cmb_game)
        cl.addWidget(QLabel("Opponent:"))
        self.cmb_opponent = QComboBox()
        self.cmb_opponent.setMinimumWidth(180)
        cl.addWidget(self.cmb_opponent, 1)
        self.btn_new = QPushButton("▶  New game")
        self.btn_new.setObjectName("PrimaryButton")
        self.btn_new.clicked.connect(self._start_new_game)
        cl.addWidget(self.btn_new)
        self.btn_reset = QPushButton("↺")
        self.btn_reset.setToolTip("Reset the board")
        self.btn_reset.setFixedWidth(40)
        self.btn_reset.clicked.connect(self._reset_game)
        cl.addWidget(self.btn_reset)
        root.addWidget(ctrl)

        # Status
        self.lbl_status = QLabel("Pick a game and opponent, then press New game.")
        self.lbl_status.setStyleSheet(
            f"color: {Colors.PRIMARY}; font-size: 13px; font-weight: 600; "
            f"padding: 4px 0;")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setWordWrap(True)
        root.addWidget(self.lbl_status)

        # Board host (rebuilt per game)
        self.board_host = QWidget()
        self.board_layout = QVBoxLayout(self.board_host)
        self.board_layout.setContentsMargins(0, 0, 0, 0)
        self.board_layout.setAlignment(Qt.AlignCenter)
        root.addWidget(self.board_host, 1)

        self._build_board_for_current_game()

    def _clear_board(self):
        while self.board_layout.count():
            it = self.board_layout.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
            elif it.layout():
                self._clear_layout(it.layout())

    def _clear_layout(self, lay):
        while lay.count():
            it = lay.takeAt(0)
            w = it.widget()
            if w: w.deleteLater()
            elif it.layout(): self._clear_layout(it.layout())

    def _current_code(self) -> str:
        return self.cmb_game.currentData()

    # ---- board builders (one per game) ----
    def _build_board_for_current_game(self):
        self._clear_board()
        code = self._current_code()
        if code == "TTT":
            self._build_grid_board(3, 3, cell_px=90, font_px=38)
        elif code == "C4":
            self._build_connect4_board()
        elif code == "RPS":
            self._build_rps_board()
        elif code == "BS":
            self._build_battleship_board()
        elif code == "NIM":
            self._build_nim_board()

    def _build_grid_board(self, rows, cols, cell_px=70, font_px=28):
        frame = QFrame(); frame.setObjectName("Card")
        g = QGridLayout(frame); g.setContentsMargins(12,12,12,12); g.setSpacing(6)
        self.cells: List[QPushButton] = []
        for i in range(rows*cols):
            b = QPushButton("")
            b.setFixedSize(cell_px, cell_px)
            b.setStyleSheet(self._cell_style(font_px))
            b.clicked.connect(lambda _=False, idx=i: self._cell_clicked(idx))
            self.cells.append(b)
            g.addWidget(b, i//cols, i%cols)
        self.board_layout.addWidget(frame)

    def _build_connect4_board(self):
        frame = QFrame(); frame.setObjectName("Card")
        outer = QVBoxLayout(frame); outer.setContentsMargins(12,12,12,12); outer.setSpacing(6)
        # drop buttons row
        drop_row = QHBoxLayout(); drop_row.setSpacing(6)
        self.drop_btns = []
        for c in range(7):
            db = QPushButton("▼"); db.setFixedSize(54,30)
            db.setStyleSheet(self._cell_style(16))
            db.clicked.connect(lambda _=False, col=c: self._cell_clicked(col))
            self.drop_btns.append(db)
            drop_row.addWidget(db)
        outer.addLayout(drop_row)
        g = QGridLayout(); g.setSpacing(6)
        self.c4_cells = {}
        for r in range(6):
            for c in range(7):
                lbl = QLabel(""); lbl.setFixedSize(54,54); lbl.setAlignment(Qt.AlignCenter)
                lbl.setStyleSheet(
                    f"background:{Colors.BG_INPUT}; border-radius:27px; "
                    f"border:1px solid {Colors.BORDER}; font-size:28px;")
                self.c4_cells[(c, 5-r)] = lbl   # row 0 = bottom
                g.addWidget(lbl, r, c)
        outer.addLayout(g)
        self.board_layout.addWidget(frame)

    def _build_rps_board(self):
        frame = QFrame(); frame.setObjectName("Card")
        v = QVBoxLayout(frame); v.setContentsMargins(20,20,20,20); v.setSpacing(16)
        row = QHBoxLayout(); row.setSpacing(16)
        self.rps_btns = {}
        for choice, emoji in (("rock","🪨"),("paper","📄"),("scissors","✂️")):
            b = QPushButton(f"{emoji}\n{choice.title()}")
            b.setFixedSize(110, 110)
            b.setStyleSheet(self._cell_style(30))
            b.clicked.connect(lambda _=False, ch=choice: self._cell_clicked(ch))
            self.rps_btns[choice] = b
            row.addWidget(b)
        v.addLayout(row)
        self.board_layout.addWidget(frame)

    def _build_battleship_board(self):
        frame = QFrame(); frame.setObjectName("Card")
        outer = QHBoxLayout(frame); outer.setContentsMargins(12,12,12,12); outer.setSpacing(24)
        # My grid (ships + incoming hits)
        my_col = QVBoxLayout(); my_col.setSpacing(4)
        my_col.addWidget(self._mini_label("YOUR FLEET"))
        myg = QGridLayout(); myg.setSpacing(4)
        self.bs_my_cells = []
        for i in range(25):
            lbl = QLabel(""); lbl.setFixedSize(40,40); lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet(self._bs_cell_css())
            self.bs_my_cells.append(lbl); myg.addWidget(lbl, i//5, i%5)
        my_col.addLayout(myg)
        outer.addLayout(my_col)
        # Enemy grid (my shots) — clickable
        en_col = QVBoxLayout(); en_col.setSpacing(4)
        en_col.addWidget(self._mini_label("ENEMY WATERS (fire here)"))
        eng = QGridLayout(); eng.setSpacing(4)
        self.bs_enemy_cells = []
        for i in range(25):
            b = QPushButton(""); b.setFixedSize(40,40)
            b.setStyleSheet(self._bs_cell_css(btn=True))
            b.clicked.connect(lambda _=False, idx=i: self._cell_clicked(idx))
            self.bs_enemy_cells.append(b); eng.addWidget(b, i//5, i%5)
        en_col.addLayout(eng)
        outer.addLayout(en_col)
        self.board_layout.addWidget(frame)
        # ready button for placement phase
        self.bs_ready_btn = QPushButton("✓  Ready (ships placed)")
        self.bs_ready_btn.setObjectName("PrimaryButton")
        self.bs_ready_btn.clicked.connect(self._bs_ready)
        self.board_layout.addWidget(self.bs_ready_btn)

    def _build_nim_board(self):
        frame = QFrame(); frame.setObjectName("Card")
        v = QVBoxLayout(frame); v.setContentsMargins(20,20,20,20); v.setSpacing(16)
        self.nim_sticks_lbl = QLabel("🪵 " * 21)
        self.nim_sticks_lbl.setWordWrap(True)
        self.nim_sticks_lbl.setStyleSheet("font-size:24px;")
        self.nim_sticks_lbl.setAlignment(Qt.AlignCenter)
        v.addWidget(self.nim_sticks_lbl)
        row = QHBoxLayout(); row.setSpacing(12)
        self.nim_btns = []
        for take in (1,2,3):
            b = QPushButton(f"Take {take}")
            b.setFixedSize(100,48); b.setStyleSheet(self._cell_style(16))
            b.clicked.connect(lambda _=False, t=take: self._cell_clicked(t))
            self.nim_btns.append(b); row.addWidget(b)
        v.addLayout(row)
        self.board_layout.addWidget(frame)

    # ---- styling helpers ----
    def _cell_style(self, font_px=28, win=False):
        bg = Colors.SUCCESS if win else Colors.BG_INPUT
        fg = Colors.BG_BASE if win else Colors.TEXT_PRIMARY
        return (f"QPushButton {{ background:{bg}; color:{fg}; "
                f"border:1px solid {Colors.BORDER}; border-radius:10px; "
                f"font-size:{font_px}px; font-weight:700; }} "
                f"QPushButton:hover:enabled {{ background:{Colors.BORDER_HI}; }} "
                f"QPushButton:disabled {{ color:{fg}; }}")

    def _bs_cell_css(self, btn=False, state=""):
        base = (f"background:{Colors.BG_INPUT}; border:1px solid {Colors.BORDER}; "
                f"border-radius:6px; font-size:18px;")
        if btn:
            return (f"QPushButton {{ {base} }} "
                    f"QPushButton:hover:enabled {{ background:{Colors.BORDER_HI}; }}")
        return base

    def _mini_label(self, text):
        l = QLabel(text)
        l.setStyleSheet(f"color:{Colors.TEXT_DIM}; font-size:10px; font-weight:700;")
        return l

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
            if nid == my: continue
            user = info.get("user", {}) if isinstance(info, dict) else {}
            name = user.get("longName") or user.get("shortName") or nid
            self.cmb_opponent.addItem(f"{name}  ({nid})", nid)
        if cur:
            idx = self.cmb_opponent.findData(cur)
            if idx >= 0: self.cmb_opponent.setCurrentIndex(idx)
        self.btn_new.setEnabled(self.manager.is_connected
                                and self.cmb_opponent.count() > 0)

    def _on_game_changed(self):
        self.engine = None
        self._build_board_for_current_game()
        self.lbl_status.setText(
            f"{self.cmb_game.currentText()} selected. Pick an opponent and "
            f"press New game.")

    # ----------------------------------------------------------- send
    def _send(self, payload: str):
        if not self._opponent or payload is None:
            return
        code = self._current_code()
        try:
            self.manager.send_text(f"{PREFIX}{code}:{payload}",
                                   destination_id=self._opponent)
        except Exception:
            log.exception("game send failed")

    def _start_new_game(self):
        nid = self.cmb_opponent.currentData()
        if not nid:
            return
        self._opponent = nid
        code = self._current_code()
        self.engine = GAME_BY_CODE[code](i_start=True)
        self._build_board_for_current_game()
        self._send("NEW")
        self._render()

    def _reset_game(self):
        if self.engine:
            self.engine.reset()
            self._send("RESET")
            self._build_board_for_current_game()
            self._render()

    def _bs_ready(self):
        if self.engine and self._current_code() == "BS":
            pay = self.engine.ready_payload()
            if pay:
                self._send(pay)
                self._render()
            else:
                self.lbl_status.setText("Place all 3 ships first.")

    # ---- a board cell / button was clicked ----
    def _cell_clicked(self, arg):
        if not self.engine or not self._opponent:
            self.lbl_status.setText("Press New game first.")
            return
        code = self._current_code()
        # Battleship placement phase = clicking YOUR grid places ships
        if code == "BS" and self.engine.phase == "place":
            # placement uses my-grid clicks; but we wired enemy grid → treat
            # arg as a placement cell on the player's own fleet
            if self.engine.place_ship(arg):
                self._render()
            return
        payload = self.engine.apply_local(arg)
        if payload is None:
            if not self.engine.my_turn:
                self.lbl_status.setText("Not your turn — waiting for opponent.")
            return
        self._send(payload)
        # Battleship: after our shot we await the result message; no immediate render of result
        self._render()

    # -------------------------------------------------------- receive
    @Slot(dict)
    def _on_text(self, msg: dict):
        text = msg.get("text") or ""
        if not text.startswith(PREFIX):
            return
        from_id = msg.get("fromId")
        body = text[len(PREFIX):]
        try:
            code, payload = body.split(":", 1)
        except ValueError:
            return

        if payload == "NEW":
            # opponent invites us to THIS game code
            self._opponent = from_id
            idx = self.cmb_game.findData(code)
            if idx >= 0:
                self.cmb_game.setCurrentIndex(idx)
            self.engine = GAME_BY_CODE.get(code, GAME_BY_CODE["TTT"])(i_start=False)
            self._build_board_for_current_game()
            idx2 = self.cmb_opponent.findData(from_id)
            if idx2 >= 0:
                self.cmb_opponent.setCurrentIndex(idx2)
            self.lbl_status.setText(
                f"{self._name(from_id)} invited you to {self.engine.name}!")
            self._render()
            return

        if from_id != self._opponent or self.engine is None:
            return
        if code != self._current_code():
            return

        if payload == "RESET":
            self.engine.reset()
            self._build_board_for_current_game()
            self._render()
            return

        applied = self.engine.apply_remote(payload)
        if applied:
            # Battleship: if opponent fired at us, we owe them a result msg
            if self._current_code() == "BS":
                res = self.engine.consume_pending_result()
                if res:
                    self._send(res)
            self._render()

    # ---------------------------------------------------------- render
    def _render(self):
        if not self.engine:
            return
        self.lbl_status.setText(self.engine.status_text())
        code = self._current_code()
        if code == "TTT":
            self._render_ttt()
        elif code == "C4":
            self._render_c4()
        elif code == "RPS":
            self._render_rps()
        elif code == "BS":
            self._render_bs()
        elif code == "NIM":
            self._render_nim()

    def _render_ttt(self):
        e = self.engine
        win = set(e.win_line) if e.win_line else set()
        for i, b in enumerate(self.cells):
            m = e.board[i]
            b.setText("✗" if m == "1" else ("◯" if m == "2" else ""))
            b.setStyleSheet(self._cell_style(38, win=(i in win)))
            b.setEnabled(e.my_turn and not m and not e.game_over)

    def _render_c4(self):
        e = self.engine
        wins = set(e.win_cells)
        for (c, r), lbl in self.c4_cells.items():
            m = e._grid(c, r)
            color = "#F5B946" if m == "1" else ("#5BA9F5" if m == "2" else "")
            disc = "●" if m else ""
            border = (f"3px solid {Colors.SUCCESS}" if (c, r) in wins
                      else f"1px solid {Colors.BORDER}")
            lbl.setText(disc)
            lbl.setStyleSheet(
                f"background:{Colors.BG_INPUT}; border-radius:27px; "
                f"border:{border}; font-size:34px; color:{color or Colors.TEXT_DIM};")
        for c, db in enumerate(self.drop_btns):
            full = len(e.board[c]) >= e.ROWS
            db.setEnabled(e.my_turn and not full and not e.game_over)

    def _render_rps(self):
        e = self.engine
        for choice, b in self.rps_btns.items():
            b.setEnabled(e.my_turn and not e.game_over)

    def _render_bs(self):
        e = self.engine
        # my fleet: show ships + incoming hits
        for i, lbl in enumerate(self.bs_my_cells):
            if i in e.my_ships and i in e.their_hits:
                lbl.setText("💥"); 
            elif i in e.their_hits:
                lbl.setText("•")
            elif i in e.my_ships:
                lbl.setText("🚢")
            else:
                lbl.setText("")
        # enemy waters: my shots
        for i, b in enumerate(self.bs_enemy_cells):
            res = e.my_shots.get(i)
            b.setText("💥" if res == "hit" else ("·" if res == "miss" else ""))
            if e.phase == "place":
                # during placement, clicking enemy grid is disabled; place on my grid
                b.setEnabled(False)
            else:
                b.setEnabled(e.my_turn and res is None and not e.game_over)
        # placement: allow clicking MY cells to place ships
        # (we reuse enemy grid clicks in battle; for placement we let the
        #  my-fleet labels act via a simpler scheme: enable ready when 3 placed)
        if e.phase == "place":
            # make my fleet cells clickable for placement
            pass
        self.bs_ready_btn.setVisible(e.phase == "place")
        self.bs_ready_btn.setEnabled(e.phase == "place" and len(e.my_ships) == e.SHIPS)

    def _render_nim(self):
        e = self.engine
        self.nim_sticks_lbl.setText("🪵 " * e.remaining if e.remaining > 0 else "—")
        for i, b in enumerate(self.nim_btns):
            take = i + 1
            b.setEnabled(e.my_turn and take <= e.remaining and not e.game_over)

    def _name(self, nid):
        if not nid: return "opponent"
        try:
            nodes = getattr(self.manager.interface, "nodes", {}) or {}
            u = nodes.get(nid, {}).get("user", {})
            return u.get("longName") or u.get("shortName") or nid
        except Exception:
            return nid
