"""Chat transcript that follows new entries until the reader scrolls away."""
from base64 import b64decode, b64encode
from uuid import uuid4

from PyQt5.QtCore import QBuffer, QIODevice, QTimer, Qt, QUrl
from PyQt5.QtGui import QImage, QTextCursor, QTextDocument, QTextOption
from PyQt5.QtWidgets import QTextBrowser


class ChatJournal(QTextBrowser):
    def __init__(self):
        super().__init__()
        self.setObjectName("journal")
        self.setOpenLinks(False)
        self.setAccessibleName("Chat and activity")
        self.snapshots = {}
        self.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.follow_latest = True
        self.replacing_entries = False
        self.tail_timer = QTimer(self)
        self.tail_timer.setSingleShot(True)
        self.tail_timer.timeout.connect(self.scroll_to_latest)
        bar = self.verticalScrollBar()
        bar.valueChanged.connect(self.reading_position_changed)
        bar.rangeChanged.connect(self.queue_scroll_to_latest)

    @staticmethod
    def encode_frames(frames):
        attachments = []
        for frame in (frames,) if isinstance(frames, bytes) else frames:
            image = QImage.fromData(frame)
            if image.isNull():
                continue
            if image.width() > 1440 or image.height() > 1000:
                image = image.scaled(1440, 1000, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            buffer = QBuffer()
            buffer.open(QIODevice.WriteOnly)
            if image.save(buffer, "JPEG", 82):
                attachments.append([uuid4().hex, b64encode(bytes(buffer.data())).decode("ascii")])
        return attachments

    def image_html(self, attachments):
        html = []
        for key, encoded in attachments:
            image = QImage.fromData(b64decode(encoded))
            if image.isNull():
                continue
            url = QUrl("assistant-snapshot:" + key)
            width = min(image.width(), 430)
            height = round(image.height() * width / image.width())
            self.snapshots[key] = image
            self.document().addResource(QTextDocument.ImageResource, url, image)
            html.append(f'<p><a href="{url.toString()}"><img src="{url.toString()}" '
                        f'width="{width}" height="{height}" alt="Captured screen"></a></p>')
        return "".join(html)

    def set_entries(self, html):
        self.replacing_entries = True
        try:
            self.setHtml(html)
        finally:
            self.replacing_entries = False
        self.follow_latest = True
        self.queue_scroll_to_latest()

    def append_entry(self, html):
        # Write with a separate cursor so the reader keeps their selection and position.
        cursor = QTextCursor(self.document())
        cursor.movePosition(QTextCursor.End)
        if not self.document().isEmpty():
            cursor.insertBlock()
        cursor.insertHtml(html)
        self.queue_scroll_to_latest()

    def reading_position_changed(self, value):
        if not self.replacing_entries:
            self.follow_latest = value >= self.verticalScrollBar().maximum() - 2

    def queue_scroll_to_latest(self):
        if self.follow_latest and not self.tail_timer.isActive():
            self.tail_timer.start(0)

    def scroll_to_latest(self):
        if self.follow_latest:
            bar = self.verticalScrollBar()
            bar.setValue(bar.maximum())

    def showEvent(self, event):
        super().showEvent(event)
        self.queue_scroll_to_latest()
