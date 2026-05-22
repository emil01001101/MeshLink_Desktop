"""
Istoric mesaje persistent in SQLite.

DB: ~/meshlink_desktop_logs/messages.db
Schema:
    messages(id, from_id, to_id, channel, text, rx_time, is_me,
             packet_id, reply_id, reactions_json, created_at)

API simpla: add_message(), get_recent(), clear_conversation()

V20 additions:
  • packet_id        — Meshtastic packet id of the message (for ACK and
                       reaction correlation). Reactions arrive later as
                       separate packets carrying replyId == this packet_id.
  • reply_id         — when the message is itself a reply, this references
                       the parent message's packet_id.
  • reactions_json   — JSON {emoji: [from_id, ...]} that we replay when the
                       history is loaded so chips persist across sessions.
"""

from __future__ import annotations

import os
import json
import sqlite3
import logging
import threading
from typing import List, Optional

log = logging.getLogger("meshlink.db")


class MessageDB:
    """Wrapper SQLite simplu, thread-safe via lock."""

    _instance: Optional["MessageDB"] = None

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_schema()

    @classmethod
    def get(cls, db_path: Optional[str] = None) -> "MessageDB":
        if cls._instance is None:
            if db_path is None:
                home = os.path.expanduser("~")
                db_dir = os.path.join(home, "meshlink_desktop_logs")
                os.makedirs(db_dir, exist_ok=True)
                db_path = os.path.join(db_dir, "messages.db")
            cls._instance = MessageDB(db_path)
        return cls._instance

    # ------------------------------------------------------------------
    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _init_schema(self):
        try:
            with self._lock, self._conn() as c:
                c.execute("""
                    CREATE TABLE IF NOT EXISTS messages (
                        id        INTEGER PRIMARY KEY AUTOINCREMENT,
                        from_id   TEXT,
                        to_id     TEXT,
                        channel   INTEGER,
                        text      TEXT,
                        rx_time   INTEGER,
                        is_me     INTEGER DEFAULT 0,
                        created_at INTEGER DEFAULT (strftime('%s','now'))
                    )
                """)
                c.execute("CREATE INDEX IF NOT EXISTS idx_rx_time ON messages(rx_time DESC)")
                c.execute("CREATE INDEX IF NOT EXISTS idx_channel ON messages(channel)")
                c.execute("CREATE INDEX IF NOT EXISTS idx_from ON messages(from_id)")

                # V20: add columns if missing (additive migration)
                existing = {row[1] for row in
                            c.execute("PRAGMA table_info(messages)")}
                for col, ddl in (
                    ("packet_id",      "INTEGER"),
                    ("reply_id",       "INTEGER"),
                    ("reactions_json", "TEXT"),
                ):
                    if col not in existing:
                        try:
                            c.execute(
                                f"ALTER TABLE messages ADD COLUMN {col} {ddl}")
                            log.info(f"messages.db: added column {col}")
                        except Exception:
                            log.exception(f"Could not add column {col}")
                c.execute(
                    "CREATE INDEX IF NOT EXISTS idx_packet_id "
                    "ON messages(packet_id)")
        except Exception:
            log.exception("DB init error")

    # ------------------------------------------------------------------
    def add_message(self, from_id: str, to_id: Optional[str], channel: int,
                    text: str, rx_time: int, is_me: bool = False,
                    packet_id: Optional[int] = None,
                    reply_id: Optional[int] = None,
                    reactions: Optional[dict] = None):
        rxn_json = json.dumps(reactions) if reactions else None
        try:
            with self._lock, self._conn() as c:
                c.execute(
                    "INSERT INTO messages(from_id, to_id, channel, text, "
                    "rx_time, is_me, packet_id, reply_id, reactions_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (from_id, to_id, channel, text, rx_time,
                     1 if is_me else 0, packet_id, reply_id, rxn_json)
                )
        except Exception:
            log.exception("Insert message error")

    def update_reactions(self, packet_id: int, reactions: dict):
        """Persist a new reactions map for the message with the given
        packet_id. Used when reactions arrive after the message was saved.
        """
        if not packet_id:
            return
        try:
            with self._lock, self._conn() as c:
                c.execute(
                    "UPDATE messages SET reactions_json=? WHERE packet_id=?",
                    (json.dumps(reactions or {}), packet_id)
                )
        except Exception:
            log.exception("update_reactions error")

    def get_channel_messages(self, channel: int, limit: int = 200) -> List[dict]:
        try:
            with self._lock, self._conn() as c:
                rows = c.execute(
                    "SELECT from_id, to_id, channel, text, rx_time, is_me, "
                    "packet_id, reply_id, reactions_json FROM messages "
                    "WHERE channel = ? AND (to_id IS NULL OR to_id IN ('^all','!ffffffff','')) "
                    "ORDER BY rx_time DESC LIMIT ?",
                    (channel, limit)
                ).fetchall()
                return [self._row_to_dict(r) for r in reversed(rows)]
        except Exception:
            log.exception("get_channel_messages error")
            return []

    def get_dm_messages(self, my_id: str, other_id: str, limit: int = 200) -> List[dict]:
        try:
            with self._lock, self._conn() as c:
                rows = c.execute(
                    "SELECT from_id, to_id, channel, text, rx_time, is_me, "
                    "packet_id, reply_id, reactions_json FROM messages "
                    "WHERE (from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?) "
                    "ORDER BY rx_time DESC LIMIT ?",
                    (my_id, other_id, other_id, my_id, limit)
                ).fetchall()
                return [self._row_to_dict(r) for r in reversed(rows)]
        except Exception:
            log.exception("get_dm_messages error")
            return []

    @staticmethod
    def _row_to_dict(row) -> dict:
        """Convert a row to dict, decoding reactions_json back to a map."""
        d = dict(row)
        rxn_json = d.pop("reactions_json", None)
        if rxn_json:
            try:
                d["reactions"] = json.loads(rxn_json)
            except Exception:
                d["reactions"] = {}
        return d

    def get_dm_partners(self, my_id: str) -> List[str]:
        """Returneaza ID-urile partenerilor cu care s-au schimbat DM-uri."""
        try:
            with self._lock, self._conn() as c:
                rows = c.execute(
                    "SELECT DISTINCT CASE WHEN from_id = ? THEN to_id ELSE from_id END as partner "
                    "FROM messages "
                    "WHERE (from_id = ? AND to_id NOT IN ('^all','!ffffffff','')) "
                    "   OR (to_id = ? AND to_id NOT IN ('^all','!ffffffff',''))",
                    (my_id, my_id, my_id)
                ).fetchall()
                return [r["partner"] for r in rows if r["partner"]]
        except Exception:
            log.exception("get_dm_partners error")
            return []

    def clear_channel(self, channel: int) -> int:
        """Delete all broadcast messages on a given channel. Returns rows deleted."""
        try:
            with self._lock, self._conn() as c:
                cur = c.execute(
                    "DELETE FROM messages WHERE channel = ? "
                    "AND (to_id IS NULL OR to_id IN ('^all','!ffffffff',''))",
                    (channel,)
                )
                return cur.rowcount
        except Exception:
            log.exception("clear_channel error")
            return 0

    def clear_dm(self, my_id: str, partner_id: str) -> int:
        """Delete the DM conversation between me and one partner. Returns rows."""
        try:
            with self._lock, self._conn() as c:
                cur = c.execute(
                    "DELETE FROM messages WHERE "
                    "(from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?)",
                    (my_id, partner_id, partner_id, my_id)
                )
                return cur.rowcount
        except Exception:
            log.exception("clear_dm error")
            return 0

    def clear_all(self):
        try:
            with self._lock, self._conn() as c:
                c.execute("DELETE FROM messages")
        except Exception:
            log.exception("clear DB error")

    def message_count(self) -> int:
        try:
            with self._lock, self._conn() as c:
                row = c.execute("SELECT COUNT(*) AS n FROM messages").fetchone()
                return int(row["n"])
        except Exception:
            return 0
