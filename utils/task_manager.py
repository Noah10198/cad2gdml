"""
TaskManager - 任务管理器

对应 C++ 版 TaskManager，管理耗时任务的进度显示。
采用单例模式，提供进度条更新、任务状态管理等功能。
"""

from typing import Optional
from PyQt6.QtCore import QObject, pyqtSignal


class TaskManager(QObject):
    """任务管理器（单例）"""

    progress_updated = pyqtSignal(float, str)  # (进度值 0-100, 描述文本)

    _instance: Optional['TaskManager'] = None

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
        self._current_task_name: str = ""
        self._progress: float = 0.0
        self._is_running: bool = False

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def current_task_name(self) -> str:
        return self._current_task_name

    @property
    def progress(self) -> float:
        return self._progress

    def start_task(self, task_name: str):
        self._current_task_name = task_name
        self._progress = 0.0
        self._is_running = True
        self.progress_updated.emit(0.0, task_name)

    def update_progress(self, value: float, description: str = ""):
        self._progress = min(100.0, max(0.0, value))
        desc = description or self._current_task_name
        self.progress_updated.emit(self._progress, desc)

    def finish_task(self):
        self._progress = 100.0
        self._is_running = False
        self.progress_updated.emit(100.0, self._current_task_name)

    def cancel_task(self):
        self._is_running = False
        self._progress = 0.0
