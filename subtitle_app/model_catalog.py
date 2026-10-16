"""Reviewed provider catalog. No network calls on startup or when browsing models.

IDs and lifecycle sources are recorded in MODEL-CATALOG.md. Sunset dates are
exclusive: the option disappears on that date, including after an app restart.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

REVIEWED = '2026-10-14'


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    url: str
    note: str = ''


PROVIDERS = (
    Provider('openai', 'OpenAI', 'https://api.openai.com/v1'),
    Provider('gemini', 'Google Gemini', 'https://generativelanguage.googleapis.com/v1beta'),
    Provider('deepseek', 'DeepSeek', 'https://api.deepseek.com/v1'),
    Provider('claude', 'Anthropic Claude', 'https://api.anthropic.com/v1'),
    Provider('qwen', '阿里云 Qwen', '', '请粘贴百炼控制台的 Base URL（含业务空间与地域）；Key 须属于同一地域。'),
    Provider('kimi', 'Kimi / Moonshot', 'https://api.moonshot.ai/v1', '默认国际站；国内站可将 URL 改为 https://api.moonshot.cn/v1。'),
    Provider('custom', '自定义服务', '', '保留自定义 URL、模型名称与接口格式。'),
)


@dataclass(frozen=True)
class Model:
    provider: str
    id: str
    tier: str
    protocol: str = 'chat'
    sunset: str = ''
    note: str = ''
    options: tuple = ()

    def available(self, today: date | None = None):
        return not self.sunset or (today or date.today()).isoformat() < self.sunset

    @property
    def title(self):
        return f'{self.id} · {self.tier}'

    @property
    def description(self):
        return ' · '.join(s for s in (self.tier, self.note,
                         f'{self.sunset} 停用' if self.sunset else '') if s)


def _group(provider, ids, tier, protocol='chat', sunset='', note='', options=()):
    return [Model(provider, model, tier, protocol, sunset, note, options) for model in ids.split()]


MODELS = tuple(
    _group('openai', 'gpt-6-luna', '省钱', 'responses', options=(('reasoning', {'effort': 'none'}),)) +
    _group('openai', 'gpt-6.1-sol', '均衡', 'responses', options=(('reasoning', {'effort': 'low'}),)) +
    _group('openai', 'gpt-6-astra', '旗舰', 'responses', options=(('reasoning', {'effort': 'low'}),)) +
    _group('openai', 'gpt-6-sol gpt-5.6-sol gpt-5.6-terra gpt-5.6-luna gpt-5.5 gpt-5.4 gpt-5.4-mini gpt-5.2',
           '往代', 'responses') +
    _group('openai', 'gpt-5.5-pro gpt-5.4-pro gpt-5.2-pro', '往代 Pro', 'responses', note='高成本；推理可能较慢') +
    _group('openai', 'gpt-5.4-nano gpt-5.1', '往代', 'responses', '2027-04-01') +
    _group('openai', 'gpt-5 gpt-5-mini gpt-5-nano gpt-5-pro o3 o3-pro gpt-5-2025-08-07 gpt-5-mini-2025-08-07 gpt-5-nano-2025-08-07 gpt-5-pro-2025-10-06 o3-2025-04-16 o3-pro-2025-06-10',
           '往代', 'responses', '2026-12-11', '推理型号可能较慢') +
    _group('openai', 'gpt-4o gpt-4o-2024-08-06 gpt-4o-2024-11-20 gpt-4o-mini gpt-4o-mini-2024-07-18 gpt-4.1 gpt-4.1-2025-04-14 gpt-4.1-mini gpt-4.1-mini-2025-04-14',
           '经典', sunset='2027-01-14') +
    _group('openai', 'gpt-4o-2024-05-13 gpt-4.1-nano gpt-4.1-nano-2025-04-14', '经典', sunset='2026-10-23') +
    _group('openai', 'o1 o1-2024-12-17 o1-pro o1-pro-2025-03-19 o3-mini o3-mini-2025-01-31 o4-mini o4-mini-2025-04-16',
           '往代推理', 'responses', '2026-10-23', '推理型号可能较慢') +
    _group('gemini', 'gemini-3.5-flash-lite', '省钱', 'gemini') +
    _group('gemini', 'gemini-4-argon', '旗舰', 'gemini', note='使用 low 思考；复杂字幕可能较慢',
           options=(('generationConfig', {'maxOutputTokens': 32768, 'thinkingConfig': {'thinkingLevel': 'low'}}),)) +
    _group('gemini', 'gemini-3.8-flash', '高质量', 'gemini') +
    _group('gemini', 'gemini-3.6-flash', '均衡', 'gemini') +
    _group('gemini', 'gemini-3.1-pro-preview', '旗舰预览', 'gemini', note='预览版；推理可能较慢') +
    _group('gemini', 'gemini-3-flash-preview', '往代预览', 'gemini') +
    _group('gemini', 'gemini-3.1-flash-lite', '往代省钱', 'gemini', '2027-05-07') +
    _group('gemini', 'gemini-2.5-pro gemini-2.5-flash gemini-2.5-flash-lite', '经典', 'gemini', note='仅限曾使用过此型号的账户') +
    _group('deepseek', 'deepseek-flash', '省钱', options=(('thinking', {'type': 'disabled'}),)) +
    _group('deepseek', 'deepseek-v4-pro', '旗舰', options=(('thinking', {'type': 'disabled'}),)) +
    _group('claude', 'claude-haiku-5-5', '省钱', 'messages') +
    _group('claude', 'claude-sonnet-5-5', '均衡', 'messages') +
    _group('claude', 'claude-opus-5-5', '旗舰', 'messages') +
    _group('claude', 'claude-fable-5-1 claude-fable-5', '旗舰推理', 'messages', note='始终思考；实时字幕可能超时') +
    _group('claude', 'claude-mythos-5-1 claude-mythos-5 claude-mythos-preview', '受限访问', 'messages', note='需要服务商专门授权；可能较慢') +
    _group('claude', 'claude-opus-5 claude-opus-4-8 claude-opus-4-7 claude-opus-4-6 claude-opus-4-5-20251101 claude-sonnet-5 claude-sonnet-4-6 claude-haiku-4-5-20251001',
           '往代', 'messages') +
    _group('claude', 'claude-sonnet-4-5-20250929', '往代', 'messages', '2026-11-30') +
    _group('qwen', 'qwen-mt-lite', '省钱 · 专用翻译', 'qwen-mt') +
    _group('qwen', 'qwen-mt-flash', '均衡 · 专用翻译', 'qwen-mt') +
    _group('qwen', 'qwen-mt-plus', '高质量 · 专用翻译', 'qwen-mt') +
    _group('qwen', 'qwen3.8-flash', '省钱', options=(('enable_thinking', False),)) +
    _group('qwen', 'qwen3.7-plus', '均衡', options=(('enable_thinking', False),)) +
    _group('qwen', 'qwen3.8-max qwen3.8-max-0902', '旗舰', options=(('enable_thinking', False),)) +
    _group('qwen', 'qwen3.7-plus-2026-05-26 qwen3.7-flash qwen3.7-flash-2026-07-15 qwen3.7-max qwen3.7-max-preview qwen3.7-max-2026-06-08 qwen3.7-max-2026-05-20 qwen3.7-max-2026-05-17 qwen3.6-plus qwen3.6-plus-2026-04-02 qwen3.6-flash qwen3.6-flash-2026-04-16 qwen3.5-plus qwen3.5-plus-2026-02-15 qwen3.5-flash qwen3.5-flash-2026-02-23 qwen3.5-397b-a17b qwen3.5-122b-a10b qwen3.5-27b qwen3.5-35b-a3b qwen3-coder-flash qwen3-coder-flash-2025-07-28 qwen-plus qwen-flash',
           '往代', options=(('enable_thinking', False),)) +
    _group('qwen', 'qwen-max qwen-long', '经典') +
    _group('kimi', 'kimi-k2.6', '均衡', options=(('thinking', {'type': 'disabled'}),)) +
    _group('kimi', 'kimi-k3', '旗舰', options=(('reasoning_effort', 'low'),)) +
    _group('kimi', 'kimi-k2.7-code kimi-k2.7-code-highspeed', '编程型号', note='始终思考；优先选择通用型号，实时字幕可能超时')
)


def models_for(provider: str, query='', today: date | None = None):
    query = query.strip().casefold()
    return [m for m in MODELS if m.provider == provider and m.available(today)
            and query in f'{m.id} {m.description}'.casefold()]


def find_model(provider: str, model: str):
    return next((m for m in MODELS if m.provider == provider and m.id == model), None)


def provider_by_id(value: str):
    return next((p for p in PROVIDERS if p.id == value), PROVIDERS[-1])
