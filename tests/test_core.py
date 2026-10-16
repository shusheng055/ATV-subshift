import asyncio
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication
from subtitle_app.capture import Observation, WindowsOCR, clean_text
from subtitle_app.pipeline import Pipeline
from subtitle_app.settings import Settings, load_key, save_key
from subtitle_app.terminology import TermTranslator, choose_candidate, parse_hotwords
from subtitle_app.translation import ApiTranslator, LocalTranslator, TranslationError, api_endpoint
from subtitle_app.windows import Player


class CoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_settings_and_dpapi(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            settings = Settings(hotwords="downforce => 下压力", keep_words="Apple TV", hotword_weight=3)
            settings.save(p)
            save_key("secret-test-value", p)
            self.assertEqual(settings, Settings.load(p))
            self.assertEqual(load_key(p), "secret-test-value")
            self.assertNotIn(b"secret-test-value", (p / "credential.dpapi").read_bytes())
            self.assertNotIn("secret-test-value", (p / "settings.json").read_text("utf-8"))
            save_key("", p)
            self.assertEqual(load_key(p), "")

    def test_broken_settings_fall_back(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            (p / "settings.json").write_text('{"font_size":"bad"}', "utf-8")
            self.assertEqual(Settings.load(p), Settings())

    def test_hotword_weight_and_source_gate(self):
        words = parse_hotwords("track => 赛道\n下压力")
        candidates = [("我们在轨道上", -.5), ("我们在赛道上", -.8)]
        self.assertEqual(choose_candidate(candidates, words, "On the track", 0), "我们在轨道上")
        self.assertEqual(choose_candidate(candidates, words, "On the track", 2), "我们在赛道上")
        self.assertEqual(choose_candidate(candidates, words, "On the road", 2), "我们在轨道上")

    def test_keep_words_never_enter_engine(self):
        class RecordingEngine:
            inputs = []
            def translate(self, text):
                self.inputs.append(text)
                return "译文"
        engine = RecordingEngine()
        result = TermTranslator(engine, "Apple\nApple TV\nF1").translate("Watch Apple TV with F1, apple and scar.")
        self.assertIn("Apple TV", result)
        self.assertIn("F1", result)
        self.assertIn("apple", result)
        self.assertTrue(all("Apple" not in s and "F1" not in s for s in engine.inputs))

    def test_endpoint_validation(self):
        self.assertEqual(api_endpoint("http://localhost:1234/v1/"), "http://localhost:1234/v1/chat/completions")
        self.assertEqual(api_endpoint("https://example.com/v1/chat/completions"), "https://example.com/v1/chat/completions")
        with self.assertRaises(TranslationError):
            api_endpoint("https://user:secret@example.com/v1")

    def test_stop_cancels_between_protected_fragments(self):
        calls = []
        class Engine:
            def translate(self, text):
                calls.append(text)
                return "译文"
        translator = TermTranslator(Engine(), "Apple TV")
        with self.assertRaises(InterruptedError):
            translator.translate("Before Apple TV after Apple TV later", cancelled=lambda: bool(calls))
        self.assertEqual(len(calls), 1)

    def test_api_payload_terms_and_safe_error(self):
        captured = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                captured.append(body)
                self.send_response(401 if body["model"] == "bad" else 200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"choices": [{"message": {"content": "赛道"}}],
                                            "sensitive": "secret-should-never-display"}).encode())
        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        settings = Settings(mode="API", api_url=f"http://127.0.0.1:{server.server_port}/v1", api_model="test",
                            hotwords="track => 赛道", hotword_weight=3)
        try:
            api = ApiTranslator(settings, "test-key")
            self.assertEqual(api.translate("On the track"), "赛道")
            self.assertIn("weight 3/5", captured[0]["messages"][0]["content"])
            self.assertIn("track => 赛道", captured[0]["messages"][0]["content"])
            api.settings = replace(settings, api_model="bad")
            with self.assertRaises(TranslationError) as error:
                api.translate("On the track")
            self.assertNotIn("secret", str(error.exception))
            api.close()
        finally:
            server.shutdown()
            server.server_close()

    def test_latest_cue_only_and_clear(self):
        pipeline = Pipeline()
        pipeline.settings = Settings()
        pipeline.running, pipeline.session = True, 7
        pipeline.started = time.monotonic()
        pipeline.last_seen = pipeline.started
        player = Player(123, 1, "fixture", (0, 0, 1280, 720))
        captions, cleared = [], []
        pipeline.caption.connect(lambda *args: captions.append(args))
        pipeline.clear.connect(lambda: cleared.append(True))
        first = Observation("Hello.", player, "test")
        pipeline._observe(7, first)
        pipeline.candidate_since -= 1
        pipeline._observe(7, first)
        first_seq = pipeline.sequence
        self.assertEqual(pipeline.jobs.qsize(), 1)
        pipeline._observe(7, Observation("Goodbye.", player, "test"))
        pipeline._translated(7, first_seq, "Hello.", "你好", 20, "")
        self.assertEqual(captions, [])
        pipeline.candidate_since -= 1
        pipeline._observe(7, Observation("Goodbye.", player, "test"))
        pipeline._translated(7, pipeline.sequence, "Goodbye.", "再见", 20, "")
        self.assertEqual(len(captions), 1)
        pipeline._observe(7, Observation("Goodbye.", player, "test"))
        self.assertEqual(len(captions), 1)
        pipeline.last_seen -= 2
        pipeline._observe(7, Observation("", player, "test"))
        self.assertEqual(pipeline.current, "")
        self.assertTrue(cleared)
        pipeline.stop()

    def test_real_windows_ocr(self):
        from PIL import Image, ImageDraw, ImageFont
        image = Image.new("RGB", (960, 200), (15, 17, 20))
        ImageDraw.Draw(image).text((180, 70), "Hello, welcome back.",
            font=ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 40), fill="white")
        text, bounds = asyncio.run(WindowsOCR().recognize(image))
        self.assertEqual(text, "Hello, welcome back.")
        self.assertIsNotNone(bounds)

    def test_real_local_model_and_weighted_beam(self):
        engine = LocalTranslator()
        translated = engine.translate("Hello, welcome back.")
        self.assertTrue(any("\u4e00" <= c <= "\u9fff" for c in translated))
        # These alternatives are generated by the actual bundled model, not mocked text.
        source = "We need more downforce."
        result = engine.model.translate_batch([engine.tokenizer.encode(source, out_type=str)],
                    beam_size=4, num_hypotheses=4, return_scores=True)[0]
        choices = [engine.tokenizer.decode(tokens).replace("▁", " ").strip() for tokens in result.hypotheses]
        preferred = choices[-1].strip("。.!?")
        engine.hotwords = parse_hotwords(preferred)
        engine.weight = 5
        self.assertIn(preferred, engine.translate(source))
        protected = TermTranslator(engine, "Apple TV").translate("Apple TV is here.")
        self.assertIn("Apple TV", protected)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    unittest.main(verbosity=2)
