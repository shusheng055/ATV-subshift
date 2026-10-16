from __future__ import annotations

import ctypes

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap, QPolygon
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import (QApplication, QComboBox, QDoubleSpinBox, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPlainTextEdit, QPushButton, QScrollArea,
    QSlider, QVBoxLayout, QWidget, QTabWidget)

from .pipeline import Pipeline
from . import __version__
from .settings import ROOT, Settings
from .translation import LANGUAGES, TranslationError, validate_api
from .api_widgets import ApiPanel
from .credentials import CredentialStore
from .presets import active_terms
from .preset_widgets import PresetManager


def app_icon():
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#3087ff"))
    painter.drawRoundedRect(2, 2, 60, 60, 15, 15)
    painter.setBrush(QColor("white"))
    painter.drawPolygon(QPolygon([QPoint(25, 18), QPoint(25, 46), QPoint(47, 32)]))
    painter.end()
    return QIcon(pixmap)


def label(text, name="", wrap=False):
    result = QLabel(text)
    result.setObjectName(name)
    result.setWordWrap(wrap)
    return result


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._initializing = True
        self.settings = Settings.load()
        self.credentials = CredentialStore(self.settings.api_url)
        self.setWindowTitle("ATV subshift")
        self.setWindowIcon(app_icon())
        self.resize(900, 910)
        self.setMinimumSize(760, 650)
        self.pipeline = Pipeline(self)
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self.save)
        self.closing = False
        self.test_hwnd = 0
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.setCentralWidget(scroll)
        content = QWidget()
        content.setObjectName("surface")
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(38, 22, 38, 22)
        layout.setSpacing(16)

        header = QHBoxLayout()
        mark = QLabel()
        mark.setPixmap(app_icon().pixmap(28, 28))
        header.addWidget(mark)
        header.addWidget(label("ATV subshift", "brand"))
        header.addStretch()
        self.theme = QPushButton()
        self.theme.setObjectName("theme")
        self.theme.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme.clicked.connect(self.toggle_theme)
        header.addWidget(self.theme)
        layout.addLayout(header)

        hero = QVBoxLayout()
        hero.setSpacing(7)
        eyebrow = label(f"SUBTITLE TRANSLATOR  /  {__version__}", "eyebrow")
        eyebrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero.addWidget(eyebrow)
        self.headline = label("英文字幕  →  简体中文", "headline")
        self.headline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero.addWidget(self.headline)
        subtitle = label("内置离线翻译，点击开始。让字幕跟上你的观看。", "muted")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero.addWidget(subtitle)
        layout.addLayout(hero)

        action = QHBoxLayout()
        self.badge = label("●  Stopped", "badge")
        self.badge.setFixedWidth(116)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        action.addWidget(self.badge)
        self.status = label("先在 Apple TV 中开启 English / English CC 字幕。", "status", True)
        action.addWidget(self.status, 1)
        self.start_button = QPushButton("▶  Start · 开始翻译")
        self.start_button.setObjectName("primary")
        self.start_button.setMinimumSize(192, 48)
        self.start_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_button.clicked.connect(self.toggle_running)
        action.addWidget(self.start_button)
        layout.addLayout(action)

        self.pages = QTabWidget()
        self.pages.setObjectName('mainTabs')
        main_page = QWidget()
        page = QVBoxLayout(main_page)
        page.setContentsMargins(0, 12, 0, 0)
        page.setSpacing(14)
        self.pages.addTab(main_page, '翻译')
        self.preset_manager = PresetManager(self.settings.term_presets, self.settings.hotword_weight)
        self.weight = self.preset_manager.weight
        self.pages.addTab(self.preset_manager, '词汇预设')
        layout.addWidget(self.pages)

        translation = self.card(page)
        top = QHBoxLayout()
        top.addWidget(label("翻译", "section"))
        top.addStretch()
        top.addWidget(label("模式", "muted"))
        self.mode = QComboBox()
        self.mode.addItems(["Local", "API"])
        self.mode.setCurrentText(self.settings.mode)
        self.mode.setFixedWidth(130)
        top.addWidget(self.mode)
        translation.addLayout(top)
        languages = QHBoxLayout()
        languages.addWidget(label("From", "muted"))
        self.source = QComboBox()
        self.target = QComboBox()
        for code, title in LANGUAGES.items():
            self.source.addItem(title, code)
            self.target.addItem(title, code)
        self.source.setCurrentIndex(max(0, self.source.findData(self.settings.source)))
        self.target.setCurrentIndex(max(0, self.target.findData(self.settings.target)))
        languages.addWidget(self.source, 1)
        languages.addWidget(label("→", "muted"))
        languages.addWidget(label("To", "muted"))
        languages.addWidget(self.target, 1)
        translation.addLayout(languages)
        self.local_note = label("本地模型 · English → 简体中文 · CPU int8 · 无需联网", "small")
        translation.addWidget(self.local_note)
        self.api_panel = ApiPanel(self.settings, self.credentials)
        self.api_url, self.api_key = self.api_panel.url, self.api_panel.key
        translation.addWidget(self.api_panel)

        display = self.card(page)
        row = QHBoxLayout()
        row.addWidget(label("字幕显示", "section"))
        row.addStretch()
        self.subtitle_mode = QComboBox()
        self.subtitle_mode.addItem("Translated · 仅译文", "Translated")
        self.subtitle_mode.addItem("Bilingual · 双语", "Bilingual")
        self.subtitle_mode.setCurrentIndex(max(0, self.subtitle_mode.findData(self.settings.subtitle_mode)))
        row.addWidget(self.subtitle_mode)
        display.addLayout(row)
        sliders = QGridLayout()
        self.size = QSlider(Qt.Orientation.Horizontal)
        self.size.setRange(18, 52)
        self.size.setValue(self.settings.font_size)
        self.size_value = label(f"{self.settings.font_size} px", "muted")
        self.size_value.setFixedWidth(46)
        self.position = QSlider(Qt.Orientation.Horizontal)
        self.position.setRange(4, 32)
        self.position.setValue(self.settings.bottom)
        self.position_value = label(str(self.settings.bottom), "muted")
        self.position_value.setFixedWidth(46)
        sliders.addWidget(label("字号", "muted"), 0, 0)
        sliders.addWidget(self.size, 0, 1)
        sliders.addWidget(self.size_value, 0, 2)
        sliders.addWidget(label("位置 ↑", "muted"), 0, 3)
        sliders.addWidget(self.position, 0, 4)
        sliders.addWidget(self.position_value, 0, 5)
        sliders.setColumnStretch(1, 1)
        sliders.setColumnStretch(4, 1)
        sliders.setHorizontalSpacing(12)
        display.addLayout(sliders)
        self.size.setEnabled(False)
        self.position.setEnabled(False)
        display.addWidget(label("使用 Apple TV 原生字幕显示；字号与位置在播放器中调整。已保存的显示偏好会保留。", "small", True))

        terms = self.card(page)
        title = QHBoxLayout()
        self.term_summary = label(self.preset_manager.summary(), 'small', True)
        title.addWidget(self.term_summary, 1)
        title.addStretch()
        self.manage_terms = QPushButton('管理词汇预设 →')
        self.manage_terms.clicked.connect(lambda: self.pages.setCurrentIndex(1))
        title.addWidget(self.manage_terms)
        terms.addLayout(title)

        preview = self.card(page)
        preview_header = QHBoxLayout()
        preview_header.addWidget(label("实时预览", "section"))
        preview_header.addStretch()
        self.metrics = label("等待字幕", "small")
        preview_header.addWidget(self.metrics)
        preview.addLayout(preview_header)
        columns = QHBoxLayout()
        columns.setSpacing(16)
        self.source_preview = self.preview_column(columns, "识别原文", "识别到的字幕会出现在这里")
        self.result_preview = self.preview_column(columns, "翻译结果", "译文将在这里显示", "result")
        preview.addLayout(columns)
        self.resources = label('内存监测准备中', 'small')
        preview.addWidget(self.resources)

        footer = QHBoxLayout()
        footer.addWidget(label("设置自动保存 · 无需账户", "small"))
        footer.addStretch()
        footer.addWidget(label("受保护画面可能无法捕获，本应用不绕过 DRM。", "small"))
        layout.addLayout(footer)
        layout.addStretch()

        self.config_controls = [self.mode, self.source, self.target, self.api_panel, self.preset_manager]
        self.mode.currentTextChanged.connect(self.mode_changed)
        for widget in (self.source, self.target):
            widget.currentIndexChanged.connect(self.defer_save)
        self.subtitle_mode.currentIndexChanged.connect(self.display_changed)
        self.size.valueChanged.connect(self.display_changed)
        self.position.valueChanged.connect(self.display_changed)
        self.api_panel.changed.connect(self.defer_save)
        self.preset_manager.changed.connect(self.terms_changed)
        self.pipeline.status.connect(self.status.setText)
        self.pipeline.state.connect(self.running_changed)
        self.pipeline.preview.connect(self.show_preview)
        self.pipeline.metrics.connect(self.metrics.setText)
        self.pipeline.resources.connect(self.resources.setText)
        self.mode_changed()
        self.apply_theme()
        self._initializing = False

    def card(self, layout):
        frame = QFrame()
        frame.setObjectName("card")
        inside = QVBoxLayout(frame)
        inside.setContentsMargins(20, 15, 20, 15)
        inside.setSpacing(10)
        layout.addWidget(frame)
        return inside

    def preview_column(self, layout, title, placeholder, name="preview"):
        column = QVBoxLayout()
        column.setSpacing(5)
        column.addWidget(label(title, "small"))
        value = label(placeholder, name, True)
        value.setTextFormat(Qt.TextFormat.PlainText)
        value.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        value.setMinimumHeight(54)
        value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        column.addWidget(value)
        layout.addLayout(column, 1)
        return value

    def mode_changed(self, *_):
        local = self.mode.currentText() == "Local"
        self.api_panel.setVisible(not local)
        self.local_note.setVisible(local)
        self.source.setEnabled(not local and not self.pipeline.running)
        self.target.setEnabled(not local and not self.pipeline.running)
        if local:
            self.source.setCurrentIndex(self.source.findData("en"))
            self.target.setCurrentIndex(self.target.findData("zh-Hans"))
        self.defer_save()

    def collect(self):
        presets = self.preset_manager.values()
        hotwords, keep_words = active_terms(presets)
        return Settings(mode=self.mode.currentText(), source=self.source.currentData(), target=self.target.currentData(),
                        **self.api_panel.values(),
                        subtitle_mode=self.subtitle_mode.currentData(), font_size=self.size.value(),
                        bottom=self.position.value(), theme=self.settings.theme,
                        hotwords=hotwords, hotword_weight=self.weight.value(), keep_words=keep_words,
                        term_presets=presets)

    def terms_changed(self):
        self.term_summary.setText(self.preset_manager.summary())
        self.defer_save()

    def defer_save(self, *_):
        if self._initializing:
            return
        self.save_timer.start(500)

    def save(self):
        try:
            self.settings = self.collect()
            self.api_panel.save_keys()
            self.settings.save()
            source_title = "英文字幕" if self.settings.source == "en" else LANGUAGES[self.settings.source]
            self.headline.setText(f"{source_title}  →  {LANGUAGES[self.settings.target]}")
            return True
        except (OSError, ValueError):
            self.status.setText("设置保存失败，请检查本机用户目录权限。")
            return False

    def display_changed(self, *_):
        self.pipeline.set_subtitle_mode(self.subtitle_mode.currentData())
        self.size_value.setText(f"{self.size.value()} px")
        self.position_value.setText(str(self.position.value()))
        self.defer_save()

    def toggle_running(self):
        if self.pipeline.running:
            self.pipeline.stop()
            return
        if not self.save():
            return
        if self.settings.mode == "API":
            try:
                validate_api(self.settings)
                if self.settings.source == self.settings.target:
                    raise TranslationError("From 与 To 请使用不同语言。")
            except TranslationError as exc:
                self.status.setText(str(exc))
                return
        self.pipeline.start(self.settings, self.api_key.text(), test_hwnd=self.test_hwnd)

    def running_changed(self, running):
        self.start_button.setText("■  Stop · 停止翻译" if running else "▶  Start · 开始翻译")
        self.badge.setText("●  Running" if running else "●  Stopped")
        self.badge.setProperty("running", running)
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)
        for control in self.config_controls:
            control.setEnabled(not running)
        if not running:
            self.mode_changed()
            self.metrics.setText("已停止")

    def show_preview(self, source, result):
        self.source_preview.setText(source or "识别到的字幕会出现在这里")
        self.result_preview.setText(result or "译文将在这里显示")

    def toggle_theme(self):
        self.settings.theme = "light" if self.settings.theme == "dark" else "dark"
        self.apply_theme()
        self.defer_save()

    def apply_theme(self):
        dark = self.settings.theme == "dark"
        bg, card, field = ("#0f141e", "#171e2b", "#101722") if dark else ("#f4f7fc", "#ffffff", "#f8faff")
        fg, muted, border = ("#f0f4fc", "#97a6bc", "#2b3648") if dark else ("#111b32", "#69758d", "#dce4f0")
        down = (ROOT / "assets" / "chevron-down.svg").as_posix()
        up = (ROOT / "assets" / "chevron-up.svg").as_posix()
        self.theme.setText("☀  浅色模式" if dark else "☾  深色模式")
        self.setStyleSheet(f"""
            QWidget {{ font-family: 'Microsoft YaHei UI'; font-size: 13px; color: {fg}; }}
            QMainWindow, QScrollArea, QWidget#surface {{ background: {bg}; }}
            QLabel {{ background: transparent; }}
            QLabel#brand {{ font-size: 17px; font-weight: 600; }}
            QLabel#eyebrow {{ font-size: 10px; letter-spacing: 2px; color: {muted}; margin-top: 5px; }}
            QLabel#headline {{ font-size: 31px; font-weight: 700; margin: 3px 0; }}
            QLabel#muted, QLabel#status {{ color: {muted}; }}
            QLabel#small {{ color: {muted}; font-size: 11px; }}
            QLabel#section {{ font-size: 14px; font-weight: 600; }}
            QLabel#badge {{ background: {field}; border: 1px solid {border}; border-radius: 15px;
                           color: {muted}; padding: 7px 0; font-size: 12px; }}
            QLabel#badge[running="true"] {{ background: {'#133c31' if dark else '#e3f7ed'}; color: {'#62d6a3' if dark else '#168b58'}; border-color: transparent; }}
            QFrame#card {{ background: {card}; border: 1px solid {border}; border-radius: 13px; }}
            QTabWidget::pane {{ border: none; background: transparent; }}
            QTabBar::tab {{ background: transparent; color: {muted}; padding: 9px 18px; border-bottom: 2px solid transparent; }}
            QTabBar::tab:selected {{ color: {fg}; border-bottom: 2px solid #4a95ff; }}
            QFrame#presetDrawer {{ background: {card}; border: 1px solid {border}; border-radius: 12px; }}
            QScrollArea#presetScroll, QWidget#presetList {{ background: {bg}; }}
            QScrollArea#tagArea, QWidget#tagSurface {{ background: {card}; }}
            QFrame#termChip {{ background: {field}; border: 1px solid {border}; border-radius: 5px; }}
            QFrame#termChip QLabel {{ font-size: 12px; }}
            QToolButton {{ background: transparent; color: {muted}; border: none; padding: 3px 5px; }}
            QToolButton:hover {{ color: {fg}; background: {border}; border-radius: 4px; }}
            QToolButton#removeTerm {{ font-size: 14px; padding: 0 3px; }}
            QLineEdit#presetName {{ background: transparent; border: 1px solid transparent; font-weight: 600; }}
            QLineEdit#presetName:focus {{ border-color: #4a95ff; background: {field}; }}
            QPushButton#presetSwitch {{ padding: 4px 8px; border-radius: 12px; color: {muted}; }}
            QPushButton#presetSwitch:checked {{ background: #2e83f4; border-color: #2e83f4; color: white; }}
            QLineEdit, QComboBox, QPlainTextEdit, QDoubleSpinBox {{ background: {field}; border: 1px solid {border};
                           border-radius: 7px; padding: 7px 10px; selection-background-color: #287df0; }}
            QPlainTextEdit {{ padding: 5px 8px; font-size: 12px; }}
            QComboBox::drop-down {{ border: none; width: 24px; }}
            QComboBox::down-arrow {{ image: url("{down}"); width: 10px; height: 7px; }}
            QDoubleSpinBox::up-arrow {{ image: url("{up}"); width: 8px; height: 5px; }}
            QDoubleSpinBox::down-arrow {{ image: url("{down}"); width: 8px; height: 5px; }}
            QComboBox QAbstractItemView {{ background: {card}; selection-background-color: #287df0; }}
            QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border: 1px solid #4a95ff; }}
            QWidget:disabled {{ color: {'#68758a' if dark else '#9fa8b6'}; }}
            QPushButton {{ background: {card}; border: 1px solid {border}; border-radius: 8px; padding: 8px 14px; }}
            QPushButton:hover {{ border-color: #4a95ff; }}
            QPushButton#theme {{ color: {muted}; font-size: 11px; padding: 6px 10px; }}
            QPushButton#primary {{ background: #2e83f4; color: white; border: none; font-size: 14px; font-weight: 600; }}
            QPushButton#primary:hover {{ background: #4796ff; }}
            QPushButton#primary:pressed {{ background: #216bd0; }}
            QSlider::groove:horizontal {{ height: 4px; border-radius: 2px; background: {border}; }}
            QSlider::sub-page:horizontal {{ background: #3c8cf6; border-radius: 2px; }}
            QSlider::handle:horizontal {{ width: 14px; margin: -5px 0; background: #77b1ff; border-radius: 7px; }}
            QLabel#preview {{ font-size: 14px; line-height: 1.5; }}
            QLabel#result {{ font-size: 15px; color: {'#9cc6ff' if dark else '#2365c2'}; font-weight: 500; }}
            QScrollBar:vertical {{ background: {bg}; width: 8px; margin: 0; }}
            QScrollBar::handle:vertical {{ background: {border}; border-radius: 4px; min-height: 30px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)
        try:
            dwm = ctypes.WinDLL("dwmapi")
            enabled = ctypes.c_int(int(dark))
            dwm.DwmSetWindowAttribute(ctypes.c_void_p(int(self.winId())), 20, ctypes.byref(enabled), 4)
        except OSError:
            pass

    def closeEvent(self, event):
        if not self.closing:
            self.closing = True
            self.save_timer.stop()
            self.save()
            self.pipeline.stop()
        # Workers are cooperative. Never destroy Qt signal objects while a worker can emit.
        if self.pipeline.busy():
            event.ignore()
            self.status.setText("正在结束后台任务…")
            self.start_button.setEnabled(False)
            QTimer.singleShot(100, self.close)
        else:
            event.accept()
