"""Small desktop overlay for the assistant's current spoken reply."""
from time import monotonic

from PyQt5.QtCore import QRectF, Qt, QTimer
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import QWidget


class SpeechOverlay(QWidget):
    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                         Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self.setAccessibleName("Assistant speaking")
        self.setFixedSize(350, 44)
        self.text = ""
        self.level = 0.0
        self.started = 0.0
        self.drag_offset = None
        self.timer = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self.update)

    def begin(self, text):
        self.text = " ".join(text.split())
        self.level = 0.0
        self.started = monotonic()
        self.show()
        self.timer.start()

    def sample(self, amount):
        self.level = amount

    def end(self):
        self.timer.stop()
        self.hide()
        self.text = ""

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            handle = self.windowHandle()
            if not (handle and hasattr(handle, "startSystemMove") and handle.startSystemMove()):
                self.drag_offset = event.globalPos() - self.pos()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self.drag_offset)
            event.accept()

    def mouseReleaseEvent(self, _event):
        self.drag_offset = None

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#494949"), 1))
        painter.setBrush(QColor(32, 32, 32, 247))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 21, 21)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(220, 220, 220, 30 + int(self.level * 100)))
        painter.drawEllipse(QRectF(8, 7, 30, 30))
        painter.setPen(QPen(QColor(245, 245, 245, 170 + int(self.level * 85)), 1.5))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(QRectF(20, 14, 6, 11), 3, 3)
        painter.drawArc(QRectF(17, 16, 12, 13), 0, -180 * 16)
        painter.drawLine(23, 29, 23, 32)
        painter.drawLine(19, 32, 27, 32)

        visible_width = self.width() - 59
        text_width = painter.fontMetrics().horizontalAdvance(self.text)
        elapsed = max(0, monotonic() - self.started - 0.75)
        offset = min(max(0, text_width - visible_width), int(elapsed * 62))
        painter.setClipRect(46, 0, visible_width, self.height())
        painter.setPen(QColor("#f0f0f0"))
        painter.drawText(QRectF(46 - offset, 0, max(text_width + 3, visible_width), self.height()),
                         Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine, self.text)
