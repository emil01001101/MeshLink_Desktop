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


# ---------------------------------------------------------------------------
# 6. Guess the Number (initiator sets 1-100, opponent guesses)
# ---------------------------------------------------------------------------
class GuessNumber(BaseGame):
    code = "GN"
    name = "Guess the Number"
    MAXN = 100

    def reset(self):
        super().reset()
        self.phase = "set"          # set → guess
        self.secret = None          # only the setter knows
        self.guesses = 0
        self.last_hint = ""
        self._i_set = False

    @property
    def my_turn(self):
        if self.game_over:
            return False
        if self.phase == "set":
            return self.i_am_p1 and not self._i_set     # setter picks number
        # guess phase: the guesser (player 2) plays
        return not self.i_am_p1

    def set_secret(self, n: int) -> Optional[str]:
        """Setter (player 1) locks in the secret. Returns the wire payload."""
        if self.phase != "set" or not self.i_am_p1:
            return None
        if not (1 <= n <= self.MAXN):
            return None
        self.secret = n
        self._i_set = True
        self.phase = "guess"
        return "SET"

    def apply_local(self, n: int) -> Optional[str]:
        # the guesser submits a guess
        if self.phase != "guess" or self.i_am_p1 or self.game_over:
            return None
        if not (1 <= n <= self.MAXN):
            return None
        self.guesses += 1
        return f"G{n}"

    def apply_remote(self, payload: str) -> bool:
        if payload == "SET":
            self.phase = "guess"
            return True
        if payload.startswith("G"):
            # setter receives a guess, replies with hint
            try:
                g = int(payload[1:])
            except ValueError:
                return False
            if self.secret is None:
                return False
            if g == self.secret:
                self._pending = f"R{g}:ok"
                self.game_over = True       # guesser wins
            elif g < self.secret:
                self._pending = f"R{g}:hi"   # go higher
            else:
                self._pending = f"R{g}:lo"   # go lower
            return True
        if payload.startswith("R"):
            # guesser receives the hint
            body = payload[1:]
            try:
                gs, res = body.split(":")
            except ValueError:
                return False
            if res == "ok":
                self.game_over = True
                self.last_hint = f"Correct! {gs} was the number 🎉"
            elif res == "hi":
                self.last_hint = f"{gs} is too low — go higher ⬆"
            else:
                self.last_hint = f"{gs} is too high — go lower ⬇"
            return True
        return False

    def consume_pending(self) -> Optional[str]:
        p = getattr(self, "_pending", None)
        if p:
            self._pending = None
            return p
        return None

    def winner(self):
        # the guesser (player 2) "wins" by finding the number
        return "2" if self.game_over else None

    def status_text(self):
        if self.phase == "set":
            if self.i_am_p1:
                return ("Pick a secret number 1–100 for your opponent to guess."
                        if not self._i_set else "Waiting for opponent to guess…")
            return "Opponent is picking a secret number…"
        if self.game_over:
            if self.i_am_p1:
                return f"Opponent guessed it in {self.guesses or '?'} tries!"
            return f"You got it in {self.guesses} guesses! 🎉"
        if self.i_am_p1:
            return "Waiting for opponent's guess…"
        base = (self.last_hint + "  ") if self.last_hint else ""
        return base + f"Guess a number 1–100  (tries: {self.guesses})"


# ---------------------------------------------------------------------------
# 7. Dots and Boxes (5x5 dots → 4x4 boxes)
# ---------------------------------------------------------------------------
class DotsAndBoxes(BaseGame):
    code = "DAB"
    name = "Dots and Boxes"
    DOTS = 5                 # 5x5 dots
    N = DOTS - 1             # 4x4 boxes

    def reset(self):
        super().reset()
        # edges stored as sets of keys
        self.h_edges = set()     # horizontal: (row, col), row 0..DOTS-1, col 0..N-1
        self.v_edges = set()     # vertical:   (row, col), row 0..N-1, col 0..DOTS-1
        self.boxes = {}          # (r,c) -> "1"/"2"
        self.my_score = 0
        self.their_score = 0

    def _claim_boxes(self, mark) -> int:
        """Claim any newly-completed boxes for mark. Returns count claimed."""
        claimed = 0
        for r in range(self.N):
            for c in range(self.N):
                if (r, c) in self.boxes:
                    continue
                if ((r, c) in self.h_edges and (r + 1, c) in self.h_edges and
                        (r, c) in self.v_edges and (r, c + 1) in self.v_edges):
                    self.boxes[(r, c)] = mark
                    claimed += 1
        return claimed

    def _edge_free(self, kind, r, c) -> bool:
        if kind == "H":
            return (r, c) not in self.h_edges
        return (r, c) not in self.v_edges

    def _draw(self, kind, r, c, mark) -> bool:
        if kind == "H":
            if (r, c) in self.h_edges:
                return False
            self.h_edges.add((r, c))
        else:
            if (r, c) in self.v_edges:
                return False
            self.v_edges.add((r, c))
        claimed = self._claim_boxes(mark)
        if mark == self.my_mark:
            self.my_score += claimed
        else:
            self.their_score += claimed
        # completing a box grants another turn
        if claimed == 0:
            self._swap_turn()
        self._check_done()
        return True

    def _check_done(self):
        if len(self.boxes) >= self.N * self.N:
            self.game_over = True

    def apply_local(self, move) -> Optional[str]:
        # move = (kind, r, c)
        if self.game_over or not self.my_turn:
            return None
        kind, r, c = move
        if not self._edge_free(kind, r, c):
            return None
        self._draw(kind, r, c, self.my_mark)
        return f"{kind}{r},{c}"

    def apply_remote(self, payload: str) -> bool:
        if not payload or payload[0] not in "HV":
            return False
        kind = payload[0]
        try:
            r, c = (int(x) for x in payload[1:].split(","))
        except ValueError:
            return False
        if not self._edge_free(kind, r, c):
            return False
        self._draw(kind, r, c, self.their_mark)
        return True

    def winner(self):
        if not self.game_over:
            return None
        if self.my_score > self.their_score:
            return self.my_mark
        if self.their_score > self.my_score:
            return self.their_mark
        return "draw"

    def status_text(self):
        sc = f"  [You {self.my_score} – {self.their_score} Opp]"
        if self.game_over:
            w = self.winner()
            if w == "draw":
                return "It's a draw! 🤝" + sc
            return ("You win! 🎉" if w == self.my_mark else "You lost.") + sc
        return ("Draw a line." if self.my_turn else "Waiting for opponent…") + sc


# ---------------------------------------------------------------------------
# 8. Hangman (initiator sets a word, opponent guesses letters)
# ---------------------------------------------------------------------------
class Hangman(BaseGame):
    code = "HM"
    name = "Hangman"
    MAX_WRONG = 6

    def reset(self):
        super().reset()
        self.phase = "set"           # set → guess
        self.word = ""               # only setter knows (uppercase A-Z)
        self.length = 0
        self.guessed = set()         # letters guessed
        self.wrong = 0
        self.revealed = []           # list of chars or "_"

    @property
    def my_turn(self):
        if self.game_over:
            return False
        if self.phase == "set":
            return self.i_am_p1 and not self.word
        return not self.i_am_p1      # guesser plays

    def set_word(self, word: str) -> Optional[str]:
        if self.phase != "set" or not self.i_am_p1:
            return None
        w = "".join(ch for ch in word.upper() if ch.isalpha())
        if not (2 <= len(w) <= 14):
            return None
        self.word = w
        self.length = len(w)
        self.revealed = ["_"] * self.length
        self.phase = "guess"
        return f"W{self.length}"

    def apply_local(self, letter: str) -> Optional[str]:
        if self.phase != "guess" or self.i_am_p1 or self.game_over:
            return None
        L = letter.upper()
        if len(L) != 1 or not L.isalpha() or L in self.guessed:
            return None
        self.guessed.add(L)
        return f"G{L}"

    def apply_remote(self, payload: str) -> bool:
        if payload.startswith("W"):
            try:
                self.length = int(payload[1:])
            except ValueError:
                return False
            self.revealed = ["_"] * self.length
            self.phase = "guess"
            return True
        if payload.startswith("G"):
            # setter receives a letter guess → reply with positions
            L = payload[1:2].upper()
            if not L or self.phase != "guess":
                return False
            positions = [i for i, ch in enumerate(self.word) if ch == L]
            self._pending = f"R{L}:" + ",".join(str(p) for p in positions)
            for p in positions:
                self.revealed[p] = L
            if "_" not in self.revealed:
                self.game_over = True          # guesser won
            return True
        if payload.startswith("R"):
            # guesser receives positions
            body = payload[1:]
            try:
                L, posstr = body.split(":", 1)
            except ValueError:
                return False
            self.guessed.add(L)
            positions = [int(p) for p in posstr.split(",") if p != ""]
            if positions:
                for p in positions:
                    if 0 <= p < self.length:
                        self.revealed[p] = L
                if "_" not in self.revealed:
                    self.game_over = True
            else:
                self.wrong += 1
                if self.wrong >= self.MAX_WRONG:
                    self.game_over = True
            return True
        return False

    def consume_pending(self) -> Optional[str]:
        p = getattr(self, "_pending", None)
        if p:
            self._pending = None
            return p
        return None

    def winner(self):
        if not self.game_over:
            return None
        # guesser (player 2) wins if word fully revealed, else setter (1) wins
        if "_" not in self.revealed:
            return "2"
        return "1"

    def status_text(self):
        if self.phase == "set":
            if self.i_am_p1:
                return ("Enter a secret word (2–14 letters) for your opponent."
                        if not self.word else "Waiting for opponent to guess…")
            return "Opponent is choosing a word…"
        shown = " ".join(self.revealed)
        lives = self.MAX_WRONG - self.wrong
        if self.game_over:
            if "_" not in self.revealed:
                return (f"Word solved: {shown}  🎉"
                        if not self.i_am_p1 else f"Opponent solved it: {shown}")
            return (f"Out of guesses! Word was hidden."
                    if not self.i_am_p1 else "You win — opponent ran out! ")
        wrongs = ", ".join(sorted(g for g in self.guessed
                                  if g not in self.revealed)) or "—"
        base = f"{shown}    ❤ {lives}   wrong: {wrongs}"
        if self.i_am_p1:
            return base + "   (waiting for guesses)"
        return base + "   — guess a letter."


# ---------------------------------------------------------------------------
# 9. Nine Men's Morris
# ---------------------------------------------------------------------------
class NineMensMorris(BaseGame):
    code = "NMM"
    name = "Nine Men's Morris"
    # 24 points (0..23). Adjacency + mills from the classic board.
    ADJ = {
        0:[1,9], 1:[0,2,4], 2:[1,14], 3:[4,10], 4:[1,3,5,7], 5:[4,13],
        6:[7,11], 7:[4,6,8], 8:[7,12], 9:[0,10,21], 10:[3,9,11,18],
        11:[6,10,15], 12:[8,13,17], 13:[5,12,14,20], 14:[2,13,23],
        15:[11,16], 16:[15,17,19], 17:[12,16], 18:[10,19], 19:[16,18,20,22],
        20:[13,19], 21:[9,22], 22:[19,21,23], 23:[14,22],
    }
    MILLS = [
        (0,1,2),(3,4,5),(6,7,8),(9,10,11),(12,13,14),(15,16,17),(18,19,20),
        (21,22,23),(0,9,21),(3,10,18),(6,11,15),(1,4,7),(16,19,22),(8,12,17),
        (5,13,20),(2,14,23),
    ]

    def reset(self):
        super().reset()
        self.board = [""] * 24
        self.placed = {"1": 0, "2": 0}    # men placed
        self.on_board = {"1": 0, "2": 0}  # men currently on board
        self.phase = "place"              # place → move
        self.await_capture = False        # current mover must remove an enemy
        self.selected = None              # for move phase (from-point)

    def _forms_mill(self, pos, mark):
        for a, b, c in self.MILLS:
            if pos in (a, b, c) and self.board[a] == self.board[b] == self.board[c] == mark:
                return True
        return False

    def _all_in_mills(self, mark):
        pts = [i for i in range(24) if self.board[i] == mark]
        for p in pts:
            in_mill = any(self.board[a]==self.board[b]==self.board[c]==mark
                          and p in (a,b,c) for a,b,c in self.MILLS)
            if not in_mill:
                return False
        return True

    def _capturable(self, enemy):
        pts = [i for i in range(24) if self.board[i] == enemy]
        non_mill = [p for p in pts if not self._in_any_mill(p, enemy)]
        return non_mill if non_mill else pts

    def _in_any_mill(self, pos, mark):
        return any(self.board[a]==self.board[b]==self.board[c]==mark
                   and pos in (a,b,c) for a,b,c in self.MILLS)

    def _post_place_phase(self):
        if self.placed["1"] >= 9 and self.placed["2"] >= 9:
            self.phase = "move"

    def _check_loss(self):
        # a player loses if they have <3 men (after placing) or cannot move
        for m in ("1", "2"):
            if self.phase == "move" and self.on_board[m] < 3:
                self.game_over = True
                self._winner = "2" if m == "1" else "1"
                return

    def apply_local(self, arg):
        """arg: int point for place/capture; ('move', frm, to) for move."""
        if self.game_over or not self.my_turn:
            return None
        mark = self.my_mark
        if self.await_capture:
            pos = arg
            enemy = self.their_mark
            if self.board[pos] != enemy or pos not in self._capturable(enemy):
                return None
            self.board[pos] = ""
            self.on_board[enemy] -= 1
            self.await_capture = False
            self._swap_turn()
            self._check_loss()
            return f"X{pos}"
        if self.phase == "place":
            pos = arg
            if self.board[pos]:
                return None
            self.board[pos] = mark
            self.placed[mark] += 1
            self.on_board[mark] += 1
            if self._forms_mill(pos, mark):
                self.await_capture = True
            else:
                self._swap_turn()
            self._post_place_phase()
            return f"P{pos}"
        else:  # move
            if not (isinstance(arg, tuple) and arg[0] == "move"):
                return None
            _, frm, to = arg
            if self.board[frm] != mark or self.board[to]:
                return None
            # flying when exactly 3 men, else must be adjacent
            if self.on_board[mark] > 3 and to not in self.ADJ[frm]:
                return None
            self.board[frm] = ""
            self.board[to] = mark
            if self._forms_mill(to, mark):
                self.await_capture = True
            else:
                self._swap_turn()
            self._check_loss()
            return f"M{frm},{to}"

    def apply_remote(self, payload: str) -> bool:
        mark = self.their_mark
        if payload.startswith("X"):
            try: pos = int(payload[1:])
            except ValueError: return False
            if self.board[pos] != self.my_mark:
                return False
            self.board[pos] = ""
            self.on_board[self.my_mark] -= 1
            self.await_capture = False
            self._swap_turn()
            self._check_loss()
            return True
        if payload.startswith("P"):
            try: pos = int(payload[1:])
            except ValueError: return False
            if self.board[pos]:
                return False
            self.board[pos] = mark
            self.placed[mark] += 1
            self.on_board[mark] += 1
            if self._forms_mill(pos, mark):
                self.await_capture = True   # remote player will capture next
            else:
                self._swap_turn()
            self._post_place_phase()
            return True
        if payload.startswith("M"):
            try:
                frm, to = (int(x) for x in payload[1:].split(","))
            except ValueError:
                return False
            if self.board[frm] != mark or self.board[to]:
                return False
            self.board[frm] = ""
            self.board[to] = mark
            if self._forms_mill(to, mark):
                self.await_capture = True
            else:
                self._swap_turn()
            self._check_loss()
            return True
        return False

    def winner(self):
        return getattr(self, "_winner", None) if self.game_over else None

    def status_text(self):
        if self.game_over:
            w = self.winner()
            return "You win! 🎉" if w == self.my_mark else "You lost."
        if self.await_capture and self.my_turn:
            return "Mill! Tap an enemy piece to remove it."
        ph = "Place" if self.phase == "place" else "Move"
        left = 9 - self.placed[self.my_mark]
        extra = f"  ({left} to place)" if self.phase == "place" else ""
        return (f"{ph} a piece.{extra}" if self.my_turn
                else "Waiting for opponent…")


# ---------------------------------------------------------------------------
# 10. Checkers (8x8, simple kings — no flying)
# ---------------------------------------------------------------------------
class Checkers(BaseGame):
    code = "CK"
    name = "Checkers"
    SIZE = 8

    def reset(self):
        super().reset()
        # board[r][c]; "" empty; pieces: p1 = "a"/"A"(king), p2 = "b"/"B"(king)
        self.board = [["" for _ in range(8)] for _ in range(8)]
        for r in range(8):
            for c in range(8):
                if (r + c) % 2 == 1:
                    if r < 3:
                        self.board[r][c] = "b"   # player 2 starts at top
                    elif r > 4:
                        self.board[r][c] = "a"   # player 1 at bottom
        self.selected = None
        self._winner = None

    def _mine(self, ch):
        return ch.lower() == ("a" if self.my_mark == "1" else "b") if ch else False

    def _is_mark(self, ch, mark):
        if not ch:
            return False
        return ch.lower() == ("a" if mark == "1" else "b")

    def _dirs(self, ch):
        # p1 ("a") moves up (-1), p2 ("b") moves down (+1); kings both
        if ch == "a":
            return [(-1, -1), (-1, 1)]
        if ch == "b":
            return [(1, -1), (1, 1)]
        return [(-1, -1), (-1, 1), (1, -1), (1, 1)]  # king

    def _legal_moves(self, mark):
        """Return dict {(r,c): [(tr,tc,is_jump), ...]} for mark."""
        moves = {}
        jumps_exist = False
        for r in range(8):
            for c in range(8):
                ch = self.board[r][c]
                if not self._is_mark(ch, mark):
                    continue
                opts = []
                for dr, dc in self._dirs(ch):
                    nr, nc = r + dr, c + dc
                    jr, jc = r + 2*dr, c + 2*dc
                    if 0 <= nr < 8 and 0 <= nc < 8 and self.board[nr][nc] == "":
                        opts.append((nr, nc, False))
                    if (0 <= jr < 8 and 0 <= jc < 8 and self.board[jr][jc] == ""
                            and self.board[nr][nc] and not self._is_mark(self.board[nr][nc], mark)):
                        opts.append((jr, jc, True))
                        jumps_exist = True
                if opts:
                    moves[(r, c)] = opts
        if jumps_exist:   # forced capture
            moves = {k: [o for o in v if o[2]] for k, v in moves.items()}
            moves = {k: v for k, v in moves.items() if v}
        return moves

    def _do_move(self, frm, to, mark):
        fr, fc = frm; tr, tc = to
        ch = self.board[fr][fc]
        self.board[fr][fc] = ""
        # capture
        if abs(tr - fr) == 2:
            mr, mc = (fr + tr)//2, (fc + tc)//2
            self.board[mr][mc] = ""
        # promote
        if mark == "1" and tr == 0:
            ch = "A"
        elif mark == "2" and tr == 7:
            ch = "B"
        self.board[tr][tc] = ch
        # win check: opponent has no pieces or no moves
        enemy = "2" if mark == "1" else "1"
        if not any(self._is_mark(self.board[r][c], enemy)
                   for r in range(8) for c in range(8)) or not self._legal_moves(enemy):
            self.game_over = True
            self._winner = mark

    def apply_local(self, move) -> Optional[str]:
        if self.game_over or not self.my_turn:
            return None
        frm, to = move
        legal = self._legal_moves(self.my_mark)
        if frm not in legal or not any((to[0], to[1]) == (o[0], o[1]) for o in legal[frm]):
            return None
        self._do_move(frm, to, self.my_mark)
        if not self.game_over:
            self._swap_turn()
        return f"{frm[0]}{frm[1]}-{to[0]}{to[1]}"

    def apply_remote(self, payload: str) -> bool:
        try:
            fr, rest = payload.split("-")
            frm = (int(fr[0]), int(fr[1]))
            to = (int(rest[0]), int(rest[1]))
        except (ValueError, IndexError):
            return False
        self._do_move(frm, to, self.their_mark)
        if not self.game_over:
            self._swap_turn()
        return True

    def winner(self):
        return self._winner if self.game_over else None

    def status_text(self):
        if self.game_over:
            return "You win! 🎉" if self.winner() == self.my_mark else "You lost."
        return ("Your move — tap a piece, then its destination."
                if self.my_turn else "Waiting for opponent…")


# Registry
GAME_CLASSES = [TicTacToe, Connect4, RockPaperScissors, Battleship, Nim,
                GuessNumber, DotsAndBoxes, Hangman, NineMensMorris, Checkers]
GAME_BY_CODE = {c.code: c for c in GAME_CLASSES}
