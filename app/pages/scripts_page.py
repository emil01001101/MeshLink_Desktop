"""
Scripts / Automation tab — user-friendly redesign (V20-turn6).

Left side:
    List of saved scripts (name + schedule + last status).

Right side:
    ┌─ Script header ────────────────────────────────────────────┐
    │  Name: [.....................]                              │
    │  Run every: [N] [hours ▼]   [✓ Enabled]                    │
    │  ──────────────────────────────────────────────────────────│
    │  Send to:                                                   │
    │    Channels:  [☑ # LongFast] [☐ # Iberia] [☐ # Other]       │
    │    Target:    ⦿ Broadcast    ○ Direct message to: [pick ▼]  │
    │  ──────────────────────────────────────────────────────────│
    │  💡 Quick insert:                                            │
    │  [📡 send_text] [🌡 env metrics] [🔋 device metrics]         │
    │  [📍 list nodes] [⏰ time]       [🗒 template]                │
    │                                                             │
    │  ┌─ Python code ───────────────────────────────────────┐   │
    │  │ # your script here                                   │   │
    │  │ ...                                                  │   │
    │  └──────────────────────────────────────────────────────┘   │
    │  [💾 Save (Ctrl+S)]  [▶ Run Now]  [🗑 Clear Output]          │
    │  ┌─ Output ─────────────────────────────────────────────┐   │
    │  └──────────────────────────────────────────────────────┘   │
    └────────────────────────────────────────────────────────────┘

The Send-to area defines defaults that send_text() uses when called
without arguments. Scripts can still override per-call with
send_text("...", channel=N, dest="!hex").
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QFont, QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QFrame,
    QListWidget, QListWidgetItem, QPlainTextEdit, QLineEdit, QSpinBox,
    QComboBox, QCheckBox, QMessageBox, QSplitter, QInputDialog,
    QRadioButton, QButtonGroup, QSizePolicy, QScrollArea
)

from ..scripts_db import ScriptsDB
from ..script_runner import ScriptScheduler
from ..theme import Colors

log = logging.getLogger("meshlink.scripts_page")


# ---------------------------------------------------------------------------
# Minimal blank-script template + ready-to-paste snippets
# ---------------------------------------------------------------------------
SCRIPT_TEMPLATE = '''"""
New automation script.

The "Send to" area above defines the default destination. Calling
send_text("...") with no other arguments uses those defaults.

API available without imports (full reference in script_runner.py):
    send_text(text, channel=None, dest=None) → send a message
    send_dm(node_id, text)                   → quick DM
    local_env() / local_device() / local_position()  → telemetry dicts
    channels() / channel_by_name(name)       → channel listings
    list_nodes() / get_node(node_id)         → node listings
    log(*msg)                                → print to output panel
    is_connected, my_node_id, my_channels    → state variables
"""

log("Hello from a Meshtastic script!")
log(f"Connected: {is_connected}")
log(f"My node: {my_node_id}")
log(f"Target channels: {my_channels}")
'''


SNIPPETS = [
    ("📡  send_text",
     'send_text("Hello mesh!")\n'),

    ("🌡  env metrics",
     '# Read local environment sensor data\n'
     'env = local_env()\n'
     'if "temperature" in env:\n'
     '    log(f"Temperature: {env[\'temperature\']:.1f}°C")\n'
     'if "relativeHumidity" in env:\n'
     '    log(f"Humidity: {env[\'relativeHumidity\']:.0f}%")\n'
     'if "barometricPressure" in env:\n'
     '    log(f"Pressure: {env[\'barometricPressure\']:.0f} hPa")\n'),

    ("🔋  device metrics",
     '# Read local device telemetry\n'
     'dev = local_device()\n'
     'if "batteryLevel" in dev:\n'
     '    log(f"Battery: {dev[\'batteryLevel\']}%")\n'
     'if "voltage" in dev:\n'
     '    log(f"Voltage: {dev[\'voltage\']:.2f} V")\n'),

    ("📍  list nodes",
     '# Iterate known mesh nodes\n'
     'for n in list_nodes():\n'
     '    user = n.get("user") or {}\n'
     '    log(f"{user.get(\'id\', \'?\')} — {user.get(\'longName\', \'\')}")\n'),

    ("⏰  current time",
     'from datetime import datetime\n'
     'now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")\n'
     'log(f"Now: {now}")\n'),

    ("🗒  full template",
     None),   # special: replaces editor contents with SCRIPT_TEMPLATE
]


# ===========================================================================
# ScriptsPage
# ===========================================================================
class ScriptsPage(QWidget):

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self._current_id: Optional[int] = None
        # Channels in the order published by the manager. Refreshed
        # whenever channelsUpdated fires.
        self._channels: List[dict] = []
        # Nodes (for the DM picker). Refreshed on nodeUpdated.
        self._nodes_by_id: Dict[str, dict] = {}

        self.scheduler = ScriptScheduler(manager, self)
        self.scheduler.runner.scriptStarted.connect(self._on_script_started)
        self.scheduler.runner.scriptLine.connect(self._on_script_line)
        self.scheduler.runner.scriptFinished.connect(self._on_script_finished)

        self._build_ui()
        self._connect_manager_signals()
        self._reload_list()

    # -----------------------------------------------------------------------
    # UI BUILDING
    # -----------------------------------------------------------------------
    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 20)
        root.setSpacing(12)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(8)
        splitter.setStyleSheet(
            f"QSplitter::handle {{ background: {Colors.BORDER}; }}")

        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 900])
        root.addWidget(splitter)

        # Initially disable controls until a script is selected
        self._set_editor_enabled(False)

        # Ctrl+S to save while editor is focused
        save_shortcut = QShortcut(QKeySequence("Ctrl+S"), self.editor)
        save_shortcut.activated.connect(self._save_current)

    # ---- LEFT: list of scripts --------------------------------------------
    def _build_left_panel(self) -> QFrame:
        left = QFrame()
        left.setObjectName("Card")
        left.setMinimumWidth(280)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(12, 12, 12, 12)
        ll.setSpacing(8)

        header = QLabel("AUTOMATION SCRIPTS")
        header.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: 10px; "
            f"font-weight: 700; letter-spacing: 1px; padding-bottom: 4px;")
        ll.addWidget(header)

        btns_top = QHBoxLayout()
        self.btn_new = QPushButton("➕  New")
        self.btn_new.setObjectName("PrimaryButton")
        self.btn_new.clicked.connect(self._new_script)
        self.btn_del = QPushButton("🗑  Delete")
        self.btn_del.setEnabled(False)
        self.btn_del.clicked.connect(self._delete_script)
        btns_top.addWidget(self.btn_new, 1)
        btns_top.addWidget(self.btn_del, 1)
        ll.addLayout(btns_top)

        self.list = QListWidget()
        self.list.setStyleSheet(f"""
            QListWidget {{
                background: {Colors.BG_BASE}; border: 1px solid {Colors.BORDER};
                border-radius: 8px; padding: 4px;
            }}
            QListWidget::item {{
                padding: 10px 12px; border-radius: 6px;
                color: {Colors.TEXT_PRIMARY};
            }}
            QListWidget::item:hover  {{ background: {Colors.BG_SURFACE_HI}; }}
            QListWidget::item:selected {{
                background: {Colors.PRIMARY_DARK}; color: white;
            }}
        """)
        self.list.currentItemChanged.connect(self._on_selection)
        ll.addWidget(self.list, 1)

        info = QLabel(
            "💡 Scripts run as Python code in a background thread.\n\n"
            "Click ▶ Run Now to test, then tick Enabled to put it on the "
            "schedule.\n\n"
            "Code lives in this app's database at:\n"
            "~/meshlink_desktop_logs/scripts.db")
        info.setWordWrap(True)
        info.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: 10px; "
            f"padding: 8px; line-height: 1.4;")
        ll.addWidget(info)

        return left

    # ---- RIGHT: editor + controls -----------------------------------------
    def _build_right_panel(self) -> QFrame:
        right = QFrame()
        right.setObjectName("Card")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(12, 12, 12, 12)
        rl.setSpacing(8)

        # ── Header: name + schedule ──
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        row1.addWidget(QLabel("Name:"))
        self.in_name = QLineEdit()
        self.in_name.setPlaceholderText("Give your script a name…")
        row1.addWidget(self.in_name, 2)
        row1.addSpacing(12)
        row1.addWidget(QLabel("Run every"))
        self.in_interval = QSpinBox()
        self.in_interval.setRange(0, 99999)
        self.in_interval.setValue(0)
        self.in_interval.setSpecialValueText("manual only")
        self.in_interval.setFixedWidth(110)
        row1.addWidget(self.in_interval)
        self.in_unit = QComboBox()
        self.in_unit.addItems(["seconds", "minutes", "hours", "days"])
        self.in_unit.setCurrentText("hours")
        self.in_unit.setFixedWidth(110)
        row1.addWidget(self.in_unit)
        self.cb_enabled = QCheckBox("Enabled")
        self.cb_enabled.setStyleSheet(
            f"QCheckBox {{ font-weight: 600; color: {Colors.TEXT_PRIMARY}; }}")
        row1.addWidget(self.cb_enabled)
        row1.addStretch(1)
        rl.addLayout(row1)

        # ── Separator ──
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.HLine)
        sep1.setStyleSheet(f"color: {Colors.BORDER};")
        rl.addWidget(sep1)

        # ── Send to: channels + target ──
        sendto_row = QVBoxLayout()
        sendto_row.setSpacing(6)

        st_header = QLabel("📤  Send to")
        st_header.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; font-size: 12px; "
            f"font-weight: 700;")
        sendto_row.addWidget(st_header)

        # Channels row (populated dynamically)
        ch_label_row = QHBoxLayout()
        ch_lbl = QLabel("Channels:")
        ch_lbl.setStyleSheet(f"color: {Colors.TEXT_DIM};")
        ch_lbl.setFixedWidth(80)
        ch_label_row.addWidget(ch_lbl)
        # Scrollable horizontal container of checkboxes
        self.channels_box = QFrame()
        self.channels_box.setStyleSheet(
            f"background: {Colors.BG_INPUT}; "
            f"border: 1px solid {Colors.BORDER}; border-radius: 6px;")
        self.channels_layout = QHBoxLayout(self.channels_box)
        self.channels_layout.setContentsMargins(8, 6, 8, 6)
        self.channels_layout.setSpacing(10)
        # Placeholder until channels are loaded
        self._channels_placeholder = QLabel(
            "(connect to a device to see channels)")
        self._channels_placeholder.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: 11px;")
        self.channels_layout.addWidget(self._channels_placeholder)
        self.channels_layout.addStretch(1)
        ch_label_row.addWidget(self.channels_box, 1)
        sendto_row.addLayout(ch_label_row)

        # Target row: Broadcast vs DM
        target_row = QHBoxLayout()
        target_lbl = QLabel("Target:")
        target_lbl.setStyleSheet(f"color: {Colors.TEXT_DIM};")
        target_lbl.setFixedWidth(80)
        target_row.addWidget(target_lbl)
        self.target_group = QButtonGroup(self)
        self.rb_broadcast = QRadioButton("📢  Broadcast (public)")
        self.rb_broadcast.setChecked(True)
        self.rb_dm = QRadioButton("🔒  Direct message (private) to:")
        self.target_group.addButton(self.rb_broadcast)
        self.target_group.addButton(self.rb_dm)
        target_row.addWidget(self.rb_broadcast)
        target_row.addWidget(self.rb_dm)
        self.dm_picker = QComboBox()
        self.dm_picker.setMinimumWidth(260)
        self.dm_picker.setEnabled(False)
        self.dm_picker.setEditable(True)   # also allows entering '!hex'
        self.dm_picker.setPlaceholderText("Pick a node or paste !hexid")
        target_row.addWidget(self.dm_picker)
        target_row.addStretch(1)
        # V20-turn14: make Broadcast vs DM a clean either/or. When DM is
        # selected, the channel checkboxes are disabled (a DM only uses the
        # primary channel as transport, it is NOT a public broadcast) so
        # there's no confusion that the message also goes out on LongFast.
        self.rb_broadcast.toggled.connect(self._on_target_mode_changed)
        sendto_row.addLayout(target_row)

        # Hint shown under the target row when DM mode is active
        self.lbl_dm_hint = QLabel(
            "🔒  Private message — sent only to the selected node. "
            "Channels above are ignored in DM mode.")
        self.lbl_dm_hint.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: 11px; "
            f"padding: 2px 0 0 84px;")
        self.lbl_dm_hint.setVisible(False)
        sendto_row.addWidget(self.lbl_dm_hint)

        rl.addLayout(sendto_row)

        # ── Separator ──
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet(f"color: {Colors.BORDER};")
        rl.addWidget(sep2)

        # ── Quick-insert snippets ──
        snippet_row = QHBoxLayout()
        snippet_row.setSpacing(6)
        snip_lbl = QLabel("💡 Quick insert:")
        snip_lbl.setStyleSheet(f"color: {Colors.TEXT_DIM}; font-size: 11px;")
        snippet_row.addWidget(snip_lbl)
        for label, code in SNIPPETS:
            btn = QPushButton(label)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {Colors.BG_INPUT};
                    color: {Colors.TEXT_PRIMARY};
                    border: 1px solid {Colors.BORDER};
                    border-radius: 6px;
                    padding: 4px 10px; font-size: 11px;
                }}
                QPushButton:hover {{
                    background: {Colors.BG_SURFACE_HI};
                    border-color: {Colors.PRIMARY};
                }}
            """)
            btn.clicked.connect(
                lambda _c=False, c=code: self._insert_snippet(c))
            snippet_row.addWidget(btn)
        snippet_row.addStretch(1)
        rl.addLayout(snippet_row)

        # ── Python editor ──
        self.editor = QPlainTextEdit()
        mono = QFont("Consolas", 10)
        mono.setStyleHint(QFont.Monospace)
        self.editor.setFont(mono)
        self.editor.setTabStopDistance(4 * 8)
        self.editor.setStyleSheet(f"""
            QPlainTextEdit {{
                background: {Colors.BG_CONSOLE}; color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER}; border-radius: 8px;
                padding: 8px; selection-background-color: {Colors.PRIMARY};
                selection-color: {Colors.TEXT_ON_PRIMARY};
            }}
        """)
        self.editor.setPlaceholderText(
            "# Pick a script on the left, or click '➕ New' to create one.")
        rl.addWidget(self.editor, 2)

        # ── Action buttons ──
        btns = QHBoxLayout()
        self.btn_save = QPushButton("💾  Save  (Ctrl+S)")
        self.btn_save.setObjectName("PrimaryButton")
        self.btn_save.clicked.connect(self._save_current)
        btns.addWidget(self.btn_save)
        self.btn_run = QPushButton("▶  Run Now")
        self.btn_run.clicked.connect(self._run_current)
        btns.addWidget(self.btn_run)
        self.btn_clear_output = QPushButton("🗑  Clear Output")
        self.btn_clear_output.clicked.connect(lambda: self.output.clear())
        btns.addWidget(self.btn_clear_output)
        btns.addStretch(1)
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: 11px;")
        btns.addWidget(self.lbl_status)
        rl.addLayout(btns)

        # ── Output panel ──
        out_lbl = QLabel("Output:")
        out_lbl.setStyleSheet(f"color: {Colors.TEXT_DIM}; font-size: 11px;")
        rl.addWidget(out_lbl)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(2000)
        self.output.setFont(mono)
        self.output.setMaximumHeight(180)
        self.output.setStyleSheet(f"""
            QPlainTextEdit {{
                background: {Colors.BG_CONSOLE}; color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER}; border-radius: 8px;
                padding: 8px;
            }}
        """)
        rl.addWidget(self.output, 1)

        return right

    # -----------------------------------------------------------------------
    # Manager signal hooks (channels + nodes for the pickers)
    # -----------------------------------------------------------------------
    def _connect_manager_signals(self):
        self.manager.channelsUpdated.connect(self._on_channels_updated)
        self.manager.nodeUpdated.connect(self._on_node_updated)

    @Slot(list)
    def _on_channels_updated(self, channels: list):
        # Keep only PRIMARY + SECONDARY
        self._channels = [c for c in channels
                          if c.get("role") in ("PRIMARY", "SECONDARY")]
        self._rebuild_channel_checkboxes()

    @Slot(str, dict)
    def _on_node_updated(self, node_id: str, node: dict):
        self._nodes_by_id[node_id] = node
        # Refresh the DM picker (preserve current selection if possible)
        prev = self.dm_picker.currentText().strip()
        self.dm_picker.blockSignals(True)
        self.dm_picker.clear()
        # Sort by long name for readability
        sorted_nodes = sorted(
            self._nodes_by_id.values(),
            key=lambda n: ((n.get("user") or {}).get("longName") or "").lower())
        for n in sorted_nodes:
            user = n.get("user") or {}
            nid  = user.get("id") or ""
            if not nid:
                continue
            long_n = user.get("longName") or nid
            short_n = user.get("shortName") or ""
            display = f"{long_n}  ({nid})" + (f"  · {short_n}" if short_n else "")
            self.dm_picker.addItem(display, nid)
        if prev:
            self.dm_picker.setEditText(prev)
        self.dm_picker.blockSignals(False)

    # -----------------------------------------------------------------------
    # Channel checkbox rebuilding
    # -----------------------------------------------------------------------
    def _rebuild_channel_checkboxes(self):
        """Replace the channel checkboxes with one per known channel."""
        # Remember current selection by index
        prev_selected = self._read_channel_indices()
        # Clear the layout
        while self.channels_layout.count():
            item = self.channels_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        if not self._channels:
            self._channels_placeholder = QLabel(
                "(connect to a device to see channels)")
            self._channels_placeholder.setStyleSheet(
                f"color: {Colors.TEXT_DIM}; font-size: 11px;")
            self.channels_layout.addWidget(self._channels_placeholder)
            self.channels_layout.addStretch(1)
            return
        # Add one checkbox per channel
        self._channel_checkboxes: List[QCheckBox] = []
        for ch in self._channels:
            idx = ch.get("index", 0)
            name = ch.get("name") or f"ch{idx}"
            icon = "★" if ch.get("role") == "PRIMARY" else "#"
            cb = QCheckBox(f"{icon}  {name}")
            cb.setProperty("channel_index", idx)
            cb.setStyleSheet(f"""
                QCheckBox {{
                    color: {Colors.TEXT_PRIMARY};
                    spacing: 6px;
                    padding: 2px 4px;
                }}
            """)
            # Restore previous selection; default to PRIMARY only
            if prev_selected:
                cb.setChecked(idx in prev_selected)
            else:
                cb.setChecked(ch.get("role") == "PRIMARY")
            self.channels_layout.addWidget(cb)
            self._channel_checkboxes.append(cb)
        self.channels_layout.addStretch(1)

    def _read_channel_indices(self) -> List[int]:
        """Return list of currently-checked channel indices."""
        if not hasattr(self, "_channel_checkboxes"):
            return []
        out = []
        for cb in self._channel_checkboxes:
            if cb.isChecked():
                idx = cb.property("channel_index")
                if idx is not None:
                    out.append(int(idx))
        return out

    def _set_channel_indices(self, indices: List[int]):
        """Check the boxes whose channel index is in `indices`."""
        if not hasattr(self, "_channel_checkboxes"):
            return
        for cb in self._channel_checkboxes:
            idx = cb.property("channel_index")
            cb.setChecked(idx in indices)

    # -----------------------------------------------------------------------
    # State helpers
    # -----------------------------------------------------------------------
    def _set_editor_enabled(self, on: bool):
        for w in (self.in_name, self.in_interval, self.in_unit, self.cb_enabled,
                  self.editor, self.btn_save, self.btn_run,
                  self.rb_broadcast, self.rb_dm, self.dm_picker,
                  self.channels_box):
            w.setEnabled(on)
        # DM picker is only enabled when DM is selected AND editor is enabled
        if on and self.rb_dm.isChecked():
            self.dm_picker.setEnabled(True)
        else:
            self.dm_picker.setEnabled(False)

    def _reload_list(self):
        prev_id = self._current_id
        self.list.blockSignals(True)
        self.list.clear()
        scripts = ScriptsDB.get().list_all()
        selected_row = -1
        for i, s in enumerate(scripts):
            item = QListWidgetItem(self._format_list_item(s))
            item.setData(Qt.UserRole, s["id"])
            self.list.addItem(item)
            if s["id"] == prev_id:
                selected_row = i
        self.list.blockSignals(False)
        if selected_row >= 0:
            self.list.setCurrentRow(selected_row)
        elif self.list.count() > 0:
            self.list.setCurrentRow(0)

    def _format_list_item(self, s: dict) -> str:
        status_icon = "⚪"
        if s.get("enabled") and (s.get("interval_seconds") or 0) > 0:
            status_icon = "🟢"
        last = ""
        ls = s.get("last_status")
        if ls == "ok":      last = " ✓"
        elif ls == "error": last = " ✗"
        elif ls == "running": last = " ⟳"
        # Schedule summary
        sec = int(s.get("interval_seconds") or 0)
        if sec > 0 and s.get("enabled"):
            schedule = " · " + _seconds_friendly(sec)
        elif sec > 0:
            schedule = " · disabled"
        else:
            schedule = " · manual"
        return f"{status_icon}  {s['name']}{last}\n      {schedule.lstrip(' ·')}"

    # -----------------------------------------------------------------------
    # Selection / load
    # -----------------------------------------------------------------------
    def _on_selection(self, cur, _prev):
        if cur is None:
            self._current_id = None
            self.btn_del.setEnabled(False)
            self._set_editor_enabled(False)
            self.in_name.clear()
            self.editor.clear()
            self.output.clear()
            return
        sid = cur.data(Qt.UserRole)
        self._current_id = sid
        self.btn_del.setEnabled(True)
        self._set_editor_enabled(True)
        s = ScriptsDB.get().get_by_id(sid)
        if not s:
            return
        self.in_name.setText(s["name"])
        sec = int(s.get("interval_seconds") or 0)
        unit_idx, value = _seconds_to_unit(sec)
        self.in_unit.setCurrentIndex(unit_idx)
        self.in_interval.setValue(value)
        self.cb_enabled.setChecked(bool(s.get("enabled")))
        self.editor.setPlainText(s.get("code") or "")
        # Channels: parse CSV
        ch_csv = s.get("target_channels") or "0"
        try:
            indices = [int(x.strip()) for x in ch_csv.split(",") if x.strip()]
        except ValueError:
            indices = [0]
        self._set_channel_indices(indices)
        # Target: broadcast vs DM
        dest = (s.get("target_dest") or "").strip()
        if dest and dest not in ("^all", "!ffffffff"):
            self.rb_dm.setChecked(True)
            self.dm_picker.setEditText(dest)
        else:
            self.rb_broadcast.setChecked(True)
        # Apply the enable/disable + hint for the loaded mode
        self._on_target_mode_changed(self.rb_broadcast.isChecked())
        # Show last output if any
        self.output.clear()
        last_out = s.get("last_output") or ""
        if last_out:
            self.output.appendPlainText(last_out)
        self._refresh_status_label(s)

    def _refresh_status_label(self, s: Optional[dict] = None):
        if s is None and self._current_id is not None:
            s = ScriptsDB.get().get_by_id(self._current_id)
        if not s:
            self.lbl_status.setText("")
            return
        parts = []
        if s.get("last_run"):
            ts = datetime.fromtimestamp(s["last_run"]).strftime("%H:%M:%S")
            ls = s.get("last_status") or "?"
            parts.append(f"Last run: {ts} ({ls})")
        if s.get("enabled") and s.get("next_run"):
            nr = datetime.fromtimestamp(s["next_run"]).strftime("%H:%M:%S")
            parts.append(f"Next: {nr}")
        self.lbl_status.setText("  ·  ".join(parts))

    # -----------------------------------------------------------------------
    # CRUD
    # -----------------------------------------------------------------------
    def _new_script(self):
        name, ok = QInputDialog.getText(self, "New script", "Name:")
        if not ok or not name.strip():
            return
        # Default: every 1 hour, broadcast on primary channel only.
        new_id = ScriptsDB.get().create(
            name=name.strip(),
            code=SCRIPT_TEMPLATE,
            interval_seconds=3600,
            enabled=False,
            target_channels="0",
            target_dest="",
        )
        self._current_id = new_id
        self._reload_list()

    def _delete_script(self):
        if self._current_id is None:
            return
        s = ScriptsDB.get().get_by_id(self._current_id)
        if not s:
            return
        r = QMessageBox.question(
            self, "Delete script",
            f"Delete '{s['name']}' permanently?")
        if r != QMessageBox.Yes:
            return
        ScriptsDB.get().delete(self._current_id)
        self._current_id = None
        self._reload_list()

    def _on_target_mode_changed(self, broadcast_checked: bool):
        """Toggle UI between Broadcast (public) and Direct message (private).

        Broadcast → channel checkboxes active, DM picker disabled.
        DM        → channel checkboxes disabled+greyed (DM only uses the
                    primary channel as transport, not a public broadcast),
                    DM picker active, hint shown.
        """
        is_dm = not broadcast_checked
        self.dm_picker.setEnabled(is_dm)
        # Grey out / disable the channel checkboxes in DM mode
        try:
            self.channels_box.setEnabled(not is_dm)
        except Exception:
            pass
        self.lbl_dm_hint.setVisible(is_dm)

    def _resolve_dm_target(self) -> str:
        """Return the node id from the DM picker (combobox can be edited)."""
        # Prefer userData if the user picked from the dropdown
        idx = self.dm_picker.currentIndex()
        if idx >= 0:
            data = self.dm_picker.itemData(idx)
            text = self.dm_picker.currentText()
            # If user typed something that doesn't match an item, prefer text
            if data and (text.startswith(data) or data in text):
                return str(data)
        # Otherwise parse the free text — accept "!hex" or "name (!hex)"
        text = self.dm_picker.currentText().strip()
        if not text:
            return ""
        # Look for !hex pattern
        import re
        m = re.search(r"!?[0-9a-fA-F]{8}", text)
        if m:
            tok = m.group(0)
            return tok if tok.startswith("!") else "!" + tok.lower()
        return text   # fall through; manager will reject if invalid

    def _save_current(self):
        if self._current_id is None:
            return
        unit = self.in_unit.currentText()
        value = int(self.in_interval.value())
        sec = _unit_to_seconds(value, unit)
        # Channels CSV
        indices = self._read_channel_indices()
        is_dm = self.rb_dm.isChecked()

        # Validation differs by target mode:
        #  • Broadcast → at least one channel must be ticked (that's where
        #    the public message goes).
        #  • Direct message → the DM still travels on a channel (the channel
        #    PSK encrypts it), but the user shouldn't have to think about
        #    that. If they picked a DM target but no channel, default to
        #    the PRIMARY channel (index 0) automatically.
        if is_dm:
            target_dest = self._resolve_dm_target()
            if not target_dest:
                QMessageBox.warning(self, "Missing DM target",
                                    "You selected 'Direct message' but didn't "
                                    "pick a node. Either pick one or switch to "
                                    "Broadcast.")
                return
            if not indices:
                # Auto-use the primary channel for the DM
                indices = [0]
                log.info("DM with no channel ticked — defaulting to PRIMARY (0)")
        else:
            target_dest = ""
            if not indices:
                QMessageBox.warning(self, "No channel selected",
                                    "Please tick at least one channel for a "
                                    "broadcast message — that's where it will "
                                    "be sent.")
                return

        target_channels = ",".join(str(i) for i in indices)
        ScriptsDB.get().update(
            self._current_id,
            name=self.in_name.text().strip() or "(unnamed)",
            code=self.editor.toPlainText(),
            interval_seconds=sec,
            enabled=1 if self.cb_enabled.isChecked() else 0,
            target_channels=target_channels,
            target_dest=target_dest,
            next_run=None,
        )
        import time as _t
        ScriptsDB.get().update(
            self._current_id,
            next_run=int(_t.time()) + sec
                     if (sec > 0 and self.cb_enabled.isChecked()) else 0,
        )
        self.lbl_status.setText("✓ Saved.")
        QTimer.singleShot(2000, lambda: self._refresh_status_label())
        self._reload_list()

    def _run_current(self):
        if self._current_id is None:
            return
        # Save first so the runner reads the latest code + target settings
        self._save_current()
        self.output.clear()
        self.scheduler.trigger_now(self._current_id)

    # -----------------------------------------------------------------------
    # Snippet insert
    # -----------------------------------------------------------------------
    def _insert_snippet(self, code: Optional[str]):
        """Insert a code snippet at the cursor.

        Special case: when code is None we replace the whole editor with the
        full SCRIPT_TEMPLATE (the "full template" button).
        """
        if not self.editor.isEnabled():
            return
        if code is None:
            # "full template" — only replace if editor is empty or user confirms
            if self.editor.toPlainText().strip():
                r = QMessageBox.question(
                    self, "Replace contents",
                    "Replace the current script with the empty template?")
                if r != QMessageBox.Yes:
                    return
            self.editor.setPlainText(SCRIPT_TEMPLATE)
            return
        cursor = self.editor.textCursor()
        # Insert at the start of the current line so snippets line up clean
        cursor.movePosition(QTextCursor.StartOfLine)
        cursor.insertText(code)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    # -----------------------------------------------------------------------
    # Runner callbacks
    # -----------------------------------------------------------------------
    def _on_script_started(self, sid: int):
        if sid != self._current_id:
            return
        self.output.appendPlainText(
            f"── started @ {datetime.now().strftime('%H:%M:%S')} ──")

    def _on_script_line(self, sid: int, line: str):
        if sid != self._current_id:
            return
        self.output.appendPlainText(line)

    def _on_script_finished(self, sid: int, status: str, _full: str):
        self._reload_list()
        if sid != self._current_id:
            return
        marker = "✓ OK" if status == "ok" else "✗ ERROR"
        self.output.appendPlainText(f"── finished: {marker} ──")
        self._refresh_status_label()


# ===========================================================================
# Helpers
# ===========================================================================
def _unit_to_seconds(value: int, unit: str) -> int:
    return {
        "seconds": value,
        "minutes": value * 60,
        "hours":   value * 3600,
        "days":    value * 86400,
    }.get(unit, value)


def _seconds_to_unit(sec: int) -> tuple:
    """Return (unit_combo_index, value) — pick the largest unit that's whole."""
    if sec == 0:
        return 2, 0   # hours, value 0 (special "manual")
    for idx, div in ((3, 86400), (2, 3600), (1, 60)):
        if sec % div == 0:
            return idx, sec // div
    return 0, sec  # seconds


def _seconds_friendly(sec: int) -> str:
    """Render seconds as a friendly schedule string (for the list)."""
    if sec >= 86400 and sec % 86400 == 0:
        d = sec // 86400
        return f"every {d}d"
    if sec >= 3600 and sec % 3600 == 0:
        h = sec // 3600
        return f"every {h}h"
    if sec >= 60 and sec % 60 == 0:
        m = sec // 60
        return f"every {m}m"
    return f"every {sec}s"
