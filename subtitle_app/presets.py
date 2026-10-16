"""Named, independently enabled terminology drawers; no translation engine state."""
from dataclasses import dataclass, field, asdict
import re
import uuid


@dataclass
class TermPreset:
    name: str = '新预设'
    enabled: bool = True
    hotwords: str = ''
    keep_words: str = ''
    expanded: bool = True
    id: str = field(default_factory=lambda: uuid.uuid4().hex)


def load_presets(raw, hotwords='', keep_words=''):
    """Migrate legacy strings verbatim. Broken preset data must not erase them."""
    if isinstance(raw, list):
        result, identities = [], set()
        for value in raw:
            if isinstance(value, TermPreset):
                value = asdict(value)
            if not isinstance(value, dict) or not isinstance(value.get('name'), str):
                continue
            preset = TermPreset(**{key: value[key] for key in TermPreset.__dataclass_fields__ if key in value})
            preset.name = preset.name.strip() or '未命名预设'
            preset.enabled = preset.enabled if isinstance(preset.enabled, bool) else True
            preset.expanded = preset.expanded if isinstance(preset.expanded, bool) else True
            preset.hotwords = preset.hotwords if isinstance(preset.hotwords, str) else ''
            preset.keep_words = preset.keep_words if isinstance(preset.keep_words, str) else ''
            if not isinstance(preset.id, str) or not preset.id or preset.id in identities:
                preset.id = uuid.uuid4().hex
            identities.add(preset.id)
            result.append(preset)
        if result or not raw:
            return result
    if hotwords or keep_words:
        return [TermPreset(name='默认词表', hotwords=hotwords, keep_words=keep_words, id='legacy-default')]
    return []


def active_terms(presets):
    def merge(key):
        groups = [getattr(p, key) for p in presets if p.enabled and getattr(p, key).strip()]
        # No normalization of an existing single dictionary during migration.
        if len(groups) <= 1:
            return groups[0] if groups else ''
        seen, result = set(), []
        for group in groups:
            for line in group.splitlines():
                identity = line.strip().casefold()
                if identity and identity not in seen:
                    result.append(line)
                    seen.add(identity)
        return '\n'.join(result)
    return merge('hotwords'), merge('keep_words')


def entries(raw):
    return [(index, line.strip()) for index, line in enumerate(raw.splitlines()) if line.strip()]


def append_terms(raw, text):
    seen = {line.casefold() for _, line in entries(raw)}
    added = []
    for value in re.split(r'[,，;；\r\n]+', text):
        value = value.strip()
        if value and value.casefold() not in seen:
            added.append(value)
            seen.add(value.casefold())
    if not added:
        return raw
    result = raw + ('\n' if raw and not raw.endswith(('\n', '\r')) else '') + '\n'.join(added)
    if len(result) > 6000:
        raise ValueError('每个预设的每类词表最多 6000 字符，请拆分到另一预设。')
    return result


def remove_term(raw, index):
    lines = raw.splitlines(keepends=True)
    return ''.join(line for i, line in enumerate(lines) if i != index)
