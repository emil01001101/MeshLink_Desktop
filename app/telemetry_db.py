"""
DB for per-node telemetry history.
Permite afisarea graficelor 1H / 24H / All in Info tab si in popup-uri.
"""

from __future__ import annotations

import os
import time
import sqlite3
import logging
import threading
from typing import List, Optional

log = logging.getLogger("meshlink.telem_db")


class TelemetryDB:
    """Wrapper SQLite pentru telemetrie (thread-safe)."""

    _instance: Optional["TelemetryDB"] = None

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_schema()

    @classmethod
    def get(cls) -> "TelemetryDB":
        if cls._instance is None:
            home = os.path.expanduser("~")
            db_dir = os.path.join(home, "meshlink_desktop_logs")
            os.makedirs(db_dir, exist_ok=True)
            cls._instance = TelemetryDB(os.path.join(db_dir, "telemetry.db"))
        return cls._instance

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _init_schema(self):
        try:
            with self._lock, self._conn() as c:
                c.execute("""
                    CREATE TABLE IF NOT EXISTS telemetry (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        node_id TEXT NOT NULL,
                        timestamp INTEGER NOT NULL,
                        battery_level REAL,
                        voltage REAL,
                        channel_utilization REAL,
                        air_util_tx REAL,
                        uptime_seconds INTEGER
                    )
                """)
                c.execute(
                    "CREATE INDEX IF NOT EXISTS idx_node_time "
                    "ON telemetry(node_id, timestamp DESC)"
                )
                # ---- V20: add env columns if missing (additive migration) ----
                existing = {row[1] for row in
                            c.execute("PRAGMA table_info(telemetry)")}
                for col in ("temperature", "humidity", "pressure",
                            "gas_resistance", "iaq"):
                    if col not in existing:
                        try:
                            c.execute(
                                f"ALTER TABLE telemetry ADD COLUMN {col} REAL"
                            )
                            log.info(f"telemetry.db: added column {col}")
                        except Exception:
                            log.exception(f"Could not add column {col}")
        except Exception:
            log.exception("Telemetry DB init error")

    def add_reading(self, node_id: str, timestamp: int,
                    battery_level=None, voltage=None,
                    channel_utilization=None, air_util_tx=None,
                    uptime_seconds=None):
        try:
            with self._lock, self._conn() as c:
                c.execute(
                    "INSERT INTO telemetry(node_id, timestamp, battery_level, "
                    "voltage, channel_utilization, air_util_tx, uptime_seconds) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (node_id, timestamp, battery_level, voltage,
                     channel_utilization, air_util_tx, uptime_seconds)
                )
        except Exception:
            log.exception("Insert telemetry error")

    def add_env_reading(self, node_id: str, timestamp: int,
                        temperature=None, humidity=None, pressure=None,
                        gas_resistance=None, iaq=None):
        """Store an environment-sensor reading.

        env metrics arrive in a separate TELEMETRY packet from deviceMetrics,
        so we store them as their own row (keyed by node_id + timestamp).
        Skips silently if none of the values are present.
        """
        if all(v is None for v in
               (temperature, humidity, pressure, gas_resistance, iaq)):
            return
        try:
            with self._lock, self._conn() as c:
                c.execute(
                    "INSERT INTO telemetry(node_id, timestamp, temperature, "
                    "humidity, pressure, gas_resistance, iaq) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (node_id, timestamp, temperature, humidity, pressure,
                     gas_resistance, iaq)
                )
        except Exception:
            log.exception("Insert env telemetry error")

    def get_history(self, node_id: str, since_seconds: int = 86400) -> List[dict]:
        """Citiri din ultimele N secunde (default 24h)."""
        cutoff = int(time.time()) - since_seconds
        try:
            with self._lock, self._conn() as c:
                rows = c.execute(
                    "SELECT timestamp, battery_level, voltage, "
                    "channel_utilization, air_util_tx, uptime_seconds, "
                    "temperature, humidity, pressure, gas_resistance, iaq "
                    "FROM telemetry WHERE node_id=? AND timestamp>=? "
                    "ORDER BY timestamp ASC",
                    (node_id, cutoff)
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            log.exception("get_history error")
            return []

    def get_all(self, node_id: str, limit: int = 10000) -> List[dict]:
        try:
            with self._lock, self._conn() as c:
                rows = c.execute(
                    "SELECT timestamp, battery_level, voltage, "
                    "channel_utilization, air_util_tx, uptime_seconds, "
                    "temperature, humidity, pressure, gas_resistance, iaq "
                    "FROM telemetry WHERE node_id=? "
                    "ORDER BY timestamp ASC LIMIT ?",
                    (node_id, limit)
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            log.exception("get_all error")
            return []

    def get_recent(self, node_id: str, limit: int = 30) -> List[dict]:
        """Citiri recente in ordine DESCRESCATOARE (cele mai noi primele)."""
        try:
            with self._lock, self._conn() as c:
                rows = c.execute(
                    "SELECT timestamp, battery_level, voltage, "
                    "channel_utilization, air_util_tx, uptime_seconds, "
                    "temperature, humidity, pressure, gas_resistance, iaq "
                    "FROM telemetry WHERE node_id=? "
                    "ORDER BY timestamp DESC LIMIT ?",
                    (node_id, limit)
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            log.exception("get_recent error")
            return []

    def count(self, node_id: str) -> int:
        try:
            with self._lock, self._conn() as c:
                row = c.execute(
                    "SELECT COUNT(*) AS n FROM telemetry WHERE node_id=?",
                    (node_id,)
                ).fetchone()
                return int(row["n"])
        except Exception:
            return 0
