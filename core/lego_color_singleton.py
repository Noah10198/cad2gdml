"""
LegoColorSingleton - 乐高配色方案

对应 C++ GEODATACENTER::LegoColorSingleton。
为每个几何部件分配预设的乐高颜色，循环使用。
"""

from typing import List, Optional

from PyQt6.QtGui import QColor
from OCC.Core.Quantity import Quantity_Color, Quantity_TOC_RGB


class LegoColorSingleton:
    """乐高颜色单例，循环返回预设颜色列表中的颜色"""

    _instance: Optional['LegoColorSingleton'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._current_index = 0
        self._color_list: List[QColor] = [
            QColor("#05131D"), QColor("#0055BF"), QColor("#B9D9EB"), QColor("#006DB0"),
            QColor("#C91A09"), QColor("#B40006"), QColor("#C80000"), QColor("#990000"),
            QColor("#F2CD37"), QColor("#F8D6C0"), QColor("#4B9F4A"), QColor("#237841"),
            QColor("#85C1E9"), QColor("#2D75B2"), QColor("#FFF03A"), QColor("#FFD662"),
            QColor("#BE4B2E"), QColor("#F89B53"), QColor("#4B2D17"), QColor("#604D33"),
            QColor("#8C4B22"), QColor("#703D24"), QColor("#A5A5CB"), QColor("#635F61"),
            QColor("#004281"), QColor("#1D1F1A"), QColor("#ACD39A"), QColor("#6A7A5B"),
            QColor("#352100"), QColor("#764A25"), QColor("#D69A2D"), QColor("#DDBB99"),
            QColor("#A5A5A5"), QColor("#6D6E5C"), QColor("#262321"), QColor("#2C2A29"),
            QColor("#FF800D"), QColor("#FFFFFF"), QColor("#E4E0E1"), QColor("#C0C0C0"),
            QColor("#7F7F7F"), QColor("#E5FFE9"), QColor("#FFFFFF"), QColor("#DCD7D5"),
            QColor("#E4E4DA"), QColor("#F5F5DC"), QColor("#000000"), QColor("#000000"),
        ]

    def get_next_color(self) -> Quantity_Color:
        qcolor = self._color_list[self._current_index]
        self._current_index = (self._current_index + 1) % len(self._color_list)
        return Quantity_Color(qcolor.redF(), qcolor.greenF(), qcolor.blueF(), Quantity_TOC_RGB)

    def reset(self):
        self._current_index = 0
