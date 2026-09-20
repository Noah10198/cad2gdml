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

# Suppress cosmetic Qt warnings on Windows (OpenGL, etc.). The dark-border
# noise itself is dropped by the Qt message handler installed in main().
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
from PyQt6.QtCore import (qInstallMessageHandler, QtMsgType, QMessageLogContext,
                          Qt)
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

from app.main_window import MainWindow
from utils.logger import AsyncLogger

# Taskbar identity. Windows groups every script launched by python.exe under a
# single "Python" entry, so without this the taskbar button keeps Python's icon
# and jump lists of unrelated scripts get mixed together.
_APP_USER_MODEL_ID = "CAD2GDML.Cad2Gdml.2"
_ICON_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "icon", "cad2gdml.svg")

# Sizes Windows asks for: 16 px is the title bar icon at 100% scaling, 24 px
# the taskbar button, and the rest cover higher DPI settings and Alt+Tab.
_ICON_SIZES = (16, 20, 24, 32, 48, 64, 96, 128, 256)


def _qt_message_filter(_msg_type: QtMsgType, _context: QMessageLogContext,
                       message: str) -> None:
    """Silence benign Qt platform noise on Windows.

    Qt tries to give native title bars a dark border when a window's
    background is dark (3D view / dark theme). On Windows builds where
    DwmSetWindowAttribute is unavailable or called before the native window
    exists it prints, per window/attempt:
      QWindowsWindow::setDarkBorderToWindow: Unable to set dark window border.
    It is cosmetic noise - the OS simply falls back to the normal border -
    so the line is dropped. Everything else is forwarded to stderr.
    """
    text = str(message)
    if "setDarkBorderToWindow" in text:
        return
    print(f"Qt: {text}", file=sys.stderr)


def _build_app_icon() -> QIcon:
    """Build the window / taskbar icon from icon/cad2gdml.svg.

    The source is a vector, so it is rendered once per size Windows may ask
    for instead of being scaled down from a single raster, which keeps the
    small title bar and taskbar versions sharp.
    """
    if not os.path.exists(_ICON_FILE):
        return QIcon()

    renderer = QSvgRenderer(_ICON_FILE)
    if not renderer.isValid():
        return QIcon(_ICON_FILE)

    icon = QIcon()
    for size in _ICON_SIZES:
        canvas = QPixmap(size, size)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        renderer.render(painter)
        painter.end()
        icon.addPixmap(canvas)
    return icon


def main():
    """
    Application entry point.

    1. Create QApplication instance.
    2. Create and show the main window.
    3. Configure logging.
    4. Enter Qt event loop.
    """
    # Must be set before any window exists, otherwise the taskbar entry is
    # already bound to python.exe and the icon below has no effect.
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                _APP_USER_MODEL_ID)
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("CAD2GDML")
    app.setApplicationVersion("2.0.0")
    app.setWindowIcon(_build_app_icon())
    _ = qInstallMessageHandler(_qt_message_filter)

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
    # The contact analysis runs in a spawned child process; this is required
    # on Windows (and mandatory if the app is ever frozen into an .exe).
    import multiprocessing
    multiprocessing.freeze_support()
    main()
