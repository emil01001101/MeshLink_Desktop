"""
Console / Debug page — production version.

Provides a CLI-style interface for advanced operations on the connected
Meshtastic device. All output and labels are in English.

Sections of this file:
  1. _ConsoleInput          — QLineEdit subclass with command history
  2. ConsolePage            — main widget (toolbar + output + input bar)
  3. Command handlers       — one method per command
  4. Output helpers         — _println, _hr, _kv
  5. Utility functions      — _ts, _humanize_age, _normalize_node_id

──────────────────────────────────────────────────────────────────────────
Available commands (type `help` to see them in-app):

  Device info
    info                              firmware, hardware, LoRa config
    nodes                             list known mesh nodes
    channels                          list channels with index and role
    qr                                primary channel sharing URL
    ports                             list available serial ports
    stats                             local router statistics (latest)

  Messaging
    sendtext <text>                   broadcast on primary channel
    send <ch> <dest|^all> <text>      send on specific channel / DM

  Remote node actions
    traceroute <nodeId>               discover the mesh path
    request-position <nodeId>         request GPS position
    request-telemetry <nodeId>        request telemetry

  Local device configuration
    set-position <lat> <lon> [alt]    set fixed GPS position
                                      (CLI equivalent: --setlat/--setlon/--setalt)
    remove-position                   remove fixed position (restore GPS)
    position-info                     show current position config
    set-owner <long> <short>          set node names (short ≤ 4 chars)

  Device control (with confirmation)
    reboot                            restart the device
    shutdown                          power off the device
    reset-nodedb                      erase node DB
    factory-reset                     reset ALL device settings to factory

  Config
    export-config                     export device config as YAML

  Console
    clear                             clear console output
    help, ?                           show this help text
"""

from __future__ import annotations

import shlex
import time
import logging
from datetime import datetime
from typing import Optional, List

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QKeyEvent, QTextCursor, QColor, QTextCharFormat
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QPlainTextEdit, QCheckBox, QFrame, QFileDialog, QMessageBox, QComboBox
)

from ..connection import MeshtasticManager
from ..logging_bridge import LogBus
from ..theme import Colors
from ..i18n import t   # for confirm dialogs that match other pages' wording

log = logging.getLogger("meshlink.console")


# ===========================================================================
# 1. INPUT WIDGET WITH HISTORY
# ===========================================================================
class _ConsoleInput(QLineEdit):
    """QLineEdit subclass supporting Up/Down arrow history navigation."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._history: List[str] = []
        self._history_idx: int = -1

    def keyPressEvent(self, e: QKeyEvent):  # noqa: N802
        if e.key() == Qt.Key_Up and self._history:
            if self._history_idx < len(self._history) - 1:
                self._history_idx += 1
                self.setText(self._history[-(self._history_idx + 1)])
            return
        if e.key() == Qt.Key_Down:
            if self._history_idx > 0:
                self._history_idx -= 1
                self.setText(self._history[-(self._history_idx + 1)])
            elif self._history_idx == 0:
                self._history_idx = -1
                self.clear()
            return
        super().keyPressEvent(e)

    def add_to_history(self, cmd: str):
        if cmd and (not self._history or self._history[-1] != cmd):
            self._history.append(cmd)
            if len(self._history) > 200:
                self._history = self._history[-200:]
        self._history_idx = -1


# ===========================================================================
# 2. CONSOLE PAGE
# ===========================================================================
class ConsolePage(QWidget):

    HELP_TEXT = (
        "Available commands (CLI -- prefix is accepted):\n"
        "\n"
        "  ── Device info ──────────────────────────────────────────────\n"
        "  info                              firmware, hardware, LoRa\n"
        "  nodes                             list known mesh nodes\n"
        "  channels                          list channels\n"
        "  qr                                primary channel sharing URL\n"
        "  qr-all                            URLs for all configured channels\n"
        "  ports                             list available serial ports\n"
        "  stats                             local router statistics\n"
        "  mesh-health                       RX/TX rates + channel util\n"
        "                                    + diagnostic hint\n"
        "  version                           app, library, Qt versions\n"
        "  support                           diagnostic dump for bug reports\n"
        "\n"
        "  ── Messaging ────────────────────────────────────────────────\n"
        "  sendtext <text>                   broadcast on primary channel\n"
        "  send <ch> <dest|^all> <text>      send on specific channel / DM\n"
        "  reply                             toggle echo-back mode\n"
        "\n"
        "  ── Remote node actions ──────────────────────────────────────\n"
        "  traceroute <nodeId>               discover the mesh path\n"
        "  request-position <nodeId>         request GPS position\n"
        "  request-telemetry <nodeId>        request telemetry\n"
        "      Example: traceroute !ba4bf9d0\n"
        "\n"
        "  ── Remote GPIO (requires Remote Hardware module on target) ──\n"
        "  gpio-rd <nodeId> <pin_mask>       read GPIO pins\n"
        "  gpio-wr <nodeId> <pin_mask> <val> write GPIO pins (mask + value)\n"
        "  gpio-wrb <nodeId> <pin> <0|1>     write a single pin (convenience)\n"
        "  gpio-watch <nodeId> <pin_mask>    subscribe to changes (0 = stop)\n"
        "      Example: gpio-rd !ba4bf9d0 0xFF\n"
        "      Example: gpio-wrb !ba4bf9d0 4 1   (set pin 4 high)\n"
        "      Example: gpio-watch !ba4bf9d0 0x0F    (watch pins 0..3)\n"
        "\n"
        "  ── File operations ──────────────────────────────────────────\n"
        "  delete-file <path>                delete a file from flash\n"
        "      Example: delete-file /prefs/cannedMessages.proto\n"
        "\n"
        "  ── Bluetooth ────────────────────────────────────────────────\n"
        "  ble-scan                          scan for nearby BLE devices\n"
        "\n"
        "  ── Channel management ───────────────────────────────────────\n"
        "  ch-add <name>                     add a SECONDARY channel\n"
        "  ch-del <index>                    delete channel at index (>0)\n"
        "  ch-set <field> <value> <index>    set a channel parameter\n"
        "      Fields: name, uplink_enabled, downlink_enabled,\n"
        "              position_precision, psk\n"
        "  seturl <url>                      apply a Meshtastic channel URL\n"
        "                                    (replaces all channels + LoRa)\n"
        "  pos-fields [FIELD...]             show or set position flags\n"
        "      Valid: ALTITUDE, ALTITUDE_MSL, GEOIDAL_SEPARATION, DOP,\n"
        "             HVDOP, SATINVIEW, SEQ_NO, TIMESTAMP, HEADING, SPEED\n"
        "\n"
        "  ── Canned messages + ringtone ───────────────────────────────\n"
        "  set-canned-message \"a|b|c\"        set canned messages (|-separated)\n"
        "  get-canned-message                show current canned messages\n"
        "  set-ringtone \"RTTTL\"              set notification ringtone\n"
        "  get-ringtone                      show current ringtone\n"
        "\n"
        "  ── Local device configuration ───────────────────────────────\n"
        "  set-position <lat> <lon> [alt]    set fixed GPS position\n"
        "      Example: set-position 41.785333 0.805527 100\n"
        "      (CLI equivalent: --setlat 41.785333 --setlon 0.805527 --setalt 100)\n"
        "  remove-position                   remove fixed position\n"
        "  send-position                     broadcast current position once\n"
        "  position-info                     show current position config\n"
        "  set-owner <long> <short>          set both names\n"
        "  set-owner-long <name>             set long name only\n"
        "  set-owner-short <abbrev>          set short name only (max 4 chars)\n"
        "      Example: set-owner \"My T-Beam\" TBM\n"
        "  set-ham <callsign>                enable HAM mode (no encryption)\n"
        "  set-region <REGION>               set LoRa region\n"
        "      Valid: US, EU_868, EU_433, CN, JP, ANZ, KR, TW, RU, IN, NZ_865,\n"
        "             TH, LORA_24, UA_433, UA_868, MY_433, MY_919, SG_923\n"
        "  set-preset <PRESET>               set modem preset\n"
        "      Valid: LONG_FAST, LONG_SLOW, VERY_LONG_SLOW, MEDIUM_SLOW,\n"
        "             MEDIUM_FAST, SHORT_SLOW, SHORT_FAST, LONG_MODERATE,\n"
        "             SHORT_TURBO\n"
        "  ch-vlongslow / ch-longslow / ch-longfast / ch-medslow /\n"
        "  ch-medfast / ch-shortslow / ch-shortfast   (preset shortcuts)\n"
        "  set <section.field> <value>       generic config setter\n"
        "      Example: set lora.hop_limit 5\n"
        "  get <section.field>               generic config getter\n"
        "      Example: get lora.region\n"
        "  remove-node <nodeId>              remove specific node from DB\n"
        "  waypoint <name> <lat> <lon> [desc] broadcast a named waypoint\n"
        "  request-info <nodeId>             request user info via admin\n"
        "\n"
        "  ── Device control (asks confirmation) ───────────────────────\n"
        "  reboot                            restart the device\n"
        "  shutdown                          power off the device\n"
        "  reset-nodedb                      erase node DB\n"
        "  factory-reset                     reset to factory defaults\n"
        "\n"
        "  ── Config import / export ───────────────────────────────────\n"
        "  export-config                     export device config as YAML\n"
        "  configure <path-to-yaml>          apply a YAML config file\n"
        "\n"
        "  ── Console ──────────────────────────────────────────────────\n"
        "  clear                             clear console output\n"
        "  help, ?                           show this help\n"
        "\n"
        "Tips:\n"
        "  • Arrow Up / Down navigates command history.\n"
        "  • Tick the boxes above to stream live raw packets or the\n"
        "    internal Python log.\n"
        "  • Node IDs may be written with or without the leading '!'."
    )

    def __init__(self, manager: MeshtasticManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self._show_raw = False
        self._show_pylog = True
        self._filter_level = logging.INFO
        # cache of latest local_stats (populated from TELEMETRY packets)
        self._latest_local_stats: dict = {}
        # V20-turn5: --reply mode — when active, every incoming text message
        # is echoed back on the same channel with metadata.
        self._reply_mode = False
        self._build_ui()
        self._connect_signals()
        self._show_welcome()

    # -----------------------------------------------------------------------
    # UI
    # -----------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 20)
        root.setSpacing(10)

        # ── toolbar ──
        tb = QHBoxLayout()
        tb.setSpacing(8)

        self.cb_raw = QCheckBox("Raw packets")
        self.cb_raw.setToolTip("Stream every received packet as JSON")
        self.cb_raw.toggled.connect(self._toggle_raw)
        tb.addWidget(self.cb_raw)

        self.cb_pylog = QCheckBox("Python log")
        self.cb_pylog.setChecked(True)
        self.cb_pylog.setToolTip("Stream internal application log messages")
        self.cb_pylog.toggled.connect(self._toggle_pylog)
        tb.addWidget(self.cb_pylog)

        tb.addWidget(QLabel("Level:"))
        self.lvl_combo = QComboBox()
        for name in ("DEBUG", "INFO", "WARNING", "ERROR"):
            self.lvl_combo.addItem(name)
        self.lvl_combo.setCurrentText("INFO")
        self.lvl_combo.currentTextChanged.connect(self._on_level_changed)
        self.lvl_combo.setFixedWidth(110)
        tb.addWidget(self.lvl_combo)

        tb.addStretch(1)

        self.btn_save = QPushButton("💾 Save")
        self.btn_save.setToolTip("Save console output to a file")
        self.btn_save.clicked.connect(self._save_log)
        tb.addWidget(self.btn_save)

        self.btn_clear = QPushButton("🗑 Clear")
        self.btn_clear.setToolTip("Clear console output")
        self.btn_clear.clicked.connect(self._clear_log)
        tb.addWidget(self.btn_clear)

        root.addLayout(tb)

        # ── output ──
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(5000)  # cap memory usage
        mono = QFont("Consolas", 10)
        mono.setStyleHint(QFont.Monospace)
        self.console.setFont(mono)
        self.console.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {Colors.BG_CONSOLE};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER};
                border-radius: 10px;
                padding: 12px;
                selection-background-color: {Colors.PRIMARY};
                selection-color: {Colors.TEXT_ON_PRIMARY};
            }}
        """)
        root.addWidget(self.console, 1)

        # ── input bar ──
        input_card = QFrame()
        input_card.setObjectName("Card")
        ic = QHBoxLayout(input_card)
        ic.setContentsMargins(14, 10, 12, 10)
        ic.setSpacing(8)

        prompt = QLabel("›")
        prompt.setStyleSheet(
            f"color: {Colors.PRIMARY}; font-weight: 700; "
            f"font-family: Consolas, monospace; font-size: 16px;"
        )
        ic.addWidget(prompt)

        self.input = _ConsoleInput()
        self.input.setPlaceholderText(
            "Type a command…  e.g.  info  ·  nodes  ·  sendtext Hello  ·  "
            "traceroute !ba4bf9d0  ·  set-position 41.785 0.805 100"
        )
        self.input.setFont(mono)
        self.input.returnPressed.connect(self._run_command)
        ic.addWidget(self.input, 1)

        self.btn_run = QPushButton("▶ Run")
        self.btn_run.setObjectName("PrimaryButton")
        self.btn_run.clicked.connect(self._run_command)
        ic.addWidget(self.btn_run)
        root.addWidget(input_card)

    def _show_welcome(self):
        self._println("◉ Meshtastic Console", color=Colors.PRIMARY, bold=True)
        self._println(
            "Type 'help' for the full command list, or '?' for a short hint.",
            color=Colors.TEXT_DIM
        )
        self._println("")

    # -----------------------------------------------------------------------
    # SIGNALS
    # -----------------------------------------------------------------------
    def _connect_signals(self):
        self.manager.stateChanged.connect(self._on_state)
        self.manager.rawPacketReceived.connect(self._on_raw_packet)
        self.manager.errorMessage.connect(self._on_manager_error)
        # V20-turn5: subscribe to text messages too, for --reply mode
        self.manager.textMessageReceived.connect(self._on_text_received_for_reply)
        # capture Python log bus (signal signature: str, str, str)
        LogBus.instance().logMessage.connect(self._on_python_log)

    def _on_text_received_for_reply(self, msg: dict):
        """When --reply is active, echo every incoming TEXT back on the
        same channel with a short metadata footer (sender, SNR, time).
        """
        if not self._reply_mode:
            return
        # Don't reply to our own broadcasts (would create a loop)
        my_id = self.manager.my_node_id
        from_id = msg.get("fromId") or ""
        if from_id == my_id:
            return
        text = (msg.get("text") or "").strip()
        if not text:
            return
        ch = int(msg.get("channel", 0))
        snr = msg.get("rxSnr")
        snr_s = f"{snr:+.1f}dB" if snr is not None else "?"
        reply = f"📡 RX from {from_id} (SNR {snr_s}): {text}"
        # Trim to LoRa packet size
        if len(reply) > 200:
            reply = reply[:197] + "…"
        try:
            self.manager.send_text(reply, channel_index=ch)
            self._println(f"  ⮕  reply → ch{ch}: {reply}",
                          color=Colors.TEXT_DIM)
        except Exception:
            log.exception("reply-mode send_text failed")

    def _toggle_raw(self, checked: bool):
        self._show_raw = bool(checked)

    def _toggle_pylog(self, checked: bool):
        self._show_pylog = bool(checked)

    def _on_level_changed(self, name: str):
        self._filter_level = getattr(logging, name, logging.INFO)

    def _on_state(self, state: str):
        if state == "ready":
            self._println("✓ Connected", color=Colors.SUCCESS, bold=True)
        elif state == "idle":
            self._println("✗ Disconnected", color=Colors.TEXT_DIM)
        elif state == "failed":
            self._println("✗ Connection failed", color=Colors.DANGER)
        elif state == "opening":
            self._println("Connecting…", color=Colors.INFO)
        elif state == "waiting_config":
            self._println("Awaiting device config…", color=Colors.INFO)
        elif state == "loading":
            self._println("Loading nodes and channels…", color=Colors.INFO)

    def _on_manager_error(self, msg: str):
        self._println(f"[manager] {msg}", color=Colors.DANGER)

    def _on_raw_packet(self, packet: dict):
        # cache local_stats for `stats` command
        try:
            dec = (packet.get("decoded") or {}) if isinstance(packet, dict) else {}
            tel = dec.get("telemetry") or {}
            stats = tel.get("localStats") or tel.get("local_stats")
            if stats:
                self._latest_local_stats = dict(stats)
        except Exception:
            pass
        if not self._show_raw:
            return
        try:
            import json
            text = json.dumps(packet, default=str)
            if len(text) > 600:
                text = text[:600] + "…"
            self._println(f"[{_ts()}] [PKT] {text}", color=Colors.TEXT_DIM)
        except Exception:
            self._println(f"[{_ts()}] [PKT] {packet}", color=Colors.TEXT_DIM)

    def _on_python_log(self, level_name: str, logger_name: str, formatted_msg: str):
        """Handler for LogBus.logMessage(str, str, str) = (level, name, msg).

        The formatted message already contains timestamp/level/name/msg
        from the logging.Formatter, so we just emit it color-coded.
        """
        if not self._show_pylog:
            return
        lvl_no = getattr(logging, level_name, logging.INFO)
        if lvl_no < self._filter_level:
            return
        color = {
            "DEBUG":    Colors.TEXT_DIM,
            "INFO":     Colors.TEXT_SECONDARY,
            "WARNING":  Colors.WARNING,
            "ERROR":    Colors.DANGER,
            "CRITICAL": Colors.DANGER,
        }.get(level_name, Colors.TEXT_PRIMARY)
        self._println(formatted_msg, color=color)

    # -----------------------------------------------------------------------
    # COMMAND DISPATCH
    # -----------------------------------------------------------------------
    def _run_command(self):
        raw_input = self.input.text()
        # BUG 22 (V20-turn2): tolerate multi-line pastes from the docs
        # (e.g. someone copies a block of "--set ..." lines from the
        # README). Each non-empty line is run as its own command.
        # Newlines in QLineEdit are rare but can happen via custom paste
        # paths or programmatic setText — we handle both \r and \n.
        lines = [l.strip().lstrip("-") .strip()
                 for l in raw_input.replace("\r", "\n").split("\n")
                 if l.strip()]
        if not lines:
            return
        self.input.clear()
        # Add the FIRST line to history (most useful for arrow-up recall);
        # for a multi-line paste we still treat each as separate command.
        self.input.add_to_history(raw_input.strip())
        for line in lines:
            self._dispatch_line(line)

    def _dispatch_line(self, raw: str):
        """Parse and dispatch a single command line.

        Extracted from the body of _run_command so multi-line pastes can
        be processed one command at a time.
        """
        if not raw:
            return
        self._println(f"› {raw}", color=Colors.PRIMARY, bold=True)

        # tolerate CLI muscle memory: strip leading "--"
        if raw.startswith("--"):
            raw = raw[2:]

        try:
            parts = shlex.split(raw)
        except ValueError as e:
            self._println(f"Parse error: {e}", color=Colors.DANGER)
            return
        if not parts:
            return

        cmd = parts[0].lower()
        args = parts[1:]

        # Commands that don't need a connection
        offline_handlers = {
            "help":     lambda: self._println(self.HELP_TEXT, color=Colors.TEXT_SECONDARY),
            "?":        lambda: self._println(self.HELP_TEXT, color=Colors.TEXT_SECONDARY),
            "clear":    self._clear_log,
            "ports":    self._cmd_ports,
            # V20-turn5: CLI parity additions that work offline
            "version":  self._cmd_version,
            "ble-scan": self._cmd_ble_scan,
        }
        if cmd in offline_handlers:
            try:
                offline_handlers[cmd]()
            except Exception as e:
                log.exception("offline command failed")
                self._println(f"[exception] {e}", color=Colors.DANGER)
            return

        # All remaining commands need an active connection
        if not self.manager.is_connected:
            self._println("Not connected. Connect to a device first.",
                          color=Colors.WARNING)
            return

        handlers = {
            # info
            "info":              self._cmd_info,
            "nodes":             self._cmd_nodes,
            "channels":          self._cmd_channels,
            "qr":                self._cmd_qr,
            "qr-all":            self._cmd_qr_all,
            "stats":             self._cmd_stats,
            "support":           self._cmd_support,
            # V20-turn8: mesh-health diagnostic (RX/TX counters, channel
            # util) to investigate "I haven't received anything in days"
            "mesh-health":       self._cmd_mesh_health,
            # messaging
            "sendtext":          lambda: self._cmd_sendtext(args),
            "send":              lambda: self._cmd_send(args),
            # remote actions
            "traceroute":        lambda: self._cmd_traceroute(args),
            "request-position":  lambda: self._cmd_request_position(args),
            "request-telemetry": lambda: self._cmd_request_telemetry(args),
            # V20-turn4: remote GPIO + file ops
            "gpio-rd":           lambda: self._cmd_gpio_rd(args),
            "gpio-wr":           lambda: self._cmd_gpio_wr(args),
            "gpio-wrb":          lambda: self._cmd_gpio_wrb(args),
            "gpio-watch":        lambda: self._cmd_gpio_watch(args),
            "delete-file":       lambda: self._cmd_delete_file(args),
            # V20-turn5: canned messages + ringtone (admin admin messages)
            "set-canned-message": lambda: self._cmd_set_canned_message(args),
            "get-canned-message": self._cmd_get_canned_message,
            "set-ringtone":       lambda: self._cmd_set_ringtone(args),
            "get-ringtone":       self._cmd_get_ringtone,
            # V20-turn5: channel URL + management shortcuts
            "seturl":             lambda: self._cmd_seturl(args),
            "pos-fields":         lambda: self._cmd_pos_fields(args),
            "ch-add":             lambda: self._cmd_ch_add(args),
            "ch-del":             lambda: self._cmd_ch_del(args),
            "ch-set":             lambda: self._cmd_ch_set(args),
            "configure":          lambda: self._cmd_configure(args),
            # V20-turn5: --reply mode (listen + echo back)
            "reply":              self._cmd_reply,
            # V20-turn5: CLI preset aliases (parity with --ch-vlongslow etc).
            # Each is a one-liner that calls _cmd_set_preset with the
            # corresponding name — keeps muscle memory of CLI users intact.
            "ch-vlongslow":       lambda: self._cmd_set_preset(["VERY_LONG_SLOW"]),
            "ch-longslow":        lambda: self._cmd_set_preset(["LONG_SLOW"]),
            "ch-longfast":        lambda: self._cmd_set_preset(["LONG_FAST"]),
            "ch-medslow":         lambda: self._cmd_set_preset(["MEDIUM_SLOW"]),
            "ch-medfast":         lambda: self._cmd_set_preset(["MEDIUM_FAST"]),
            "ch-shortslow":       lambda: self._cmd_set_preset(["SHORT_SLOW"]),
            "ch-shortfast":       lambda: self._cmd_set_preset(["SHORT_FAST"]),
            # local config
            "set-position":      lambda: self._cmd_set_position(args),
            "remove-position":   self._cmd_remove_position,
            "position-info":     self._cmd_position_info,
            "send-position":     self._cmd_send_position,
            "set-owner":         lambda: self._cmd_set_owner(args),
            "set-owner-long":    lambda: self._cmd_set_owner_long(args),
            "set-owner-short":   lambda: self._cmd_set_owner_short(args),
            "set-ham":           lambda: self._cmd_set_ham(args),
            "set-region":        lambda: self._cmd_set_region(args),
            "set-preset":        lambda: self._cmd_set_preset(args),
            "set":               lambda: self._cmd_set(args),
            "get":               lambda: self._cmd_get(args),
            "remove-node":       lambda: self._cmd_remove_node(args),
            "waypoint":          lambda: self._cmd_waypoint(args),
            "request-info":      lambda: self._cmd_request_info(args),
            # device control
            "reboot":            self._cmd_reboot,
            "shutdown":          self._cmd_shutdown,
            "reset-nodedb":      self._cmd_reset_nodedb,
            "factory-reset":     self._cmd_factory_reset,
            # config
            "export-config":     self._cmd_export_config,
        }

        h = handlers.get(cmd)
        if h is None:
            self._println(
                f"Unknown command: '{cmd}'. Type 'help' for the list.",
                color=Colors.WARNING
            )
            return

        try:
            h()
        except Exception as e:
            log.exception("command failed")
            self._println(f"[exception] {e}", color=Colors.DANGER)

    # =======================================================================
    # 3. COMMAND HANDLERS
    # =======================================================================

    # ── Device info ─────────────────────────────────────────────────────────
    def _cmd_info(self):
        iface = self.manager.interface
        self._hr("DEVICE INFO")

        mi   = getattr(iface, "myInfo",   None)
        meta = getattr(iface, "metadata", None)

        if mi is not None:
            self._kv("My node number",  getattr(mi, "my_node_num",    "?"))
            self._kv("Min app version", getattr(mi, "min_app_version", "?"))
            self._kv("Reboot count",    getattr(mi, "reboot_count",    "?"))

        # Firmware: prefer metadata.firmware_version (always set in 2.5+);
        # fall back to myInfo.firmware_version which is empty on newer builds.
        fw = None
        if meta is not None:
            fw = getattr(meta, "firmware_version", None)
        if not fw and mi is not None:
            fw = getattr(mi, "firmware_version", None)
        self._kv("Firmware", fw or "?")

        if meta is not None:
            hw_raw = getattr(meta, "hw_model", None)
            # hw_model is an enum int (e.g. 43 = HELTEC_V3); try to resolve name
            hw_name = None
            if hw_raw is not None:
                try:
                    from meshtastic.protobuf.mesh_pb2 import HardwareModel
                    hw_name = HardwareModel.Name(int(hw_raw))
                except Exception:
                    hw_name = str(hw_raw)
            self._kv("Hardware model", hw_name or str(hw_raw or "?"))

        my_id = self.manager.my_node_id
        if my_id:
            self._kv("My node ID", my_id)

        ln = getattr(iface, "localNode", None)
        if ln is not None:
            try:
                cfg = ln.localConfig
                lora = getattr(cfg, "lora", None)
                if lora is not None:
                    self._hr("LoRa CONFIGURATION")
                    self._kv("Region",       _enum_name(lora, "region"))
                    self._kv("Modem preset", _enum_name(lora, "modem_preset"))
                    self._kv("Hop limit",    getattr(lora, "hop_limit", "?"))
                    self._kv("TX enabled",   getattr(lora, "tx_enabled", "?"))
                pos = getattr(cfg, "position", None)
                if pos is not None:
                    self._hr("POSITION CONFIG")
                    self._kv("Fixed position",  getattr(pos, "fixed_position", "?"))
                    self._kv("Broadcast secs",  getattr(pos, "position_broadcast_secs", "?"))
            except Exception as e:
                self._println(f"  ⚠ Cannot read config: {e}", color=Colors.WARNING)

    def _cmd_nodes(self):
        iface = self.manager.interface
        nodes = getattr(iface, "nodes", {}) or {}
        if not nodes:
            self._println("No nodes known.", color=Colors.WARNING)
            return
        self._hr(f"ACTIVE NODES ({len(nodes)})")
        self._println(
            f"  {'ID':<12} {'Long name':<22} {'Short':<6} {'HW':<12} "
            f"{'SNR':>6} {'Bat':>5} {'Seen':>6}",
            color=Colors.TEXT_DIM
        )
        def _seen(n):
            return n.get("lastHeard") or 0
        for nid, n in sorted(nodes.items(), key=lambda kv: _seen(kv[1]), reverse=True):
            user = (n.get("user") or {}) if isinstance(n, dict) else {}
            dm   = (n.get("deviceMetrics") or {}) if isinstance(n, dict) else {}
            snr  = n.get("snr") if isinstance(n, dict) else None
            lh   = n.get("lastHeard") if isinstance(n, dict) else None
            bat  = dm.get("batteryLevel")
            bat_s = ("USB" if bat is not None and bat > 100
                     else (f"{int(bat)}%" if bat is not None else "-"))
            snr_s = f"{snr:.1f}" if snr is not None else "-"
            self._println(
                f"  {str(nid):<12} "
                f"{str(user.get('longName')  or '-')[:22]:<22} "
                f"{str(user.get('shortName') or '-')[:6]:<6} "
                f"{str(user.get('hwModel')   or '-')[:12]:<12} "
                f"{snr_s:>6} {bat_s:>5} {_humanize_age(lh):>6}"
            )

    def _cmd_channels(self):
        iface = self.manager.interface
        try:
            chans = iface.localNode.channels or []
        except Exception as e:
            self._println(f"  ✗ Error: {e}", color=Colors.DANGER)
            return
        self._hr("CHANNELS")
        any_shown = False
        for ch in chans:
            role = getattr(ch, "role", None)
            role_int = int(role) if role is not None else 0
            if role_int == 0:  # DISABLED
                continue
            any_shown = True
            settings = getattr(ch, "settings", None)
            name = (getattr(settings, "name", "") or "") if settings else ""
            if not name:
                name = f"Ch{ch.index}"
            role_name = {1: "PRIMARY", 2: "SECONDARY"}.get(role_int, str(role_int))
            self._println(f"  [{ch.index}]  {name:<20}  ({role_name})")
        if not any_shown:
            self._println("  No channels enabled.", color=Colors.TEXT_DIM)

    def _cmd_qr(self):
        try:
            url = self.manager.interface.localNode.getURL()
            self._hr("PRIMARY CHANNEL URL")
            self._println(url, color=Colors.SUCCESS)
            self._println(
                "  Share this URL or its QR code to invite others to your mesh.",
                color=Colors.TEXT_DIM
            )
        except Exception as e:
            self._println(f"  ✗ Error: {e}", color=Colors.DANGER)

    def _cmd_ports(self):
        ports = self.manager.list_serial_ports()
        self._hr("SERIAL PORTS")
        if not ports:
            self._println("  No serial ports found on this system.",
                          color=Colors.WARNING)
            return
        for p in ports:
            self._println(
                f"  {p['device']:<14}  {p.get('description', '') or '-'}"
            )

    def _cmd_stats(self):
        s = self._latest_local_stats
        if not s:
            self._println(
                "  No router statistics yet. The device sends them every few minutes.",
                color=Colors.WARNING
            )
            return
        self._hr("LOCAL STATISTICS (latest)")
        self._kv("Uptime",          _human_uptime(s.get("uptimeSeconds")))
        self._kv("Air util TX",     f"{s.get('airUtilTx', 0):.2f}%")
        if "channelUtilization" in s:
            self._kv("Channel util", f"{s['channelUtilization']:.2f}%")
        self._kv("Packets TX",      s.get("numPacketsTx", "?"))
        self._kv("Packets RX",      s.get("numPacketsRx", "?"))
        self._kv("Packets RX bad",  s.get("numPacketsRxBad", "?"))
        self._kv("RX duplicates",   s.get("numRxDupe", "?"))
        self._kv("TX relay",        s.get("numTxRelay", "?"))
        self._kv("Online nodes",    s.get("numOnlineNodes", "?"))
        self._kv("Total nodes",     s.get("numTotalNodes", "?"))
        heap_t = s.get("heapTotalBytes")
        heap_f = s.get("heapFreeBytes")
        if heap_t and heap_f:
            pct = (heap_f / heap_t) * 100 if heap_t else 0
            self._kv("Heap (free)",
                     f"{heap_f // 1024} KB / {heap_t // 1024} KB ({pct:.1f}% free)")

    # ── Messaging ───────────────────────────────────────────────────────────
    def _cmd_sendtext(self, args):
        if not args:
            self._println("Usage: sendtext <text>", color=Colors.WARNING)
            return
        text = " ".join(args)
        if len(text) > 230:
            self._println(
                f"  ⚠ Text is {len(text)} chars; LoRa payload max ≈ 230 chars.",
                color=Colors.WARNING
            )
        ok = self.manager.send_text(text, channel_index=0)
        if ok:
            self._println(f"  ✓ Broadcast on channel 0: {text}",
                          color=Colors.SUCCESS)
        else:
            self._println("  ✗ Send failed.", color=Colors.DANGER)

    def _cmd_send(self, args):
        if len(args) < 3:
            self._println('Usage: send <ch_index> <dest|^all> <text>',
                          color=Colors.WARNING)
            self._println('  Examples:', color=Colors.TEXT_DIM)
            self._println('    send 0 ^all Hello mesh!', color=Colors.TEXT_DIM)
            self._println('    send 0 !ba4bf9d0 "Private message"',
                          color=Colors.TEXT_DIM)
            return
        try:
            ch_idx = int(args[0])
        except ValueError:
            self._println("Error: ch_index must be an integer (0..7).",
                          color=Colors.DANGER)
            return
        if not (0 <= ch_idx <= 7):
            self._println("Error: ch_index must be 0..7.", color=Colors.DANGER)
            return
        dest = args[1]
        text = " ".join(args[2:])
        dest_param = None if dest in ("^all", "all", "broadcast") \
                          else _normalize_node_id(dest)
        ok = self.manager.send_text(text, channel_index=ch_idx,
                                    destination_id=dest_param)
        if ok:
            tag = "broadcast" if dest_param is None else f"DM to {dest_param}"
            self._println(f"  ✓ ch={ch_idx} {tag}: {text}",
                          color=Colors.SUCCESS)
        else:
            self._println("  ✗ Send failed.", color=Colors.DANGER)

    # ── Remote node actions ─────────────────────────────────────────────────
    def _cmd_traceroute(self, args):
        if not args:
            self._println("Usage: traceroute <nodeId>", color=Colors.WARNING)
            self._println("  Example: traceroute !ba4bf9d0", color=Colors.TEXT_DIM)
            return
        node_id = _normalize_node_id(args[0])
        ok = self.manager.traceroute(node_id)
        if ok:
            self._println(
                f"  ✓ Traceroute request sent to {node_id}. "
                f"The response will appear in raw packets.",
                color=Colors.SUCCESS
            )
            self._println(
                "  Tip: tick 'Raw packets' above to see the response.",
                color=Colors.TEXT_DIM
            )
        else:
            self._println("  ✗ Traceroute failed.", color=Colors.DANGER)

    def _cmd_request_position(self, args):
        if not args:
            self._println("Usage: request-position <nodeId>",
                          color=Colors.WARNING)
            return
        node_id = _normalize_node_id(args[0])
        ok = self.manager.request_position(node_id)
        if ok:
            self._println(
                f"  ✓ Position request sent to {node_id}. "
                f"Response is asynchronous (up to 60s).",
                color=Colors.SUCCESS
            )
        else:
            self._println("  ✗ Request failed.", color=Colors.DANGER)

    def _cmd_request_telemetry(self, args):
        if not args:
            self._println("Usage: request-telemetry <nodeId>",
                          color=Colors.WARNING)
            return
        node_id = _normalize_node_id(args[0])
        # Use the popup-aware version if available
        if hasattr(self.manager, "request_telemetry_with_popup"):
            ok = self.manager.request_telemetry_with_popup(node_id)
        else:
            ok = self.manager.request_telemetry(node_id)
        if ok:
            self._println(
                f"  ✓ Telemetry request sent to {node_id}. "
                f"A popup will open when the response arrives.",
                color=Colors.SUCCESS
            )
        else:
            self._println("  ✗ Request failed.", color=Colors.DANGER)

    # ── V20-turn4: Remote GPIO ──────────────────────────────────────────────
    @staticmethod
    def _parse_mask(s: str) -> int:
        """Accept '0xff', 'ff', '255', '0b1111' — return int."""
        s = s.strip().lower()
        if s.startswith("0x"):    return int(s, 16)
        if s.startswith("0b"):    return int(s, 2)
        # bare hex if contains a-f
        if any(c in s for c in "abcdef"):
            return int(s, 16)
        return int(s)

    def _cmd_gpio_rd(self, args):
        """gpio-rd <nodeId> <pin_mask>"""
        if len(args) < 2:
            self._println("Usage: gpio-rd <nodeId> <pin_mask>",
                          color=Colors.WARNING)
            self._println("  Example: gpio-rd !ba4bf9d0 0xFF "
                          "(read pins 0..7)", color=Colors.TEXT_DIM)
            return
        node_id = _normalize_node_id(args[0])
        try:
            mask = self._parse_mask(args[1])
        except ValueError as e:
            self._println(f"  ✗ Bad mask: {e}", color=Colors.DANGER)
            return
        ok = self.manager.gpio_read(node_id, mask)
        if ok:
            self._println(
                f"  ✓ GPIO read request sent to {node_id} (mask=0x{mask:x}). "
                f"Response arrives as a GPIOS_CHANGED packet; "
                f"toggle 'Raw packets' above to see it.",
                color=Colors.SUCCESS)
        else:
            self._println("  ✗ GPIO read failed.", color=Colors.DANGER)

    def _cmd_gpio_wr(self, args):
        """gpio-wr <nodeId> <pin_mask> <value_mask>"""
        if len(args) < 3:
            self._println("Usage: gpio-wr <nodeId> <pin_mask> <value_mask>",
                          color=Colors.WARNING)
            self._println("  Example: gpio-wr !ba4bf9d0 0x01 0x01 "
                          "(set pin 0 high)", color=Colors.TEXT_DIM)
            self._println("           gpio-wr !ba4bf9d0 0x01 0x00 "
                          "(set pin 0 low)", color=Colors.TEXT_DIM)
            return
        node_id = _normalize_node_id(args[0])
        try:
            mask = self._parse_mask(args[1])
            value = self._parse_mask(args[2])
        except ValueError as e:
            self._println(f"  ✗ Bad mask: {e}", color=Colors.DANGER)
            return
        ok = self.manager.gpio_write(node_id, mask, value)
        if ok:
            self._println(
                f"  ✓ GPIO write sent to {node_id} "
                f"(mask=0x{mask:x} value=0x{value:x}).",
                color=Colors.SUCCESS)
        else:
            self._println("  ✗ GPIO write failed.", color=Colors.DANGER)

    def _cmd_gpio_watch(self, args):
        """gpio-watch <nodeId> <pin_mask> — mask=0 disables."""
        if len(args) < 2:
            self._println("Usage: gpio-watch <nodeId> <pin_mask>",
                          color=Colors.WARNING)
            self._println("  Example: gpio-watch !ba4bf9d0 0x0F "
                          "(watch pins 0..3)", color=Colors.TEXT_DIM)
            self._println("           gpio-watch !ba4bf9d0 0    "
                          "(stop watching)", color=Colors.TEXT_DIM)
            return
        node_id = _normalize_node_id(args[0])
        try:
            mask = self._parse_mask(args[1])
        except ValueError as e:
            self._println(f"  ✗ Bad mask: {e}", color=Colors.DANGER)
            return
        ok = self.manager.gpio_watch(node_id, mask)
        if ok:
            if mask == 0:
                self._println(
                    f"  ✓ Watch disabled on {node_id}.",
                    color=Colors.SUCCESS)
            else:
                self._println(
                    f"  ✓ Watching mask 0x{mask:x} on {node_id}. "
                    f"GPIOS_CHANGED packets will arrive when pins change.",
                    color=Colors.SUCCESS)
        else:
            self._println("  ✗ GPIO watch failed.", color=Colors.DANGER)

    def _cmd_delete_file(self, args):
        """delete-file <path> — remove a file from the device flash."""
        if not args:
            self._println("Usage: delete-file <path>", color=Colors.WARNING)
            self._println("  Example: delete-file /static/bigfont.bin",
                          color=Colors.TEXT_DIM)
            return
        path = args[0].strip()
        if not path.startswith("/"):
            self._println(
                "  Warning: paths usually start with '/' (e.g. /prefs/cannedMessages.proto)",
                color=Colors.WARNING)
        # Hard-confirm because there's no undo
        from PySide6.QtWidgets import QMessageBox
        ans = QMessageBox.question(
            self.window(),
            t("common.confirm"),
            f"Delete file '{path}' from the device's flash filesystem? "
            "This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No)
        if ans != QMessageBox.Yes:
            self._println("  Cancelled.", color=Colors.TEXT_DIM)
            return
        ok = self.manager.delete_file(path)
        if ok:
            self._println(
                f"  ✓ Delete request sent for '{path}'. The device will "
                f"apply it asynchronously.", color=Colors.SUCCESS)
        else:
            self._println("  ✗ Delete failed.", color=Colors.DANGER)

    # ── V20-turn5: CLI-parity commands ──────────────────────────────────────
    def _cmd_version(self):
        """Print app, meshtastic-python, and PySide6 versions (CLI: --version)."""
        self._hr("VERSIONS")
        try:
            import pkg_resources
            mver = pkg_resources.get_distribution("meshtastic").version
        except Exception:
            mver = "?"
        try:
            import PySide6
            pver = PySide6.__version__
        except Exception:
            pver = "?"
        self._kv("MeshLink Desktop", "V20")
        self._kv("meshtastic-python", mver)
        self._kv("PySide6",            pver)

    def _cmd_support(self):
        """Print diagnostic info to help support requests (CLI: --support)."""
        self._hr("SUPPORT INFO")
        import sys, platform
        self._kv("Platform",      f"{platform.system()} {platform.release()}")
        self._kv("Python",        sys.version.split()[0])
        try:
            import pkg_resources
            self._kv("meshtastic", pkg_resources.get_distribution("meshtastic").version)
        except Exception:
            pass
        my_id = self.manager.my_node_id or "—"
        self._kv("My node ID",    my_id)
        st = self.manager.state
        self._kv("Connection",    st)
        iface = self.manager.interface
        if iface is not None:
            mi   = getattr(iface, "myInfo",   None)
            meta = getattr(iface, "metadata", None)
            # Firmware: prefer metadata (always present in 2.5+)
            fw = None
            if meta:  fw = getattr(meta, "firmware_version", None)
            if not fw and mi: fw = getattr(mi, "firmware_version", None)
            self._kv("Firmware",     fw or "?")
            if mi:
                self._kv("Reboot count", getattr(mi, "reboot_count", "?"))
            if meta:
                hw_raw = getattr(meta, "hw_model", None)
                try:
                    from meshtastic.protobuf.mesh_pb2 import HardwareModel
                    hw = HardwareModel.Name(int(hw_raw))
                except Exception:
                    hw = str(hw_raw or "?")
                self._kv("HW model", hw)
            try:
                ln = iface.localNode
                cfg = ln.localConfig
                if hasattr(cfg, "lora"):
                    self._kv("LoRa region", _enum_name(cfg.lora, "region"))
                    self._kv("Modem preset",
                             _enum_name(cfg.lora, "modem_preset"))
                ch_count = sum(1 for c in (ln.channels or [])
                               if int(getattr(c, "role", 0) or 0) != 0)
                self._kv("Active channels", ch_count)
            except Exception:
                pass

    def _cmd_mesh_health(self):
        """Show RX/TX activity + channel utilization to help diagnose
        'why am I not receiving anything?'.

        Reads the manager's per-port deque counters, the device's own
        channel_utilization samples, and prints a short report plus a
        plain-English diagnostic line.
        """
        h = self.manager.get_mesh_health()
        self._hr("MESH HEALTH")

        sess_s = h["session_seconds"]
        if   sess_s < 60:    sess_str = f"{sess_s}s"
        elif sess_s < 3600:  sess_str = f"{sess_s // 60}m {sess_s % 60}s"
        else:                sess_str = f"{sess_s // 3600}h {(sess_s % 3600) // 60}m"
        self._kv("Session uptime", sess_str)

        # TX
        self._kv("TX (this session)", h["tx_total"])
        self._kv("TX (last hour)",    h["tx_last_hour"])

        # RX breakdown
        self._println("")
        self._println("  Decoded RX (excluding our own broadcasts):",
                      color=Colors.PRIMARY, bold=True)
        for port in ("TEXT_MESSAGE_APP", "POSITION_APP", "TELEMETRY_APP",
                     "NODEINFO_APP", "ROUTING_APP", "OTHER"):
            stat = h["rx_by_port"].get(port, {"total": 0, "1h": 0, "24h": 0})
            self._kv(f"  {port}",
                     f"total={stat['total']:>4}   "
                     f"last 1h={stat['1h']:>3}   last 24h={stat['24h']:>4}")

        # Unique neighbours
        self._println("")
        self._kv("Unique neighbours heard (1h)",  h["rx_unique_nodes_1h"])
        self._kv("Unique neighbours heard (24h)", h["rx_unique_nodes_24h"])

        # Time since last RX
        if h["rx_last_packet_age"] < 0:
            self._kv("Last decoded packet", "(none this session)")
        else:
            self._kv("Last decoded packet",
                     _format_age(h["rx_last_packet_age"]) + " ago")
        if h["rx_last_text_age"] < 0:
            self._kv("Last text message",  "(none this session)")
        else:
            self._kv("Last text message",
                     _format_age(h["rx_last_text_age"]) + " ago")

        # Channel utilization (the device's own air-time measurement)
        self._println("")
        if h["channel_util_avg"] >= 0:
            self._kv("Channel utilization (avg)",
                     f"{h['channel_util_avg']:.2f}%")
            self._kv("Channel utilization (max)",
                     f"{h['channel_util_max']:.2f}%")
            self._kv("Channel utilization (last)",
                     f"{h['channel_util_last']:.2f}%")
        else:
            self._kv("Channel utilization",
                     "(waiting for first device telemetry…)")

        # Diagnostic hint
        self._println("")
        diag = h.get("diagnostic") or ""
        color = (Colors.WARNING if "⚠" in diag or "interference" in diag.lower()
                 else (Colors.SUCCESS if diag.startswith("✓") else Colors.TEXT_DIM))
        self._println(f"  Diagnostic: {diag}", color=color)

    def _cmd_qr_all(self):
        """Print URL for primary channel + every secondary channel
        (CLI: --qr-all). Each is a self-contained shareable URL.
        """
        iface = self.manager.interface
        if iface is None:
            self._println("Not connected.", color=Colors.WARNING)
            return
        try:
            self._hr("CHANNEL URLs (all)")
            # Primary URL has the full LoRa config encoded
            primary_url = iface.localNode.getURL()
            self._println(f"  Primary (with LoRa config):",
                          color=Colors.PRIMARY, bold=True)
            self._println(f"    {primary_url}", color=Colors.TEXT_PRIMARY)
            self._println(
                "  (use this URL to onboard a new device — applies all "
                "channels at once)", color=Colors.TEXT_DIM)
            # If newer firmware/library supports getChannelURL for individual
            # channels we list them; otherwise print just the primary.
            try:
                ln = iface.localNode
                for ch in (ln.channels or []):
                    role = int(getattr(ch, "role", 0) or 0)
                    if role == 0:
                        continue
                    name = ch.settings.name or ("LongFast" if role == 1
                                                else f"Channel {ch.index}")
                    self._println(
                        f"  Channel {ch.index} [{name}]: "
                        f"(individual URL not exposed by library)",
                        color=Colors.TEXT_DIM)
            except Exception:
                pass
        except Exception as e:
            self._println(f"  ✗ Could not fetch URLs: {e}", color=Colors.DANGER)

    def _cmd_seturl(self, args):
        """Apply a Meshtastic channel URL — replaces all channels + LoRa.

        CLI equivalent: --seturl <url>
        """
        if not args:
            self._println("Usage: seturl <meshtastic-url>", color=Colors.WARNING)
            self._println(
                "  Example: seturl https://meshtastic.org/e/#"
                "ChAKEAYAACIRn0...",
                color=Colors.TEXT_DIM)
            return
        url = args[0].strip()
        if not url.startswith(("http://", "https://", "meshtastic://")):
            self._println(
                "  Warning: URLs usually start with https:// or meshtastic://",
                color=Colors.WARNING)
        from PySide6.QtWidgets import QMessageBox
        ans = QMessageBox.question(
            self.window(),
            t("common.confirm"),
            "Apply this channel URL? It will REPLACE all current "
            "channels and the LoRa configuration on the device.",
            QMessageBox.Yes | QMessageBox.No)
        if ans != QMessageBox.Yes:
            self._println("  Cancelled.", color=Colors.TEXT_DIM)
            return
        try:
            self.manager.interface.localNode.setURL(url)
            self._println(
                f"  ✓ URL applied. Device will reconfigure.",
                color=Colors.SUCCESS)
        except Exception as e:
            log.exception("seturl failed")
            self._println(f"  ✗ Failed: {e}", color=Colors.DANGER)

    def _cmd_pos_fields(self, args):
        """Show or set position fields bitmask (CLI: --pos-fields).

        Without args: print current position_flags + valid field names.
        With args:    OR the named flags together and write to position config.
        """
        ln = self.manager.interface.localNode
        try:
            pos_cfg = ln.localConfig.position
        except Exception as e:
            self._println(f"  ✗ Could not read position config: {e}",
                          color=Colors.DANGER)
            return
        from meshtastic.protobuf import config_pb2
        flags_enum = config_pb2.Config.PositionConfig.PositionFlags
        names = {v.name: v.number for v in flags_enum.DESCRIPTOR.values}
        # Drop the synthetic UNSET=0 from the user-facing list
        names_user = {k: v for k, v in names.items() if v > 0}

        if not args:
            # Show current
            current = int(pos_cfg.position_flags)
            self._hr("POSITION FIELDS")
            active = [n for n, v in names_user.items() if current & v]
            self._kv("Current bitmask", f"0x{current:x}")
            self._kv("Active fields", ", ".join(active) if active else "(none)")
            self._println(
                f"  Valid flags: {', '.join(names_user.keys())}",
                color=Colors.TEXT_DIM)
            self._println(
                f"  Example: pos-fields ALTITUDE HEADING SPEED",
                color=Colors.TEXT_DIM)
            return

        # Set
        bitmask = 0
        unknown = []
        for arg in args:
            name = arg.strip().upper()
            if name in names_user:
                bitmask |= names_user[name]
            elif name.startswith("0X"):
                try: bitmask |= int(name, 16)
                except ValueError: unknown.append(arg)
            elif name.isdigit():
                bitmask |= int(name)
            else:
                unknown.append(arg)
        if unknown:
            self._println(
                f"  ✗ Unknown flag(s): {', '.join(unknown)}. "
                f"Valid: {', '.join(names_user.keys())}",
                color=Colors.DANGER)
            return
        try:
            pos_cfg.position_flags = bitmask
            ln.writeConfig("position")
            self._println(
                f"  ✓ position_flags = 0x{bitmask:x} written. "
                f"Device will apply.",
                color=Colors.SUCCESS)
        except Exception as e:
            log.exception("pos-fields write failed")
            self._println(f"  ✗ Failed: {e}", color=Colors.DANGER)

    def _cmd_set_canned_message(self, args):
        """Set canned messages, separated by | (CLI: --set-canned-message)."""
        if not args:
            self._println(
                'Usage: set-canned-message "msg1|msg2|msg3|..."',
                color=Colors.WARNING)
            self._println(
                "  Example: set-canned-message "
                "\"On my way|Roger|Need help|ETA 5 min\"",
                color=Colors.TEXT_DIM)
            return
        text = " ".join(args)
        if len(text) > 200:
            self._println(
                f"  ✗ Too long ({len(text)} chars). Max 200.",
                color=Colors.DANGER)
            return
        try:
            self.manager.interface.localNode.set_canned_message(text)
            self._println(
                f"  ✓ Canned messages set ({text.count('|') + 1} entries).",
                color=Colors.SUCCESS)
        except Exception as e:
            log.exception("set-canned-message failed")
            self._println(f"  ✗ Failed: {e}", color=Colors.DANGER)

    def _cmd_get_canned_message(self):
        """Show currently stored canned messages (CLI: --get-canned-message)."""
        try:
            ln = self.manager.interface.localNode
            ln.get_canned_message()
            cm = getattr(ln, "cannedPluginMessage", None)
            self._hr("CANNED MESSAGES")
            if not cm:
                self._println("  (none set or response pending)",
                              color=Colors.TEXT_DIM)
                return
            entries = str(cm).split("|")
            for i, entry in enumerate(entries):
                self._kv(f"  [{i}]", entry)
        except Exception as e:
            log.exception("get-canned-message failed")
            self._println(f"  ✗ Failed: {e}", color=Colors.DANGER)

    def _cmd_set_ringtone(self, args):
        """Set RTTTL ringtone (CLI: --set-ringtone). Max 230 chars."""
        if not args:
            self._println('Usage: set-ringtone "RTTTL string"',
                          color=Colors.WARNING)
            return
        text = " ".join(args)
        if len(text) > 230:
            self._println(
                f"  ✗ Too long ({len(text)} chars). Max 230.",
                color=Colors.DANGER)
            return
        try:
            self.manager.interface.localNode.set_ringtone(text)
            self._println(f"  ✓ Ringtone set ({len(text)} chars).",
                          color=Colors.SUCCESS)
        except Exception as e:
            log.exception("set-ringtone failed")
            self._println(f"  ✗ Failed: {e}", color=Colors.DANGER)

    def _cmd_get_ringtone(self):
        """Show stored ringtone (CLI: --get-ringtone)."""
        try:
            ln = self.manager.interface.localNode
            ln.get_ringtone()
            r = getattr(ln, "cannedPluginRingtone", None)
            self._hr("RINGTONE")
            if not r:
                self._println("  (none set or response pending)",
                              color=Colors.TEXT_DIM)
                return
            self._println(f"  {r}", color=Colors.TEXT_PRIMARY)
        except Exception as e:
            log.exception("get-ringtone failed")
            self._println(f"  ✗ Failed: {e}", color=Colors.DANGER)

    def _cmd_ch_add(self, args):
        """Add a secondary channel (CLI: --ch-add NAME)."""
        if not args:
            self._println("Usage: ch-add <name>", color=Colors.WARNING)
            self._println("  Example: ch-add iberia", color=Colors.TEXT_DIM)
            return
        name = args[0].strip()
        ok = self.manager.add_channel(name=name)
        if ok:
            self._println(
                f"  ✓ Channel '{name}' added (default key). "
                f"Use the Channels tab to set the encryption key.",
                color=Colors.SUCCESS)
        else:
            self._println(f"  ✗ Add failed.", color=Colors.DANGER)

    def _cmd_ch_del(self, args):
        """Delete a SECONDARY channel by index (CLI: --ch-index N --ch-del)."""
        if not args:
            self._println("Usage: ch-del <index>", color=Colors.WARNING)
            self._println("  Note: index 0 is PRIMARY and cannot be deleted.",
                          color=Colors.TEXT_DIM)
            return
        try:
            idx = int(args[0])
        except ValueError:
            self._println(f"  ✗ Bad index: {args[0]!r}", color=Colors.DANGER)
            return
        from PySide6.QtWidgets import QMessageBox
        ans = QMessageBox.question(
            self.window(),
            t("common.confirm"),
            f"Delete channel at index {idx}?",
            QMessageBox.Yes | QMessageBox.No)
        if ans != QMessageBox.Yes:
            self._println("  Cancelled.", color=Colors.TEXT_DIM)
            return
        ok = self.manager.remove_channel(idx)
        if ok:
            self._println(f"  ✓ Channel {idx} deleted.", color=Colors.SUCCESS)
        else:
            self._println(f"  ✗ Delete failed.", color=Colors.DANGER)

    def _cmd_ch_set(self, args):
        """Set a channel parameter (CLI: --ch-set <field> <value> --ch-index N).

        Usage in our console (index goes last for parsing simplicity):
            ch-set <field> <value> <index>

        Common fields: name, uplink_enabled, downlink_enabled.
        """
        if len(args) < 3:
            self._println(
                "Usage: ch-set <field> <value> <index>",
                color=Colors.WARNING)
            self._println("  Examples:", color=Colors.TEXT_DIM)
            self._println("    ch-set name Iberia 1", color=Colors.TEXT_DIM)
            self._println("    ch-set uplink_enabled true 1",
                          color=Colors.TEXT_DIM)
            self._println("    ch-set downlink_enabled false 1",
                          color=Colors.TEXT_DIM)
            return
        field = args[0].strip()
        value_tokens = args[1:-1]
        try:
            idx = int(args[-1])
        except ValueError:
            self._println(f"  ✗ Last arg must be an integer index, "
                          f"got {args[-1]!r}", color=Colors.DANGER)
            return
        raw_value = " ".join(value_tokens)
        # Map field name → manager.update_channel keyword
        kwargs = {}
        if field == "name":
            kwargs["name"] = raw_value
        elif field in ("uplink_enabled", "uplink"):
            kwargs["uplink"] = _coerce_value(raw_value, bool)
        elif field in ("downlink_enabled", "downlink"):
            kwargs["downlink"] = _coerce_value(raw_value, bool)
        elif field in ("position_precision", "module_settings.position_precision"):
            try:
                kwargs["position_precision"] = int(raw_value)
            except ValueError:
                self._println(f"  ✗ position_precision must be int",
                              color=Colors.DANGER)
                return
        elif field == "psk":
            # Decode base64/hex
            from ..dialogs.channel_edit_dialog import _decode_psk_input
            psk = _decode_psk_input(raw_value)
            if psk is None:
                self._println("  ✗ PSK must be base64 or hex (16 or 32 bytes)",
                              color=Colors.DANGER)
                return
            kwargs["psk"] = psk
        else:
            self._println(
                f"  ✗ Unknown field {field!r}. "
                f"Known: name, uplink_enabled, downlink_enabled, "
                f"position_precision, psk",
                color=Colors.DANGER)
            return
        ok = self.manager.update_channel(idx, **kwargs)
        if ok:
            self._println(f"  ✓ ch[{idx}].{field} updated.", color=Colors.SUCCESS)
        else:
            self._println(f"  ✗ Update failed.", color=Colors.DANGER)

    def _cmd_configure(self, args):
        """Apply a YAML config file to the device (CLI: --configure FILE).

        The YAML format mirrors the output of `export-config`.
        """
        if not args:
            self._println("Usage: configure <path-to-yaml>",
                          color=Colors.WARNING)
            return
        path = args[0].strip()
        try:
            import yaml
        except ImportError:
            self._println(
                "  ✗ Requires PyYAML. Install with: "
                "pip install pyyaml",
                color=Colors.DANGER)
            return
        import os
        if not os.path.isfile(path):
            self._println(f"  ✗ File not found: {path}", color=Colors.DANGER)
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            self._println(f"  ✗ Could not parse YAML: {e}", color=Colors.DANGER)
            return
        if not isinstance(data, dict):
            self._println("  ✗ YAML must be a mapping.", color=Colors.DANGER)
            return

        from PySide6.QtWidgets import QMessageBox
        ans = QMessageBox.question(
            self.window(),
            t("common.confirm"),
            f"Apply configuration from '{path}' to the device? "
            "This may reboot the device.",
            QMessageBox.Yes | QMessageBox.No)
        if ans != QMessageBox.Yes:
            self._println("  Cancelled.", color=Colors.TEXT_DIM)
            return

        ln = self.manager.interface.localNode
        applied = 0
        errors = []
        # Apply known top-level sections
        for top_key in ("config", "module_config", "owner", "channels"):
            section = data.get(top_key)
            if not section:
                continue
            try:
                if top_key == "config" and isinstance(section, dict):
                    for sub_name, sub_values in section.items():
                        proto = getattr(ln.localConfig, sub_name, None)
                        if proto is None or not isinstance(sub_values, dict):
                            continue
                        for k, v in sub_values.items():
                            try:
                                fd = proto.DESCRIPTOR.fields_by_name.get(k)
                                if fd is None:
                                    continue
                                cur = getattr(proto, k)
                                # Coerce via existing helper for enum support
                                conv = _coerce_value(str(v), type(cur),
                                                     field_descriptor=fd)
                                setattr(proto, k, conv)
                            except Exception:
                                log.exception(f"config.{sub_name}.{k} apply failed")
                        ln.writeConfig(sub_name)
                        applied += 1
                elif top_key == "module_config" and isinstance(section, dict):
                    for sub_name, sub_values in section.items():
                        proto = getattr(ln.moduleConfig, sub_name, None)
                        if proto is None or not isinstance(sub_values, dict):
                            continue
                        for k, v in sub_values.items():
                            try:
                                fd = proto.DESCRIPTOR.fields_by_name.get(k)
                                if fd is None:
                                    continue
                                cur = getattr(proto, k)
                                conv = _coerce_value(str(v), type(cur),
                                                     field_descriptor=fd)
                                setattr(proto, k, conv)
                            except Exception:
                                log.exception(f"module_config.{sub_name}.{k} apply failed")
                        ln.writeConfig(sub_name)
                        applied += 1
                elif top_key == "owner" and isinstance(section, dict):
                    long_n = section.get("long_name") or section.get("longName")
                    short_n = section.get("short_name") or section.get("shortName")
                    if long_n or short_n:
                        ln.setOwner(long_name=long_n, short_name=short_n)
                        applied += 1
            except Exception as e:
                errors.append(f"{top_key}: {e}")
                log.exception(f"applying {top_key}")

        if applied:
            self._println(
                f"  ✓ Applied {applied} configuration section(s).",
                color=Colors.SUCCESS)
        if errors:
            for err in errors:
                self._println(f"  ✗ {err}", color=Colors.DANGER)
        if not applied and not errors:
            self._println(
                "  (no recognized sections in YAML — "
                "expected 'config', 'module_config', 'owner')",
                color=Colors.WARNING)

    def _cmd_reply(self):
        """Toggle --reply mode (echo received messages back to the mesh)."""
        self._reply_mode = not self._reply_mode
        if self._reply_mode:
            self._println(
                "  ✓ Reply mode ON. Every incoming TEXT will be echoed back "
                "on its channel with sender + SNR. Run 'reply' again to stop.",
                color=Colors.SUCCESS)
        else:
            self._println("  ✓ Reply mode OFF.", color=Colors.TEXT_DIM)

    def _cmd_ble_scan(self):
        """List nearby BLE Meshtastic devices (CLI: --ble-scan).

        Scanning blocks for ~5 seconds. Runs in a worker thread so the UI
        stays responsive.
        """
        self._println(
            "  Scanning BLE for ~5 seconds…",
            color=Colors.INFO)
        import threading
        def _scan():
            results = []
            err = None
            try:
                from meshtastic.ble_interface import BLEInterface
                # BLEInterface.scan() returns list of (name, addr) on most
                # versions of meshtastic-python. Wrap to handle either form.
                raw = BLEInterface.scan()
                for item in raw or []:
                    if isinstance(item, tuple) and len(item) >= 2:
                        results.append((str(item[0]), str(item[1])))
                    elif hasattr(item, "address"):
                        results.append((getattr(item, "name", "?"),
                                        item.address))
                    else:
                        results.append(("?", str(item)))
            except Exception as e:
                err = e
            # Dispatch result to Qt thread for printing
            self.manager._invoke_on_qt(self._ble_scan_done, results, err)
        threading.Thread(target=_scan, daemon=True).start()

    def _ble_scan_done(self, results, err):
        if err is not None:
            self._println(f"  ✗ BLE scan failed: {err}", color=Colors.DANGER)
            return
        self._hr("BLE DEVICES")
        if not results:
            self._println("  (no Meshtastic BLE devices found)",
                          color=Colors.TEXT_DIM)
            return
        for name, addr in results:
            self._kv(name, addr)

    def _cmd_gpio_wrb(self, args):
        """Set a single GPIO pin to 0 or 1 (CLI: --gpio-wrb PIN VALUE --dest).

        Convenience over `gpio-wr` which uses a mask + value bitmap. This
        one takes a pin number and a 0/1 value and computes the masks.
        """
        if len(args) < 3:
            self._println(
                "Usage: gpio-wrb <nodeId> <pin> <0|1>",
                color=Colors.WARNING)
            self._println(
                "  Example: gpio-wrb !ba4bf9d0 4 1   (set pin 4 high)",
                color=Colors.TEXT_DIM)
            return
        node_id = _normalize_node_id(args[0])
        try:
            pin = int(args[1])
            value = int(args[2])
        except ValueError as e:
            self._println(f"  ✗ Bad arg: {e}", color=Colors.DANGER)
            return
        if pin < 0 or pin > 63:
            self._println(f"  ✗ Pin must be 0..63", color=Colors.DANGER)
            return
        if value not in (0, 1):
            self._println(f"  ✗ Value must be 0 or 1", color=Colors.DANGER)
            return
        mask = (1 << pin)
        value_mask = (value << pin)
        ok = self.manager.gpio_write(node_id, mask, value_mask)
        if ok:
            self._println(
                f"  ✓ Set pin {pin} = {value} on {node_id}.",
                color=Colors.SUCCESS)
        else:
            self._println(f"  ✗ Failed.", color=Colors.DANGER)

    # ── Local device configuration ──────────────────────────────────────────
    def _cmd_set_position(self, args):
        """
        set-position <lat> <lon> [alt]

        Set a FIXED GPS position on the local device.
        CLI equivalent:
            python -m meshtastic --setlat <lat> --setlon <lon> --setalt <alt>
        """
        if len(args) < 2:
            self._println("Usage: set-position <lat> <lon> [alt_meters]",
                          color=Colors.WARNING)
            self._println("  Example: set-position 41.785333 0.805527 100",
                          color=Colors.TEXT_DIM)
            self._println(
                "  (CLI equivalent: --setlat <lat> --setlon <lon> --setalt <alt>)",
                color=Colors.TEXT_DIM)
            return
        try:
            lat = float(args[0])
            lon = float(args[1])
            alt = int(float(args[2])) if len(args) > 2 else 0
        except ValueError:
            self._println(
                "Error: latitude and longitude must be decimal numbers.",
                color=Colors.DANGER
            )
            return
        if not (-90.0 <= lat <= 90.0):
            self._println(f"Error: latitude {lat} is out of range -90..90.",
                          color=Colors.DANGER)
            return
        if not (-180.0 <= lon <= 180.0):
            self._println(f"Error: longitude {lon} is out of range -180..180.",
                          color=Colors.DANGER)
            return

        self._println(
            f"  Setting fixed position: lat={lat:.6f}  lon={lon:.6f}  alt={alt}m …",
            color=Colors.TEXT_DIM
        )
        try:
            local_node = self.manager.interface.localNode
            if hasattr(local_node, "setFixedPosition"):
                local_node.setFixedPosition(lat, lon, alt)
                self._println(
                    f"  ✓ Position saved on the device: "
                    f"{lat:.6f}, {lon:.6f}  alt={alt}m",
                    color=Colors.SUCCESS
                )
                self._println(
                    "  The device will broadcast this position on the next beacon.",
                    color=Colors.TEXT_DIM
                )
            else:
                # legacy fallback
                self.manager.interface.sendPosition(
                    latitude=lat, longitude=lon, altitude=alt,
                    destinationId="^all"
                )
                self._println(
                    "  ⚠ Library too old for persistent position — broadcast only.",
                    color=Colors.WARNING
                )
                self._println(
                    "  Upgrade with: pip install --upgrade meshtastic",
                    color=Colors.TEXT_DIM
                )
        except Exception as e:
            self._println(f"  ✗ Error: {e}", color=Colors.DANGER)
            log.exception("set-position failed")

    def _cmd_remove_position(self):
        """
        remove-position

        Clear the fixed GPS position and let the device use its GPS again.
        CLI equivalent: python -m meshtastic --remove-position
        """
        self._println("  Removing fixed position…", color=Colors.TEXT_DIM)
        try:
            local_node = self.manager.interface.localNode
            if hasattr(local_node, "removeFixedPosition"):
                local_node.removeFixedPosition()
                self._println("  ✓ Fixed position removed. GPS restored.",
                              color=Colors.SUCCESS)
                return
            # Fallback: clear fixed_position in localConfig
            try:
                cfg = local_node.localConfig
                if hasattr(cfg, "position"):
                    cfg.position.fixed_position = False
                    local_node.writeConfig("position")
                    self._println(
                        "  ✓ fixed_position cleared and config written.",
                        color=Colors.SUCCESS
                    )
                    return
            except Exception as e2:
                self._println(f"  ✗ Fallback failed: {e2}", color=Colors.DANGER)
                return
            self._println(
                "  ✗ Operation not supported by this library version.",
                color=Colors.DANGER
            )
        except Exception as e:
            self._println(f"  ✗ Error: {e}", color=Colors.DANGER)
            log.exception("remove-position failed")

    def _cmd_position_info(self):
        try:
            local_node = self.manager.interface.localNode
            cfg = local_node.localConfig
            pos = getattr(cfg, "position", None)
            if pos is None:
                self._println("  Position config not available.",
                              color=Colors.WARNING)
                return
            self._hr("POSITION CONFIG")
            self._kv("Fixed position",   getattr(pos, "fixed_position", "?"))
            self._kv("GPS update sec",   getattr(pos, "gps_update_interval", "?"))
            self._kv("Broadcast sec",    getattr(pos, "position_broadcast_secs", "?"))
            self._kv("Smart broadcast",  getattr(pos, "position_broadcast_smart_enabled", "?"))

            # local node's own position from the node DB
            my_id = self.manager.my_node_id
            if my_id:
                node = (self.manager.interface.nodes or {}).get(my_id, {})
                np_ = node.get("position") or {}
                lat = np_.get("latitude")
                lon = np_.get("longitude")
                if lat is None and np_.get("latitudeI") is not None:
                    lat = np_["latitudeI"] / 1e7
                    lon = np_.get("longitudeI", 0) / 1e7
                if lat is not None:
                    self._hr("CURRENT POSITION")
                    self._kv("Latitude",  f"{lat:.6f}")
                    self._kv("Longitude", f"{lon:.6f}")
                    self._kv("Altitude",  f"{np_.get('altitude','?')} m")
                    self._kv("Source",    np_.get("locationSource", "?"))
        except Exception as e:
            self._println(f"  ✗ Error: {e}", color=Colors.DANGER)

    def _cmd_set_owner(self, args):
        if len(args) < 2:
            self._println('Usage: set-owner "<long name>" <short>',
                          color=Colors.WARNING)
            self._println('  Example: set-owner "My T-Beam" TBM',
                          color=Colors.TEXT_DIM)
            return
        long_name  = args[0]
        short_name = args[1][:4]
        if len(args[1]) > 4:
            self._println(
                f"  ⚠ Short name '{args[1]}' truncated to '{short_name}' "
                f"(max 4 chars).",
                color=Colors.WARNING
            )
        try:
            self.manager.set_owner(long_name, short_name)
            self._println(
                f"  ✓ Owner set: longName='{long_name}'  shortName='{short_name}'",
                color=Colors.SUCCESS
            )
        except Exception as e:
            self._println(f"  ✗ Error: {e}", color=Colors.DANGER)
            log.exception("set-owner failed")

    def _cmd_send_position(self):
        """Broadcast the current device position once (non-persistent)."""
        try:
            self.manager.interface.sendPosition(destinationId="^all")
            self._println("  ✓ Position broadcast sent.", color=Colors.SUCCESS)
        except Exception as e:
            self._println(f"  ✗ Error: {e}", color=Colors.DANGER)

    def _cmd_set_owner_long(self, args):
        if not args:
            self._println('Usage: set-owner-long "<long name>"', color=Colors.WARNING)
            return
        long_name = " ".join(args)
        try:
            ln = self.manager.interface.localNode
            # Read current short to keep it
            owner = getattr(ln, "myNodeNum", None)
            short = None
            try:
                nodes = self.manager.interface.nodes or {}
                me = nodes.get(self.manager.my_node_id, {})
                short = (me.get("user") or {}).get("shortName")
            except Exception:
                pass
            ln.setOwner(long_name=long_name, short_name=short or long_name[:4].upper())
            self._println(f"  ✓ Long name set: '{long_name}'", color=Colors.SUCCESS)
        except Exception as e:
            self._println(f"  ✗ Error: {e}", color=Colors.DANGER)

    def _cmd_set_owner_short(self, args):
        if not args:
            self._println("Usage: set-owner-short <abbrev>", color=Colors.WARNING)
            return
        short = args[0][:4]
        if len(args[0]) > 4:
            self._println(
                f"  ⚠ Truncated '{args[0]}' to '{short}' (max 4 chars).",
                color=Colors.WARNING)
        try:
            ln = self.manager.interface.localNode
            long_name = None
            try:
                nodes = self.manager.interface.nodes or {}
                me = nodes.get(self.manager.my_node_id, {})
                long_name = (me.get("user") or {}).get("longName")
            except Exception:
                pass
            ln.setOwner(long_name=long_name or short, short_name=short)
            self._println(f"  ✓ Short name set: '{short}'", color=Colors.SUCCESS)
        except Exception as e:
            self._println(f"  ✗ Error: {e}", color=Colors.DANGER)

    def _cmd_set_ham(self, args):
        """Enable HAM mode with a callsign (max 8 chars, unencrypted broadcasts)."""
        if not args:
            self._println("Usage: set-ham <callsign>", color=Colors.WARNING)
            self._println(
                "  HAM mode disables encryption and sets your callsign as long name.",
                color=Colors.TEXT_DIM)
            return
        callsign = args[0].upper()[:8]
        try:
            ln = self.manager.interface.localNode
            if hasattr(ln, "setOwner"):
                ln.setOwner(long_name=callsign, short_name=callsign[:4],
                            is_licensed=True)
                self._println(
                    f"  ✓ HAM mode enabled: callsign={callsign}",
                    color=Colors.SUCCESS)
                self._println(
                    "  ⚠ Encryption is now DISABLED on the primary channel.",
                    color=Colors.WARNING)
            else:
                self._println("  ✗ Library does not support setOwner with HAM flag.",
                              color=Colors.DANGER)
        except Exception as e:
            self._println(f"  ✗ Error: {e}", color=Colors.DANGER)

    def _cmd_set_region(self, args):
        """Set the LoRa region. Valid: US, EU_868, EU_433, CN, JP, ANZ, KR, TW,
        RU, IN, NZ_865, TH, LORA_24, UA_433, UA_868, MY_433, MY_919, SG_923."""
        if not args:
            self._println("Usage: set-region <REGION>", color=Colors.WARNING)
            self._println(
                "  Valid regions: US, EU_868, EU_433, CN, JP, ANZ, KR, TW, RU,",
                color=Colors.TEXT_DIM)
            self._println(
                "                 IN, NZ_865, TH, LORA_24, UA_433, UA_868,",
                color=Colors.TEXT_DIM)
            self._println(
                "                 MY_433, MY_919, SG_923",
                color=Colors.TEXT_DIM)
            return
        region = args[0].upper()
        try:
            from meshtastic import config_pb2
            val = config_pb2.Config.LoRaConfig.RegionCode.Value(region)
            ln = self.manager.interface.localNode
            ln.localConfig.lora.region = val
            ln.writeConfig("lora")
            self._println(
                f"  ✓ LoRa region set to {region}. Device will reboot.",
                color=Colors.SUCCESS)
        except ValueError:
            self._println(f"  ✗ Invalid region: '{region}'", color=Colors.DANGER)
        except Exception as e:
            self._println(f"  ✗ Error: {e}", color=Colors.DANGER)

    def _cmd_set_preset(self, args):
        """Set the modem preset.
        Valid: LONG_FAST, LONG_SLOW, VERY_LONG_SLOW, MEDIUM_SLOW, MEDIUM_FAST,
        SHORT_SLOW, SHORT_FAST, LONG_MODERATE, SHORT_TURBO."""
        if not args:
            self._println("Usage: set-preset <PRESET>", color=Colors.WARNING)
            self._println(
                "  Valid: LONG_FAST, LONG_SLOW, VERY_LONG_SLOW, MEDIUM_SLOW,",
                color=Colors.TEXT_DIM)
            self._println(
                "         MEDIUM_FAST, SHORT_SLOW, SHORT_FAST, LONG_MODERATE,",
                color=Colors.TEXT_DIM)
            self._println(
                "         SHORT_TURBO",
                color=Colors.TEXT_DIM)
            return
        preset = args[0].upper()
        try:
            from meshtastic import config_pb2
            val = config_pb2.Config.LoRaConfig.ModemPreset.Value(preset)
            ln = self.manager.interface.localNode
            ln.localConfig.lora.modem_preset = val
            ln.writeConfig("lora")
            self._println(
                f"  ✓ Modem preset set to {preset}. Device will reboot.",
                color=Colors.SUCCESS)
        except ValueError:
            self._println(f"  ✗ Invalid preset: '{preset}'", color=Colors.DANGER)
        except Exception as e:
            self._println(f"  ✗ Error: {e}", color=Colors.DANGER)

    def _cmd_set(self, args):
        """Generic setter: set <config.field> <value>.

        CLI equivalent: --set <key> <value>
        Examples:
            set lora.hop_limit 5
            set lora.tx_enabled true
            set position.position_broadcast_secs 900
            set device.role ROUTER
        """
        if len(args) < 2:
            self._println("Usage: set <key.path> <value>", color=Colors.WARNING)
            self._println("  Examples:", color=Colors.TEXT_DIM)
            self._println("    set lora.hop_limit 5", color=Colors.TEXT_DIM)
            self._println("    set lora.tx_enabled true", color=Colors.TEXT_DIM)
            self._println("    set position.position_broadcast_secs 900",
                          color=Colors.TEXT_DIM)
            return
        key = args[0]
        value = " ".join(args[1:])
        try:
            ln = self.manager.interface.localNode
            section, _, field = key.partition(".")
            if not field:
                self._println("Error: key must be 'section.field' (e.g. lora.hop_limit)",
                              color=Colors.DANGER)
                return
            cfg = getattr(ln.localConfig, section, None)
            if cfg is None:
                # Maybe it's a module config section
                cfg = getattr(ln.moduleConfig, section, None)
            if cfg is None:
                self._println(f"Error: unknown config section '{section}'",
                              color=Colors.DANGER)
                self._suggest_field_location(field)
                return
            # coerce value to the right type by inspecting current field
            current = getattr(cfg, field, None)
            if current is None and not hasattr(cfg, field):
                self._println(f"Error: unknown field '{field}' in section '{section}'",
                              color=Colors.DANGER)
                # Search every section for this field and suggest the fix
                self._suggest_field_location(field)
                return
            # Find field descriptor (for enum name resolution)
            field_desc = None
            try:
                field_desc = cfg.DESCRIPTOR.fields_by_name.get(field)
            except Exception:
                pass
            # Convert value to right type
            converted = _coerce_value(value, type(current), field_descriptor=field_desc)
            setattr(cfg, field, converted)
            ln.writeConfig(section)
            self._println(
                f"  ✓ Set {key} = {value} (raw: {converted}).",
                color=Colors.SUCCESS)
            self._println(
                "  Note: the device applies config by rebooting. The "
                "connection may drop briefly — it will reconnect "
                "automatically.", color=Colors.TEXT_DIM)
        except Exception as e:
            self._println(f"  ✗ Error: {e}", color=Colors.DANGER)
            log.exception("set command failed")

    def _suggest_field_location(self, field: str):
        """When a `set`/`get` field isn't found, search every config and
        module section for it (exact + fuzzy) and suggest the correct
        command. This fixes the common confusion where users guess the
        wrong section, e.g. `set device.position_broadcast_secs` when the
        field actually lives in `position`.
        """
        try:
            ln = self.manager.interface.localNode
        except Exception:
            return
        field_l = field.lower()
        exact = []
        fuzzy = []
        for kind, root in (("config", ln.localConfig),
                           ("module", ln.moduleConfig)):
            for sect_desc in root.DESCRIPTOR.fields:
                sect_name = sect_desc.name
                sub = getattr(root, sect_name, None)
                if sub is None or not hasattr(sub, "DESCRIPTOR"):
                    continue
                for fd in sub.DESCRIPTOR.fields:
                    if fd.name == field:
                        exact.append((sect_name, fd.name))
                    elif field_l in fd.name.lower() or fd.name.lower() in field_l:
                        fuzzy.append((sect_name, fd.name))
        if exact:
            self._println("  Did you mean:", color=Colors.TEXT_SECONDARY)
            for sect, fn in exact:
                self._println(f"    set {sect}.{fn} <value>", color=Colors.PRIMARY)
        elif fuzzy:
            self._println("  Similar fields:", color=Colors.TEXT_SECONDARY)
            for sect, fn in fuzzy[:6]:
                self._println(f"    set {sect}.{fn} <value>", color=Colors.PRIMARY)
        else:
            self._println("  Tip: run 'get <section>' to list available fields, "
                          "e.g. 'get position'", color=Colors.TEXT_DIM)

    def _cmd_get(self, args):
        """Generic getter: get <section.field>  OR  get <section> to list all."""
        if not args:
            self._println("Usage: get <section.field>  or  get <section>",
                          color=Colors.WARNING)
            self._println("  Examples:  get lora.region   ·   get position",
                          color=Colors.TEXT_DIM)
            return
        key = args[0]
        try:
            ln = self.manager.interface.localNode
            section, _, field = key.partition(".")

            # Resolve section in either config or module config
            cfg = getattr(ln.localConfig, section, None)
            if cfg is None:
                cfg = getattr(ln.moduleConfig, section, None)
            if cfg is None:
                self._println(f"Error: unknown section '{section}'",
                              color=Colors.DANGER)
                self._println("  Config sections: device, position, power, "
                              "network, display, lora, bluetooth",
                              color=Colors.TEXT_DIM)
                self._println("  Module sections: mqtt, serial, telemetry, "
                              "neighbor_info, detection_sensor, ...",
                              color=Colors.TEXT_DIM)
                return

            # No field → list all fields in this section
            if not field:
                self._println(f"── {section} ──", color=Colors.PRIMARY, bold=True)
                for fd in cfg.DESCRIPTOR.fields:
                    val = getattr(cfg, fd.name, None)
                    name = getattr(val, "name", None)
                    self._println(f"  {fd.name} = {name if name else val}",
                                  color=Colors.TEXT_SECONDARY)
                return

            val = getattr(cfg, field, None)
            if val is None and not hasattr(cfg, field):
                self._println(f"Error: unknown field '{field}' in '{section}'",
                              color=Colors.DANGER)
                self._suggest_field_location(field)
                return
            name = getattr(val, "name", None)
            self._println(f"  {key} = {name if name else val}",
                          color=Colors.SUCCESS)
        except Exception as e:
            self._println(f"  ✗ Error: {e}", color=Colors.DANGER)

    def _cmd_remove_node(self, args):
        """Remove a specific node from the device's NodeDB."""
        if not args:
            self._println("Usage: remove-node <nodeId>", color=Colors.WARNING)
            return
        node_id = _normalize_node_id(args[0])
        try:
            ln = self.manager.interface.localNode
            num = int(node_id[1:], 16) if node_id.startswith("!") else int(node_id)
            if hasattr(ln, "removeNode"):
                ln.removeNode(num)
            elif hasattr(ln, "removeNodeFromDb"):
                ln.removeNodeFromDb(num)
            else:
                self._println("  ✗ removeNode not supported by this library.",
                              color=Colors.DANGER)
                return
            self._println(f"  ✓ Node {node_id} removed from DB.",
                          color=Colors.SUCCESS)
        except Exception as e:
            self._println(f"  ✗ Error: {e}", color=Colors.DANGER)

    def _cmd_waypoint(self, args):
        """Broadcast a named waypoint to the mesh.

        Usage: waypoint <name> <lat> <lon> [description]
        """
        if len(args) < 3:
            self._println(
                "Usage: waypoint <name> <lat> <lon> [description]",
                color=Colors.WARNING)
            self._println(
                '  Example: waypoint "Mountain hut" 41.785 0.806 "Open all year"',
                color=Colors.TEXT_DIM)
            return
        name = args[0]
        try:
            lat = float(args[1])
            lon = float(args[2])
        except ValueError:
            self._println("Error: lat/lon must be numbers.", color=Colors.DANGER)
            return
        desc = " ".join(args[3:]) if len(args) > 3 else ""
        try:
            iface = self.manager.interface
            if hasattr(iface, "sendWaypoint"):
                iface.sendWaypoint(name=name, description=desc,
                                   latitude=lat, longitude=lon)
                self._println(
                    f"  ✓ Waypoint '{name}' broadcast at {lat:.6f}, {lon:.6f}",
                    color=Colors.SUCCESS)
            else:
                self._println(
                    "  ✗ Waypoints not supported by this library version.",
                    color=Colors.DANGER)
        except Exception as e:
            self._println(f"  ✗ Error: {e}", color=Colors.DANGER)

    def _cmd_request_info(self, args):
        """Request a node's user/info via the admin channel."""
        if not args:
            self._println("Usage: request-info <nodeId>", color=Colors.WARNING)
            return
        node_id = _normalize_node_id(args[0])
        try:
            iface = self.manager.interface
            # Use sendData with adminPort to request NodeInfo
            ln = iface.localNode
            if hasattr(ln, "requestRemoteOwner"):
                ln.requestRemoteOwner(destinationId=node_id)
                self._println(
                    f"  ✓ User info request sent to {node_id}. "
                    f"Response will arrive asynchronously.",
                    color=Colors.SUCCESS)
            else:
                # Fallback: send empty admin message
                self._println(
                    "  ✗ Library does not expose requestRemoteOwner.",
                    color=Colors.DANGER)
        except Exception as e:
            self._println(f"  ✗ Error: {e}", color=Colors.DANGER)

    # ── Device control (with confirmation) ──────────────────────────────────
    def _cmd_reboot(self):
        r = QMessageBox.question(
            self, "Reboot device",
            "Are you sure you want to reboot the device?\n"
            "The current connection will be lost briefly."
        )
        if r != QMessageBox.Yes:
            self._println("  (cancelled)", color=Colors.TEXT_DIM)
            return
        try:
            self.manager.reboot()
            self._println("  ✓ Reboot command sent.", color=Colors.SUCCESS)
        except Exception as e:
            self._println(f"  ✗ Error: {e}", color=Colors.DANGER)

    def _cmd_shutdown(self):
        r = QMessageBox.question(
            self, "Shutdown device",
            "Are you sure you want to power off the device?\n"
            "You will need to press the power button to turn it back on."
        )
        if r != QMessageBox.Yes:
            self._println("  (cancelled)", color=Colors.TEXT_DIM)
            return
        try:
            local_node = self.manager.interface.localNode
            if hasattr(local_node, "shutdown"):
                local_node.shutdown()
            elif hasattr(local_node, "shutdownDevice"):
                local_node.shutdownDevice()
            else:
                self._println("  ✗ Shutdown not supported by this library.",
                              color=Colors.DANGER)
                return
            self._println("  ✓ Shutdown command sent.", color=Colors.SUCCESS)
        except Exception as e:
            self._println(f"  ✗ Error: {e}", color=Colors.DANGER)

    def _cmd_reset_nodedb(self):
        r = QMessageBox.question(
            self, "Reset Node DB",
            "This will erase the list of nodes known to the device.\n"
            "The mesh will re-discover them over time.\n\nContinue?"
        )
        if r != QMessageBox.Yes:
            self._println("  (cancelled)", color=Colors.TEXT_DIM)
            return
        try:
            self.manager.interface.localNode.resetNodeDb()
            self._println("  ✓ NodeDB reset.", color=Colors.SUCCESS)
        except Exception as e:
            self._println(f"  ✗ Error: {e}", color=Colors.DANGER)

    def _cmd_factory_reset(self):
        # double-confirm dangerous operation
        r = QMessageBox.warning(
            self, "FACTORY RESET",
            "⚠ WARNING ⚠\n\n"
            "This will reset ALL device settings to factory defaults:\n"
            "  • Channels (you will lose your channel keys!)\n"
            "  • Owner names\n"
            "  • LoRa region and preset\n"
            "  • Position config\n"
            "  • All preferences\n\n"
            "The device will reboot.\n\n"
            "Are you absolutely sure?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if r != QMessageBox.Yes:
            self._println("  (cancelled)", color=Colors.TEXT_DIM)
            return
        r2 = QMessageBox.question(
            self, "Final confirmation",
            "Last chance. Click Yes to PROCEED with factory reset.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel
        )
        if r2 != QMessageBox.Yes:
            self._println("  (cancelled)", color=Colors.TEXT_DIM)
            return
        try:
            local_node = self.manager.interface.localNode
            done = False
            for method_name in ("factoryReset", "factoryResetDevice",
                                "factoryResetConfig"):
                fn = getattr(local_node, method_name, None)
                if callable(fn):
                    fn()
                    done = True
                    break
            if not done:
                self._println(
                    "  ✗ Factory reset not supported by this library version.",
                    color=Colors.DANGER
                )
                return
            self._println(
                "  ✓ Factory reset command sent. The device will reboot.",
                color=Colors.SUCCESS
            )
        except Exception as e:
            self._println(f"  ✗ Error: {e}", color=Colors.DANGER)
            log.exception("factory-reset failed")

    # ── Config ──────────────────────────────────────────────────────────────
    def _cmd_export_config(self):
        try:
            iface = self.manager.interface
            text = None
            try:
                import yaml
                from google.protobuf.json_format import MessageToDict
                cfg_dict = MessageToDict(
                    iface.localNode.localConfig,
                    preserving_proto_field_name=True
                )
                text = yaml.safe_dump(cfg_dict, sort_keys=False,
                                       allow_unicode=True,
                                       default_flow_style=False)
            except ImportError:
                text = str(iface.localNode.localConfig)
            except Exception:
                text = str(iface.localNode.localConfig)
            self._hr("DEVICE CONFIG (YAML)")
            self._println(text or "(empty)", color=Colors.TEXT_SECONDARY)
        except Exception as e:
            self._println(f"  ✗ Error: {e}", color=Colors.DANGER)

    # =======================================================================
    # 4. OUTPUT HELPERS
    # =======================================================================
    def _println(self, text: str, color: Optional[str] = None,
                 bold: bool = False):
        """Append a colored line to the console output area."""
        cursor = self.console.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        if color:
            fmt.setForeground(QColor(color))
        font = self.console.font()
        if bold:
            font.setBold(True)
        fmt.setFont(font)
        cursor.insertText(text + "\n", fmt)
        # autoscroll
        sb = self.console.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _hr(self, title: str):
        bar = "─" * max(0, 60 - len(title))
        self._println(f"\n── {title} {bar}", color=Colors.PRIMARY, bold=True)

    def _kv(self, key: str, value):
        self._println(f"  {key:<18} : {value}")

    def _clear_log(self):
        self.console.clear()
        self._show_welcome()

    def _save_log(self):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save console output",
            f"meshtastic_console_{ts}.log",
            "Log files (*.log *.txt);;All files (*)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.console.toPlainText())
            self._println(f"  ✓ Saved: {path}", color=Colors.SUCCESS)
        except Exception as e:
            self._println(f"  ✗ Error: {e}", color=Colors.DANGER)


# ===========================================================================
# 5. UTILITY FUNCTIONS
# ===========================================================================
def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _humanize_age(ts) -> str:
    """Convert a unix epoch to a relative age like '2m', '3h', '4d'."""
    if not ts:
        return "?"
    try:
        delta = int(time.time()) - int(ts)
    except Exception:
        return "?"
    if delta < 0:     return "future"
    if delta < 60:    return "now"
    if delta < 3600:  return f"{delta // 60}m"
    if delta < 86400: return f"{delta // 3600}h"
    return f"{delta // 86400}d"


def _human_uptime(s) -> str:
    """Convert seconds to '12h 34m 56s' style string."""
    if s is None:
        return "?"
    try:
        s = int(s)
    except Exception:
        return str(s)
    d, rem = divmod(s, 86400)
    h, rem = divmod(rem, 3600)
    m, sec = divmod(rem, 60)
    if d: return f"{d}d {h}h {m}m {sec}s"
    if h: return f"{h}h {m}m {sec}s"
    if m: return f"{m}m {sec}s"
    return f"{sec}s"


def _coerce_value(s: str, target_type, *, field_descriptor=None):
    """Convert a string value to the appropriate type.

    Handles:
      • bool          → 'true'/'1'/'yes'/'on' → True
      • int / float   → numeric parse
      • protobuf enum → look up name in enum descriptor

    field_descriptor (optional): protobuf FieldDescriptor for the target
    field; needed to resolve enum string names like 'LONG_FAST' → int value.

    BUG 22 (V20-turn2): a multi-line paste like
        set lora.region EU_868
        --set lora.use_preset true
        --set lora.modem_preset LONG_FAST
    used to be sent in one shot to _cmd_set, which then joined args[1:] into
    a value containing literal newlines. _coerce_value now normalises any
    embedded whitespace/newlines and, for enum and numeric fields, considers
    only the first whitespace-separated token.
    """
    s = str(s).strip()
    if target_type is bool:
        # bool also only cares about the first token
        first = s.split()[0] if s.split() else s
        return first.lower() in ("true", "1", "yes", "on", "y", "enable", "enabled")

    # protobuf enum resolution (when descriptor provided)
    if field_descriptor is not None:
        try:
            from google.protobuf.descriptor import FieldDescriptor
            if field_descriptor.type == FieldDescriptor.TYPE_ENUM:
                # Enums are always single tokens — be tolerant of accidental
                # multi-line / multi-word pastes by considering only the
                # first non-empty whitespace-separated token.
                tokens = s.split()
                if not tokens:
                    raise ValueError("empty enum value")
                token = tokens[0]
                # Accept either numeric or name (case-insensitive)
                if token.lstrip("-").isdigit():
                    return int(token)
                enum_type = field_descriptor.enum_type
                # Try exact + uppercased + lowercased lookup
                for name in (token, token.upper(), token.lower()):
                    val = enum_type.values_by_name.get(name)
                    if val is not None:
                        return val.number
                valid = [v.name for v in enum_type.values]
                raise ValueError(
                    f"invalid enum value '{token}'. Valid: {', '.join(valid)}")
        except ImportError:
            pass

    if target_type is int:
        first = s.split()[0] if s.split() else s
        try: return int(first)
        except ValueError: return int(float(first))
    if target_type is float:
        first = s.split()[0] if s.split() else s
        return float(first)
    return s


def _normalize_node_id(s: str) -> str:
    """Accept '!ba4bf9d0' or 'ba4bf9d0' — return canonical '!hex' form."""
    if not s:
        return s
    s = s.strip()
    if s.startswith("!"):
        return s.lower()
    # bare 8-char hex accepted
    if len(s) == 8 and all(c in "0123456789abcdefABCDEF" for c in s):
        return f"!{s.lower()}"
    return s  # leave unchanged; will likely error downstream


def _enum_name(obj, attr: str) -> str:
    """Get an enum-like attribute, prefer .name when available."""
    v = getattr(obj, attr, None)
    if v is None:
        return "?"
    name = getattr(v, "name", None)
    if name:
        return str(name)
    return str(v)


def _format_age(seconds: int) -> str:
    """Render a 'time since' duration compactly: 5s / 12m / 3h / 2d."""
    seconds = max(0, int(seconds))
    if seconds < 60:    return f"{seconds}s"
    if seconds < 3600:  return f"{seconds // 60}m"
    if seconds < 86400: return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"
