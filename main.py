"""
CAD2GDML - STEP to GDML Geometry Conversion Tool

Entry point for the application.
Initializes the Qt application, creates and displays the main window.
"""

import sys
import os
import ctypes

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Suppress cosmetic Qt warnings on Windows (dark border, OpenGL, etc.)
os.environ["QT_WIN_NEED_DARK_BORDER"] = "1"
os.environ["QT_LOGGING_RULES"] = ("qt.qpa.windows.warning=false;"
                                  "qt.qpa.gl.warning=false;"
                                  "qt.qpa.eglfs.warning=false")

# Disable Windows "Not Responding" ghosting for the entire process.
# This prevents the system from replacing our window with a white ghost
# overlay when the main thread is briefly blocked (e.g. during OCC I/O).
# Any OCC blocking operation will simply pause the UI without triggering
# the "无响应" / "Not Responding" indicator.
try:
    ctypes.windll.user32.DisableProcessWindowsGhosting()
except Exception:
    pass

from PyQt6.QtWidgets import QApplication

from app.main_window import MainWindow
from utils.logger import AsyncLogger


def main():
    """
    Application entry point.

    1. Create QApplication instance.
    2. Create and show the main window.
    3. Configure logging.
    4. Enter Qt event loop.
    """
    app = QApplication(sys.argv)
    app.setApplicationName("CAD2GDML")
    app.setApplicationVersion("2.0.0")

    # Create main window
    main_window = MainWindow()

    # Configure logger with the system log widget
    logger = AsyncLogger()
    logger.set_system_log_widget(main_window.get_system_log_widget())

    # Log startup info
    logger.log_system("CAD2GDML started")
    logger.log_system(f"Python version: {sys.version}")

    # Show main window
    main_window.show()

    # Enter Qt event loop
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
