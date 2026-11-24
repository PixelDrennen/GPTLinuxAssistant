"""Compact signal history for the current microphone and playback streams."""
from collections import deque

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import QWidget


class VoiceMeter(QWidget):
    def __init__(self, name, color, *, compact=False):
        super().__init__()
        self.setAccessibleName(name)
        self.color = QColor(color)
        self.samples = deque([0.0] * 32, maxlen=32)
        self.height_hint = 15 if compact else 35
        self.setMinimumHeight(self.height_hint)

    def sizeHint(self):
        return QSize(70, self.height_hint)

    def sample(self, amount):
        self.samples.append(amount)
        self.update()

    def clear(self):
        self.samples = deque([0.0] * 32, maxlen=32)
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setPen(Qt.NoPen)
        step = self.width() / len(self.samples)
        for index, amount in enumerate(self.samples):
            height = max(3, int((self.height() - 4) * amount))
            color = QColor(self.color)
            color.setAlpha(245 if amount > 0.02 else 90)
            painter.setBrush(color)
            painter.drawRoundedRect(int(step * index), (self.height() - height) // 2,
                                    max(1, int(step) - 2), height, 1, 1)
