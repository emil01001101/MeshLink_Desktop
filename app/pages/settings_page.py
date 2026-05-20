"""
Settings page — app preferences (language, auto-reconnect, notifications,
istoric) + actiuni device (owner, reboot, reset NodeDB). Cu i18n.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFrame, QMessageBox, QGridLayout, QComboBox, QCheckBox
)

from ..connection import MeshtasticManager
from ..settings_store import Settings
from ..theme import Colors
from ..i18n import t, i18n, LANGUAGE_NAMES


class SettingsPage(QWidget):

    preferenceChanged = Signal(str, object)   # (key, value)

    def __init__(self, manager: MeshtasticManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self._build_ui()
        self._load_preferences()
        self._connect_signals()
        i18n.languageChanged.connect(self._retranslate)
        self._retranslate()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 20)
        root.setSpacing(16)

        # info / hint
        hint = QFrame()
        hint.setObjectName("Card")
        hl = QHBoxLayout(hint)
        hl.setContentsMargins(16, 12, 16, 12)
        ic = QLabel("ℹ")
        ic.setStyleSheet(f"color: {Colors.PRIMARY}; font-size: 18px;")
        hl.addWidget(ic)
        self.lbl_hint = QLabel()
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        hl.addWidget(self.lbl_hint, 1)
        root.addWidget(hint)

        # ============== Application preferences ==============
        prefs = QFrame()
        prefs.setObjectName("Card")
        pl = QVBoxLayout(prefs)
        pl.setContentsMargins(18, 16, 18, 16)
        pl.setSpacing(10)
        self.lbl_section_prefs = QLabel()
        self.lbl_section_prefs.setProperty("role", "section")
        pl.addWidget(self.lbl_section_prefs)

        # limba
        lang_row = QHBoxLayout()
        self.lbl_lang = QLabel()
        lang_row.addWidget(self.lbl_lang)
        self.lang_combo = QComboBox()
        for code, label in LANGUAGE_NAMES.items():
            self.lang_combo.addItem(label, code)
        lang_row.addWidget(self.lang_combo, 1)
        pl.addLayout(lang_row)

        self.cb_auto_reconnect = QCheckBox()
        pl.addWidget(self.cb_auto_reconnect)
        self.cb_notifications = QCheckBox()
        pl.addWidget(self.cb_notifications)
        self.cb_save_history = QCheckBox()
        pl.addWidget(self.cb_save_history)

        root.addWidget(prefs)

        # ============== Owner ==============
        owner = QFrame()
        owner.setObjectName("Card")
        ol = QVBoxLayout(owner)
        ol.setContentsMargins(18, 16, 18, 16)
        ol.setSpacing(10)
        self.lbl_section_owner = QLabel()
        self.lbl_section_owner.setProperty("role", "section")
        ol.addWidget(self.lbl_section_owner)
        self.lbl_owner_hint = QLabel()
        self.lbl_owner_hint.setWordWrap(True)
        ol.addWidget(self.lbl_owner_hint)

        og = QGridLayout()
        og.setHorizontalSpacing(10)
        og.setVerticalSpacing(8)
        og.setColumnStretch(1, 1)
        self.lbl_long_name = QLabel()
        og.addWidget(self.lbl_long_name, 0, 0)
        self.long_name_input = QLineEdit()
        self.long_name_input.setMaxLength(40)
        og.addWidget(self.long_name_input, 0, 1)
        self.lbl_short_name = QLabel()
        og.addWidget(self.lbl_short_name, 1, 0)
        self.short_name_input = QLineEdit()
        self.short_name_input.setMaxLength(4)
        og.addWidget(self.short_name_input, 1, 1)
        ol.addLayout(og)

        obtns = QHBoxLayout()
        obtns.addStretch(1)
        self.save_owner_btn = QPushButton()
        self.save_owner_btn.setObjectName("PrimaryButton")
        self.save_owner_btn.setEnabled(False)
        self.save_owner_btn.clicked.connect(self._save_owner)
        obtns.addWidget(self.save_owner_btn)
        ol.addLayout(obtns)
        root.addWidget(owner)

        # ============== Actions ==============
        actions = QFrame()
        actions.setObjectName("Card")
        al = QVBoxLayout(actions)
        al.setContentsMargins(18, 16, 18, 16)
        al.setSpacing(10)
        self.lbl_section_actions = QLabel()
        self.lbl_section_actions.setProperty("role", "section")
        al.addWidget(self.lbl_section_actions)
        self.lbl_actions_warn = QLabel()
        self.lbl_actions_warn.setWordWrap(True)
        self.lbl_actions_warn.setStyleSheet(f"color: {Colors.WARNING}; font-size: 11px;")
        al.addWidget(self.lbl_actions_warn)

        ar = QHBoxLayout()
        self.reboot_btn = QPushButton()
        self.reboot_btn.setEnabled(False)
        self.reboot_btn.clicked.connect(self._reboot_confirm)
        ar.addWidget(self.reboot_btn)
        self.reset_db_btn = QPushButton()
        self.reset_db_btn.setObjectName("DangerButton")
        self.reset_db_btn.setEnabled(False)
        self.reset_db_btn.clicked.connect(self._reset_db_confirm)
        ar.addWidget(self.reset_db_btn)
        ar.addStretch(1)
        al.addLayout(ar)
        root.addWidget(actions)

        # ============== About ==============
        about = QFrame()
        about.setObjectName("Card")
        abl = QVBoxLayout(about)
        abl.setContentsMargins(18, 16, 18, 16)
        abl.setSpacing(6)
        self.lbl_section_about = QLabel()
        self.lbl_section_about.setProperty("role", "section")
        abl.addWidget(self.lbl_section_about)
        self.lbl_about_text = QLabel()
        abl.addWidget(self.lbl_about_text)
        self.lbl_about_inspired = QLabel()
        self.lbl_about_inspired.setStyleSheet(f"color: {Colors.TEXT_DIM}; font-size: 11px;")
        self.lbl_about_inspired.setWordWrap(True)
        abl.addWidget(self.lbl_about_inspired)
        self.lbl_log_hint = QLabel()
        self.lbl_log_hint.setStyleSheet(f"color: {Colors.TEXT_DIM}; font-size: 11px;")
        abl.addWidget(self.lbl_log_hint)
        root.addWidget(about)
        root.addStretch(1)

    def _load_preferences(self):
        s = Settings.get()
        # limba
        idx = self.lang_combo.findData(s.language)
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)
        self.cb_auto_reconnect.setChecked(s.auto_reconnect)
        self.cb_notifications.setChecked(s.notifications)
        self.cb_save_history.setChecked(s.save_history)

    def _connect_signals(self):
        self.manager.stateChanged.connect(self._on_state)
        self.manager.deviceInfoReady.connect(self._on_device_info)
        self.manager.errorMessage.connect(self._on_error)
        self.lang_combo.currentIndexChanged.connect(self._on_lang_changed)
        self.cb_auto_reconnect.toggled.connect(
            lambda v: self._on_pref("auto_reconnect", v))
        self.cb_notifications.toggled.connect(
            lambda v: self._on_pref("notifications", v))
        self.cb_save_history.toggled.connect(
            lambda v: self._on_pref("save_history", v))

    def _retranslate(self, *_):
        self.lbl_hint.setText(t("settings.connection_hint"))
        self.lbl_section_prefs.setText(t("settings.preferences"))
        self.lbl_lang.setText(t("settings.language"))
        self.cb_auto_reconnect.setText(t("settings.auto_reconnect"))
        self.cb_notifications.setText(t("settings.notifications"))
        self.cb_save_history.setText(t("settings.save_history"))
        self.lbl_section_owner.setText(t("settings.owner"))
        self.lbl_owner_hint.setText(t("settings.owner_hint"))
        self.lbl_long_name.setText(t("settings.long_name"))
        self.lbl_short_name.setText(t("settings.short_name"))
        self.long_name_input.setPlaceholderText(t("settings.long_name_placeholder"))
        self.short_name_input.setPlaceholderText(t("settings.short_name_placeholder"))
        self.save_owner_btn.setText(t("settings.save_name"))
        self.lbl_section_actions.setText(t("settings.actions"))
        self.lbl_actions_warn.setText(t("settings.actions_warn"))
        self.reboot_btn.setText(t("settings.reboot"))
        self.reset_db_btn.setText(t("settings.reset_db"))
        self.lbl_section_about.setText(t("settings.about"))
        self.lbl_about_text.setText(t("settings.about_text"))
        self.lbl_about_inspired.setText(t("settings.about_inspired"))
        self.lbl_log_hint.setText(t("settings.log_hint"))

    def _on_state(self, state):
        is_ready = (state == "ready")
        self.save_owner_btn.setEnabled(is_ready)
        self.reboot_btn.setEnabled(is_ready)
        self.reset_db_btn.setEnabled(is_ready)
        if state == "idle":
            self.long_name_input.clear()
            self.short_name_input.clear()

    def _on_device_info(self, info: dict):
        if info.get("longName"):
            self.long_name_input.setText(info["longName"])
        if info.get("shortName"):
            self.short_name_input.setText(info["shortName"])

    def _on_error(self, err: str):
        QMessageBox.warning(self, t("common.error"), err)

    def _on_lang_changed(self):
        code = self.lang_combo.currentData()
        if code:
            i18n.set_language(code)
            Settings.get().language = code

    def _on_pref(self, key: str, val: bool):
        s = Settings.get()
        setattr(s, key, val)
        self.preferenceChanged.emit(key, val)

    def _save_owner(self):
        ln = self.long_name_input.text().strip()
        sn = self.short_name_input.text().strip()
        if not ln or not sn:
            QMessageBox.information(self, t("settings.incomplete"),
                                    t("settings.incomplete_msg"))
            return
        self.manager.set_owner(ln, sn)
        self.save_owner_btn.setText(t("common.saved"))
        QTimer.singleShot(1500, lambda: self.save_owner_btn.setText(t("settings.save_name")))

    def _reboot_confirm(self):
        r = QMessageBox.question(self, t("common.confirm"), t("settings.reboot_confirm"))
        if r == QMessageBox.Yes:
            self.manager.reboot()

    def _reset_db_confirm(self):
        r = QMessageBox.question(self, t("common.confirm"), t("settings.reset_db_confirm"))
        if r == QMessageBox.Yes:
            try:
                self.manager.interface.localNode.resetNodeDb()
            except Exception as e:
                QMessageBox.warning(self, t("common.error"), str(e))
