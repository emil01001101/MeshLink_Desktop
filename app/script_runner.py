"""
Script runner + scheduler for the Automation tab.

The runner executes user-defined Python scripts on background threads, capturing
their stdout/stderr and any exceptions. Scripts have access to a small API
that lets them interact with the Meshtastic device.

The scheduler ticks every 5 seconds and runs any enabled script whose
next_run timestamp is in the past.

Exposed to scripts (as built-in names — no imports needed):

    Messaging:
        send_text(text, channel=None, dest=None) → bool
            channel/dest=None → use the channels + destination set in the UI
            channel=int       → override channel index for this call
            dest='!hex'       → send as DM (overrides UI target)
        send_dm(node_id, text)                   → bool
            shortcut for send_text(text, dest=node_id)

    Telemetry helpers (V20-turn6):
        local_env()        → environmentMetrics dict (may be empty)
        local_device()     → deviceMetrics dict (battery, voltage, util)
        local_position()   → position dict (lat, lon, alt) — may be empty

    Channel helpers:
        channels()         → list of active channels [{index, name, role}]
        channel_by_name(n) → channel dict or None
        my_channels        → list of channel indices selected for this script

    Node info:
        list_nodes()       → list of node dicts
        get_node(node_id)  → node dict or None

    State:
        is_connected       → bool variable
        my_node_id         → '!hex' or None

    Logging:
        log(*msg)          → print to script output

All standard library modules are importable as usual.
"""

from __future__ import annotations

import io
import sys
import time
import logging
import threading
import traceback
import contextlib
from typing import Callable, Optional, Any, Dict, List

from PySide6.QtCore import QObject, Signal, QTimer

from .scripts_db import ScriptsDB

log = logging.getLogger("meshlink.scripts")


# ===========================================================================
# Script API exposed to user code
# ===========================================================================
class ScriptAPI:
    """Wraps the MeshtasticManager with a stable, simple API for scripts."""

    def __init__(self, manager, log_callback: Callable[[str], None],
                 target_channels: Optional[List[int]] = None,
                 target_dest: str = ""):
        self._manager = manager
        self._log = log_callback
        # Channels + destination configured in the UI for this script.
        # send_text() without explicit channel/dest uses these.
        self._target_channels: List[int] = list(target_channels or [0])
        self._target_dest: str = (target_dest or "").strip()
        # Treat "^all" and "!ffffffff" both as broadcast (empty dest)
        if self._target_dest in ("^all", "!ffffffff"):
            self._target_dest = ""

    # --- Properties (queried at call time) -------------------------------
    @property
    def is_connected(self) -> bool:
        return bool(self._manager.is_connected)

    @property
    def my_node_id(self) -> Optional[str]:
        return self._manager.my_node_id

    @property
    def my_channels(self) -> List[int]:
        """Channels selected for this script in the UI."""
        return list(self._target_channels)

    # --- Messaging --------------------------------------------------------
    def send_text(self, text: str, channel: Optional[int] = None,
                  dest: Optional[str] = None) -> bool:
        """Send a text message.

        Calling without arguments uses the channels + target set in the UI:
            • If "Direct message" was selected, sends ONE DM to that node.
            • Otherwise broadcasts on every channel selected, returning True
              only if EVERY send succeeded.

        Per-call overrides:
            channel=N   send on this specific channel index instead
            dest='!hex' send as DM to this node (overrides UI target)
        """
        if not self._manager.is_connected:
            self._log("[api] not connected; cannot send_text")
            return False
        if not text or not str(text).strip():
            return False

        # Resolve per-call overrides
        if channel is not None:
            channels = [int(channel)]
        else:
            channels = self._target_channels or [0]

        if dest is not None:
            target_dest = dest if dest not in ("^all", "!ffffffff") else ""
        else:
            target_dest = self._target_dest

        # DM: always one packet, ignore multi-channel
        if target_dest:
            ch = channels[0] if channels else 0
            ok = bool(self._manager.send_text(
                text, channel_index=ch, destination_id=target_dest))
            if ok:
                self._log(f"[api] DM → {target_dest} on ch{ch}")
            return ok

        # Broadcast on every selected channel
        all_ok = True
        for ch in channels:
            ok = bool(self._manager.send_text(
                text, channel_index=int(ch), destination_id=None))
            if not ok:
                all_ok = False
            self._log(f"[api] broadcast → ch{ch}: "
                      f"{'✓' if ok else '✗'}")
        return all_ok

    def send_dm(self, node_id: str, text: str) -> bool:
        """Shortcut for a direct message."""
        return self.send_text(text, channel=0, dest=node_id)

    # --- Channel helpers --------------------------------------------------
    def channels(self) -> List[Dict[str, Any]]:
        """Return active channels: [{index, name, role}, …]."""
        try:
            iface = self._manager.interface
            if not iface:
                return []
            out = []
            for ch in (iface.localNode.channels or []):
                role_int = int(getattr(ch, "role", 0) or 0)
                if role_int == 0:
                    continue
                name = ""
                if ch.settings and ch.settings.name:
                    name = ch.settings.name
                elif role_int == 1:
                    name = "LongFast"
                role = "PRIMARY" if role_int == 1 else "SECONDARY"
                out.append({"index": ch.index, "name": name, "role": role})
            return out
        except Exception:
            return []

    def channel_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Look up a channel by (case-insensitive) name."""
        name_l = (name or "").strip().lower()
        for ch in self.channels():
            if ch["name"].lower() == name_l:
                return ch
        return None

    # --- Telemetry helpers ------------------------------------------------
    def _local_node(self) -> Optional[Dict[str, Any]]:
        """Return the local node's dict from iface.nodes (or None)."""
        try:
            iface = self._manager.interface
            if not iface or not iface.nodes:
                return None
            my_id = self._manager.my_node_id
            if my_id and my_id in iface.nodes:
                return iface.nodes[my_id]
            # Fallback: find a node whose user.id matches our number
            mi = getattr(iface, "myInfo", None)
            if mi is not None:
                for n in iface.nodes.values():
                    if (n.get("num") == getattr(mi, "my_node_num", None)):
                        return n
            return None
        except Exception:
            return None

    def local_env(self) -> Dict[str, Any]:
        """Return the LOCAL node's most recent environmentMetrics dict.

        Keys (when present, depending on sensor): temperature,
        relativeHumidity, barometricPressure, gasResistance, iaq, lux,
        whiteLux, uvLux, irLux, windSpeed, windDirection, windGust,
        windLull, rainfall1h, rainfall24h, distance, weight,
        radiation, soilMoisture, soilTemperature, voltage, current,
        ch1Voltage, ch1Current, ch2Voltage, ch2Current, ch3Voltage,
        ch3Current. Returns {} if unavailable.
        """
        n = self._local_node() or {}
        return dict(n.get("environmentMetrics") or {})

    def local_device(self) -> Dict[str, Any]:
        """Return the LOCAL node's most recent deviceMetrics dict.

        Keys (when present): batteryLevel, voltage, channelUtilization,
        airUtilTx, uptimeSeconds. Returns {} if unavailable.
        """
        n = self._local_node() or {}
        return dict(n.get("deviceMetrics") or {})

    def local_position(self) -> Dict[str, Any]:
        """Return the LOCAL node's most recent position dict (or {})."""
        n = self._local_node() or {}
        return dict(n.get("position") or {})

    # --- Node info --------------------------------------------------------
    def list_nodes(self) -> List[Dict[str, Any]]:
        try:
            iface = self._manager.interface
            return list((iface.nodes or {}).values()) if iface else []
        except Exception:
            return []

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        try:
            iface = self._manager.interface
            return (iface.nodes or {}).get(node_id) if iface else None
        except Exception:
            return None


# ===========================================================================
# Script runner — executes a single script on a background thread
# ===========================================================================
class ScriptRunner(QObject):
    """Runs scripts on daemon threads, emits results.

    Signals:
        scriptStarted(int)                  — script id
        scriptLine(int, str)                — incremental stdout line
        scriptFinished(int, str, str)       — id, status ('ok'|'error'), full output
    """

    scriptStarted  = Signal(int)
    scriptLine     = Signal(int, str)
    scriptFinished = Signal(int, str, str)

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager

    def run_async(self, script_id: int, code: str,
                  target_channels: Optional[List[int]] = None,
                  target_dest: str = ""):
        """Run the given code in a background daemon thread.

        target_channels / target_dest are forwarded to ScriptAPI so
        send_text() without arguments knows where to deliver.
        """
        t = threading.Thread(
            target=self._run, args=(script_id, code,
                                    target_channels, target_dest),
            daemon=True, name=f"script-{script_id}"
        )
        t.start()

    def _run(self, script_id: int, code: str,
             target_channels: Optional[List[int]], target_dest: str):
        self.scriptStarted.emit(script_id)
        buffer: List[str] = []

        def emit_line(*args):
            line = " ".join(str(a) for a in args)
            buffer.append(line)
            self.scriptLine.emit(script_id, line)

        runner_self = self

        class _Stream(io.TextIOBase):
            def write(_self, s):
                if s and s != "\n":
                    for line in s.rstrip("\n").split("\n"):
                        if line:
                            buffer.append(line)
                            try:
                                runner_self.scriptLine.emit(script_id, line)
                            except Exception:
                                pass
                return len(s)
            def flush(_self): pass

        api = ScriptAPI(self.manager, emit_line,
                        target_channels=target_channels,
                        target_dest=target_dest)

        # Builtins exposed without explicit import
        script_globals: Dict[str, Any] = {
            "__name__": "__script__",
            "__builtins__": __builtins__,
            "mesh":           api,
            "send_text":      api.send_text,
            "send_dm":        api.send_dm,
            "list_nodes":     api.list_nodes,
            "get_node":       api.get_node,
            "channels":       api.channels,
            "channel_by_name":api.channel_by_name,
            "local_env":      api.local_env,
            "local_device":   api.local_device,
            "local_position": api.local_position,
            "log":            emit_line,
            "is_connected":   api.is_connected,
            "my_node_id":     api.my_node_id,
            "my_channels":    api.my_channels,
        }

        stream = _Stream()
        try:
            with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
                compiled = compile(code, f"<script-{script_id}>", "exec")
                exec(compiled, script_globals)
            status = "ok"
        except Exception:
            status = "error"
            tb = traceback.format_exc()
            for line in tb.rstrip().split("\n"):
                buffer.append(line)
                self.scriptLine.emit(script_id, line)
        full_output = "\n".join(buffer)
        self.scriptFinished.emit(script_id, status, full_output)


# ===========================================================================
# Scheduler — periodically polls DB and runs scripts whose next_run is in past
# ===========================================================================
class ScriptScheduler(QObject):
    """Runs scripts on their configured interval."""

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.runner = ScriptRunner(manager, self)
        self.runner.scriptFinished.connect(self._on_finished)
        self.timer = QTimer(self)
        self.timer.setInterval(5000)  # check every 5 seconds
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        log.info("Script scheduler started")

    @staticmethod
    def _parse_channels_csv(s: Any) -> List[int]:
        """Parse a CSV string like "0,1" into [0, 1]. Empty → [0]."""
        if not s:
            return [0]
        out: List[int] = []
        for tok in str(s).split(","):
            tok = tok.strip()
            if not tok:
                continue
            try:
                out.append(int(tok))
            except ValueError:
                pass
        return out or [0]

    def _tick(self):
        try:
            now = int(time.time())
            for script in ScriptsDB.get().get_enabled():
                if (script.get("next_run") or 0) <= now:
                    if script.get("last_status") == "running":
                        continue  # already running, don't double-fire
                    log.info(f"Scheduler firing script #{script['id']} "
                             f"({script['name']})")
                    ScriptsDB.get().update(
                        script["id"],
                        last_status="running",
                        next_run=now + int(script.get("interval_seconds") or 60),
                    )
                    self.runner.run_async(
                        script["id"], script["code"],
                        target_channels=self._parse_channels_csv(
                            script.get("target_channels")),
                        target_dest=script.get("target_dest") or "",
                    )
        except Exception:
            log.exception("Scheduler tick failed")

    def _on_finished(self, sid: int, status: str, output: str):
        try:
            row = ScriptsDB.get().get_by_id(sid)
            if not row:
                return
            interval = int(row.get("interval_seconds") or 0)
            next_run = int(time.time()) + interval if interval > 0 else None
            ScriptsDB.get().set_run_result(sid, status, output, next_run)
            log.info(f"Script #{sid} finished: {status}")
        except Exception:
            log.exception("Failed to save script result")

    def trigger_now(self, script_id: int):
        """Manually run a script (out-of-band; doesn't affect schedule)."""
        row = ScriptsDB.get().get_by_id(script_id)
        if row:
            self.runner.run_async(
                script_id, row["code"],
                target_channels=self._parse_channels_csv(
                    row.get("target_channels")),
                target_dest=row.get("target_dest") or "",
            )
