"""
AsyncLogger - 异步日志系统

对应 C++ 版 AsyncLogger，提供系统日志和求解日志的记录功能。
采用单例模式，支持日志分级输出到 UI 控件。
"""

import html
from typing import Optional
from enum import Enum
from PyQt6.QtCore import QObject, pyqtSignal, QDateTime


class LogLevel(Enum):
    """日志级别"""
    DEBUG = 0
    INFO = 1
    WARNING = 2
    ERROR = 3


# The two levels a reader has to find by eye in a log that is otherwise one
# wall of INFO text. Everything else is appended as plain text on purpose:
# QTextEdit.append() auto-detects HTML, so a message that happens to contain
# '<' would be swallowed as a tag if every line went through the rich path.
_ALERT_COLOR = "#ff4d4f"
_ALERT_LEVELS = (LogLevel.WARNING, LogLevel.ERROR)


class AsyncLogger(QObject):
    """异步日志管理器（单例）"""

    log_received = pyqtSignal(str, str)  # (log_type, message)

    _instance: Optional['AsyncLogger'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        super().__init__()
        self._system_log_buffer: list = []
        self._solver_log_buffer: list = []
        self._system_log_widget = None
        self._solver_log_widget = None

    def set_system_log_widget(self, text_edit):
        self._system_log_widget = text_edit
        for formatted, level in self._system_log_buffer:
            if self._system_log_widget:
                self._append(self._system_log_widget, formatted, level)
        self._system_log_buffer.clear()

    def set_solver_log_widget(self, text_edit):
        self._solver_log_widget = text_edit
        for formatted, level in self._solver_log_buffer:
            if self._solver_log_widget:
                self._append(self._solver_log_widget, formatted, level)
        self._solver_log_buffer.clear()

    @staticmethod
    def _append(widget, formatted: str, level: LogLevel):
        """One line into the view, coloured only when it has to stand out."""
        if level not in _ALERT_LEVELS:
            widget.append(formatted)
            return
        alert = (f'<span style="color:{_ALERT_COLOR}">'
                 f'{html.escape(formatted)}</span>')
        # QPlainTextEdit spells this appendHtml(); the panel the logger is handed
        # is a QTextEdit (main_window._init_log_panel), which has no such method --
        # its append() detects the markup by itself, so the line is written both
        # ways rather than for one widget.
        append_html = getattr(widget, "appendHtml", None)
        if append_html is None:
            widget.append(alert)
        else:
            append_html(alert)

    def log(self, message: str, level: LogLevel = LogLevel.INFO, log_type: str = "system"):
        timestamp = QDateTime.currentDateTime().toString("yyyy-MM-dd hh:mm:ss")
        level_str = level.name
        formatted = f"[{timestamp}] [{level_str}] {message}"
        if log_type == "solver":
            widget, buffer = self._solver_log_widget, self._solver_log_buffer
        else:
            widget, buffer = self._system_log_widget, self._system_log_buffer
        # The buffer keeps the level as well: lines that arrive before the view
        # exists are replayed through the same colour rule.
        if widget is None:
            buffer.append((formatted, level))
        else:
            self._append(widget, formatted, level)
        self.log_received.emit(log_type, formatted)

    def log_system(self, message: str, level: LogLevel = LogLevel.INFO):
        self.log(message, level, "system")

    def log_solver(self, message: str, level: LogLevel = LogLevel.INFO):
        self.log(message, level, "solver")
