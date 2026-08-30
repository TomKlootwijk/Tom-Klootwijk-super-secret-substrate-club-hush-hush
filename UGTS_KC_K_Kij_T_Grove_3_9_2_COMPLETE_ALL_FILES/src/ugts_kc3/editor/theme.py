"""Calm, high-contrast dark theme for the desktop editor."""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


STYLE_SHEET = """
QWidget {
    color: #edf5ff;
    background: #0a1019;
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 10pt;
}
QMainWindow { background: #050910; }
QMenuBar { background: #070c13; border: none; padding: 3px 5px; }
QMenuBar::item { background: transparent; padding: 6px 10px; border-radius: 5px; }
QMenuBar::item:selected { background: #162636; color: #ffffff; }
QMenu {
    background: #0c141f;
    border: 1px solid #213447;
    padding: 5px;
}
QMenu::item { padding: 7px 30px 7px 11px; border-radius: 4px; }
QMenu::item:selected { background: #16465c; color: #ffffff; }
QMenu::separator { height: 1px; background: #1c2b39; margin: 5px 8px; }
QToolBar {
    background: #080e17;
    border: none;
    spacing: 6px;
    padding: 7px 10px;
}
QToolBar::separator { background: #20303e; width: 1px; margin: 7px 6px; }
QToolButton, QPushButton {
    background: #131f2d;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 6px 11px;
    min-height: 18px;
}
QToolButton:hover, QPushButton:hover { background: #1a3041; color: #ffffff; }
QToolButton:pressed, QPushButton:pressed { background: #102433; }
QToolButton:checked, QPushButton:checked { background: #173b4d; color: #f7fcff; }
QToolButton:focus, QPushButton:focus { border-color: #48d7ff; }
QToolButton:disabled, QPushButton:disabled {
    color: #5f6f81;
    background: #0e1621;
    border-color: transparent;
}
#PrimaryButton {
    background: #12627c;
    border-color: #3fd5ff;
    color: #f7fdff;
    font-weight: 650;
}
#PrimaryButton:hover { background: #177a98; }
#PlayButton {
    background: #0f6f86;
    border-color: #48ddff;
    color: #ffffff;
    font-weight: 700;
    padding: 7px 16px;
}
#PlayButton:hover { background: #16879f; }
#StopButton {
    background: #4b3720;
    border-color: #f3b95b;
    color: #fff5df;
    font-weight: 650;
}
#StopButton:hover { background: #664924; }
#DeployButton {
    background: #125d76;
    border-color: #45d7ff;
    color: #ffffff;
    font-weight: 700;
    padding: 7px 14px;
}
#DeployButton:hover { background: #16758f; }
#ProfileButton { background: #49371f; border-color: #efb654; color: #fff4dc; font-weight: 650; }
#ProfileButton:hover { background: #624a27; }
QDockWidget { color: #cbd8e7; font-weight: 650; }
QDockWidget::title {
    background: #0b131e;
    border: none;
    padding: 8px 10px;
    text-align: left;
}
QTreeWidget, QListWidget, QTableWidget, QPlainTextEdit, QTextEdit {
    background: #070d15;
    alternate-background-color: #0b131e;
    border: none;
    border-radius: 5px;
    selection-background-color: #16516a;
    selection-color: #ffffff;
    outline: none;
}
QTreeWidget:focus, QListWidget:focus, QTableWidget:focus,
QPlainTextEdit:focus, QTextEdit:focus { border: 1px solid #2f7890; }
QTreeWidget::item { min-height: 25px; padding: 1px 4px; }
QTreeWidget::item:hover { background: #122334; }
QTreeWidget::item:selected:active { background: #17627c; color: #ffffff; }
QHeaderView::section {
    background: #0e1824;
    color: #9fb1c5;
    padding: 6px;
    border: none;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: #080f18;
    border: 1px solid #213446;
    border-radius: 6px;
    padding: 5px 7px;
    selection-background-color: #16708e;
    selection-color: #ffffff;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border-color: #48d7ff;
    background: #0b1621;
}
QComboBox::drop-down { border: none; width: 22px; }
QTabWidget::pane { border: none; background: #080e17; }
QTabBar::tab {
    background: #0b131e;
    color: #91a4b8;
    padding: 8px 16px;
    border: none;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:selected {
    background: #101d2a;
    color: #f3f9ff;
    border-bottom-color: #46d6ff;
}
QTabBar::tab:hover:!selected { background: #10202e; color: #d8e7f5; }
QGroupBox {
    background: #0c151f;
    border: none;
    border-radius: 8px;
    margin-top: 11px;
    padding: 13px 9px 9px 9px;
    font-weight: 600;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #a8bbcf; }
QSplitter::handle { background: #182736; width: 2px; height: 2px; }
QScrollBar:vertical { background: #080e17; width: 11px; margin: 0; }
QScrollBar::handle:vertical { background: #2b4053; min-height: 28px; border-radius: 5px; margin: 2px; }
QScrollBar::handle:vertical:hover { background: #3c6078; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: #080e17; height: 11px; }
QScrollBar::handle:horizontal { background: #2b4053; min-width: 28px; border-radius: 5px; margin: 2px; }
QScrollBar::handle:horizontal:hover { background: #3c6078; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QStatusBar { background: #060b12; border: none; color: #96a9bd; }
QStatusBar::item { border: none; }
QProgressBar { border: none; border-radius: 5px; background: #101a26; text-align: center; }
QProgressBar::chunk { background: #35bddd; border-radius: 4px; }
#PanelTitle { color: #f4f9ff; font-size: 13pt; font-weight: 700; }
#MutedLabel { color: #96aabd; }
#WelcomeTitle { color: #f6fbff; font-size: 28pt; font-weight: 750; }
#WelcomeSubtitle { color: #a2b5c8; font-size: 12pt; }
#WelcomeCard { background: #0e1824; border: none; border-radius: 12px; }
#GraphToolbar { background: #0b131e; border: none; }
#NodePalette { background: #0b131e; border: none; }
#SceneViewport, #VisualGraphView { background: #04070c; }
QToolTip {
    color: #f4f9ff;
    background: #132333;
    border: 1px solid #d39b43;
    padding: 5px;
}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#0a1019"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#edf5ff"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#070d15"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#0b131e"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#132333"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#f4f9ff"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#edf5ff"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#131f2d"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#edf5ff"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffca72"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#17627c"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#48d7ff"))
    palette.setColor(QPalette.ColorRole.LinkVisited, QColor("#f0b85d"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#6f8194"))
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Text,
        QColor("#5f6f81"),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor("#5f6f81"),
    )
    app.setPalette(palette)
    app.setStyleSheet(STYLE_SHEET)


__all__ = ["STYLE_SHEET", "apply_theme"]
