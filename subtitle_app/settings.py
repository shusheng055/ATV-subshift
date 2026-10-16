from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import asdict, dataclass, field, fields
import json
import os
from pathlib import Path
import sys

from .presets import TermPreset, load_presets, active_terms

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
DATA = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ATVSubshift"


@dataclass
class Settings:
    mode: str = "Local"
    source: str = "en"
    target: str = "zh-Hans"
    api_url: str = "https://api.openai.com/v1"
    api_model: str = ""
    api_provider: str = "custom"
    api_protocol: str = "chat"
    api_profiles: dict = field(default_factory=dict)
    subtitle_mode: str = "Translated"
    font_size: int = 30
    bottom: int = 12
    theme: str = "light"
    hotwords: str = ""
    hotword_weight: float = 3.0
    keep_words: str = ""
    term_presets: list[TermPreset] | None = None

    def __post_init__(self):
        # Seed fresh profiles only; an explicit empty list or legacy terms win.
        if self.term_presets is None and not self.hotwords and not self.keep_words:
            self.term_presets = json.loads((ROOT / "assets/racing-preset.json").read_text("utf-8"))
        self.term_presets = load_presets(self.term_presets, self.hotwords, self.keep_words)

    def resolved(self):
        from dataclasses import replace
        hotwords, keep_words = active_terms(self.term_presets)
        return replace(self, hotwords=hotwords, keep_words=keep_words)

    @classmethod
    def load(cls, directory: Path = DATA):
        try:
            raw = json.loads((directory / "settings.json").read_text("utf-8"))
            value = cls(**{f.name: raw[f.name] for f in fields(cls) if f.name in raw})
            if value.mode not in ("Local", "API") or value.theme not in ("dark", "light"):
                return cls()
            value.font_size = max(18, min(52, int(value.font_size)))
            value.bottom = max(4, min(32, int(value.bottom)))
            value.hotword_weight = max(0.0, min(5.0, float(value.hotword_weight)))
            if not isinstance(value.api_profiles, dict):
                value.api_profiles = {}
            value.hotwords, value.keep_words = active_terms(value.term_presets)
            if value.subtitle_mode not in ("Translated", "Bilingual"):
                value.subtitle_mode = "Translated"
            if value.mode == "Local":
                value.source, value.target = "en", "zh-Hans"
            return value
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self, directory: Path = DATA):
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / "settings.tmp"
        temporary.write_text(json.dumps(asdict(self.resolved()), ensure_ascii=False, indent=2), "utf-8")
        temporary.replace(directory / "settings.json")


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _protect(data: bytes, decrypt=False) -> bytes:
    """DPAPI binds the encrypted credential to the current Windows account."""
    source = ctypes.create_string_buffer(data)
    blob = Blob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        fn = crypt.CryptUnprotectData
        fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        ok = fn(ctypes.byref(blob), None, None, None, None, 1, ctypes.byref(output))
    else:
        fn = crypt.CryptProtectData
        fn.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        ok = fn(ctypes.byref(blob), "ATV subshift", None, None, None, 1, ctypes.byref(output))
    if not ok:
        raise OSError("Windows 无法安全保存或读取 API Key。")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(output.data)


def save_key(value: str, directory: Path = DATA):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "credential.dpapi"
    if not value:
        path.unlink(missing_ok=True)
        return
    temporary = directory / "credential.tmp"
    temporary.write_bytes(_protect(value.encode("utf-8")))
    temporary.replace(path)


def load_key(directory: Path = DATA) -> str:
    try:
        return _protect((directory / "credential.dpapi").read_bytes(), decrypt=True).decode("utf-8")
    except (OSError, UnicodeError):
        return ""
