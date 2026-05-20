"""
Self-test dialog — UI wrapper for app.self_test.run_all().

Two phases:
  1. Intro phase  — explains what will run, big "▶ Run" button
  2. Run/result   — progress bar while running, then grouped results

Each result row shows: status icon, name, message, expandable details with
the suggested fix (if any).
"""

from __future__ import annotations

from typing import List, Dict, Any

from PySide6.QtCore import Qt, Signal, QThread, QTimer
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar,
    QScrollArea, QWidget, QFrame, QSizePolicy, QApplication
)

from ..self_test import (
    run_all, summary, ALL_CHECKS,
    PASS, INFO, SKIP, WARN, FAIL,
)
from ..theme import Colors
from ..i18n import t


# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------
class _SelfTestWorker(QThread):
    progress = Signal(int, int, str)     # done, total, current_name
    finished_with_results = Signal(list)  # list of result dicts

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager

    def run(self):
        results = run_all(self.manager, progress_cb=self._on_progress)
        self.finished_with_results.emit(results)

    def _on_progress(self, done: int, total: int, name: str):
        self.progress.emit(done, total, name)


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------
_STATUS_ICONS = {
    PASS: ("✓", "#67EA94"),
    INFO: ("ℹ", "#5BA9F5"),
    SKIP: ("—", "#5C6573"),
    WARN: ("⚠", "#F5B946"),
    FAIL: ("✗", "#F0584B"),
}


class SelfTestDialog(QDialog):

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.setWindowTitle("Device Self-Test")
        self.setMinimumSize(680, 560)
        self.resize(760, 640)

        self._worker = None
        self._results: List[Dict[str, Any]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        # ----- header -----
        title = QLabel("🩺  Device self-test")
        title.setStyleSheet(
            f"font-size: 17px; font-weight: 700; color: {Colors.TEXT_PRIMARY};")
        root.addWidget(title)

        # ----- intro -----
        self.lbl_intro = QLabel(
            f"This will run <b>{len(ALL_CHECKS)} diagnostic checks</b> against "
            "your connected device and this app's environment. It's safe and "
            "doesn't transmit anything.\n\n"
            "Categories tested: "
            "<b>Software, Connection, Firmware/HW, LoRa config, Position, "
            "Telemetry, Channels, Mesh, Power.</b>"
        )
        self.lbl_intro.setWordWrap(True)
        self.lbl_intro.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; font-size: 12px; "
            f"line-height: 1.5; padding: 6px 8px; "
            f"background: {Colors.BG_INPUT}; border-radius: 6px;")
        root.addWidget(self.lbl_intro)

        # ----- progress bar (hidden until running) -----
        self.progress = QProgressBar()
        self.progress.setRange(0, len(ALL_CHECKS))
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setFormat("Idle")
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        # ----- results area (hidden until run) -----
        self.results_scroll = QScrollArea()
        self.results_scroll.setWidgetResizable(True)
        self.results_scroll.setFrameShape(QFrame.NoFrame)
        self.results_scroll.setStyleSheet(
            f"QScrollArea {{ background: {Colors.BG_BASE}; border: none; }}")
        self.results_host = QWidget()
        self.results_layout = QVBoxLayout(self.results_host)
        self.results_layout.setContentsMargins(0, 4, 0, 4)
        self.results_layout.setSpacing(8)
        self.results_layout.addStretch(1)
        self.results_scroll.setWidget(self.results_host)
        self.results_scroll.setVisible(False)
        root.addWidget(self.results_scroll, 1)

        # ----- summary line (filled after run) -----
        self.lbl_summary = QLabel("")
        self.lbl_summary.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; "
            f"font-size: 12px; padding: 6px 0;")
        self.lbl_summary.setVisible(False)
        root.addWidget(self.lbl_summary)

        # ----- buttons -----
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_copy = QPushButton("📋  Copy report")
        self.btn_copy.setToolTip("Copy a plain-text version of the results "
                                 "to the clipboard, useful for bug reports.")
        self.btn_copy.setVisible(False)
        self.btn_copy.clicked.connect(self._copy_report)
        btn_row.addWidget(self.btn_copy)

        self.btn_rerun = QPushButton("🔄  Re-run")
        self.btn_rerun.setVisible(False)
        self.btn_rerun.clicked.connect(self._run_tests)
        btn_row.addWidget(self.btn_rerun)

        btn_row.addStretch(1)

        self.btn_run = QPushButton("▶  Run self-test")
        self.btn_run.setObjectName("PrimaryButton")
        self.btn_run.clicked.connect(self._run_tests)
        btn_row.addWidget(self.btn_run)

        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.accept)
        btn_row.addWidget(self.btn_close)

        root.addLayout(btn_row)

    # ------------------------------------------------------------------
    # RUN
    # ------------------------------------------------------------------
    def _run_tests(self):
        # Reset UI
        self.btn_run.setEnabled(False)
        self.btn_rerun.setEnabled(False)
        self.btn_copy.setVisible(False)
        self.lbl_summary.setVisible(False)
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.progress.setFormat("Starting…")
        # Clear results
        self._clear_results()
        self.results_scroll.setVisible(False)

        # Kick off worker
        self._worker = _SelfTestWorker(self.manager, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_with_results.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, done: int, total: int, name: str):
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.progress.setFormat(f"{done}/{total}  ·  {name}")

    def _on_finished(self, results: list):
        self._results = results
        self.progress.setVisible(False)
        self.btn_run.setEnabled(True)
        self.btn_run.setVisible(False)
        self.btn_rerun.setVisible(True)
        self.btn_rerun.setEnabled(True)
        self.btn_copy.setVisible(True)
        self._render_results(results)
        self._render_summary(results)
        self.results_scroll.setVisible(True)
        self.lbl_summary.setVisible(True)

    # ------------------------------------------------------------------
    # RENDER
    # ------------------------------------------------------------------
    def _clear_results(self):
        while self.results_layout.count() > 1:
            item = self.results_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _render_results(self, results: List[Dict[str, Any]]):
        # Group by category, preserve order of first appearance
        ordered_categories: List[str] = []
        groups: Dict[str, list] = {}
        for r in results:
            cat = r.get("category") or "Other"
            if cat not in groups:
                ordered_categories.append(cat)
                groups[cat] = []
            groups[cat].append(r)
        # Build the widget tree
        for cat in ordered_categories:
            # Section header
            hdr = QLabel(cat.upper())
            hdr.setStyleSheet(
                f"color: {Colors.TEXT_DIM}; font-size: 10px; "
                f"font-weight: 700; letter-spacing: 1.5px; "
                f"padding: 6px 0 4px 4px;")
            self.results_layout.insertWidget(
                self.results_layout.count() - 1, hdr)
            # Section card
            section = QFrame()
            section.setObjectName("Card")
            section.setStyleSheet(
                f"#Card {{ background: {Colors.BG_SURFACE}; "
                f"border: 1px solid {Colors.BORDER}; border-radius: 8px; }}")
            sec_lay = QVBoxLayout(section)
            sec_lay.setContentsMargins(2, 4, 2, 4)
            sec_lay.setSpacing(0)
            for r in groups[cat]:
                sec_lay.addWidget(_ResultRow(r))
                # Separator
                sep = QFrame()
                sep.setFrameShape(QFrame.HLine)
                sep.setStyleSheet(f"color: {Colors.BORDER}; "
                                  f"max-height: 1px; background: {Colors.BORDER};")
                sec_lay.addWidget(sep)
            # Drop the last separator
            last = sec_lay.itemAt(sec_lay.count() - 1).widget()
            if isinstance(last, QFrame):
                last.setVisible(False)
            self.results_layout.insertWidget(
                self.results_layout.count() - 1, section)

    def _render_summary(self, results: List[Dict[str, Any]]):
        s = summary(results)
        parts = []
        for k, label in (
            (PASS, "✓ pass"), (INFO, "ℹ info"), (SKIP, "— skip"),
            (WARN, "⚠ warn"), (FAIL, "✗ fail"),
        ):
            if s.get(k, 0) > 0:
                color = _STATUS_ICONS[k][1]
                parts.append(
                    f"<span style='color:{color};font-weight:600'>"
                    f"{s[k]}</span> {label}")
        # Verdict colour
        if s.get(FAIL, 0) > 0:
            verdict_color = "#F0584B"
            verdict = "⚠ FAIL — some checks failed; expand them for the fix"
        elif s.get(WARN, 0) > 0:
            verdict_color = "#F5B946"
            verdict = "⚠ WARN — some warnings; system functional but tuning suggested"
        else:
            verdict_color = "#67EA94"
            verdict = "✓ PASS — system looks healthy"
        text = (
            f"<span style='color:{verdict_color};font-weight:700'>"
            f"{verdict}</span><br>"
            f"<span style='color:{Colors.TEXT_DIM};font-size:11px'>"
            + "   ·   ".join(parts) + "</span>"
        )
        self.lbl_summary.setText(text)

    # ------------------------------------------------------------------
    # Plain-text export
    # ------------------------------------------------------------------
    def _copy_report(self):
        lines = ["=== MeshLink Desktop self-test report ==="]
        s = summary(self._results)
        lines.append(f"Summary: pass={s[PASS]} info={s[INFO]} skip={s[SKIP]} "
                     f"warn={s[WARN]} fail={s[FAIL]}")
        lines.append("")
        # Group by category
        seen: list = []
        for r in self._results:
            cat = r.get("category") or "Other"
            if cat not in seen:
                seen.append(cat)
                lines.append(f"-- {cat} --")
            icon = {"pass":"[OK]","info":"[i]","skip":"[--]",
                    "warn":"[!!]","fail":"[XX]"}.get(r["status"],"[??]")
            lines.append(f"  {icon} {r['name']}: {r['message']}")
            if r.get("fix"):
                lines.append(f"       fix: {r['fix']}")
        text = "\n".join(lines)
        QApplication.clipboard().setText(text)
        # tiny confirmation flash
        self.btn_copy.setText("✓  Copied!")
        QTimer.singleShot(1500, lambda: self.btn_copy.setText("📋  Copy report"))


# ---------------------------------------------------------------------------
# Result row widget
# ---------------------------------------------------------------------------
class _ResultRow(QFrame):
    """Single result line: icon + name + message + optional expanded fix."""

    def __init__(self, result: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.result = result
        self._expanded = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(4)

        icon_char, color = _STATUS_ICONS.get(result["status"], ("?", "#FFF"))
        row = QHBoxLayout()
        row.setSpacing(10)

        icon = QLabel(icon_char)
        icon.setFixedWidth(22)
        icon.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        icon.setStyleSheet(
            f"color: {color}; font-weight: 700; font-size: 14px;")
        row.addWidget(icon)

        # Name + message in one line
        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        text_col.setContentsMargins(0, 0, 0, 0)
        name = QLabel(result["name"])
        name.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; font-weight: 600; font-size: 13px;")
        text_col.addWidget(name)
        if result.get("message"):
            msg = QLabel(result["message"])
            msg.setWordWrap(True)
            msg.setStyleSheet(
                f"color: {Colors.TEXT_SECONDARY}; font-size: 12px;")
            text_col.addWidget(msg)
        row.addLayout(text_col, 1)

        # Expand button if there's a fix to show
        if result.get("fix"):
            self.btn_more = QPushButton("Details ▾")
            self.btn_more.setFlat(True)
            self.btn_more.setCursor(Qt.PointingHandCursor)
            self.btn_more.setStyleSheet(
                f"QPushButton {{ background: transparent; "
                f"color: {Colors.PRIMARY}; border: none; "
                f"padding: 2px 6px; font-size: 11px; }}"
                f"QPushButton:hover {{ text-decoration: underline; }}")
            self.btn_more.clicked.connect(self._toggle_expand)
            row.addWidget(self.btn_more, 0, Qt.AlignTop)
        outer.addLayout(row)

        # Fix panel (hidden initially)
        if result.get("fix"):
            self.fix_panel = QLabel(f"💡 {result['fix']}")
            self.fix_panel.setWordWrap(True)
            self.fix_panel.setStyleSheet(
                f"color: {Colors.TEXT_PRIMARY}; "
                f"font-size: 12px; "
                f"padding: 8px 12px; "
                f"background: {Colors.BG_INPUT}; "
                f"border-left: 3px solid {color}; "
                f"border-radius: 4px;"
                f"margin: 4px 0 2px 30px;")
            self.fix_panel.setVisible(False)
            outer.addWidget(self.fix_panel)

    def _toggle_expand(self):
        self._expanded = not self._expanded
        self.fix_panel.setVisible(self._expanded)
        self.btn_more.setText("Hide ▴" if self._expanded else "Details ▾")
