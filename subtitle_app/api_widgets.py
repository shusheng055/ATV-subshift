"""Single-window API selector. Browsing/searching never contacts a provider."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QGridLayout, QVBoxLayout, QHBoxLayout, QComboBox, QLineEdit, QLabel

from .model_catalog import PROVIDERS, REVIEWED, models_for, find_model, provider_by_id
from .credentials import CredentialStore

PROTOCOLS = (('chat', 'OpenAI Chat Completions'), ('responses', 'OpenAI Responses'),
             ('messages', 'Anthropic Messages'), ('gemini', 'Google Gemini'), ('qwen-mt', 'Qwen 专用翻译'))


class ApiPanel(QWidget):
    changed = Signal()

    def __init__(self, settings, credentials: CredentialStore):
        super().__init__()
        self.credentials = credentials
        self._changing = True
        self._model = settings.api_model
        self.profiles = {k: dict(v) for k, v in settings.api_profiles.items() if isinstance(v, dict)}
        self._provider = settings.api_provider
        if self._provider not in {p.id for p in PROVIDERS}:
            self._provider = 'custom'
        # An old custom URL/model is kept exactly as it was. A new empty model
        # can use the OpenAI catalog without changing saved values on construction.
        if self._provider == 'custom' and not self._model and settings.api_url == PROVIDERS[0].url:
            self._provider = 'openai'
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setVerticalSpacing(8)
        self.provider = QComboBox()
        for item in PROVIDERS:
            self.provider.addItem(item.name, item.id)
        self.provider.setCurrentIndex(max(0, self.provider.findData(self._provider)))
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索模型名称 / 省钱 / 旗舰 / 经典…')
        self.models = QComboBox()
        self.models.setMinimumContentsLength(20)
        self.models.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.models.setMaxVisibleItems(12)
        self.custom_model = QLineEdit(self._model)
        self.custom_model.setPlaceholderText('自定义服务的模型 ID')
        self.model_note = QLabel()
        self.model_note.setObjectName('small')
        self.model_note.setWordWrap(True)
        self.model_note.setTextFormat(Qt.TextFormat.PlainText)
        selector = QWidget()
        column = QVBoxLayout(selector)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(7)
        column.addWidget(self.search)
        column.addWidget(self.models)
        column.addWidget(self.custom_model)
        column.addWidget(self.model_note)
        self.url = QLineEdit(settings.api_url)
        self.url.setPlaceholderText('从服务商控制台复制 Base URL')
        self._key_url = settings.api_url
        self.key = QLineEdit(credentials.get(self._key_url))
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText('API Key · 按服务地址分别加密保存')
        self.protocol = QComboBox()
        for value, name in PROTOCOLS:
            self.protocol.addItem(name, value)
        self.protocol.setCurrentIndex(max(0, self.protocol.findData(settings.api_protocol)))
        self.provider_note = QLabel()
        self.provider_note.setWordWrap(True)
        self.provider_note.setObjectName('small')
        self.provider_note.setTextFormat(Qt.TextFormat.PlainText)
        self.protocol_caption = None
        for row, (name, widget) in enumerate((('服务商', self.provider), ('模型', selector),
                                             ('URL', self.url), ('Key', self.key), ('接口', self.protocol))):
            caption = QLabel(name)
            caption.setObjectName('muted')
            if widget is self.protocol:
                self.protocol_caption = caption
            layout.addWidget(caption, row, 0, Qt.AlignmentFlag.AlignTop)
            layout.addWidget(widget, row, 1)
        layout.setColumnStretch(1, 1)
        layout.addWidget(self.provider_note, 5, 1)
        self._refresh_models()
        self._visibility()
        self.provider.currentIndexChanged.connect(self._provider_changed)
        self.search.textChanged.connect(self._refresh_models)
        self.models.activated.connect(self._model_selected)
        self.custom_model.textChanged.connect(self._custom_changed)
        self.url.textChanged.connect(self._url_changed)
        self.key.textChanged.connect(self._emit)
        self.protocol.currentIndexChanged.connect(self._emit)
        self._changing = False

    def _emit(self, *_):
        if not self._changing:
            self.changed.emit()

    def _remember(self):
        self.profiles[self._provider] = {'url': self.url.text(), 'model': self._model,
                                         'protocol': self.protocol.currentData()}

    def _provider_changed(self, *_):
        if self._changing:
            return
        self._remember()
        self._changing = True
        self._provider = self.provider.currentData()
        provider = provider_by_id(self._provider)
        saved = self.profiles.get(self._provider, {})
        options = models_for(self._provider)
        self._model = saved.get('model', options[0].id if options else '')
        spec = find_model(self._provider, self._model)
        self.protocol.setCurrentIndex(max(0, self.protocol.findData(saved.get('protocol', spec.protocol if spec else 'chat'))))
        self.custom_model.setText(self._model)
        self.search.clear()
        # Even during a provider change, save the old key to its OLD URL first.
        self.url.setText(saved.get('url', provider.url))
        self._refresh_models()
        self._visibility()
        self._changing = False
        self.changed.emit()

    def _refresh_models(self, *_):
        self.models.blockSignals(True)
        self.models.clear()
        options = models_for(self._provider, self.search.text())
        for spec in options:
            self.models.addItem(spec.title, spec.id)
            self.models.setItemData(self.models.count() - 1, spec.description, Qt.ItemDataRole.ToolTipRole)
        self.models.setCurrentIndex(self.models.findData(self._model))
        self.models.setPlaceholderText('没有匹配项' if not options else '请选择翻译模型')
        self.models.blockSignals(False)
        self._update_note()

    def _model_selected(self, index):
        value = self.models.itemData(index)
        if not value:
            return
        self._model = value
        spec = find_model(self._provider, value)
        if spec:
            self.protocol.setCurrentIndex(self.protocol.findData(spec.protocol))
        self._update_note()
        self.changed.emit()

    def _custom_changed(self, value):
        if self._changing or self._provider != 'custom':
            return
        self._model = value
        self._update_note()
        self.changed.emit()

    def _update_note(self):
        spec = find_model(self._provider, self._model)
        if spec and not spec.available():
            text = '已保存型号已停用，请从列表重新选择。原配置仍保留。'
        elif spec:
            text = f'当前：{spec.id} · {spec.description}'
        elif self._model:
            text = f'当前：{self._model} · 已保留的自定义型号'
        else:
            text = '选择一个模型即可，无需填写型号名称。'
        self.model_note.setText(text)

    def _visibility(self):
        custom = self._provider == 'custom'
        self.search.setVisible(not custom)
        self.models.setVisible(not custom)
        self.custom_model.setVisible(custom)
        self.protocol.setEnabled(custom)
        self.protocol.setVisible(custom)
        self.protocol_caption.setVisible(custom)
        note = provider_by_id(self._provider).note
        self.provider_note.setText((note + '\n' if note else '') +
            f'目录核对：{REVIEWED} · 已知停用型号不显示；可用性取决于账户权限。')

    def _url_changed(self, *_):
        try:
            self.credentials.set(self._key_url, self.key.text())
        except OSError:
            self.model_note.setText('Key 保存失败；服务地址未应用，请检查本机用户目录。')
            self.url.blockSignals(True)
            self.url.setText(self._key_url)
            self.url.blockSignals(False)
            return
        self._key_url = self.url.text()
        self.key.setText(self.credentials.get(self._key_url))
        self._emit()

    def save_keys(self):
        self.credentials.set(self._key_url, self.key.text())

    def values(self):
        self._remember()
        return dict(api_provider=self._provider, api_model=self._model.strip(),
                    api_protocol=self.protocol.currentData(), api_url=self.url.text().strip(),
                    api_profiles={k: dict(v) for k, v in self.profiles.items()})
