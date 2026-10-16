"""Shared term handling for local and API engines."""
from __future__ import annotations

from dataclasses import dataclass
import re
import time


@dataclass(frozen=True)
class Hotword:
    source: str
    target: str


def parse_hotwords(value: str) -> list[Hotword]:
    result = []
    for line in value.splitlines():
        line = line.strip()
        if not line:
            continue
        pair = re.split(r"\s*(?:=>|→|=)\s*", line, maxsplit=1)
        source, target = pair if len(pair) == 2 else ("", line)
        if target.strip():
            result.append(Hotword(source.strip(), target.strip()))
    return result


def contains(text: str, term: str):
    # Latin word boundaries keep `car` from matching `scar`; Chinese terms match substrings.
    left = r"(?<!\w)" if term and term[0].isascii() and term[0].isalnum() else ""
    right = r"(?!\w)" if term and term[-1].isascii() and term[-1].isalnum() else ""
    return bool(re.search(left + re.escape(term) + right, text, re.IGNORECASE))


def active_hotwords(words: list[Hotword], source: str):
    return [word for word in words if not word.source or contains(source, word.source)]


def choose_candidate(candidates: list[tuple[str, float]], words: list[Hotword], source: str, weight: float):
    active = active_hotwords(words, source)
    return max(candidates, key=lambda pair: pair[1] + weight * sum(contains(pair[0], word.target) for word in active))[0]


class TermTranslator:
    def __init__(self, engine, keep_words: str):
        self.engine = engine
        words = sorted(set(w.strip() for w in keep_words.splitlines() if w.strip()), key=len, reverse=True)
        # Split before inference, so protected text is never sent to either engine.
        patterns = []
        for word in words:
            left = r"(?<!\w)" if word[0].isascii() and word[0].isalnum() else ""
            right = r"(?!\w)" if word[-1].isascii() and word[-1].isalnum() else ""
            patterns.append(left + re.escape(word) + right)
        self.pattern = re.compile("(" + "|".join(patterns) + ")", re.IGNORECASE) if patterns else None

    def translate(self, text, cancelled=None, deadline=None):
        def check():
            if cancelled and cancelled():
                raise InterruptedError()
            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError()
        check()
        def translate_piece(piece):
            if getattr(self.engine, 'supports_cancellation', False):
                return self.engine.translate(piece, cancelled=cancelled, deadline=deadline)
            return self.engine.translate(piece)
        if not self.pattern:
            return translate_piece(text)
        pieces = self.pattern.split(text)
        result = []
        for i, piece in enumerate(pieces):
            check()
            if i % 2 or not any(c.isalpha() for c in piece):
                result.append(piece)
            else:
                leading = " " if piece[:1].isspace() else ""
                trailing = " " if piece[-1:].isspace() else ""
                result.append(leading + translate_piece(piece.strip()) + trailing)
        check()
        return "".join(result).strip()

    def translate_segment(self, text, context=(), allow_wait=False, cancelled=None, deadline=None):
        """API: one intact passage with validated placeholders, including protected history."""
        if not getattr(self.engine, 'supports_placeholders', False):
            # The bundled small model was not trained to preserve placeholder tokens.
            return self.translate(text, cancelled=cancelled, deadline=deadline)
        def check():
            if cancelled and cancelled():
                raise InterruptedError()
            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError()
        check()
        replacements = {}
        # Prevent literal subtitle text from impersonating a protected token.
        marker = re.compile(r'⟦ATV_KEEP_\d+⟧')
        pattern = re.compile(marker.pattern + (r'|' + self.pattern.pattern if self.pattern else ''),
                             re.IGNORECASE)
        def mask(match):
            token = f'⟦ATV_KEEP_{len(replacements)}⟧'
            replacements[token] = match[0]
            return token
        masked = pattern.sub(mask, text)
        # History needs masking too, but its tokens must not appear in the output.
        identities = {value.casefold(): token for token, value in replacements.items()}
        context_ids = {}
        def mask_context(match):
            identity = match[0].casefold()
            if identity in identities:
                return identities[identity]
            if identity not in context_ids:
                context_ids[identity] = f'⟦ATV_CONTEXT_{len(context_ids)}⟧'
            return context_ids[identity]
        masked_context = tuple(pattern.sub(mask_context, part) for part in context)
        result = self.engine.translate(masked, context=masked_context, allow_wait=allow_wait, segment=True,
                                       cancelled=cancelled, deadline=deadline)
        check()
        found = marker.findall(result)
        if sorted(found) != sorted(replacements) or re.search(r'⟦ATV_CONTEXT_\d+⟧', result):
            from .translation import TranslationError
            raise TranslationError("API 未完整保留词汇标记，本句保留原文。")
        remaining = marker.sub('', masked)
        if (result.strip() == masked.strip() and any(c.isalpha() for c in remaining)
                and self.engine.settings.source != self.engine.settings.target):
            from .translation import TranslationError
            raise TranslationError("API 原样返回了待译文本，本句保留原文。")
        # One substitution pass avoids accidentally replacing tokens inside restored text.
        return marker.sub(lambda match: replacements[match[0]], result)
