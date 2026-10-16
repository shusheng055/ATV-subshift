from pathlib import Path
import hashlib
import json
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from subtitle_app.capture import CaptureLoop
from subtitle_app.native_source import NativeCaption, verify_package
from subtitle_app.terminology import TermTranslator, parse_hotwords
from subtitle_app.windows import Player


class SourceTests(unittest.TestCase):
    def run_capture(self, direct):
        stop = threading.Event()
        observations, grabs = [], []
        class Source:
            def __init__(self, _stop, **_kwargs): pass
            def start(self): return self
            def snapshot(self): return direct
            def close(self): pass
        class UIA:
            def read(self, player): return '', None
            def close(self): pass
        class OCR:
            def __init__(self, _language): pass
            async def recognize(self, image): return 'Fallback words', (10, 10, 100, 30)
        class Capture:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def grab(self, roi):
                grabs.append(roi)
                class Shot:
                    size = (roi['width'], roi['height'])
                    bgra = b'\x40\x40\x40\xff' * (roi['width'] * roi['height'])
                return Shot()
        def emit(observation):
            observations.append(observation)
            stop.set()
        with (patch('subtitle_app.capture.NativeSource', Source),
              patch('subtitle_app.capture.NativeText', UIA),
              patch('subtitle_app.capture.WindowsOCR', OCR),
              patch('subtitle_app.capture.find_player', return_value=Player(1, 2, 'fixture', (0, 0, 1000, 600))),
              patch('subtitle_app.capture.foreground', return_value=True),
              patch('mss.mss', Capture)):
            CaptureLoop(stop, emit).run()
        return observations[0], grabs

    def test_native_text_bypasses_screen_capture(self):
        observation, grabs = self.run_capture(NativeCaption('Native original words', 'WebVTT', 2, time.monotonic(), 1))
        self.assertEqual(observation.text, 'Native original words')
        self.assertEqual(observation.origin, 'Apple TV 原生字幕 · WebVTT')
        self.assertEqual(grabs, [])

    def test_native_empty_cue_does_not_re_ocr(self):
        observation, grabs = self.run_capture(NativeCaption('', 'CEA-608', 2, time.monotonic(), 1))
        self.assertEqual(observation.text, '')
        self.assertEqual(grabs, [])

    def test_native_unavailable_falls_back_to_ocr(self):
        observation, grabs = self.run_capture(None)
        self.assertEqual(observation.text, 'Fallback words')
        self.assertEqual(observation.origin, 'Windows OCR')
        self.assertEqual(len(grabs), 1)

    def test_version_and_hash_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / 'AppleInc.AppleTVWin_1.1540.23558.0_x64__test'
            package.mkdir()
            data = b'verified test module'
            (package / 'module.dll').write_bytes(data)
            profile = {'package_name': 'AppleInc.AppleTVWin', 'package_version': '1.1540.23558.0',
                       'modules': [{'name': 'module.dll', 'sha256': hashlib.sha256(data).hexdigest()}]}
            self.assertEqual(verify_package(package, profile)['package_root'], str(package))
            (package / 'module.dll').write_bytes(b'updated')
            with self.assertRaises(RuntimeError): verify_package(package, profile)
            with self.assertRaises(RuntimeError): verify_package(Path(directory), profile)

    def test_all_saved_terms_are_used_above_one_hundred(self):
        class Engine:
            def translate(self, text): return '译文'
        words = '\n'.join([f'LongProtectedName{i}' for i in range(108)] + ['AI'])
        self.assertIn('AI', TermTranslator(Engine(), words).translate('AI is here.'))
        self.assertEqual(len(parse_hotwords('\n'.join(f'word{i}' for i in range(130)))), 130)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    unittest.main(verbosity=2)
