"""
RibbonToolBar - Office-style ribbon toolbar with emoji icons.

Provides 8 action buttons arranged horizontally:
  [Import CAD] [Interference 1 🔌] [Interference 2 ⚡] [Material] [Mesh] [View Mesh] [Export GDML] [Export Mesh] [Dark/Light] ... [Help]

Each button displays an emoji icon above with a text label below,
mimicking the Microsoft Office Ribbon style.
"""

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QToolButton, QSizePolicy
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QFont, QColor


def _create_emoji_icon(emoji: str, size: int = 36) -> QIcon:
    """Render emoji at 2x resolution for supersampled crispness."""
    scale = 2
    px = size * scale
    pixmap = QPixmap(px, px)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    font = QFont("Segoe UI Emoji", px - 24)
    painter.setFont(font)
    painter.setPen(QColor(220, 220, 220))
    _ = painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, emoji)
    _ = painter.end()
    return QIcon(pixmap)


def _ribbon_button(emoji: str, text: str) -> QToolButton:
    """Create a single ribbon-style tool button with icon above and text below."""
    btn = QToolButton()
    btn.setIcon(_create_emoji_icon(emoji))
    btn.setIconSize(QSize(36, 36))
    btn.setText(text)
    btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
    btn.setMinimumSize(85, 68)
    btn.setMaximumSize(120, 72)
    btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    return btn


class RibbonToolBar(QWidget):
    """
    Office-style ribbon toolbar widget.

    Signals are emitted when each button is clicked, allowing
    the MainWindow to connect and handle the actions.
    """

    import_step_clicked = pyqtSignal()
    interference_clicked = pyqtSignal()
    interference2_clicked = pyqtSignal()
    mesh_clicked = pyqtSignal()
    view_mesh_clicked = pyqtSignal()
    assign_material_clicked = pyqtSignal()
    export_gdml_clicked = pyqtSignal()
    export_mesh_clicked = pyqtSignal()
    theme_toggled = pyqtSignal()
    help_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("RibbonToolBar")
        self._dark_theme = False
        self._build_ui()
        self._apply_theme(False)

    def _build_ui(self):
        """Construct the horizontal button layout."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(4)

        # Define button spec: (emoji, label, signal)
        buttons = [
            ("📂", "Import CAD", self.import_step_clicked),
            ("🔌", "Interference 1", self.interference_clicked),
            ("⚡", "Interference 2", self.interference2_clicked),
            ("🧪", "Material", self.assign_material_clicked),
            ("🔧", "Mesh", self.mesh_clicked),
            ("👁", "View Mesh", self.view_mesh_clicked),
            ("📦", "Export GDML", self.export_gdml_clicked),
            ("📤", "Export Mesh", self.export_mesh_clicked),
        ]

        for emoji, label, signal in buttons:
            btn = _ribbon_button(emoji, label)
            _ = btn.clicked.connect(signal.emit)
            layout.addWidget(btn)

        # Push right-side buttons (theme + help)
        layout.addStretch()

        self._theme_btn = _ribbon_button("🌙", "Dark")
        self._theme_btn.setObjectName("ThemeToggle")
        _ = self._theme_btn.clicked.connect(self.theme_toggled.emit)
        layout.addWidget(self._theme_btn)

        help_btn = _ribbon_button("❓", "Help")
        _ = help_btn.clicked.connect(self.help_clicked.emit)
        layout.addWidget(help_btn)

    def set_dark_theme(self, is_dark: bool):
        """Switch the toolbar between dark and light appearance."""
        self._dark_theme = is_dark
        self._apply_theme(is_dark)
        emoji = "🌙" if is_dark else "☀️"
        label = "Dark" if is_dark else "Light"
        self._theme_btn.setIcon(_create_emoji_icon(emoji))
        self._theme_btn.setText(label)

    def _apply_theme(self, dark: bool):
        """Apply stylesheet based on current theme mode."""
        if dark:
            bg = "#1e1e2e"
            border = "#313244"
            btn_text = "#cdd6f4"
            btn_hover = "#313244"
            btn_hover_border = "#45475a"
            btn_pressed = "#45475a"
        else:
            bg = "#f5f5f5"
            border = "#d0d0d0"
            btn_text = "#2c2c2c"
            btn_hover = "#e0e0e0"
            btn_hover_border = "#c0c0c0"
            btn_pressed = "#cccccc"

        self.setStyleSheet(f"""
            #RibbonToolBar {{
                background-color: {bg};
                border-bottom: 2px solid {border};
                min-height: 72px;
            }}
            QToolButton {{
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 5px;
                padding: 3px 10px;
                color: {btn_text};
                font-size: 12px;
                font-family: "Segoe UI", "Arial", sans-serif;
            }}
            QToolButton:hover {{
                background-color: {btn_hover};
                border: 1px solid {btn_hover_border};
            }}
            QToolButton:pressed {{
                background-color: {btn_pressed};
            }}
        """)
