"""
Theme / culori / stylesheet QSS pentru MeshLink Desktop.

V20-turn10: dark + light theme support. Two palettes live as dicts;
apply_theme() mutates the Colors class attributes so existing references
keep working (Colors.PRIMARY etc.) and the global stylesheet is then
re-applied via the main window. Default theme is dark.
"""

# ---------------------------------------------------------------------------
# Palette dicts
# ---------------------------------------------------------------------------
DARK_PALETTE = {
    "PRIMARY":        "#67EA94",
    "PRIMARY_DARK":   "#3FB872",
    "PRIMARY_GLOW":   "#67EA9433",

    "BG_BASE":        "#0F1115",
    "BG_SIDEBAR":     "#13161C",
    "BG_SURFACE":     "#1A1E27",
    "BG_SURFACE_HI":  "#222732",
    "BG_INPUT":       "#0B0D11",
    "BG_CONSOLE":     "#05080B",

    "TEXT_PRIMARY":   "#ECEEF2",
    "TEXT_SECONDARY": "#9098A5",
    "TEXT_DIM":       "#5C6573",
    "TEXT_ON_PRIMARY":"#0A1A12",

    "BORDER":         "#262B36",
    "BORDER_HI":      "#333845",

    "SUCCESS":        "#67EA94",
    "WARNING":        "#F5B946",
    "DANGER":         "#F0584B",
    "INFO":           "#5BA9F5",

    "BUBBLE_ME":      "#2E5F44",
    "BUBBLE_OTHER":   "#222732",
}

LIGHT_PALETTE = {
    # Greens slightly muted so they sit well on light backgrounds
    "PRIMARY":        "#2BAA5F",
    "PRIMARY_DARK":   "#1F8246",
    "PRIMARY_GLOW":   "#2BAA5F22",

    "BG_BASE":        "#F5F7FA",
    "BG_SIDEBAR":     "#FFFFFF",
    "BG_SURFACE":     "#FFFFFF",
    "BG_SURFACE_HI":  "#EEF1F5",
    "BG_INPUT":       "#FFFFFF",
    "BG_CONSOLE":     "#FAFBFC",

    "TEXT_PRIMARY":   "#1A1E27",
    "TEXT_SECONDARY": "#525B6B",
    "TEXT_DIM":       "#8590A1",
    "TEXT_ON_PRIMARY":"#FFFFFF",

    "BORDER":         "#DDE2E9",
    "BORDER_HI":      "#C3CAD4",

    "SUCCESS":        "#1F8246",
    "WARNING":        "#D58D14",
    "DANGER":         "#D7392A",
    "INFO":           "#2A78C4",

    "BUBBLE_ME":      "#D2EFDB",
    "BUBBLE_OTHER":   "#EEF1F5",
}


class Colors:
    """Active palette — gets mutated by apply_theme().

    Initialised below with DARK_PALETTE values. Don't read these at
    module-import time and stash them as locals — read them when you
    need them so theme switches are picked up.
    """
    # placeholders filled by apply_theme() at import time
    PRIMARY = PRIMARY_DARK = PRIMARY_GLOW = ""
    BG_BASE = BG_SIDEBAR = BG_SURFACE = BG_SURFACE_HI = BG_INPUT = BG_CONSOLE = ""
    TEXT_PRIMARY = TEXT_SECONDARY = TEXT_DIM = TEXT_ON_PRIMARY = ""
    BORDER = BORDER_HI = ""
    SUCCESS = WARNING = DANGER = INFO = ""
    BUBBLE_ME = BUBBLE_OTHER = ""


_current_theme = "dark"


def apply_theme(name: str = "dark"):
    """Switch the active theme. Subsequent build_stylesheet() picks it up."""
    global _current_theme
    palette = LIGHT_PALETTE if name == "light" else DARK_PALETTE
    for k, v in palette.items():
        setattr(Colors, k, v)
    _current_theme = "light" if name == "light" else "dark"


def current_theme() -> str:
    return _current_theme


# Initialise to dark on import so any code that uses Colors.X immediately
# gets sensible values.
apply_theme("dark")

def build_stylesheet() -> str:
    c = Colors
    return f"""
    /* GENERAL */
    QWidget {{
        background-color: {c.BG_BASE};
        color: {c.TEXT_PRIMARY};
        font-family: "Segoe UI Variable", "Segoe UI", "Inter", sans-serif;
        font-size: 13px;
    }}
    QMainWindow, QDialog {{ background-color: {c.BG_BASE}; }}

    /* TABS - layout principal */
    QTabWidget::pane {{
        border: none;
        background: {c.BG_BASE};
        top: 0px;
    }}
    QTabBar {{
        background: {c.BG_SIDEBAR};
        border-bottom: 1px solid {c.BORDER};
    }}
    QTabBar::tab {{
        background: transparent;
        color: {c.TEXT_SECONDARY};
        padding: 11px 22px;
        margin: 0;
        border: none;
        border-bottom: 2px solid transparent;
        font-weight: 500;
        min-width: 90px;
    }}
    QTabBar::tab:hover {{
        background: {c.BG_SURFACE};
        color: {c.TEXT_PRIMARY};
    }}
    QTabBar::tab:selected {{
        color: {c.PRIMARY};
        border-bottom: 2px solid {c.PRIMARY};
        font-weight: 600;
    }}

    /* HEADER ANTET APLICATIE */
    #AppHeader {{
        background-color: {c.BG_SIDEBAR};
        border-bottom: 1px solid {c.BORDER};
    }}
    #AppTitle {{
        color: {c.PRIMARY};
        font-size: 16px;
        font-weight: 700;
        letter-spacing: 0.5px;
    }}
    #AppSubtitle {{
        color: {c.TEXT_DIM};
        font-size: 11px;
    }}

    /* STATUS BAR */
    #StatusBar {{
        background-color: {c.BG_SIDEBAR};
        border-top: 1px solid {c.BORDER};
    }}
    #StatusBar QLabel {{
        color: {c.TEXT_SECONDARY};
        font-size: 11px;
        background: transparent;
    }}
    #StatusDot {{
        border-radius: 5px;
        min-width: 10px; max-width: 10px;
        min-height: 10px; max-height: 10px;
    }}
    #StatusDot[state="online"]     {{ background-color: {c.SUCCESS}; }}
    #StatusDot[state="offline"]    {{ background-color: {c.DANGER}; }}
    #StatusDot[state="connecting"] {{ background-color: {c.WARNING}; }}

    /* CARDS */
    QFrame#Card {{
        background-color: {c.BG_SURFACE};
        border: 1px solid {c.BORDER};
        border-radius: 14px;
    }}

    /* LISTS */
    QListWidget, QListView {{
        background-color: {c.BG_SURFACE};
        border: 1px solid {c.BORDER};
        border-radius: 12px;
        padding: 6px;
        outline: 0;
    }}
    QListWidget::item {{
        background-color: transparent;
        color: {c.TEXT_PRIMARY};
        padding: 12px;
        border-radius: 10px;
        margin: 2px 0;
    }}
    QListWidget::item:hover    {{ background-color: {c.BG_SURFACE_HI}; }}
    QListWidget::item:selected {{
        background-color: {c.BG_SURFACE_HI};
        border-left: 3px solid {c.PRIMARY};
    }}

    /* INPUTS */
    QLineEdit, QTextEdit, QPlainTextEdit {{
        background-color: {c.BG_INPUT};
        color: {c.TEXT_PRIMARY};
        border: 1px solid {c.BORDER};
        border-radius: 10px;
        padding: 9px 12px;
        selection-background-color: {c.PRIMARY};
        selection-color: {c.TEXT_ON_PRIMARY};
    }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
        border: 1px solid {c.PRIMARY};
    }}
    QComboBox {{
        background-color: {c.BG_INPUT};
        color: {c.TEXT_PRIMARY};
        border: 1px solid {c.BORDER};
        border-radius: 10px;
        padding: 8px 12px;
        min-height: 20px;
    }}
    QComboBox:hover {{ border: 1px solid {c.BORDER_HI}; }}
    QComboBox:focus {{ border: 1px solid {c.PRIMARY}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background-color: {c.BG_SURFACE};
        border: 1px solid {c.BORDER};
        border-radius: 8px;
        padding: 4px;
        selection-background-color: {c.BG_SURFACE_HI};
        selection-color: {c.PRIMARY};
        outline: 0;
    }}
    QSpinBox, QDoubleSpinBox {{
        background-color: {c.BG_INPUT};
        color: {c.TEXT_PRIMARY};
        border: 1px solid {c.BORDER};
        border-radius: 10px;
        padding: 8px 10px;
    }}

    /* BUTTONS */
    QPushButton {{
        background-color: {c.BG_SURFACE_HI};
        color: {c.TEXT_PRIMARY};
        border: 1px solid {c.BORDER};
        border-radius: 10px;
        padding: 9px 16px;
        font-weight: 500;
    }}
    QPushButton:hover {{
        background-color: {c.BORDER_HI};
        border: 1px solid {c.BORDER_HI};
    }}
    QPushButton:pressed  {{ background-color: {c.BG_SURFACE}; }}
    QPushButton:disabled {{
        background-color: {c.BG_SURFACE};
        color: {c.TEXT_DIM};
        border: 1px solid {c.BORDER};
    }}
    QPushButton#PrimaryButton {{
        background-color: {c.PRIMARY};
        color: {c.TEXT_ON_PRIMARY};
        border: none;
        font-weight: 600;
    }}
    QPushButton#PrimaryButton:hover    {{ background-color: {c.PRIMARY_DARK}; }}
    QPushButton#PrimaryButton:pressed  {{ background-color: {c.PRIMARY_DARK}; }}
    QPushButton#PrimaryButton:disabled {{
        background-color: {c.BG_SURFACE};
        color: {c.TEXT_DIM};
    }}
    QPushButton#DangerButton {{
        background-color: transparent;
        color: {c.DANGER};
        border: 1px solid {c.DANGER};
    }}
    QPushButton#DangerButton:hover {{
        background-color: {c.DANGER};
        color: white;
    }}

    /* SCROLLBARS */
    QScrollBar:vertical {{
        background: transparent; width: 10px;
        margin: 4px 2px; border-radius: 5px;
    }}
    QScrollBar::handle:vertical {{
        background: {c.BORDER_HI}; min-height: 30px; border-radius: 5px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {c.TEXT_DIM}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar:horizontal {{
        background: transparent; height: 10px;
        margin: 2px 4px; border-radius: 5px;
    }}
    QScrollBar::handle:horizontal {{
        background: {c.BORDER_HI}; min-width: 30px; border-radius: 5px;
    }}
    QScrollBar::handle:horizontal:hover {{ background: {c.TEXT_DIM}; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

    /* LABELS */
    QLabel[role="muted"]   {{ color: {c.TEXT_SECONDARY}; }}
    QLabel[role="dim"]     {{ color: {c.TEXT_DIM}; font-size: 11px; }}
    QLabel[role="title"]   {{ color: {c.TEXT_PRIMARY}; font-size: 15px; font-weight: 600; }}
    QLabel[role="section"] {{
        color: {c.TEXT_SECONDARY}; font-size: 11px; font-weight: 600;
        letter-spacing: 1px;
    }}

    /* TOOLTIPS */
    QToolTip {{
        background-color: {c.BG_SURFACE_HI};
        color: {c.TEXT_PRIMARY};
        border: 1px solid {c.BORDER};
        border-radius: 6px;
        padding: 4px 8px;
    }}

    /* BUBBLES */
    QFrame#BubbleMe {{
        background-color: {c.BUBBLE_ME};
        border-radius: 14px;
        border-bottom-right-radius: 4px;
    }}
    QFrame#BubbleOther {{
        background-color: {c.BUBBLE_OTHER};
        border-radius: 14px;
        border-bottom-left-radius: 4px;
    }}
    QLabel#BubbleText   {{ color: {c.TEXT_PRIMARY}; font-size: 13px; background: transparent; }}
    QLabel#BubbleMeta   {{ color: {c.TEXT_DIM}; font-size: 10px; background: transparent; }}
    QLabel#BubbleSender {{ color: {c.PRIMARY}; font-size: 11px; font-weight: 600; background: transparent; }}

    /* NODE CARD */
    QFrame#NodeCard {{
        background-color: {c.BG_SURFACE};
        border: 1px solid {c.BORDER};
        border-radius: 12px;
    }}
    QFrame#NodeCard:hover {{ border: 1px solid {c.BORDER_HI}; }}
    QLabel#NodeShort {{
        background-color: {c.BG_SURFACE_HI};
        color: {c.PRIMARY};
        border: 2px solid {c.BORDER_HI};
        border-radius: 22px;
        font-weight: 700; font-size: 13px;
        qproperty-alignment: AlignCenter;
    }}
    QLabel#NodeShort[role="me"] {{
        background-color: {c.PRIMARY};
        color: {c.TEXT_ON_PRIMARY};
        border: 2px solid {c.PRIMARY_DARK};
    }}
    QLabel#NodeName {{ font-size: 14px; font-weight: 600; color: {c.TEXT_PRIMARY}; }}
    QLabel#NodeId   {{ font-size: 11px; color: {c.TEXT_DIM}; font-family: Consolas, monospace; }}
    QLabel#NodeStat {{ font-size: 11px; color: {c.TEXT_SECONDARY}; }}

    /* SEPARATOR */
    QFrame#HSeparator {{
        background-color: {c.BORDER};
        max-height: 1px; min-height: 1px;
        border: none;
    }}

    /* CHECKBOX */
    QCheckBox {{ spacing: 8px; color: {c.TEXT_PRIMARY}; }}
    QCheckBox::indicator {{
        width: 18px; height: 18px;
        border-radius: 5px;
        border: 1px solid {c.BORDER_HI};
        background: {c.BG_INPUT};
    }}
    QCheckBox::indicator:hover    {{ border: 1px solid {c.PRIMARY}; }}
    QCheckBox::indicator:checked  {{
        background-color: {c.PRIMARY};
        border: 1px solid {c.PRIMARY};
    }}

    /* MENU */
    QMenu {{
        background-color: {c.BG_SURFACE};
        border: 1px solid {c.BORDER};
        border-radius: 8px;
        padding: 6px;
    }}
    QMenu::item {{ padding: 7px 18px; border-radius: 6px; }}
    QMenu::item:selected {{ background-color: {c.BG_SURFACE_HI}; color: {c.PRIMARY}; }}

    /* MESSAGE BOX */
    QMessageBox {{ background-color: {c.BG_SURFACE}; }}
    QMessageBox QLabel {{ color: {c.TEXT_PRIMARY}; }}

    /* CONNECTION PROGRESS STEPS */
    QLabel#StepDone     {{ color: {c.SUCCESS}; font-weight: 600; }}
    QLabel#StepActive   {{ color: {c.PRIMARY}; font-weight: 600; }}
    QLabel#StepPending  {{ color: {c.TEXT_DIM}; }}
    QLabel#StepFailed   {{ color: {c.DANGER}; font-weight: 600; }}

    /* V20-turn10: theme-toggle button + author label */
    QPushButton#ThemeToggle {{
        background: transparent; color: {c.TEXT_SECONDARY};
        border: none; font-size: 14px; padding: 0;
    }}
    QPushButton#ThemeToggle:hover {{
        color: {c.PRIMARY};
    }}
    QLabel#AuthorLabel:hover {{
        color: {c.PRIMARY};
        text-decoration: underline;
    }}
    """
