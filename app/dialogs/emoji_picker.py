"""
Emoji picker popup — like in mobile chat apps.

Categories of curated emojis useful for mesh radio comms.
Click to insert at the cursor position of the active message input.

IMPLEMENTATION NOTE:
We use QLabel inside a clickable QFrame instead of QPushButton because
QPushButton on Windows uses the native widget style which does NOT render
color emoji from Segoe UI Emoji — they appear as colored vertical strips.
QLabel uses Qt's text rendering engine which properly handles color glyph
tables (CBLC/CBDT/COLR) when given an appropriate font via stylesheet.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont, QMouseEvent
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QTabWidget, QWidget, QLabel, QFrame, QScrollArea
)

from ..theme import Colors


def _emoji_font_css() -> str:
    """CSS font-family string with full emoji fallback chain."""
    return ("'Segoe UI Emoji', 'Apple Color Emoji', 'Noto Color Emoji', "
            "'Twemoji Mozilla', 'EmojiOne Color', 'Symbola', sans-serif")


def _emoji_font(size: int = 18) -> QFont:
    """Return a QFont that can render color emojis on the current platform.

    NOTE: On Windows, using setFont() on a QPushButton with this font still
    does NOT render color emoji correctly — the native button widget bypasses
    Qt's color glyph rendering. Use stylesheet font-family CSS instead for
    buttons; use this for QLabel / other Qt-rendered widgets if needed.
    """
    if sys.platform == "win32":
        f = QFont("Segoe UI Emoji", size)
    elif sys.platform == "darwin":
        f = QFont("Apple Color Emoji", size)
    else:
        f = QFont("Noto Color Emoji", size)
    f.setStyleStrategy(QFont.PreferAntialias)
    return f


# ===========================================================================
# Curated emoji set — organized by category, useful for mesh comms
# ===========================================================================
EMOJI_CATEGORIES = {
    "Recent":      [],  # populated at runtime
    "Smileys":     ["😀","😃","😄","😁","😆","😅","🤣","😂","🙂","🙃","😉","😊",
                    "😇","🥰","😍","🤩","😘","😋","😛","😜","🤪","😝","🤗","🤔",
                    "🤐","😐","😑","😶","😏","😒","🙄","😬","🤥","😌","😔","😪",
                    "😴","😷","🤒","🤕","🤢","🤮","🤧","🥵","🥶","😵","🤯","🤠",
                    "🥳","😎","🤓","🧐","😕","😟","🙁","😮","😯","😲","😳","🥺",
                    "😦","😧","😨","😰","😥","😢","😭","😱","😖","😣","😞","😓",
                    "😩","😫","😤","😡","😠","🤬","😈","👿","💀","☠","🤡"],
    "Gestures":    ["👋","🤚","🖐","✋","🖖","👌","✌","🤞","🤟","🤘","🤙",
                    "👈","👉","👆","👇","☝","👍","👎","👊","✊","🤛","🤜",
                    "👏","🙌","👐","🤝","🙏","✍","💪","👀","👁","👅","👄"],
    "Hearts":      ["❤","🧡","💛","💚","💙","💜","🤎","🖤","🤍","💔","❣","💕",
                    "💞","💓","💗","💖","💘","💝","💟","♥"],
    "Status":      ["✅","❌","⛔","🚫","⚠","⚡","🔥","💧","💯","✔","✖",
                    "❎","❗","❓","❕","❔","‼","⁉","🔔","🔕","📣","📢","🆘",
                    "🆗","🆕","🆒","🆓","🆙","✳","✴","❇","💢","💤","💥","💫"],
    "Travel":      ["🚗","🚕","🚙","🚌","🚎","🏎","🚓","🚑","🚒","🚐","🚚","🚛",
                    "🚜","🛴","🚲","🛵","🏍","🚨","🚲","🏁","✈","🚀","🛸","🚁",
                    "⛵","🚤","🚢","⚓","⛽","🚧","🚦","🗺","🏝","⛰","🏔","🗻",
                    "🏕","⛺","🏠","🏢","🏥","🏪","🏫","🏛","⛪"],
    "Geo":         ["📍","🧭","🗺","🌍","🌎","🌏","🌐","🛰","📡","📶","📊","📈",
                    "📉","⏱","⏲","⏰","🕰","⌚","📱","🔋","🔌","💻","🖥","⌨",
                    "💾","🔦","💡"],
    "Weather":     ["☀","🌤","⛅","🌥","☁","🌦","🌧","⛈","🌩","🌨","❄","☃",
                    "⛄","🌬","💨","🌪","🌫","🌊","💧","💦","☔","☂","🌈","🌟",
                    "⭐","🌠","☄","🌙","🌛","🌜","🌝","🌞"],
    "Food":        ["🍏","🍎","🍐","🍊","🍋","🍌","🍉","🍇","🍓","🍒","🍑","🍍",
                    "🥥","🥝","🍅","🍆","🥑","🥦","🥒","🌽","🥕","🥔","🥐","🍞",
                    "🥖","🧀","🥚","🍳","🥞","🥓","🍗","🍖","🌭","🍔","🍟","🍕",
                    "🥪","🌮","🌯","🥗","🍝","🍜","🍲","🍣","🍱","🍙","🍚","🍛",
                    "🍫","🍿","🍩","🍪","🍯","🥛","☕","🍵","🍶","🍺","🍻","🥂",
                    "🍷","🥃","🍸","🍹","🍾"],
    "Activities":  ["⚽","🏀","🏈","⚾","🥎","🎾","🏐","🏉","🎱","🏓","🏸","🏒",
                    "🏑","🥍","🏏","⛳","🏹","🎣","🥊","🥋","🎽","⛸","🎿","⛷",
                    "🏂","🏋","🤸","🏌","🧘","🏄","🏊","🚣","🧗","🚵","🚴","🏆",
                    "🥇","🥈","🥉","🏅","🎯","🎮","🎲","🎬","🎤","🎧","🎼","🎹",
                    "🥁","🎷","🎺","🎸","🎻"],
    "Objects":     ["⌚","📱","💻","⌨","🖥","🖨","🖱","💾","📷","📸","📹","🎥",
                    "📞","☎","📟","📠","📺","📻","🎙","🧭","⏱","⏲","⏰","⌛",
                    "⏳","📡","🔋","🔌","💡","🔦","🕯","🧯","💸","💵","💰","💳",
                    "💎","⚖","🔧","🔨","⚒","🛠","⚙","⛓","🧲","🔪","🛡","🚬"],
}


# Keep recent emojis (last 16 used)
_recent: list = []


def _push_recent(emoji: str):
    if emoji in _recent:
        _recent.remove(emoji)
    _recent.insert(0, emoji)
    del _recent[16:]


# ===========================================================================
# EmojiCell — a single clickable emoji cell using QLabel (NOT QPushButton)
# ===========================================================================
class _EmojiCell(QFrame):
    """Clickable cell rendering a single emoji via QLabel.

    Using QPushButton with setText('emoji') on Windows yields
    colored-vertical-bar artifacts because the native button widget bypasses
    Qt's color-glyph rendering. QLabel uses Qt's QTextEngine which renders
    color emoji correctly when CSS font-family includes 'Segoe UI Emoji'.
    """

    clicked = Signal(str)

    def __init__(self, emoji: str, parent=None):
        super().__init__(parent)
        self._emoji = emoji
        self.setObjectName("EmojiCell")
        self.setFixedSize(QSize(38, 38))
        self.setCursor(Qt.PointingHandCursor)

        self.setStyleSheet(
            "QFrame#EmojiCell {"
            "  background: transparent; border-radius: 6px;"
            "  border: 1px solid transparent;"
            "}"
            "QFrame#EmojiCell:hover {"
            f"  background: {Colors.BG_SURFACE_HI};"
            f"  border: 1px solid {Colors.BORDER};"
            "}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel(emoji, self)
        self._label.setAlignment(Qt.AlignCenter)
        # Stylesheet (NOT setFont!) so Qt uses CSS font fallback chain
        # and engages the color-glyph rendering path.
        self._label.setStyleSheet(
            "QLabel {"
            f"  font-family: {_emoji_font_css()};"
            "  font-size: 22px;"
            "  background: transparent; border: none;"
            "  color: " + Colors.TEXT_PRIMARY + ";"
            "}"
        )
        layout.addWidget(self._label)

    def mousePressEvent(self, e: QMouseEvent):  # noqa: N802
        super().mousePressEvent(e)
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self._emoji)


# ===========================================================================
# EmojiPicker dialog
# ===========================================================================
class EmojiPicker(QDialog):
    """Compact emoji picker. Emits emojiPicked(str) on selection."""

    emojiPicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Popup)
        self.setWindowTitle("Emoji")
        self.setStyleSheet(f"""
            QDialog {{
                background: {Colors.BG_SURFACE};
                border: 1px solid {Colors.BORDER};
                border-radius: 10px;
            }}
        """)
        self.resize(460, 400)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid {Colors.BORDER}; border-radius: 8px;
                background: {Colors.BG_BASE};
            }}
            QTabBar::tab {{
                background: transparent; color: {Colors.TEXT_SECONDARY};
                padding: 6px 10px; font-size: 11px;
            }}
            QTabBar::tab:selected {{
                color: {Colors.PRIMARY}; font-weight: 700;
                border-bottom: 2px solid {Colors.PRIMARY};
            }}
        """)
        root.addWidget(self.tabs, 1)

        for cat, emojis in EMOJI_CATEGORIES.items():
            self._build_tab(cat, emojis)

    def _build_tab(self, name: str, emojis: list):
        page = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"QScrollArea {{ background: {Colors.BG_BASE}; }}")
        inner = QWidget()
        grid = QGridLayout(inner)
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setSpacing(2)

        actual = _recent if name == "Recent" else emojis
        if name == "Recent" and not actual:
            empty = QLabel("Pick any emoji and it will show here next time.")
            empty.setStyleSheet(f"color: {Colors.TEXT_DIM}; padding: 30px;")
            empty.setAlignment(Qt.AlignCenter)
            empty.setWordWrap(True)
            grid.addWidget(empty, 0, 0)
        else:
            cols = 10
            for i, e in enumerate(actual):
                cell = _EmojiCell(e)
                cell.clicked.connect(self._on_pick)
                grid.addWidget(cell, i // cols, i % cols)

        scroll.setWidget(inner)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)
        self.tabs.addTab(page, name)

    def _on_pick(self, emoji: str):
        _push_recent(emoji)
        self.emojiPicked.emit(emoji)
        self.accept()
