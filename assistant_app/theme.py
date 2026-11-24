STYLE = """
QMainWindow, QWidget#workspace, QDialog, QScrollArea { background: #212121; color: #ececec; border: 0; }
QWidget#sidebar { background: #171717; border-right: 1px solid #292929; }
QLabel, QCheckBox, QGroupBox { color: #ececec; }
QLabel#muted { color: #a8a8a8; }
QPushButton, QToolButton { background: #303030; color: #ededed; border: 1px solid #444;
                           padding: 6px 10px; border-radius: 7px; }
QToolButton#circle { background: #252525; border-color: #363636; padding: 0; border-radius: 15px; }
QToolButton::menu-indicator { image: none; }
QToolButton#circle:hover, QPushButton:hover { background: #3a3a3a; }
QPushButton:disabled, QToolButton:disabled { color: #777; }
QPushButton:focus-visible, QToolButton:focus-visible { border-color: #a0a0a0; }
QTextBrowser, QPlainTextEdit, QLineEdit, QComboBox, QListWidget {
    background: #272727; color: #ececec; border: 1px solid #404040; border-radius: 7px;
    padding: 6px; selection-background-color: #525252; selection-color: #ffffff;
}
QTextBrowser#journal { background: transparent; border: 0; padding: 3px 8px; }
QListWidget#chats { border: 0; background: transparent; padding: 0; outline: 0; }
QListWidget::item { padding: 7px 8px; margin: 1px 0; border-radius: 7px; }
QListWidget::item:hover { background: #292929; }
QListWidget::item:selected { background: #303030; color: #ffffff; }
QComboBox#profile { background: transparent; border: 0; padding-left: 5px; }
QComboBox QAbstractItemView, QMenu { background: #292929; color: #ededed; selection-background-color: #434343; }
QMenu::item { padding: 7px 22px; }
QMenu::item:selected { background: #404040; }
QMenu::item:disabled { color: #818181; }
QMenu::separator { height: 1px; background: #484848; margin: 3px 7px; }
QGroupBox { border: 1px solid #414141; border-radius: 8px; margin-top: 12px; padding: 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }
QScrollBar::handle:vertical { background: #505050; border-radius: 4px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""
