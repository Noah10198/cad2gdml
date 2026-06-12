"""
ImportWorker - Non-blocking CAD file import in a background thread.

Reads STEP/IGES/BREP/STL files without blocking the GUI.
The resulting GDataNode tree is delivered via signal for the main
thread to register with GeoDataAgent and display.
"""

from typing import List, Optional
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from core.cad_reader import CADReader
from core.g_data_node import GDataNode


class ImportWorker(QThread):
    """Read CAD files in a background thread."""

    progress_updated = pyqtSignal(int, str)
    log_emitted = pyqtSignal(str)
    finished_with_result = pyqtSignal(bool, list, list)  # success, file_nodes, error_info

    def __init__(self, file_paths: List[str], parent=None):
        super().__init__(parent)
        self._file_paths = file_paths
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        if not self._file_paths:
            self.finished_with_result.emit(False, [], ["No files to import."])
            return

        reader = CADReader()
        file_nodes: List[GDataNode] = []
        error_info: List[str] = []
        total = len(self._file_paths)

        self.log_emitted.emit("=== CAD Import Started ===")

        for i, fp in enumerate(self._file_paths):
            if self._cancelled:
                self.log_emitted.emit("Import cancelled by user.")
                self.finished_with_result.emit(False, [], ["Cancelled."])
                return

            label = Path(fp).name
            pct = int((i / total) * 95)

            self.log_emitted.emit(f"[{i+1}/{total}] Reading {label} ...")
            self.progress_updated.emit(pct, f"Reading {label}...")

            node = reader.read_file(fp, error_info)
            if node is not None:
                file_nodes.append(node)

            self.progress_updated.emit(pct + 5 if pct < 95 else 100, f"Done: {label}")

        # Log errors
        for err in error_info:
            self.log_emitted.emit(f"  [ERROR] {err}")

        self.log_emitted.emit("=== CAD Import Complete ===")
        ok = len(file_nodes) > 0
        msg = f"Imported {len(file_nodes)} file(s)" if ok else "Import failed."
        self.progress_updated.emit(100, msg)
        self.finished_with_result.emit(ok, file_nodes, error_info)
