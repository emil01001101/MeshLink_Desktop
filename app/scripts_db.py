"""
SQLite store for user-defined automation scripts.

Each script has:
  • id: auto-increment integer
  • name: human-readable label
  • code: Python source (free-form, runs in sandboxed-ish exec context)
  • interval_seconds: how often to run (0 = manual only)
  • enabled: bool — does the scheduler run it automatically?
  • target_channels: CSV of channel indices to send on by default
                    (e.g. "0" for primary only, "0,1" for primary + Iberia).
                    Empty = primary channel (0).
  • target_dest: destination node ID for DM mode (e.g. "!ba4bf9d0")
                 OR empty / "^all" for broadcast.
  • last_run / last_status / last_output / next_run: runtime tracking
  • created_at / updated_at

Where to put your Python code:
    Open the Scripts tab → click "+ New script" → name it → choose how often
    it should run and on which channels → write Python in the editor → click
    "▶ Run Now" to test → tick "Enabled" once it works.

Scripts run in a daemon thread with their stdout captured to the output
panel. The Meshtastic API is injected as built-ins (see script_runner.py).
"""

from __future__ import annotations

import os
import time
import sqlite3
import logging
import threading
from typing import List, Optional, Dict, Any

log = logging.getLogger("meshlink.scripts_db")


# ---------------------------------------------------------------------------
# Demo script that ships with a fresh install
#
# Posts the LOCAL device's current environmental + power telemetry to the
# selected channels every 6 hours. Pulls data from the node objects that
# the manager already maintains — no internet required.
# ---------------------------------------------------------------------------
DEFAULT_ENV_TELEMETRY_SCRIPT = '''"""
Environment telemetry broadcast.

Reads the local node's most recent telemetry and posts a compact one-line
summary to the channels configured in the panel above (default: LongFast).

What gets included depends on what sensors your radio has:
  • Temperature                       (BME280 / BME680 / SHT31 / DHT22)
  • Humidity                          (BME280 / BME680 / SHT31 / DHT22)
  • Barometric pressure               (BME280 / BME680 / BMP280)
  • IAQ (indoor air quality)          (BME680)
  • Battery level + voltage           (built-in)

If no environment sensor is present, only battery + voltage are reported.
Adjust the interval and channels in the panel above; modify this code to
customise the format.

The function send_text() with no arguments uses the channels + target
selected in the UI. You can still override per-call with
send_text("...", channel=2, dest="!1234abcd").
"""

from datetime import datetime

if not is_connected:
    log("Not connected to a device; skipping.")
else:
    env = local_env()       # environmentMetrics dict (may be empty)
    dev = local_device()    # deviceMetrics dict (battery, voltage, etc.)

    parts = []
    if "temperature" in env:
        parts.append(f"🌡 {env['temperature']:.1f}°C")
    if "relativeHumidity" in env:
        parts.append(f"💧 {env['relativeHumidity']:.0f}%")
    if "barometricPressure" in env:
        parts.append(f"📊 {env['barometricPressure']:.0f} hPa")
    if "iaq" in env:
        iaq = int(env["iaq"])
        # IAQ 0-50 excellent, 51-100 good, 101-150 moderate, 151-200 poor,
        # 201-300 unhealthy, 301+ very unhealthy
        face = "🟢" if iaq <= 100 else ("🟡" if iaq <= 200 else "🔴")
        parts.append(f"{face} IAQ {iaq}")
    if "gasResistance" in env:
        parts.append(f"🌫 {env['gasResistance']/1000:.1f}kΩ")

    # Always include battery + voltage if available
    if "batteryLevel" in dev:
        bat = int(dev["batteryLevel"])
        if bat > 100:
            parts.append("🔌 USB")
        else:
            parts.append(f"🔋 {bat}%")
    if "voltage" in dev:
        parts.append(f"⚡ {dev['voltage']:.2f}V")

    if not parts:
        log("No telemetry available yet — try again after the device "
            "publishes its first reading.")
    else:
        ts = datetime.now().strftime("%H:%M")
        msg = "📡 " + ts + " · " + " · ".join(parts)
        # Trim to LoRa packet size (200 chars is safe across regions)
        if len(msg) > 200:
            msg = msg[:197] + "…"
        log(f"Sending: {msg}")
        ok = send_text(msg)   # uses the channels + target from the UI
        if ok:
            log("✓ Broadcast sent.")
        else:
            log("✗ Send failed — check the connection state.")
'''


class ScriptsDB:
    _instance: Optional["ScriptsDB"] = None

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_schema()

    @classmethod
    def get(cls) -> "ScriptsDB":
        if cls._instance is None:
            home = os.path.expanduser("~")
            db_dir = os.path.join(home, "meshlink_desktop_logs")
            os.makedirs(db_dir, exist_ok=True)
            cls._instance = ScriptsDB(os.path.join(db_dir, "scripts.db"))
            cls._instance._migrate_legacy_demo()
            cls._instance._seed_defaults()
        return cls._instance

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _init_schema(self):
        """Create the table if missing, then additively add new columns.

        V20-turn6 additions:
          • target_channels  TEXT  (CSV of channel indices, default "0")
          • target_dest      TEXT  ("" for broadcast, "!hex" for DM)
        """
        try:
            with self._lock, self._conn() as c:
                c.execute("""
                    CREATE TABLE IF NOT EXISTS scripts (
                        id              INTEGER PRIMARY KEY AUTOINCREMENT,
                        name            TEXT NOT NULL,
                        code            TEXT NOT NULL,
                        interval_seconds INTEGER DEFAULT 0,
                        enabled         INTEGER DEFAULT 0,
                        last_run        INTEGER,
                        last_status     TEXT,
                        last_output     TEXT,
                        next_run        INTEGER,
                        created_at      INTEGER DEFAULT (strftime('%s','now')),
                        updated_at      INTEGER DEFAULT (strftime('%s','now'))
                    )
                """)
                # Additive migration for new fields
                existing = {row[1] for row in
                            c.execute("PRAGMA table_info(scripts)")}
                for col, ddl, default in (
                    ("target_channels", "TEXT", "'0'"),
                    ("target_dest",     "TEXT", "''"),
                ):
                    if col not in existing:
                        try:
                            c.execute(
                                f"ALTER TABLE scripts ADD COLUMN "
                                f"{col} {ddl} DEFAULT {default}")
                            log.info(f"scripts.db: added column {col}")
                        except Exception:
                            log.exception(f"Could not add column {col}")
        except Exception:
            log.exception("Failed to init scripts DB")

    def _migrate_legacy_demo(self):
        """If the legacy 'Weather bot (example)' is still untouched, remove
        it so the new demo seeds in its place. Users who customised it
        keep their copy."""
        try:
            with self._lock, self._conn() as c:
                row = c.execute(
                    "SELECT id, code FROM scripts "
                    "WHERE name='Weather bot (example)' LIMIT 1"
                ).fetchone()
                if row is None:
                    return
                # Only delete if the code still contains the original Catalan
                # phrase — leave user-modified copies alone.
                if "Balaguer" in (row["code"] or ""):
                    c.execute("DELETE FROM scripts WHERE id=?", (row["id"],))
                    log.info("Removed legacy 'Weather bot' demo (unchanged)")
        except Exception:
            log.exception("Failed to migrate legacy demo")

    def _seed_defaults(self):
        try:
            if self.count() == 0:
                self.create(
                    name="Environment telemetry (example)",
                    code=DEFAULT_ENV_TELEMETRY_SCRIPT,
                    interval_seconds=6 * 3600,   # every 6 hours
                    enabled=False,
                    target_channels="0",          # LongFast
                    target_dest="",               # broadcast
                )
                log.info("Seeded default env-telemetry example script")
        except Exception:
            log.exception("Failed to seed example script")

    # ---- CRUD ----
    def list_all(self) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT * FROM scripts ORDER BY id ASC").fetchall()
            return [dict(r) for r in rows]

    def get_by_id(self, sid: int) -> Optional[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT * FROM scripts WHERE id=?", (sid,)).fetchone()
            return dict(row) if row else None

    def get_enabled(self) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT * FROM scripts WHERE enabled=1 AND interval_seconds>0"
            ).fetchall()
            return [dict(r) for r in rows]

    def count(self) -> int:
        with self._lock, self._conn() as c:
            return int(c.execute("SELECT COUNT(*) FROM scripts").fetchone()[0])

    def create(self, name: str, code: str = "",
               interval_seconds: int = 0, enabled: bool = False,
               target_channels: str = "0",
               target_dest: str = "") -> int:
        with self._lock, self._conn() as c:
            cur = c.execute(
                "INSERT INTO scripts(name, code, interval_seconds, enabled, "
                "target_channels, target_dest) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (name, code, int(interval_seconds), 1 if enabled else 0,
                 target_channels or "0", target_dest or "")
            )
            return cur.lastrowid

    def update(self, sid: int, **fields):
        if not fields:
            return
        keys = list(fields.keys())
        vals = [fields[k] for k in keys]
        sets = ", ".join(f"{k}=?" for k in keys)
        with self._lock, self._conn() as c:
            c.execute(
                f"UPDATE scripts SET {sets}, updated_at=strftime('%s','now') WHERE id=?",
                (*vals, sid)
            )

    def delete(self, sid: int):
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM scripts WHERE id=?", (sid,))

    def set_run_result(self, sid: int, status: str, output: str,
                       next_run: Optional[int] = None):
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE scripts SET last_run=?, last_status=?, last_output=?, "
                "next_run=COALESCE(?, next_run), updated_at=strftime('%s','now') "
                "WHERE id=?",
                (int(time.time()), status, output[:50000], next_run, sid)
            )
