"""
AsyncLogger - 异步日志系统

对应 C++ 版 AsyncLogger，提供系统日志和求解日志的记录功能。
采用单例模式，支持日志分级输出到 UI 控件。
"""

from typing import Optional
from enum import Enum
from PyQt6.QtCore import QObject, pyqtSignal, QDateTime


class LogLevel(Enum):
    """日志级别"""
    DEBUG = 0
    INFO = 1
    WARNING = 2
    ERROR = 3


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
        for msg in self._system_log_buffer:
            if self._system_log_widget:
                self._system_log_widget.append(msg)
        self._system_log_buffer.clear()

    def set_solver_log_widget(self, text_edit):
        self._solver_log_widget = text_edit
        for msg in self._solver_log_buffer:
            if self._solver_log_widget:
                self._solver_log_widget.append(msg)
        self._solver_log_buffer.clear()

    def log(self, message: str, level: LogLevel = LogLevel.INFO, log_type: str = "system"):
        timestamp = QDateTime.currentDateTime().toString("yyyy-MM-dd hh:mm:ss")
        level_str = level.name
        formatted = f"[{timestamp}] [{level_str}] {message}"
        if log_type == "solver":
            if self._solver_log_widget:
                self._solver_log_widget.append(formatted)
            else:
                self._solver_log_buffer.append(formatted)
        else:
            if self._system_log_widget:
                self._system_log_widget.append(formatted)
            else:
                self._system_log_buffer.append(formatted)
        self.log_received.emit(log_type, formatted)

    def log_system(self, message: str, level: LogLevel = LogLevel.INFO):
        self.log(message, level, "system")

    def log_solver(self, message: str, level: LogLevel = LogLevel.INFO):
        self.log(message, level, "solver")
