"""Accordion terminology presets, with wrapping tags and a compact editor."""
from dataclasses import replace

from PySide6.QtCore import Qt, Signal, QSize, QRect, QPoint, QTimer
from PySide6.QtWidgets import (QWidget, QLayout, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QPushButton, QToolButton, QLineEdit, QPlainTextEdit, QScrollArea, QTabWidget,
    QDoubleSpinBox, QSizePolicy)

from .presets import TermPreset, active_terms, entries, append_terms, remove_term


class FlowLayout(QLayout):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(6)

    def addItem(self, item): self.items.append(item)
    def count(self): return len(self.items)
    def itemAt(self, index): return self.items[index] if 0 <= index < len(self.items) else None
    def takeAt(self, index): return self.items.pop(index) if 0 <= index < len(self.items) else None
    def expandingDirections(self): return Qt.Orientation(0)
    def hasHeightForWidth(self): return True
    def heightForWidth(self, width): return self.arrange(QRect(0, 0, width, 0), True)
    def sizeHint(self): return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self.items:
            size = size.expandedTo(item.minimumSize())
        return size

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.arrange(rect, False)

    def arrange(self, rect, measure):
        x, y, row = rect.x(), rect.y(), 0
        for item in self.items:
            size = item.sizeHint()
            if x + size.width() > rect.right() + 1 and row:
                x, y, row = rect.x(), y + row + self.spacing(), 0
            if not measure:
                item.setGeometry(QRect(QPoint(x, y), size))
            x += size.width() + self.spacing()
            row = max(row, size.height())
        return y + row - rect.y()


class TermEditor(QWidget):
    changed = Signal(str)

    def __init__(self, raw, kind, parent=None):
        super().__init__(parent)
        self.raw, self.kind = raw, kind
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(8)
        self.scroll = QScrollArea()
        self.scroll.setObjectName('tagArea')
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.tags = QWidget()
        self.tags.setObjectName('tagSurface')
        self.flow = FlowLayout(self.tags)
        self.scroll.setWidget(self.tags)
        layout.addWidget(self.scroll)
        add_row = QHBoxLayout()
        self.input = QPlainTextEdit()
        self.input.setAccessibleName('添加热词' if kind == 'hotwords' else '添加不翻译词汇')
        self.input.setPlaceholderText('添加热词：track => 赛道（逗号或换行分隔）' if kind == 'hotwords'
                                      else '添加不翻译词汇（逗号或换行分隔）')
        self.input.setFixedHeight(52)
        self.input.setTabChangesFocus(True)
        add_row.addWidget(self.input, 1)
        self.add_button = QPushButton('＋ 添加')
        self.add_button.setAccessibleName('添加到热词' if kind == 'hotwords' else '添加到不翻译词汇')
        self.add_button.clicked.connect(self.add)
        add_row.addWidget(self.add_button)
        layout.addLayout(add_row)
        self.error = QLabel()
        self.error.setObjectName('small')
        self.error.setWordWrap(True)
        self.error.hide()
        layout.addWidget(self.error)
        self.rebuild()

    def rebuild(self):
        while self.flow.count():
            self.flow.takeAt(0).widget().deleteLater()
        for index, text in entries(self.raw):
            chip = QFrame()
            chip.setObjectName('termChip')
            row = QHBoxLayout(chip)
            row.setContentsMargins(8, 2, 4, 2)
            row.setSpacing(3)
            title = QLabel()
            title.setTextFormat(Qt.TextFormat.PlainText)
            title.setText(title.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, 270))
            title.setToolTip(text)
            row.addWidget(title)
            remove = QToolButton()
            remove.setText('×')
            remove.setObjectName('removeTerm')
            remove.setAccessibleName('移除词条 ' + text)
            remove.setToolTip('移除此词条')
            remove.clicked.connect(lambda _=False, i=index: self.remove(i))
            row.addWidget(remove)
            self.flow.addWidget(chip)
        if not entries(self.raw):
            empty = QLabel('暂无词条，在下方添加。')
            empty.setObjectName('small')
            self.flow.addWidget(empty)
        self.fit_tags()
        QTimer.singleShot(0, self.fit_tags)

    def fit_tags(self):
        height = self.flow.heightForWidth(max(240, self.scroll.viewport().width()))
        self.scroll.setFixedHeight(min(200, max(38, height + 8)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_tags()

    def add(self):
        try:
            raw = append_terms(self.raw, self.input.toPlainText())
        except ValueError as exc:
            self.error.setText(str(exc))
            self.error.show()
            return
        self.error.hide()
        self.input.clear()
        if raw != self.raw:
            self.raw = raw
            self.rebuild()
            self.changed.emit(raw)

    def remove(self, index):
        self.raw = remove_term(self.raw, index)
        self.rebuild()
        self.changed.emit(self.raw)


class PresetDrawer(QFrame):
    changed = Signal()
    removed = Signal(object)

    def __init__(self, preset, parent=None):
        super().__init__(parent)
        self.preset = replace(preset)
        self.setObjectName('presetDrawer')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        header = QHBoxLayout()
        self.expand = QToolButton()
        self.expand.setObjectName('drawerArrow')
        self.expand.setCheckable(True)
        self.expand.setChecked(preset.expanded)
        self.expand.setAccessibleName('展开或收起预设 ' + preset.name)
        header.addWidget(self.expand)
        self.enabled = QPushButton('启用' if preset.enabled else '停用')
        self.enabled.setObjectName('presetSwitch')
        self.enabled.setCheckable(True)
        self.enabled.setChecked(preset.enabled)
        self.enabled.setAccessibleName('启用预设 ' + preset.name)
        self.enabled.setFixedWidth(52)
        header.addWidget(self.enabled)
        self.name = QLineEdit(preset.name)
        self.name.setObjectName('presetName')
        self.name.setMaxLength(60)
        self.name.setAccessibleName('预设名称')
        self.name.setPlaceholderText('预设名称')
        header.addWidget(self.name, 1)
        self.count = QLabel()
        self.count.setObjectName('small')
        header.addWidget(self.count)
        remove = QToolButton()
        remove.setText('删除')
        remove.setAccessibleName('删除预设 ' + preset.name)
        remove.clicked.connect(lambda: self.removed.emit(self))
        header.addWidget(remove)
        layout.addLayout(header)
        self.body = QTabWidget()
        self.body.setObjectName('termTypes')
        self.hotwords = TermEditor(preset.hotwords, 'hotwords')
        self.keep_words = TermEditor(preset.keep_words, 'keep_words')
        self.body.addTab(self.hotwords, '热词')
        self.body.addTab(self.keep_words, '不翻译词汇')
        layout.addWidget(self.body)
        self.expand.toggled.connect(self.set_expanded)
        self.enabled.toggled.connect(self.set_enabled)
        self.name.textChanged.connect(self.rename)
        self.name.editingFinished.connect(self.finish_name)
        self.hotwords.changed.connect(lambda raw: self.set_terms('hotwords', raw))
        self.keep_words.changed.connect(lambda raw: self.set_terms('keep_words', raw))
        self.refresh()

    def refresh(self):
        hot, keep = len(entries(self.preset.hotwords)), len(entries(self.preset.keep_words))
        self.count.setText(f'{hot} 热词 / {keep} 不翻译')
        self.body.setTabText(0, f'热词  {hot}')
        self.body.setTabText(1, f'不翻译词汇  {keep}')
        self.body.setVisible(self.preset.expanded)
        self.expand.setText('▾' if self.preset.expanded else '▸')
        self.enabled.setText('启用' if self.preset.enabled else '停用')

    def set_expanded(self, value):
        self.preset.expanded = value
        self.refresh()
        self.changed.emit()

    def set_enabled(self, value):
        self.preset.enabled = value
        self.refresh()
        self.changed.emit()

    def rename(self, value):
        if value.strip():
            self.preset.name = value.strip()
            self.expand.setAccessibleName('展开或收起预设 ' + self.preset.name)
            self.enabled.setAccessibleName('启用预设 ' + self.preset.name)
            self.changed.emit()

    def finish_name(self):
        self.name.setText(self.preset.name)

    def set_terms(self, kind, raw):
        setattr(self.preset, kind, raw)
        self.refresh()
        self.changed.emit()


class PresetManager(QWidget):
    changed = Signal()

    def __init__(self, presets, weight, parent=None):
        super().__init__(parent)
        self.drawers, self.deleted = [], None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(12)
        header = QHBoxLayout()
        title = QLabel('按观看内容切换词表')
        title.setObjectName('section')
        header.addWidget(title)
        header.addStretch()
        header.addWidget(QLabel('热词权重'))
        self.weight = QDoubleSpinBox()
        self.weight.setRange(0, 5)
        self.weight.setDecimals(1)
        self.weight.setSingleStep(.5)
        self.weight.setValue(weight)
        self.weight.setFixedWidth(80)
        self.weight.setAccessibleName('热词权重')
        self.weight.setToolTip('仅对已启用预设中的热词加权，0 关闭。')
        header.addWidget(self.weight)
        layout.addLayout(header)
        note = QLabel('可同时启用多个预设。停用仅暂停使用，词条仍保留；更改后下次 Start 生效。')
        note.setObjectName('small')
        note.setWordWrap(True)
        layout.addWidget(note)
        create = QHBoxLayout()
        self.new_name = QLineEdit()
        self.new_name.setMaxLength(60)
        self.new_name.setPlaceholderText('预设名称，如：赛车、AI')
        self.new_name.setAccessibleName('新预设名称')
        create.addWidget(self.new_name, 1)
        self.add_button = QPushButton('＋ 新建预设')
        self.add_button.clicked.connect(self.add_preset)
        self.new_name.returnPressed.connect(self.add_preset)
        create.addWidget(self.add_button)
        layout.addLayout(create)
        self.scroll = QScrollArea()
        self.scroll.setObjectName('presetScroll')
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setMinimumHeight(320)
        content = QWidget()
        content.setObjectName('presetList')
        self.list_layout = QVBoxLayout(content)
        self.list_layout.setContentsMargins(0, 0, 6, 0)
        self.list_layout.setSpacing(12)
        self.empty = QLabel('还没有预设。新建一个分类，添加常用热词和不翻译词汇。')
        self.empty.setObjectName('small')
        self.empty.setWordWrap(True)
        self.list_layout.addWidget(self.empty)
        self.list_layout.addStretch()
        self.scroll.setWidget(content)
        layout.addWidget(self.scroll, 1)
        undo = QHBoxLayout()
        self.notice = QLabel()
        self.notice.setObjectName('small')
        self.notice.setWordWrap(True)
        undo.addWidget(self.notice, 1)
        self.undo_button = QPushButton('撤销删除')
        self.undo_button.clicked.connect(self.undo_delete)
        self.undo_button.hide()
        undo.addWidget(self.undo_button)
        layout.addLayout(undo)
        for preset in presets:
            self.insert(preset)
        self.weight.valueChanged.connect(self.changed)
        self.refresh()

    def values(self):
        return [replace(drawer.preset) for drawer in self.drawers]

    def refresh(self):
        self.empty.setVisible(not self.drawers)

    def insert(self, preset, index=None):
        drawer = PresetDrawer(preset)
        index = len(self.drawers) if index is None else index
        self.drawers.insert(index, drawer)
        self.list_layout.insertWidget(index + 1, drawer)
        drawer.changed.connect(self.changed)
        drawer.removed.connect(self.remove_preset)
        self.refresh()
        return drawer

    def add_preset(self):
        name = self.new_name.text().strip()
        if not name:
            self.new_name.setFocus()
            return
        if any(p.name.casefold() == name.casefold() for p in self.values()):
            self.notice.setText('已有同名预设，请使用不同名称。')
            return
        drawer = self.insert(TermPreset(name=name))
        self.new_name.clear()
        self.notice.clear()
        self.scroll.ensureWidgetVisible(drawer)
        self.changed.emit()

    def remove_preset(self, drawer):
        index = self.drawers.index(drawer)
        self.deleted = (index, replace(drawer.preset))
        self.drawers.remove(drawer)
        self.list_layout.removeWidget(drawer)
        drawer.deleteLater()
        self.notice.setText(f'已删除“{self.deleted[1].name}”。')
        self.undo_button.show()
        self.refresh()
        self.changed.emit()

    def undo_delete(self):
        if self.deleted:
            index, preset = self.deleted
            self.insert(preset, min(index, len(self.drawers)))
            self.deleted = None
            self.notice.setText('已恢复预设及全部词条。')
            self.undo_button.hide()
            self.changed.emit()

    def summary(self):
        enabled = [p for p in self.values() if p.enabled]
        hotwords, keep_words = active_terms(enabled)
        names = '、'.join(p.name for p in enabled) or '未启用预设'
        return f'{names}\n已启用 {len(enabled)} 个 · {len(entries(hotwords))} 热词 / {len(entries(keep_words))} 不翻译'
