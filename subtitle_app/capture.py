from __future__ import annotations

import asyncio
from collections import deque
from contextlib import ExitStack
from dataclasses import dataclass
import hashlib
import re
import threading
import time

from .windows import Player, find_player, foreground
from .native_source import NativeSource


def clean_text(text: str) -> str:
    text = text.replace("\r", "\n").replace("\u200b", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)[:800]


def plausible(text: str) -> bool:
    return (2 <= len(text) <= 800 and sum(c.isalpha() for c in text) >= 2
            and text.lower() not in {"play", "pause", "subtitles", "audio", "english", "english cc",
                                     "apple tv", "skip intro", "skip recap", "next episode", "字幕", "播放", "暂停"})


@dataclass
class Observation:
    text: str = ""
    player: Player | None = None
    origin: str = ""
    notice: str = ""
    captured_at: float = 0.0
    bounds: tuple[float, float, float, float] | None = None  # Client-relative physical pixels.
    native_token: dict | None = None


class WindowsOCR:
    def __init__(self, language: str = "en"):
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine
        tag = {"en": "en-US", "zh-Hans": "zh-Hans-CN", "zh-Hant": "zh-Hant-TW"}.get(language, language)
        self.engine = OcrEngine.try_create_from_language(Language(tag))
        if self.engine is None:
            raise RuntimeError(f"Windows 缺少 {tag} OCR 语言组件。请在 Windows 语言设置安装对应语言的基本输入。")
        self.max_size = OcrEngine.max_image_dimension

    async def recognize(self, image):
        from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
        from winrt.windows.storage.streams import DataWriter

        with ExitStack() as resources:
            original = image.size
            scale = min(1.5, 1600 / image.width, self.max_size / max(image.size))
            if abs(scale - 1) > .02:
                image = resources.enter_context(image.resize((int(image.width * scale), int(image.height * scale))))
            scale_x, scale_y = image.width / original[0], image.height / original[1]
            rgba = resources.enter_context(image.convert("RGBA"))
            writer = DataWriter()
            resources.callback(writer.close)
            writer.write_bytes(rgba.tobytes("raw", "BGRA"))
            buffer = writer.detach_buffer()
            bitmap = SoftwareBitmap(BitmapPixelFormat.BGRA8, rgba.width, rgba.height, BitmapAlphaMode.IGNORE)
            resources.callback(bitmap.close)
            bitmap.copy_from_buffer(buffer)
            result = await self.engine.recognize_async(bitmap)
            lines = []
            for line in result.lines:
                text = clean_text(line.text)
                words = list(line.words)
                if not words or not plausible(text):
                    continue
                left = min(w.bounding_rect.x for w in words)
                top = min(w.bounding_rect.y for w in words)
                right = max(w.bounding_rect.x + w.bounding_rect.width for w in words)
                bottom = max(w.bounding_rect.y + w.bounding_rect.height for w in words)
                center = (left + right) / 2 / image.width
                if bottom - top < 10 or not .12 < center < .88:
                    continue
                lines.append((text, (left / scale_x, top / scale_y, right / scale_x, bottom / scale_y)))
            # Keep the last compact block, avoiding distant incidental scene text.
            block = []
            for line in sorted(lines, key=lambda v: v[1][1], reverse=True):
                if block and block[-1][1][1] - line[1][3] > max(28, (line[1][3] - line[1][1]) * 1.8):
                    break
                block.append(line)
                if len(block) == 3:
                    break
            block.reverse()
            if not block:
                return "", None
            bounds = (min(v[1][0] for v in block), min(v[1][1] for v in block),
                      max(v[1][2] for v in block), max(v[1][3] for v in block))
            return "\n".join(v[0] for v in block), bounds


class NativeText:
    """Only visible TextControls in the subtitle band, never arbitrary window labels."""
    def __init__(self):
        import uiautomation as auto
        self.auto = auto
        self.context = auto.UIAutomationInitializerInThread()
        self.context.__enter__()

    def read(self, player: Player):
        x, y, width, height = player.rect
        root = self.auto.ControlFromHandle(player.hwnd)
        pending = deque([(root, 0)])
        lines = []
        started, visited = time.monotonic(), 0
        while pending and visited < 100 and time.monotonic() - started < .18:
            control, depth = pending.popleft()
            visited += 1
            if control.ControlTypeName == "TextControl" and not control.IsOffscreen:
                r = control.BoundingRectangle
                text = clean_text(control.Name or "")
                if (r.top >= y + height * .58 and r.bottom <= y + height * .97
                    and r.left >= x + width * .04 and r.right <= x + width * .96 and plausible(text)):
                    lines.append((text, (r.left - x, r.top - y, r.right - x, r.bottom - y)))
            if depth < 7:
                pending.extend((child, depth + 1) for child in control.GetChildren())
        lines.sort(key=lambda v: (v[1][1], v[1][0]))
        if not lines:
            return "", None
        return clean_text("\n".join(dict.fromkeys(v[0] for v in lines))), (
            min(v[1][0] for v in lines), min(v[1][1] for v in lines),
            max(v[1][2] for v in lines), max(v[1][3] for v in lines))

    def close(self):
        self.context.__exit__(None, None, None)


class CaptureLoop:
    def __init__(self, stop: threading.Event, emit, language="en", test_hwnd=0):
        self.stop, self.emit, self.language, self.test_hwnd = stop, emit, language, test_hwnd
        self.direct_source = None

    def deliver(self, token, texts):
        return self.direct_source.submit(token, texts) if self.direct_source else False

    def clear_native_cache(self):
        if self.direct_source:
            self.direct_source.clear_cache()

    def run(self):
        import winrt.runtime
        from PIL import Image
        import mss

        native, ocr, direct_source = None, None, None
        ocr_error = ""
        native_attempted = ocr_attempted = False
        apartment = False
        loop = None
        try:
            winrt.runtime.init_apartment(winrt.runtime.ApartmentType.SINGLE_THREADED)
            apartment = True
            loop = asyncio.new_event_loop()
            if not self.test_hwnd:
                direct_source = NativeSource(self.stop, render=True).start()
                self.direct_source = direct_source
            cached_image, cached_ocr = None, ("", None)
            next_native, black_since = 0.0, 0.0
            with ExitStack() as resources:
                capture = None
                while not self.stop.is_set():
                    began = time.monotonic()
                    player = find_player(self.test_hwnd)
                    observation = Observation(player=player, captured_at=began)
                    if player is None:
                        observation.notice = "等待 Apple TV。请打开播放器并开启 English / English CC 字幕。"
                        self.emit(observation)
                        self.stop.wait(.6)
                        cached_image = None
                        continue
                    direct = direct_source.snapshot() if direct_source else None
                    if direct is None and not foreground(player.hwnd):
                        observation.notice = "Apple TV 在后台，等待可读取的原生字幕；OCR 已暂停。"
                        self.emit(observation)
                        self.stop.wait(.35)
                        cached_image = None
                        continue
                    if direct is not None:
                        observation.text = clean_text(direct.text)
                        route = {'cea608': 'CEA-608', 'webvtt': 'WebVTT'}.get(direct.route, direct.route)
                        observation.origin = 'Apple TV 原生字幕 · ' + route
                        observation.native_token = direct.token
                    else:
                        if not native_attempted:
                            native_attempted = True
                            try:
                                native = NativeText()
                            except Exception:
                                pass
                        if native and began >= next_native:
                            try:
                                observation.text, observation.bounds = native.read(player)
                            except Exception:
                                pass
                            next_native = began + (.25 if observation.text else 3.0)
                        if not observation.text and not ocr_attempted:
                            ocr_attempted = True
                            try:
                                ocr = WindowsOCR(self.language)
                            except Exception as exc:
                                ocr_error = str(exc)
                    if direct is not None:
                        pass  # Empty native cues clear output without running OCR over a valid source.
                    elif observation.text:
                        observation.origin = "Windows 字幕文本"
                    elif ocr:
                        x, y, w, h = player.rect
                        left, top = int(w * .06), int(h * .58)
                        roi = {"left": x + left, "top": y + top, "width": int(w * .88), "height": int(h * .38)}
                        try:
                            if capture is None:
                                capture = resources.enter_context(mss.mss())
                            shot = capture.grab(roi)
                            with Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX") as image:
                                # Fingerprint includes player identity: switching/reopening never reuses another cue.
                                digest = (player.hwnd, hashlib.blake2b(shot.bgra, digest_size=12).digest())
                                if digest != cached_image:
                                    cached_ocr = loop.run_until_complete(ocr.recognize(image))
                                    cached_image = digest
                                observation.text, bounds = cached_ocr
                                if bounds:
                                    observation.bounds = (bounds[0] + left, bounds[1] + top,
                                                          bounds[2] + left, bounds[3] + top)
                                observation.origin = "Windows OCR"
                                with image.resize((64, 24)) as small, small.convert("L") as gray:
                                    extrema = gray.getextrema()
                                if extrema[1] < 22:
                                    black_since = black_since or began
                                    if began - black_since > 3:
                                        observation.notice = "捕获区域持续接近全黑：可能是暗场或播放保护。无法读取时不能翻译；本应用不绕过 DRM。"
                                else:
                                    black_since = 0
                        except Exception:
                            observation.notice = "屏幕捕获或 Windows OCR 失败。请确认窗口位于屏幕内；受保护内容可能无法捕获。"
                    else:
                        observation.notice = ocr_error or "无法读取字幕文本，也无法启动 Windows OCR。"
                    self.emit(observation)
                    # Native cues need no OCR settling interval. Keep OCR at its
                    # lower-cost cadence, but notice short native cues promptly.
                    interval = .05 if direct is not None else .35
                    self.stop.wait(max(.01, interval - (time.monotonic() - began)))
        except Exception:
            self.emit(Observation(notice="字幕捕获线程异常，点击 Stop 后可重新启动。"))
        finally:
            # Every cleanup runs, even when a preceding provider raises.
            cleanup = [direct_source.close if direct_source else None,
                       native.close if native else None,
                       loop.close if loop else None,
                       winrt.runtime.uninit_apartment if apartment else None]
            for close in cleanup:
                if close:
                    try:
                        close()
                    except Exception:
                        pass
