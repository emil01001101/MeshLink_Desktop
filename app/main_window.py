"""
Main window — production version.

Integreaza:
  • ConnectionBar sus (cu selector limba)
  • Tabs: Messages | Nodes | Channels | Info | Map | Scripts | Console | Settings
  • Status bar jos cu baterie + uptime + last activity
  • System tray + notificari pentru mesaje noi
  • Persistenta setarilor intre sesiuni
  • Auto-reconnect (configurabil)
  • Istoric mesaje SQLite (configurabil)
"""

from __future__ import annotations

import time
import logging

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QFrame, QLabel,
    QTabWidget, QMessageBox, QApplication, QPushButton
)

from .connection import MeshtasticManager
from .widgets.connection_bar import ConnectionBar
from .pages.messages_page import MessagesPage
from .pages.nodes_page    import NodesPage
from .pages.channels_page import ChannelsPage
from .pages.info_page     import InfoPage
from .pages.scanner_page  import ScannerPage
from .pages.map_page      import MapPage
from .pages.console_page  import ConsolePage
from .pages.games_page    import GamesPage
from .pages.scripts_page  import ScriptsPage
from .pages.modules_page  import ModulesPage
from .pages.settings_page import SettingsPage
from .theme import Colors
from .i18n import t, i18n
from .settings_store import Settings
from .notifications import NotificationManager, SoundPlayer, make_app_icon

log = logging.getLogger("meshlink.window")


# index taburi
TAB_MESSAGES = 0
TAB_NODES    = 1
TAB_CHANNELS = 2
TAB_INFO     = 3
TAB_SCANNER  = 4   # V20-turn15: RF activity scanner
TAB_MAP      = 5
TAB_SCRIPTS  = 6
TAB_MODULES  = 7
TAB_CONSOLE  = 8
TAB_GAMES    = 9   # V0.44: Tic-Tac-Toe over mesh
TAB_SETTINGS = 10


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("MeshLink Desktop")
        self.setWindowIcon(make_app_icon(64))
        self.resize(1320, 840)
        # V20-turn10: allow rendering on small laptop screens (1280x720) and
        # tiny windows for tile-managers. Pages have their own scroll areas
        # so content reflows when the window is narrower than the design.
        self.setMinimumSize(QSize(760, 500))

        self.manager = MeshtasticManager(self)
        self._device_info = {}
        self._my_metrics = {}
        self._my_metrics_ts = 0
        self._last_activity_ts = 0
        self._first_ready = True
        self._allow_close = False

        # restore window geometry
        geom = Settings.get().window_geometry
        if geom:
            try:
                self.restoreGeometry(geom)
            except Exception:
                pass

        # notifications / tray / sound
        self.notif = NotificationManager(self)
        self.notif.set_enabled(Settings.get().notifications)
        self.notif.tray_show_request.connect(self._show_from_tray)
        self.notif.tray_quit_request.connect(self._force_quit)

        self.sound = SoundPlayer(self)
        self.sound.set_muted(not Settings.get().sound_enabled)

        # auto-reconnect setting
        self.manager.set_auto_reconnect(Settings.get().auto_reconnect)

        # BUILD UI FIRST, then start timers that touch widgets
        self._build_ui()
        self._connect_signals()

        # status update timer (must be AFTER _build_ui creates status bar widgets)
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(1000)
        self._status_timer.timeout.connect(self._refresh_status_bar)
        self._status_timer.start()

        self._restore_last_connection()
        self._refresh_serial_ports()

    # =================================================================
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # TOP CONNECTION BAR
        self.conn_bar = ConnectionBar()
        root.addWidget(self.conn_bar)

        # TABS
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        self.page_messages = MessagesPage(self.manager)
        self.page_nodes    = NodesPage(self.manager)
        self.page_channels = ChannelsPage(self.manager)
        self.page_info     = InfoPage(self.manager)
        self.page_scanner  = ScannerPage(self.manager)
        self.page_map      = MapPage(self.manager)
        self.page_scripts  = ScriptsPage(self.manager)
        self.page_modules  = ModulesPage(self.manager)
        self.page_console  = ConsolePage(self.manager)
        self.page_games    = GamesPage(self.manager)
        self.page_settings = SettingsPage(self.manager)

        self.tabs.addTab(self.page_messages, "")
        self.tabs.addTab(self.page_nodes,    "")
        self.tabs.addTab(self.page_channels, "")
        self.tabs.addTab(self.page_info,     "")
        self.tabs.addTab(self.page_scanner,  "")
        self.tabs.addTab(self.page_map,      "")
        self.tabs.addTab(self.page_scripts,  "")
        self.tabs.addTab(self.page_modules,  "")
        self.tabs.addTab(self.page_console,  "")
        self.tabs.addTab(self.page_games,    "")
        self.tabs.addTab(self.page_settings, "")

        # Let the Scanner pause the script scheduler during a scan.
        try:
            self.page_scanner.set_scheduler(self.page_scripts.scheduler)
        except Exception:
            pass

        root.addWidget(self.tabs, 1)
        root.addWidget(self._build_status_bar())

        # initial tab si traduceri
        self.tabs.setCurrentIndex(TAB_INFO)
        i18n.languageChanged.connect(self._retranslate_tabs)
        i18n.languageChanged.connect(lambda *_: self._on_state(self.manager.state))
        self._retranslate_tabs()

    def _build_status_bar(self) -> QFrame:
        s = QFrame()
        s.setObjectName("StatusBar")
        s.setFixedHeight(28)
        l = QHBoxLayout(s)
        l.setContentsMargins(14, 4, 14, 4)
        l.setSpacing(12)
        self.sb_dot = QLabel()
        self.sb_dot.setObjectName("StatusDot")
        self.sb_dot.setProperty("state", "offline")
        l.addWidget(self.sb_dot)
        self.sb_state = QLabel("")
        l.addWidget(self.sb_state)
        l.addWidget(self._sep())
        self.sb_device = QLabel("device: —")
        l.addWidget(self.sb_device)
        l.addWidget(self._sep())
        self.sb_battery = QLabel("🔋 —")
        l.addWidget(self.sb_battery)
        l.addWidget(self._sep())
        self.sb_uptime = QLabel("⏱ —")
        l.addWidget(self.sb_uptime)
        l.addStretch(1)
        self.sb_fw = QLabel("fw: —")
        l.addWidget(self.sb_fw)
        l.addWidget(self._sep())
        self.sb_last_msg = QLabel("packet: —")
        l.addWidget(self.sb_last_msg)

        # V20-turn10: theme toggle (sun / moon)
        l.addWidget(self._sep())
        self.btn_theme = QPushButton()
        self.btn_theme.setObjectName("ThemeToggle")
        self.btn_theme.setFlat(True)
        self.btn_theme.setCursor(Qt.PointingHandCursor)
        self.btn_theme.setFixedSize(24, 22)
        self.btn_theme.setToolTip("Toggle light / dark theme")
        self.btn_theme.clicked.connect(self._toggle_theme)
        self._refresh_theme_button_label()
        l.addWidget(self.btn_theme)

        # V20-turn10: elegant author label, clickable -> About popup
        l.addWidget(self._sep())
        self.sb_author = QLabel("© Emil M.")
        self.sb_author.setObjectName("AuthorLabel")
        self.sb_author.setCursor(Qt.PointingHandCursor)
        self.sb_author.setToolTip("About MeshLink Desktop")
        self.sb_author.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; "
            f"font-size: 11px; font-style: italic; "
            f"padding: 2px 6px;")
        self.sb_author.mousePressEvent = lambda _e: self._show_about_dialog()
        l.addWidget(self.sb_author)
        return s

    def _refresh_theme_button_label(self):
        from .theme import current_theme
        # show the icon for the theme you'd switch TO
        self.btn_theme.setText("☀" if current_theme() == "dark" else "🌙")

    def _toggle_theme(self):
        """Flip between dark and light themes and persist to Settings."""
        from .theme import current_theme, apply_theme, build_stylesheet
        from PySide6.QtWidgets import QApplication
        new = "light" if current_theme() == "dark" else "dark"
        apply_theme(new)
        app = QApplication.instance()
        if app:
            app.setStyleSheet(build_stylesheet())
        self._refresh_theme_button_label()
        # Persist
        try:
            from .settings_store import Settings
            s = Settings.get()
            s.theme = new
            s.save()
        except Exception:
            log.exception("Could not persist theme preference")
        log.info(f"Theme switched to {new}")

    def _show_about_dialog(self):
        """Small About popup — description + GitHub link."""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel
        from PySide6.QtCore import Qt
        dlg = QDialog(self)
        dlg.setWindowTitle("About MeshLink Desktop")
        dlg.setFixedWidth(420)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(20, 18, 20, 16)
        v.setSpacing(10)
        title = QLabel("MeshLink Desktop")
        title.setStyleSheet(
            f"font-size: 16px; font-weight: 700; "
            f"color: {Colors.PRIMARY};")
        v.addWidget(title)
        author = QLabel("by Emil M.")
        author.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; font-size: 12px;")
        v.addWidget(author)
        # ≤300 char description
        desc = QLabel(
            "MeshLink Desktop started as a personal project — built for my "
            "own use, out of pure passion for radio and technology. "
            "I'm sharing the source code freely so others can enjoy it too, "
            "learn from it, and make it even better together. "
            "If it's useful to you, that already makes me happy. 🙂\n\n"
            "Open source under GPL-3.0 · Python + PySide6 · "
            "crafted with the help of AI (Claude by Anthropic)."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; "
            f"font-size: 12px; line-height: 1.6; padding: 6px 0;")
        v.addWidget(desc)
        thanks = QLabel(
            "Thanks for being here — happy meshing! 📡")
        thanks.setStyleSheet(
            f"color: {Colors.PRIMARY}; font-size: 12px; "
            f"font-style: italic; padding: 2px 0 6px 0;")
        v.addWidget(thanks)
        link = QLabel(
            '<a href="https://github.com/emil01001101/MeshLink_Desktop" '
            f'style="color: {Colors.PRIMARY}; text-decoration: none;">'
            '🔗  github.com/emil01001101/MeshLink_Desktop</a>')
        link.setOpenExternalLinks(True)
        link.setStyleSheet("font-size: 12px; padding: 6px 0;")
        v.addWidget(link)
        v.addStretch(1)
        from PySide6.QtWidgets import QPushButton, QHBoxLayout
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn = QPushButton("Close")
        btn.setObjectName("PrimaryButton")
        btn.clicked.connect(dlg.accept)
        btn_row.addWidget(btn)
        v.addLayout(btn_row)
        dlg.exec()

    def _sep(self) -> QLabel:
        s = QLabel("│")
        s.setStyleSheet(f"color: {Colors.BORDER_HI};")
        return s

    def _retranslate_tabs(self, *_):
        self.tabs.setTabText(TAB_MESSAGES, "💬  " + t("tab.messages"))
        self.tabs.setTabText(TAB_NODES,    "📡  " + t("tab.nodes"))
        self.tabs.setTabText(TAB_CHANNELS, "#  " + t("tab.channels"))
        self.tabs.setTabText(TAB_INFO,     "ℹ  " + t("tab.info"))
        self.tabs.setTabText(TAB_SCANNER,  "📡  " + t("tab.scanner"))
        self.tabs.setTabText(TAB_MAP,      "🗺  " + t("tab.map"))
        self.tabs.setTabText(TAB_SCRIPTS,  "🤖  " + t("tab.scripts"))
        self.tabs.setTabText(TAB_MODULES,  "🧩  " + t("tab.modules"))
        self.tabs.setTabText(TAB_CONSOLE,  "⌘  " + t("tab.console"))
        self.tabs.setTabText(TAB_GAMES,    "🎮  " + t("tab.games"))
        self.tabs.setTabText(TAB_SETTINGS, "⚙  " + t("tab.settings"))

    # =================================================================
    # SIGNALS
    # =================================================================
    def _connect_signals(self):
        self.conn_bar.connectRequested.connect(self._on_connect_request)
        self.conn_bar.disconnectRequested.connect(self._on_disconnect_request)
        self.conn_bar.refreshPortsRequested.connect(self._refresh_serial_ports)
        self.conn_bar.languageChangeRequested.connect(self._change_language)
        self.conn_bar.muteToggled.connect(self._on_mute_toggled)

        self.manager.stateChanged.connect(self._on_state)
        self.manager.progressMessage.connect(self._on_progress)
        self.manager.deviceInfoReady.connect(self._on_device_info)
        self.manager.rawPacketReceived.connect(self._on_packet)
        self.manager.nodeUpdated.connect(self._on_node_updated)
        self.manager.telemetryReceived.connect(self._on_telemetry)
        self.manager.telemetryPopupReady.connect(self._show_telemetry_popup)
        self.manager.errorMessage.connect(self._on_error)

        self.page_nodes.requestStartDM.connect(self._start_dm_from_nodes)
        self.page_messages.newMessageReceived.connect(self._on_new_message_notify)
        self.page_settings.preferenceChanged.connect(self._on_preference_changed)

        # initialize mute button state from settings
        self.conn_bar.set_muted(not Settings.get().sound_enabled)

    def _on_mute_toggled(self, muted: bool):
        self.sound.set_muted(muted)
        Settings.get().sound_enabled = not muted

    def _refresh_serial_ports(self):
        self.conn_bar.populate_serial_ports(self.manager.list_serial_ports())

    def _restore_last_connection(self):
        s = Settings.get()
        self.conn_bar.set_initial(
            conn_type   = s.last_conn_type,
            serial_port = s.last_serial_port,
            ble_addr    = s.last_ble_address,
            wifi_host   = s.last_wifi_host,
            wifi_port   = s.last_wifi_port,
        )

    def _on_connect_request(self, conn_type: str, target: str):
        # save the latest settings for next time
        s = Settings.get()
        s.last_conn_type = conn_type
        if conn_type == "serial":
            s.last_serial_port = target
        elif conn_type == "ble":
            s.last_ble_address = target
        elif conn_type == "tcp":
            host, _, port_str = target.partition(":")
            s.last_wifi_host = host
            try: s.last_wifi_port = int(port_str)
            except Exception: pass
        self.manager.connect_to_device(conn_type, target)

    def _on_disconnect_request(self):
        self.manager.disconnect(user_initiated=True)

    def _change_language(self, code: str):
        i18n.set_language(code)
        Settings.get().language = code

    def _on_preference_changed(self, key: str, val):
        if key == "auto_reconnect":
            self.manager.set_auto_reconnect(bool(val))
        elif key == "notifications":
            self.notif.set_enabled(bool(val))

    # =================================================================
    # STATE
    # =================================================================
    def _on_state(self, state: str):
        labels = {
            "ready":          (t("state.ready"),    "online"),
            "opening":        (t("state.opening"),  "connecting"),
            "waiting_config": (t("state.waiting"),  "connecting"),
            "loading":        (t("state.loading"),  "connecting"),
            "failed":         (t("state.failed"),   "offline"),
            "idle":           (t("state.idle"),     "offline"),
        }
        text, dot_state = labels.get(state, (state, "offline"))
        self.conn_bar.update_state(state, text, dot_state, "")
        self.sb_dot.setProperty("state", dot_state)
        self.sb_dot.style().unpolish(self.sb_dot); self.sb_dot.style().polish(self.sb_dot)
        self.sb_state.setText(text)
        self.notif.set_tooltip(f"MeshLink Desktop — {text}")

        if state == "ready":
            if self._first_ready:
                self.tabs.setCurrentIndex(TAB_INFO)
                self._first_ready = False
        elif state == "idle":
            self._device_info = {}
            self._my_metrics  = {}
            self._my_metrics_ts = 0
            self._refresh_status_bar()

    def _on_progress(self, msg: str):
        self.conn_bar.update_state(
            self.manager.state,
            self.conn_bar.lbl_state.text(),
            self.conn_bar.dot.property("state") or "offline",
            msg,
        )

    def _on_device_info(self, info: dict):
        self._device_info = info
        self._refresh_status_bar()
        my_id = self.manager.my_node_id
        iface = self.manager.interface
        if iface and my_id and iface.nodes and my_id in iface.nodes:
            me = iface.nodes[my_id]
            dm = me.get("deviceMetrics") or {}
            if dm:
                self._my_metrics = dm
                self._my_metrics_ts = int(time.time())

    def _on_packet(self, _pkt: dict):
        self._last_activity_ts = int(time.time())

    def _on_node_updated(self, node_id: str, node: dict):
        if node_id == self.manager.my_node_id:
            dm = node.get("deviceMetrics") or {}
            if dm:
                self._my_metrics.update(dm)
                self._my_metrics_ts = int(time.time())
        # V0.44: watchlist — alert when a watched node comes back online
        try:
            from .watchlist import Watchlist
            wl = Watchlist.get()
            if wl.enabled and wl.is_watched_node(node_id):
                if wl.note_node_seen(node_id):
                    user = (node.get("user") or {})
                    name = user.get("longName") or user.get("shortName") or node_id
                    self.sound.play_message()
                    self.notif.notify("🔔 Watched node online",
                                      f"{name} is back on the mesh.")
        except Exception:
            log.debug("watchlist node check failed", exc_info=True)

    def _on_telemetry(self, node_id: str, telemetry: dict):
        if node_id == self.manager.my_node_id:
            dm = telemetry.get("deviceMetrics") or {}
            if dm:
                self._my_metrics.update(dm)
                self._my_metrics_ts = int(time.time())

    def _on_error(self, err: str):
        log.warning(f"Manager error: {err[:200]}")
        # afisare in conn bar
        self.conn_bar.lbl_progress.setText(err.split("\n", 1)[0][:60])

    def _on_new_message_notify(self, convo_id: str, sender: str, text: str):
        # SOUND always (relevant even when window is focused)
        self.sound.play_message()
        # V0.44: watchlist keyword alert — fires even when focused, because
        # a keyword like "SOS" or "urgent" is important regardless.
        try:
            from .watchlist import Watchlist
            hits = Watchlist.get().match_keywords(text)
            if hits:
                self.notif.notify(
                    f"🔔 Keyword alert: {hits[0]}",
                    f"{sender}: {text[:90]}")
        except Exception:
            log.debug("watchlist keyword check failed", exc_info=True)
        # Tray NOTIFICATION only when window isn't focused
        if not self.isActiveWindow():
            preview = text if len(text) <= 100 else text[:97] + "…"
            self.notif.notify(t("notif.new_message", sender), preview)

    def _start_dm_from_nodes(self, node_id: str):
        self.page_messages.start_dm_with(node_id)
        self.tabs.setCurrentIndex(TAB_MESSAGES)

    def _show_telemetry_popup(self, node_id: str):
        """Deschide popup non-modal cu telemetrie pentru nodul cerut."""
        # ia numele din node_data daca-l avem
        node_data = self.page_nodes.node_data.get(node_id, {})
        user = (node_data.get("user") or {})
        name = user.get("longName") or user.get("shortName") or node_id
        try:
            from .dialogs.telemetry_dialog import TelemetryDialog
            dlg = TelemetryDialog(node_id, name, self)
            dlg.setAttribute(Qt.WA_DeleteOnClose, True)
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
        except Exception:
            log.exception("Error opening telemetry popup")

    def _refresh_status_bar(self):
        # Defensive: status bar might not be built yet on first timer tick.
        if not hasattr(self, "sb_device"):
            return
        name = self._device_info.get("longName") or self._device_info.get("id") or "—"
        fw   = self._device_info.get("firmwareVersion") or "—"
        self.sb_device.setText(f"device: {name}")
        self.sb_fw.setText(f"fw: {fw}")

        bat = self._my_metrics.get("batteryLevel")
        if bat is not None:
            if bat > 100:
                self.sb_battery.setText("🔌 USB")
            else:
                icon = "🔋" if bat > 20 else "🪫"
                self.sb_battery.setText(f"{icon} {bat}%")
        else:
            self.sb_battery.setText("🔋 —")

        up = self._my_metrics.get("uptimeSeconds")
        if up is not None:
            elapsed = max(0, int(time.time()) - self._my_metrics_ts)
            current = up + elapsed
            d, rem = divmod(int(current), 86400)
            h, rem = divmod(rem, 3600)
            m, _   = divmod(rem, 60)
            if d:    fmt = f"{d}d {h}h"
            elif h:  fmt = f"{h}h {m}m"
            else:    fmt = f"{m}m"
            self.sb_uptime.setText(f"⏱ {fmt}")
        else:
            self.sb_uptime.setText("⏱ —")

        if self._last_activity_ts:
            delta = int(time.time()) - self._last_activity_ts
            if delta < 5:        age = "now"
            elif delta < 60:     age = f"{delta}s"
            elif delta < 3600:   age = f"{delta // 60}m"
            else:                age = f"{delta // 3600}h"
            self.sb_last_msg.setText(f"packet: {age}")
        else:
            self.sb_last_msg.setText("packet: —")

    # =================================================================
    # TRAY / CLOSE
    # =================================================================
    def _show_from_tray(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def _force_quit(self):
        self._allow_close = True
        self.close()

    def closeEvent(self, event: QCloseEvent):  # noqa: N802
        # daca tray e activ si user-ul nu a cerut explicit Iesire -> minimize
        if not self._allow_close and self.notif._tray and Settings.get().notifications:
            event.ignore()
            self.hide()
            self.notif.notify(
                t("notif.tray_minimized_title"),
                t("notif.tray_minimized_body"),
                ms=3000,
            )
            return
        log.info("Closing application")
        try:
            Settings.get().window_geometry = bytes(self.saveGeometry())
        except Exception:
            pass
        try:
            self.manager.disconnect(user_initiated=True)
        except Exception:
            log.exception("Error on close")
        self.notif.hide()
        super().closeEvent(event)
