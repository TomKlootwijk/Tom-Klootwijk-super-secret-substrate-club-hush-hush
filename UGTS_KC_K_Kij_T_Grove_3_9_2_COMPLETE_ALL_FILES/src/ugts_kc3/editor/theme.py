"""Calm, high-contrast dark theme for the desktop editor."""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


STYLE_SHEET = """
QWidget {
    color: #dce8f5;
    background: #101925;
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 10pt;
}
QMainWindow, QMenuBar, QMenu { background: #0d1520; }
QMenuBar { border-bottom: 1px solid #243247; padding: 2px; }
QMenuBar::item { padding: 6px 10px; border-radius: 5px; }
QMenuBar::item:selected, QMenu::item:selected { background: #26384f; }
QMenu { border: 1px solid #31435b; padding: 5px; }
QMenu::item { padding: 7px 28px 7px 11px; border-radius: 4px; }
QToolBar {
    background: #111c29;
    border: none;
    border-bottom: 1px solid #26364c;
    spacing: 5px;
    padding: 6px 9px;
}
QToolButton, QPushButton {
    background: #1b2a3d;
    border: 1px solid #31465f;
    border-radius: 7px;
    padding: 6px 11px;
    min-height: 18px;
}
QToolButton:hover, QPushButton:hover { background: #243954; border-color: #4e7196; }
QToolButton:pressed, QPushButton:pressed { background: #172437; }
QToolButton:disabled, QPushButton:disabled { color: #65758a; background: #151e2b; border-color: #263244; }
#PrimaryButton { background: #16617c; border-color: #2faad0; color: #f2fbff; font-weight: 600; }
#PrimaryButton:hover { background: #1b7898; }
#PlayButton { background: #19764a; border-color: #39cf82; color: white; font-weight: 700; padding: 7px 16px; }
#PlayButton:hover { background: #218e5b; }
#StopButton { background: #6c2b3c; border-color: #d85b79; color: white; font-weight: 600; }
QDockWidget { color: #cbd9e9; font-weight: 600; }
QDockWidget::title {
    background: #111c2a;
    border-bottom: 1px solid #283950;
    padding: 8px 10px;
    text-align: left;
}
QTreeWidget, QListWidget, QTableWidget, QPlainTextEdit, QTextEdit {
    background: #0c1521;
    alternate-background-color: #101c2a;
    border: 1px solid #26384d;
    border-radius: 6px;
    selection-background-color: #205b79;
    selection-color: #f4fbff;
    outline: none;
}
QTreeWidget::item { min-height: 25px; padding: 1px 4px; }
QTreeWidget::item:hover { background: #17283b; }
QHeaderView::section { background: #152235; color: #91a6bd; padding: 6px; border: none; border-right: 1px solid #26374d; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: #0c1521;
    border: 1px solid #30435a;
    border-radius: 6px;
    padding: 5px 7px;
    selection-background-color: #28789d;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: #45bfe8; }
QComboBox::drop-down { border: none; width: 22px; }
QTabWidget::pane { border: 1px solid #26374c; background: #0d1622; }
QTabBar::tab { background: #111c2a; color: #91a5bc; padding: 8px 16px; border-right: 1px solid #233449; }
QTabBar::tab:selected { background: #18283a; color: #e7f5ff; border-bottom: 2px solid #4bc8f1; }
QTabBar::tab:hover:!selected { background: #152235; }
QGroupBox { border: 1px solid #2a3b51; border-radius: 8px; margin-top: 11px; padding: 13px 9px 9px 9px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #9eb2c9; }
QSplitter::handle { background: #26374c; width: 1px; height: 1px; }
QScrollBar:vertical { background: #0d1622; width: 11px; margin: 0; }
QScrollBar::handle:vertical { background: #344960; min-height: 28px; border-radius: 5px; margin: 2px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: #0d1622; height: 11px; }
QScrollBar::handle:horizontal { background: #344960; min-width: 28px; border-radius: 5px; margin: 2px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QStatusBar { background: #0b131d; border-top: 1px solid #243348; color: #8fa3b9; }
QStatusBar::item { border: none; }
QProgressBar { border: 1px solid #30435a; border-radius: 5px; background: #0c1521; text-align: center; }
QProgressBar::chunk { background: #36a7cc; border-radius: 4px; }
#PanelTitle { color: #eef8ff; font-size: 13pt; font-weight: 700; }
#MutedLabel { color: #8fa4bb; }
#WelcomeTitle { color: #effaff; font-size: 28pt; font-weight: 750; }
#WelcomeSubtitle { color: #9db2c8; font-size: 12pt; }
#WelcomeCard { background: #111e2d; border: 1px solid #2a3d55; border-radius: 12px; }
#GraphToolbar { background: #101b29; border-bottom: 1px solid #293a50; }
#NodePalette { background: #101b29; border-right: 1px solid #2b3b50; }
#SceneViewport, #VisualGraphView { background: #08101a; }
QToolTip { color: #ecf8ff; background: #172638; border: 1px solid #426180; padding: 5px; }
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#101925"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#dce8f5"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#0c1521"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#111c2a"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#dce8f5"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#1b2a3d"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#dce8f5"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#24789b"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#657990"))
    app.setPalette(palette)
    app.setStyleSheet(STYLE_SHEET)


__all__ = ["STYLE_SHEET", "apply_theme"]
