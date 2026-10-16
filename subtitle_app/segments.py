"""Current-cue translation with bounded context and committed roll-up deduplication."""
from collections import deque
from dataclasses import dataclass
import re

WAIT_MARKER = "[[ATV_WAIT_FOR_MORE]]"


def flatten(text):
    return re.sub(r"\s+", " ", text).strip()


def speaker(text):
    match = re.match(r"^(?:>>\s*)?([A-Z][A-Za-z .'-]{0,30}):\s", text)
    return match[1].casefold() if match else None


def unfinished(text):
    """Classify an open English thought for telemetry, never to block translation."""
    value = flatten(text).rstrip('"\u201d\u2019)] ')
    words = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", value.lower().replace('\u2019', "'"))
    if not words:
        return False
    if value.endswith(("...", "\u2026", ",", ";", "\u2014", " -")):
        return True
    if words[-1] in {
        "a", "an", "the", "to", "of", "with", "onto", "into", "from", "for", "at",
        "in", "on", "as", "than", "so", "between", "about",
        "by", "and", "or", "but", "because", "although", "unless", "whether", "if",
        "that", "which", "whose", "my", "your", "his", "her", "our", "their",
        "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
        "will", "would", "could", "should", "must", "can", "cannot", "don't",
        "doesn't", "didn't", "isn't", "aren't", "not", "i", "he", "she", "we", "they",
        "mr", "mrs", "dr",
        "it's", "that's", "there's", "he's", "she's", "we're", "they're", "you're",
        "i'm", "i've", "we've", "they've", "it'll", "he'll", "she'll", "who's", "what's",
    }:
        return True
    # A subordinate clause alone is not a complete statement.
    if words[0] in {"if", "unless", "although", "because", "when", "while"} and "," not in value:
        return True
    return False


def complete(text):
    value = flatten(text).rstrip('"\u201d\u2019)] ')
    if unfinished(value):
        return False
    return bool(re.search(r"[.!?\u3002\uff01\uff1f]$", value)) or value.lower() in {
        "yes", "no", "okay", "ok", "thanks", "thank you", "go", "stop", "right", "sure",
    }


@dataclass(frozen=True)
class Segment:
    text: str
    context: tuple[str, ...]
    started: float
    observed: float
    ready_at: float
    revision: int
    allow_wait: bool = False
    reason: str = "complete"

    @property
    def cache_key(self):
        return self.context, self.text


class SpeechBuffer:
    CONTINUATION_GAP = 4.0
    HISTORY_AGE = 35.0

    def __init__(self):
        self.reset()

    def reset(self):
        self.history = deque(maxlen=8)
        self.pending = ""
        self.last_text = ""
        self.last_speaker = None
        self.started = self.observed = self.due = 0.0
        self.revision = 0
        self.submitted = -1
        self.consumed = ""

    def _remember(self, text, now):
        if text and (not self.history or self.history[-1][1] != text):
            self.history.append((now, text))

    def context(self, now):
        values, size = [], 0
        for stamp, text in reversed(self.history):
            if now-stamp > self.HISTORY_AGE or size+len(text) > 1600:
                break
            values.append(text)
            size += len(text)
        return tuple(reversed(values))

    def observe(self, text, now, *, continuous=False):
        text = flatten(text)
        if not text:
            return
        if self.observed and now-self.observed > self.HISTORY_AGE:
            self.reset()
        who = speaker(text)
        changed_speaker = who and self.last_speaker and who != self.last_speaker
        raw_text = text
        # A roll-up cue can retain words that have already been displayed in Chinese.
        if (self.consumed and text != self.last_text and not changed_speaker
                and (continuous or now-self.observed <= self.CONTINUATION_GAP)):
            left, right = self.consumed.split(), text.split()
            for length in range(min(len(left), len(right)), 0, -1):
                if [v.casefold() for v in left[-length:]] == [v.casefold() for v in right[:length]]:
                    remaining = " ".join(right[length:])
                    if remaining:
                        text = remaining
                    break
        # Previous source is context even when its request was cancelled. Never
        # accumulate unfinished captions into the next visible translation.
        if self.pending and self.pending != text:
            self._remember(self.pending, now)
        self.pending = text
        self.started = now
        self.last_text = raw_text
        self.last_speaker = who
        self.observed = now
        self.revision += 1
        self.submitted = -1
        self.due = now

    def take(self, now):
        if not self.pending or self.submitted == self.revision or now < self.due:
            return None
        self.submitted = self.revision
        return Segment(self.pending, self.context(now), self.started, self.observed, now,
                       self.revision, False,
                       "complete" if complete(self.pending) else "conservative")

    def commit(self, segment, now):
        if segment.revision != self.revision or not self.pending.startswith(segment.text):
            return
        self._remember(segment.text, now)
        self.consumed = self.last_text
        self.pending = ""
        self.started = self.observed
        self.revision += 1
        self.submitted = self.revision
        self.due = now
