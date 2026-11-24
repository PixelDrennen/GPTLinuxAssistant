STYLE = """
QMainWindow, QWidget#workspace, QScrollArea { background: #10141e; color: #edf2ff; border: 0; }
QWidget#sidebar { background: #151b28; border-right: 1px solid #252e41; }
QWidget#voiceCard { background: #181f2e; border: 1px solid #293349; border-radius: 12px; }
QLabel, QCheckBox, QGroupBox { color: #e4ebfc; }
QLabel#appTitle { color: #f5f7ff; }
QLabel#muted { color: #a8b6cf; }
QLabel#state { background: #222d40; color: #c6d5eb; border-radius: 9px; padding: 6px 11px; }
QPushButton { background: #222d40; color: #edf2ff; border: 1px solid #334158;
             padding: 7px 10px; border-radius: 8px; }
QPushButton:hover { background: #2d3a51; border-color: #5b6e8b; }
QPushButton:checked { background: #30405d; color: #f2f6ff; }
QPushButton:disabled { background: #1a2232; color: #8491a8; border-color: #273249; }
QPushButton#primary { background: #84e1ce; color: #102922; border-color: #84e1ce; font-weight: bold; }
QPushButton#primary:hover { background: #a6eddc; }
QPushButton#primary:disabled { background: #203c3b; color: #b2d4d0; border-color: #345754; }
QTextBrowser, QPlainTextEdit, QLineEdit, QComboBox, QListWidget {
    background: #151c29; color: #eaf1ff; border: 1px solid #303c53; border-radius: 8px;
    padding: 7px; selection-background-color: #455e88; selection-color: #ffffff;
}
QTextBrowser#journal { padding: 12px; }
QListWidget#chats { border: 0; background: transparent; padding: 0; outline: 0; }
QListWidget::item { padding: 10px; margin: 2px 0; border-radius: 7px; }
QListWidget::item:hover { background: #233047; }
QListWidget::item:selected { background: #304364; color: #ffffff; }
QComboBox QAbstractItemView, QMenu { background: #222d40; color: #edf2ff; selection-background-color: #3b5274; }
QGroupBox { background: #181f2e; border: 1px solid #303c53; border-radius: 10px; margin-top: 12px; padding: 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }
QScrollBar:vertical { background: #151c29; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #4a5972; border-radius: 4px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""
