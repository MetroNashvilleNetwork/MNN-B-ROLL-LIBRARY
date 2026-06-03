"""Phase 3 — PyQt5 main search window.

A simple, daily-use search interface over the local index:

* search bar (keyword search over filename / folder / shooter),
* filters: file type, shot type, shooter, and month/shoot-date range,
* results table (filename, shooter, month, shot type, type, modified, folder),
* double-click a row to reveal the file in Windows File Explorer,
* "Re-index Now" button that runs in the background, and
* a status bar showing the last index time and total file count.

At launch it runs the Phase 1 drive check and indexes in the background if a
daily re-index is due. Designed to stay responsive: all indexing happens off the
UI thread.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from typing import Optional

from PyQt5 import QtCore, QtGui, QtWidgets

from .. import __app_name__, database as db
from ..config import Config
from .. import indexer, scheduler
from ..drive_validator import ValidationReport, validate_config


# --- Background indexing worker ------------------------------------------


class IndexWorker(QtCore.QObject):
    """Runs an index pass on a worker thread and reports progress/finish."""

    progress = QtCore.pyqtSignal(int, str)      # processed, current path
    message = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(object)        # indexer.IndexResult
    failed = QtCore.pyqtSignal(str)

    def __init__(self, config: Config, full: bool = False) -> None:
        super().__init__()
        self._config = config
        self._full = full

    @QtCore.pyqtSlot()
    def run(self) -> None:
        try:
            result = indexer.run_index(
                self._config,
                progress=lambda n, total, path: self.progress.emit(n, path),
                log=lambda m: self.message.emit(m),
                full_rescan=self._full,
            )
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


# --- Helpers --------------------------------------------------------------


def _human_size(num: Optional[int]) -> str:
    if not num:
        return ""
    size = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _human_duration(sec: Optional[float]) -> str:
    if not sec:
        return ""
    sec = int(sec)
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _pretty_dt(iso: Optional[str]) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso


def reveal_in_explorer(path: str) -> None:
    """Open Windows Explorer with the file selected (falls back to the folder)."""
    if os.name == "nt":
        if os.path.exists(path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            folder = os.path.dirname(path)
            if os.path.isdir(folder):
                subprocess.Popen(["explorer", os.path.normpath(folder)])
    else:  # dev convenience on non-Windows
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen([opener, folder])


# --- Results table model --------------------------------------------------

COLUMNS = ["Filename", "Shooter", "Month", "Shot type", "Type", "Modified",
           "Duration", "Size", "Folder"]


class ResultsModel(QtCore.QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list = []

    def set_rows(self, rows: list) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def row_path(self, row: int) -> Optional[str]:
        if 0 <= row < len(self._rows):
            return self._rows[row]["path"]
        return None

    def rowCount(self, parent=QtCore.QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QtCore.QModelIndex()) -> int:  # noqa: N802
        return len(COLUMNS)

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):  # noqa: N802
        if role == QtCore.Qt.DisplayRole and orientation == QtCore.Qt.Horizontal:
            return COLUMNS[section]
        return None

    def data(self, index, role=QtCore.Qt.DisplayRole):  # noqa: N802
        if not index.isValid():
            return None
        r = self._rows[index.row()]
        col = index.column()
        if role == QtCore.Qt.ToolTipRole:
            return r["path"]
        if role != QtCore.Qt.DisplayRole:
            return None
        return [
            r["filename"],
            r["shooter"] or "",
            r["month_name"] or "",
            r["shot_type"] or "",
            (r["extension"] or "").lstrip("."),
            _pretty_dt(r["date_modified"]),
            _human_duration(r["duration_sec"]),
            _human_size(r["size_bytes"]),
            r["folder_path"] or "",
        ][col]


# --- Main window ----------------------------------------------------------


class MainWindow(QtWidgets.QMainWindow):
    ANY = "All"

    def __init__(self, config: Config, report: Optional[ValidationReport] = None) -> None:
        super().__init__()
        self.config = config
        self.setWindowTitle(__app_name__)
        self.resize(1100, 650)

        self._con = db.connect(config.database_abspath)
        self._thread: Optional[QtCore.QThread] = None
        self._worker: Optional[IndexWorker] = None

        self._build_ui()
        self._reload_filter_values()
        self._run_search()
        self._refresh_status()

        if report and report.errors:
            self._show_drive_warning(report)

        # Kick off a daily re-index in the background if one is due.
        if scheduler.is_index_due(config):
            self._start_index(full=False, reason="daily auto-index")

    # -- UI construction --------------------------------------------------

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        outer = QtWidgets.QVBoxLayout(central)

        # Drive warning banner (hidden unless there's a problem).
        self.banner = QtWidgets.QLabel()
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet(
            "background:#fff3cd; color:#664d03; border:1px solid #ffe69c;"
            "padding:8px; border-radius:4px;")
        self.banner.hide()
        outer.addWidget(self.banner)

        # Search row.
        search_row = QtWidgets.QHBoxLayout()
        self.search_box = QtWidgets.QLineEdit()
        self.search_box.setPlaceholderText(
            "Search b-roll by keyword, e.g. 'blodgett oven', 'commissary', 'kitchen closeup'")
        self.search_box.returnPressed.connect(self._run_search)
        self.search_box.textChanged.connect(self._on_text_changed)
        search_btn = QtWidgets.QPushButton("Search")
        search_btn.clicked.connect(self._run_search)
        clear_btn = QtWidgets.QPushButton("Clear")
        clear_btn.clicked.connect(self._clear_filters)
        search_row.addWidget(self.search_box, 1)
        search_row.addWidget(search_btn)
        search_row.addWidget(clear_btn)
        outer.addLayout(search_row)

        # Filter row.
        filt = QtWidgets.QHBoxLayout()
        self.type_combo = QtWidgets.QComboBox()
        self.shot_combo = QtWidgets.QComboBox()
        self.shooter_combo = QtWidgets.QComboBox()
        self.from_combo = QtWidgets.QComboBox()
        self.to_combo = QtWidgets.QComboBox()
        for label, widget in [
            ("File type:", self.type_combo), ("Shot type:", self.shot_combo),
            ("Shooter:", self.shooter_combo), ("From:", self.from_combo),
            ("To:", self.to_combo),
        ]:
            filt.addWidget(QtWidgets.QLabel(label))
            widget.currentIndexChanged.connect(self._run_search)
            filt.addWidget(widget)
        filt.addStretch(1)
        outer.addLayout(filt)

        # Results table.
        self.model = ResultsModel()
        self.table = QtWidgets.QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(False)
        self.table.doubleClicked.connect(self._open_selected)
        self.table.setAlternatingRowColors(True)
        hdr = self.table.horizontalHeader()
        hdr.setStretchLastSection(True)
        hdr.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        outer.addWidget(self.table, 1)

        # Bottom row: result count + open button + re-index.
        bottom = QtWidgets.QHBoxLayout()
        self.result_label = QtWidgets.QLabel("")
        open_btn = QtWidgets.QPushButton("Open file location")
        open_btn.clicked.connect(self._open_selected)
        self.reindex_btn = QtWidgets.QPushButton("Re-index Now")
        self.reindex_btn.clicked.connect(lambda: self._start_index(full=False,
                                                                   reason="manual"))
        bottom.addWidget(self.result_label)
        bottom.addStretch(1)
        bottom.addWidget(open_btn)
        bottom.addWidget(self.reindex_btn)
        outer.addLayout(bottom)

        # Status bar with a progress indicator.
        self.status = self.statusBar()
        self.progress = QtWidgets.QProgressBar()
        self.progress.setMaximumWidth(180)
        self.progress.setRange(0, 0)  # indeterminate
        self.progress.hide()
        self.status.addPermanentWidget(self.progress)

    # -- Filters ----------------------------------------------------------

    def _reload_filter_values(self) -> None:
        """Populate filter dropdowns from the current index contents."""
        def fill(combo: QtWidgets.QComboBox, values: list[str], current: str = ""):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(self.ANY)
            for v in values:
                combo.addItem(v)
            if current:
                idx = combo.findText(current)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            combo.blockSignals(True)
            combo.blockSignals(False)

        exts = [e.lstrip(".").upper() for e in db.distinct_values(self._con, "extension")]
        fill(self.type_combo, exts)
        fill(self.shot_combo, db.distinct_values(self._con, "shot_type"))
        fill(self.shooter_combo, db.distinct_values(self._con, "shooter"))

        months = self._available_months()
        for combo in (self.from_combo, self.to_combo):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(self.ANY)
            for label, _iso in months:
                combo.addItem(label, _iso)
            combo.blockSignals(False)

    def _available_months(self) -> list[tuple[str, str]]:
        rows = self._con.execute(
            "SELECT DISTINCT shoot_year, shoot_month, shoot_date FROM files "
            "WHERE shoot_date IS NOT NULL ORDER BY shoot_date"
        ).fetchall()
        out = []
        for r in rows:
            label = f"{r['shoot_year']:04d}-{r['shoot_month']:02d}"
            out.append((label, r["shoot_date"]))
        return out

    def _clear_filters(self) -> None:
        self.search_box.clear()
        for combo in (self.type_combo, self.shot_combo, self.shooter_combo,
                      self.from_combo, self.to_combo):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self._run_search()

    def _combo_value(self, combo: QtWidgets.QComboBox) -> Optional[str]:
        return None if combo.currentIndex() <= 0 else combo.currentText()

    # -- Search -----------------------------------------------------------

    def _on_text_changed(self) -> None:
        # Debounce live search so typing stays smooth.
        if not hasattr(self, "_debounce"):
            self._debounce = QtCore.QTimer(self)
            self._debounce.setSingleShot(True)
            self._debounce.setInterval(220)
            self._debounce.timeout.connect(self._run_search)
        self._debounce.start()

    def _run_search(self) -> None:
        ext = self._combo_value(self.type_combo)
        extensions = [ext.lower()] if ext else None
        date_from = self.from_combo.currentData() if self.from_combo.currentIndex() > 0 else None
        date_to = self.to_combo.currentData() if self.to_combo.currentIndex() > 0 else None
        rows = db.search(
            self._con,
            self.search_box.text(),
            extensions=extensions,
            shot_type=self._combo_value(self.shot_combo),
            shooter=self._combo_value(self.shooter_combo),
            date_from=date_from,
            date_to=date_to,
            limit=2000,
        )
        self.model.set_rows(rows)
        self.result_label.setText(f"{len(rows)} result(s)")

    # -- File actions -----------------------------------------------------

    def _open_selected(self) -> None:
        idxs = self.table.selectionModel().selectedRows()
        if not idxs:
            self.status.showMessage("Select a result first.", 3000)
            return
        path = self.model.row_path(idxs[0].row())
        if path:
            reveal_in_explorer(path)

    # -- Indexing ---------------------------------------------------------

    def _start_index(self, full: bool, reason: str) -> None:
        if self._thread is not None:
            self.status.showMessage("Indexing already in progress…", 3000)
            return
        self.reindex_btn.setEnabled(False)
        self.progress.show()
        self.status.showMessage(f"Indexing ({reason})…")

        self._thread = QtCore.QThread()
        self._worker = IndexWorker(self.config, full=full)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_index_progress)
        self._worker.message.connect(lambda m: self.status.showMessage(m, 5000))
        self._worker.finished.connect(self._on_index_finished)
        self._worker.failed.connect(self._on_index_failed)
        self._thread.start()

    def _on_index_progress(self, n: int, path: str) -> None:
        if n % 50 == 0:
            self.status.showMessage(f"Indexing… {n} files ({os.path.basename(path)})")

    def _on_index_finished(self, result) -> None:
        self._teardown_thread()
        self._reload_filter_values()
        self._run_search()
        self._refresh_status()
        self.status.showMessage(result.summary(), 8000)

    def _on_index_failed(self, msg: str) -> None:
        self._teardown_thread()
        QtWidgets.QMessageBox.warning(self, "Indexing failed", msg)
        self._refresh_status()

    def _teardown_thread(self) -> None:
        if self._thread:
            self._thread.quit()
            self._thread.wait()
        self._thread = None
        self._worker = None
        self.progress.hide()
        self.reindex_btn.setEnabled(True)

    # -- Status / banners -------------------------------------------------

    def _refresh_status(self) -> None:
        last = db.get_meta(self._con, "last_index_completed_at")
        count = db.file_count(self._con)
        last_txt = _pretty_dt(last) if last else "never"
        self.status.showMessage(f"Last indexed: {last_txt}   |   {count} files in index")

    def _show_drive_warning(self, report: ValidationReport) -> None:
        msgs = "; ".join(r.message for r in report.errors)
        self.banner.setText("⚠ Drive issue: " + msgs)
        self.banner.show()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802
        self._teardown_thread()
        try:
            self._con.close()
        except Exception:
            pass
        super().closeEvent(event)


def launch(config: Config, report: Optional[ValidationReport] = None) -> int:
    """Entry point used by main.py. Returns the Qt application exit code."""
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    if report is None:
        report = validate_config(config)
    win = MainWindow(config, report)
    win.show()
    return app.exec_()
