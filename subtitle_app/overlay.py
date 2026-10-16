from __future__ import annotations

import time
from PySide6.QtCore import Qt, QRectF, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter
from PySide6.QtWidgets import QWidget

from . import windows


class SubtitleOverlay(QWidget):
    def __init__(self, settings, parent=None):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.settings = settings
        self.target = None
        self.source = self.translation = ""
        self.bounds = None
        self.safe = windows.exclude_from_capture(int(self.winId()))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.follow)
        self.timer.start(80)
        self.visible_since = 0.0

    def set_player(self, player):
        self.target = player
        self.follow()

    def set_caption(self, source, translated, bounds):
        self.source, self.translation, self.bounds = source, translated, bounds
        self.visible_since = time.monotonic()
        self.follow()

    def clear_caption(self):
        self.source = self.translation = ""
        self.hide()

    def follow(self):
        if (not self.safe or not self.target or not self.translation
            or not windows.foreground(self.target.hwnd) or windows.user.IsIconic(self.target.hwnd)):
            self.hide()
            return
        rect = windows.client_rect(self.target.hwnd)
        if not rect:
            self.clear_caption()
            return
        if not self.isVisible():
            self.show()
        windows.place_overlay(int(self.winId()), rect)
        self.update()

    def paintEvent(self, event):
        if not self.translation:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont("Microsoft YaHei UI")
        font.setPixelSize(self.settings.font_size)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        metrics = QFontMetricsF(font)
        bilingual = self.settings.subtitle_mode == "Bilingual"
        content = self.translation + ("\n" + self.source if bilingual else "")
        flags = Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap
        max_width = self.width() * .88
        measured = metrics.boundingRect(QRectF(0, 0, max_width - 36, self.height()), flags, content)
        dpr = self.devicePixelRatioF()
        source_width = (self.bounds[2] - self.bounds[0]) / dpr + 40 if self.bounds else 0
        width = min(max_width, max(source_width, measured.width() + 40, 180))
        height = min(self.height() * .52, measured.height() + 22)
        delta = (12 - self.settings.bottom) / 100 * self.height()
        if self.bounds:
            bottom = self.bounds[3] / dpr + 12 + delta
            height = max(height, (self.bounds[3] - self.bounds[1]) / dpr + 22)
        else:
            bottom = self.height() * (1 - self.settings.bottom / 100)
        top = max(6, min(self.height() - height - 6, bottom - height))
        center = (self.bounds[0] + self.bounds[2]) / (2 * dpr) if self.bounds else self.width() / 2
        left = max(6, min(self.width() - width - 6, center - width / 2))
        box = QRectF(left, top, width, height)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(8, 10, 15, 255))
        painter.drawRoundedRect(box, 8, 8)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(box.adjusted(18, 8, -18, -8), flags, content)
