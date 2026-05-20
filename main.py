"""
MeshLink Desktop — entry point.

Copyright (C) 2026 Emil M.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, version 3 of the License.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

Verifies project structure, sets up logging, captures crashes,
loads preferences and brings up the UI.
"""

from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime


def _bail_out(title: str, message: str):
    print("\n" + "=" * 60, file=sys.stderr)
    print(f"  {title}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(message, file=sys.stderr)
    print("=" * 60 + "\n", file=sys.stderr)
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk(); root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
    except Exception:
        pass
    sys.exit(1)


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR    = os.path.join(SCRIPT_DIR, "app")

if not os.path.isdir(APP_DIR):
    _bail_out(
        "Project structure incomplete",
        f"Folder 'app/' does not exist in:\n  {SCRIPT_DIR}\n\n"
        "You probably extracted only 'main.py' from the ZIP.\n\n"
        "FIX:\n"
        "  1. Extract the ENTIRE ZIP archive into a dedicated folder.\n"
        "  2. In that folder you should see:\n"
        "       main.py\n"
        "       requirements.txt\n"
        "       run.bat\n"
        "       app/   <- this subfolder MUST exist\n"
        "  3. Run again (double-click run.bat or\n"
        "     'python main.py' from PowerShell)."
    )

if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)


def _check_dependencies():
    missing = []
    for mod, hint in [
        ("PySide6",    "pip install PySide6"),
        ("meshtastic", "pip install meshtastic"),
        ("pubsub",     "pip install pypubsub"),
        ("serial",     "pip install pyserial"),
    ]:
        try:
            __import__(mod)
        except ImportError:
            missing.append((mod, hint))
    if missing:
        msg = "Missing Python modules:\n\n"
        for mod, hint in missing:
            msg += f"  • {mod}\n      {hint}\n"
        msg += ("\nIn a terminal:\n"
                "    pip install -r requirements.txt\n\n"
                "If pip is not working, try:\n"
                "    python -m pip install -r requirements.txt")
        _bail_out("Missing dependencies", msg)


_check_dependencies()


from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402
from PySide6.QtGui    import QFont                       # noqa: E402

from app.logging_bridge   import setup_logging           # noqa: E402
from app.main_window      import MainWindow              # noqa: E402
from app.theme            import build_stylesheet        # noqa: E402
from app.settings_store   import Settings                # noqa: E402
from app.i18n             import i18n                    # noqa: E402
from app.notifications    import make_app_icon           # noqa: E402


_crash_log_path = ""


def _global_excepthook(exc_type, exc_value, exc_tb):
    txt = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    sys.stderr.write(txt)
    try:
        with open(_crash_log_path or "crash.log", "a", encoding="utf-8") as f:
            f.write(f"\n========== {datetime.now().isoformat()} ==========\n")
            f.write(txt)
    except Exception:
        pass
    try:
        QMessageBox.critical(
            None, "Unexpected error",
            f"An error occurred:\n\n{exc_type.__name__}: {exc_value}\n\n"
            f"Details in:\n{_crash_log_path or 'crash.log'}"
        )
    except Exception:
        pass


def main():
    home = os.path.expanduser("~")
    log_dir = os.path.join(home, "meshlink_desktop_logs")
    global _crash_log_path
    _crash_log_path = setup_logging(log_dir=log_dir, verbose=True)

    import logging
    log = logging.getLogger("meshlink.main")
    log.info("==== MeshLink Desktop started ====")
    log.info(f"Log file: {_crash_log_path}")
    log.info(f"Python:   {sys.version.split()[0]}")
    log.info(f"Platform: {sys.platform}")

    sys.excepthook = _global_excepthook

    # Qt App
    app = QApplication(sys.argv)
    app.setApplicationName("MeshLink Desktop")
    app.setOrganizationName("Meshtastic Community")
    app.setStyle("Fusion")
    app.setWindowIcon(make_app_icon(64))

    # Font
    f = QFont("Segoe UI Variable", 10)
    if not f.exactMatch():
        f = QFont("Segoe UI", 10)
    app.setFont(f)

    # Apply saved theme BEFORE building the stylesheet (otherwise we'd
    # paint with the dark default for a frame, then flicker to light).
    s = Settings.get()
    from app.theme import apply_theme           # noqa: E402
    apply_theme(s.theme)
    log.info(f"Theme: {s.theme}")

    # Stylesheet
    app.setStyleSheet(build_stylesheet())

    # Incarca limba salvata
    i18n.set_language(s.language)
    log.info(f"Language: {s.language}")

    # Quit on tray-only? No — default is to keep the app alive until user asks
    app.setQuitOnLastWindowClosed(False)

    window = MainWindow()
    window.show()

    log.info("Main window shown")
    exit_code = app.exec()
    log.info(f"==== Shutdown (exit={exit_code}) ====")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
