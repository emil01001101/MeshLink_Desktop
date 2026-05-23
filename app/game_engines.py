"""
Game engines (V0.45) — pure game logic, no UI, no networking.

Each engine is a small state machine that:
  • knows the board/state and whose turn it is
  • validates and applies a local move, producing a wire payload string
  • applies a remote move from a wire payload
  • reports winner/draw/status

All wire payloads are tiny (a few bytes) so a whole game costs only a
handful of small mesh messages.

Wire protocol is shared: messages are DMs prefixed with "MLGAME:".
Format: MLGAME:<game_code>:<payload>
  e.g. MLGAME:TTT:M4   MLGAME:C4:3   MLGAME:RPS:rock

The page handles networking; engines only deal with state + payloads.
"""

from __future__ import annotations

from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------
class BaseGame:
    code = "BASE"
    name = "Base"
    # "X"/"O" style marks for the two players
    def __init__(self, i_start: bool):
        """i_start=True if THIS client made the first move (player 1)."""
        self.i_am_p1 = i_start
        self.my_mark = "1" if i_start else "2"
        self.their_mark = "2" if i_start else "1"
        self.turn = "1"          # player 1 always moves first
        self.game_over = False
        self.reset()

    def reset(self):
        self.game_over = False
        self.turn = "1"

    @property
    def my_turn(self) -> bool:
        return (not self.game_over) and self.turn == self.my_mark

    def _swap_turn(self):
        self.turn = "2" if self.turn == "1" else "1"

    # to be implemented by subclasses
    def apply_local(self, *args) -> Optional[str]:
        """Apply a local move; return the wire payload to send, or None if
        the move was invalid."""
        raise NotImplementedError

    def apply_remote(self, payload: str) -> bool:
        """Apply a remote move from the wire payload. Return True if applied."""
        raise NotImplementedError

    def status_text(self) -> str:
        raise NotImplementedError

    def winner(self) -> Optional[str]:
        """Return '1'/'2'/'draw'/None."""
        return None


# ---------------------------------------------------------------------------
# 1. Tic-Tac-Toe
# ---------------------------------------------------------------------------
class TicTacToe(BaseGame):
    code = "TTT"
    name = "Tic-Tac-Toe"
    WIN = [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]

    def reset(self):
        super().reset()
        self.board: List[str] = [""] * 9
        self.win_line: Optional[Tuple[int,int,int]] = None

    def apply_local(self, idx: int) -> Optional[str]:
        if self.game_over or not self.my_turn or self.board[idx]:
            return None
        self.board[idx] = self.my_mark
        self._swap_turn()
        self._check()
        return f"M{idx}"

    def apply_remote(self, payload: str) -> bool:
        if not payload.startswith("M"):
            return False
        try:
            idx = int(payload[1:])
        except ValueError:
            return False
        if not (0 <= idx <= 8) or self.board[idx]:
            return False
        self.board[idx] = self.their_mark
        self._swap_turn()
        self._check()
        return True

    def _check(self):
        for a,b,c in self.WIN:
            if self.board[a] and self.board[a]==self.board[b]==self.board[c]:
                self.win_line=(a,b,c); self.game_over=True; return
        if all(self.board):
            self.game_over=True

    def winner(self):
        if self.win_line:
            return self.board[self.win_line[0]]
        if self.game_over and all(self.board):
            return "draw"
        return None

    def status_text(self):
        w=self.winner()
        if w=="draw": return "It's a draw! 🤝"
        if w==self.my_mark: return "You win! 🎉"
        if w==self.their_mark: return "You lost — try again!"
        return "Your move." if self.my_turn else "Waiting for opponent…"


# ---------------------------------------------------------------------------
# 2. Connect 4
# ---------------------------------------------------------------------------
class Connect4(BaseGame):
    code = "C4"
    name = "Connect 4"
    COLS, ROWS = 7, 6

    def reset(self):
        super().reset()
        # board[col] = list bottom→top of marks
        self.board: List[List[str]] = [[] for _ in range(self.COLS)]
        self.win_cells: List[Tuple[int,int]] = []

    def _grid(self, col, row) -> str:
        """row 0 = bottom."""
        stack = self.board[col]
        return stack[row] if row < len(stack) else ""

    def apply_local(self, col: int) -> Optional[str]:
        if self.game_over or not self.my_turn:
            return None
        if len(self.board[col]) >= self.ROWS:
            return None
        self.board[col].append(self.my_mark)
        self._swap_turn()
        self._check()
        return f"{col}"

    def apply_remote(self, payload: str) -> bool:
        try:
            col = int(payload)
        except ValueError:
            return False
        if not (0 <= col < self.COLS) or len(self.board[col]) >= self.ROWS:
            return False
        self.board[col].append(self.their_mark)
        self._swap_turn()
        self._check()
        return True

    def _check(self):
        def cell(c, r): return self._grid(c, r)
        dirs = [(1,0),(0,1),(1,1),(1,-1)]
        for c in range(self.COLS):
            for r in range(self.ROWS):
                m = cell(c, r)
                if not m:
                    continue
                for dc, dr in dirs:
                    line = [(c+dc*i, r+dr*i) for i in range(4)]
                    if all(0 <= cc < self.COLS and 0 <= rr < self.ROWS
                           and cell(cc, rr) == m for cc, rr in line):
                        self.win_cells = line
                        self.game_over = True
                        self._winner_mark = m
                        return
        if all(len(s) >= self.ROWS for s in self.board):
            self.game_over = True

    def winner(self):
        if getattr(self, "_winner_mark", None):
            return self._winner_mark
        if self.game_over:
            return "draw"
        return None

    def status_text(self):
        w=self.winner()
        if w=="draw": return "It's a draw! 🤝"
        if w==self.my_mark: return "You win! 🎉"
        if w==self.their_mark: return "You lost — try again!"
        return "Drop a disc." if self.my_turn else "Waiting for opponent…"


# ---------------------------------------------------------------------------
# 3. Rock-Paper-Scissors (best of 5)
# ---------------------------------------------------------------------------
class RockPaperScissors(BaseGame):
    code = "RPS"
    name = "Rock-Paper-Scissors"
    BEATS = {"rock":"scissors","scissors":"paper","paper":"rock"}
    TARGET = 3   # first to 3 wins

    def reset(self):
        super().reset()
        self.my_choice: Optional[str] = None
        self.their_choice: Optional[str] = None
        self.my_score = 0
        self.their_score = 0
        self.round_result = ""

    @property
    def my_turn(self) -> bool:
        # In RPS both choose simultaneously; "my_turn" = haven't chosen yet
        return (not self.game_over) and self.my_choice is None

    def apply_local(self, choice: str) -> Optional[str]:
        if self.game_over or self.my_choice is not None:
            return None
        if choice not in self.BEATS:
            return None
        self.my_choice = choice
        self._resolve_if_ready()
        return choice

    def apply_remote(self, payload: str) -> bool:
        if payload not in self.BEATS:
            return False
        if self.their_choice is not None:
            return False
        self.their_choice = payload
        self._resolve_if_ready()
        return True

    def _resolve_if_ready(self):
        if self.my_choice and self.their_choice:
            if self.my_choice == self.their_choice:
                self.round_result = "Tie!"
            elif self.BEATS[self.my_choice] == self.their_choice:
                self.my_score += 1
                self.round_result = f"You won that round! ({self.my_choice} beats {self.their_choice})"
            else:
                self.their_score += 1
                self.round_result = f"Opponent won ({self.their_choice} beats {self.my_choice})"
            # reset for next round
            self.my_choice = None
            self.their_choice = None
            if self.my_score >= self.TARGET or self.their_score >= self.TARGET:
                self.game_over = True

    def winner(self):
        if not self.game_over:
            return None
        return self.my_mark if self.my_score > self.their_score else self.their_mark

    def status_text(self):
        score = f"  [You {self.my_score} – {self.their_score} Opp]"
        if self.game_over:
            w = "You win the match! 🎉" if self.my_score > self.their_score else "You lost the match."
            return w + score
        base = self.round_result + "  " if self.round_result else ""
        if self.my_choice is not None:
            return base + "Waiting for opponent's choice…" + score
        return base + "Pick rock, paper, or scissors." + score


# ---------------------------------------------------------------------------
# 4. Battleship (simplified 5x5, 3 single-cell ships)
# ---------------------------------------------------------------------------
class Battleship(BaseGame):
    code = "BS"
    name = "Battleship"
    SIZE = 5
    SHIPS = 3   # number of 1-cell ships each

    def reset(self):
        super().reset()
        self.phase = "place"          # place → battle
        self.my_ships: set = set()    # cells I placed my ships on
        self.their_hits: set = set()  # cells opponent fired at me (hit/miss)
        self.my_shots: dict = {}      # cell → "hit"/"miss" (my shots at them)
        self.my_sunk = 0              # how many of MY ships are sunk
        self.their_sunk = 0           # how many of THEIR ships I sunk
        self._their_ready = False
        self._i_ready = False

    @property
    def my_turn(self) -> bool:
        if self.phase != "battle" or self.game_over:
            return False
        return self.turn == self.my_mark

    def place_ship(self, cell: int) -> bool:
        if self.phase != "place" or cell in self.my_ships:
            return False
        if len(self.my_ships) >= self.SHIPS:
            return False
        self.my_ships.add(cell)
        return True

    def ready_payload(self) -> Optional[str]:
        """Call when done placing — returns the READY wire payload."""
        if len(self.my_ships) != self.SHIPS:
            return None
        self._i_ready = True
        self._maybe_start_battle()
        return "READY"

    def apply_local(self, cell: int) -> Optional[str]:
        # a "shot" during battle
        if self.phase != "battle" or not self.my_turn:
            return None
        if cell in self.my_shots:
            return None
        return f"S{cell}"

    def apply_remote(self, payload: str) -> bool:
        if payload == "READY":
            self._their_ready = True
            self._maybe_start_battle()
            return True
        if payload.startswith("S"):
            # opponent fired at me
            try:
                cell = int(payload[1:])
            except ValueError:
                return False
            hit = cell in self.my_ships
            self.their_hits.add(cell)
            if hit:
                self.my_sunk += 1
            # tell them the result
            self._pending_result = (cell, "hit" if hit else "miss")
            if self.my_sunk >= self.SHIPS:
                self.game_over = True
                self._loser = True
            else:
                self.turn = self.my_mark   # now it's my turn to shoot
            return True
        if payload.startswith("R"):
            # result of MY shot: R<cell>:<hit/miss>
            body = payload[1:]
            try:
                cs, res = body.split(":")
                cell = int(cs)
            except ValueError:
                return False
            self.my_shots[cell] = res
            if res == "hit":
                self.their_sunk += 1
            if self.their_sunk >= self.SHIPS:
                self.game_over = True
                self._loser = False
            else:
                self.turn = self.their_mark
            return True
        return False

    def consume_pending_result(self) -> Optional[str]:
        """If an opponent shot just landed, return the R… payload to send back."""
        pr = getattr(self, "_pending_result", None)
        if pr:
            self._pending_result = None
            cell, res = pr
            return f"R{cell}:{res}"
        return None

    def _maybe_start_battle(self):
        if self._i_ready and self._their_ready and self.phase == "place":
            self.phase = "battle"
            self.turn = "1"   # player 1 shoots first

    def winner(self):
        if not self.game_over:
            return None
        return self.their_mark if getattr(self, "_loser", False) else self.my_mark

    def status_text(self):
        if self.phase == "place":
            left = self.SHIPS - len(self.my_ships)
            if left > 0:
                return f"Place your ships: {left} left (tap empty cells)."
            if not self._their_ready:
                return "Ready! Waiting for opponent to place ships…"
            return "Starting battle…"
        if self.game_over:
            return "You win! 🎉" if not getattr(self, "_loser", False) else "You lost — fleet sunk!"
        hits = sum(1 for v in self.my_shots.values() if v == "hit")
        sc = f"  [You sank {self.their_sunk}/{self.SHIPS} · lost {self.my_sunk}/{self.SHIPS}]"
        return ("Your shot — fire at the enemy grid." if self.my_turn
                else "Waiting for opponent's shot…") + sc


# ---------------------------------------------------------------------------
# 5. Nim (21 sticks — take 1-3, whoever takes the last loses)
# ---------------------------------------------------------------------------
class Nim(BaseGame):
    code = "NIM"
    name = "Nim (21)"
    START = 21

    def reset(self):
        super().reset()
        self.remaining = self.START
        self._loser = None

    def apply_local(self, take: int) -> Optional[str]:
        if self.game_over or not self.my_turn:
            return None
        if take < 1 or take > 3 or take > self.remaining:
            return None
        self.remaining -= take
        if self.remaining <= 0:
            # I took the last stick → I lose
            self.game_over = True
            self._loser = self.my_mark
        else:
            self._swap_turn()
        return f"T{take}"

    def apply_remote(self, payload: str) -> bool:
        if not payload.startswith("T"):
            return False
        try:
            take = int(payload[1:])
        except ValueError:
            return False
        if take < 1 or take > 3 or take > self.remaining:
            return False
        self.remaining -= take
        if self.remaining <= 0:
            self.game_over = True
            self._loser = self.their_mark
        else:
            self._swap_turn()
        return True

    def winner(self):
        if not self.game_over:
            return None
        # the one who took the last stick loses
        return self.their_mark if self._loser == self.my_mark else self.my_mark

    def status_text(self):
        if self.game_over:
            return ("You win! 🎉 Opponent took the last stick."
                    if self._loser == self.their_mark
                    else "You lost — you took the last stick!")
        base = f"🪵 {self.remaining} sticks left.  "
        return base + ("Take 1, 2, or 3 (don't take the last!)."
                       if self.my_turn else "Waiting for opponent…")


# Registry
GAME_CLASSES = [TicTacToe, Connect4, RockPaperScissors, Battleship, Nim]
GAME_BY_CODE = {c.code: c for c in GAME_CLASSES}
