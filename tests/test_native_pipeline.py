"""Regression checks for short native cues, rolling rows and failed delivery.

No Apple TV attachment or screen automation; real playback remains a separate gate.
"""
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from subtitle_app.capture import Observation
from subtitle_app.pipeline import Pipeline
from subtitle_app.settings import Settings
from subtitle_app.windows import Player


class NativePipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.pipeline = Pipeline()
        self.pipeline.settings = Settings()
        self.pipeline.running = True
        self.pipeline.session = 1
        self.pipeline.started = self.pipeline.last_seen = time.monotonic()
        self.player = Player(123, 456, 'test fixture', (0, 0, 1280, 720))

    def tearDown(self):
        self.pipeline.stop()
        for thread in self.pipeline.threads:
            thread.join(timeout=1)
        self.pipeline.timer.stop()

    def native(self, text, epoch=1, sources=None):
        return Observation(text, self.player, 'Apple TV 原生字幕 · CEA-608',
                           native_token={'pid': 456, 'epoch': epoch, 'key': str(epoch),
                                         'sources': sources if sources is not None else [text]})

    def test_short_native_cue_does_not_wait_for_second_sample(self):
        self.pipeline._observe(1, self.native('Yes.'))
        self.assertEqual(self.pipeline.jobs.get_nowait()[1], 'Yes.')

    def test_fast_cue_change_cancels_old_and_queues_new(self):
        self.pipeline._observe(1, self.native('Yes.'))
        old_sequence = self.pipeline.sequence
        self.pipeline._observe(1, self.native('Go!', 2))
        sequence, text, _, token = self.pipeline.jobs.get_nowait()
        self.assertGreater(sequence, old_sequence)
        self.assertEqual((text, token['epoch']), ('Go!', 2))

    def test_blank_native_cue_cancels_immediately(self):
        self.pipeline._observe(1, self.native('Hello.'))
        sequence = self.pipeline.sequence
        self.pipeline._observe(1, self.native('', 2, []))
        self.assertEqual(self.pipeline.current, '')
        self.assertGreater(self.pipeline.sequence, sequence)

    def test_duplicate_native_sample_is_not_requeued(self):
        self.pipeline._observe(1, self.native('Hello.'))
        self.pipeline._observe(1, self.native('Hello.'))
        self.assertEqual(self.pipeline.jobs.qsize(), 1)

    def test_same_text_new_epoch_still_reaches_renderer(self):
        self.pipeline._observe(1, self.native('Hello.'))
        self.pipeline.jobs.get_nowait()
        self.pipeline._observe(1, self.native('Hello.', 2))
        self.assertEqual(self.pipeline.jobs.get_nowait()[3]['epoch'], 2)

    def test_ocr_retains_stability_check(self):
        observation = Observation('Hello.', self.player, 'Windows OCR')
        self.pipeline._observe(1, observation)
        self.assertTrue(self.pipeline.jobs.empty())
        self.pipeline.candidate_since -= .2
        self.pipeline._observe(1, observation)
        self.assertEqual(self.pipeline.jobs.get_nowait()[1], 'Hello.')

    def test_incomplete_native_cue_is_queued_immediately_with_no_wait(self):
        self.pipeline._observe(1, self.native('The only thing I want you to'))
        first_seq = self.pipeline.jobs.get_nowait()[0]
        self.assertFalse(self.pipeline.plans[first_seq].allow_wait)
        self.pipeline._observe(1, self.native('do is stay here.', 2))
        seq, source, _, token = self.pipeline.jobs.get_nowait()
        self.assertEqual(source, 'do is stay here.')
        self.assertEqual(token['epoch'], 2)
        self.assertEqual(self.pipeline.plans[seq].text, 'do is stay here.')
        self.assertEqual(self.pipeline.plans[seq].context, ('The only thing I want you to',))

    def test_seek_resets_history_even_when_the_new_text_is_identical(self):
        first = self.native('Max is leading.')
        first.native_token['stream_id'] = 1
        self.pipeline._observe(1, first)
        self.pipeline.jobs.get_nowait()
        second = self.native('He is ahead.', 2)
        second.native_token['stream_id'] = 1
        self.pipeline._observe(1, second)
        seq = self.pipeline.jobs.get_nowait()[0]
        self.assertEqual(self.pipeline.plans[seq].context, ('Max is leading.',))
        sought = self.native('He is ahead.', 3)
        sought.native_token['stream_id'] = 2
        self.pipeline._observe(1, sought)
        seq = self.pipeline.jobs.get_nowait()[0]
        self.assertEqual(self.pipeline.plans[seq].context, ())

    def test_native_blank_keeps_context_but_not_stale_delivery_or_accumulated_source(self):
        self.pipeline._observe(1, self.native('I want you to'))
        self.pipeline._observe(1, self.native('', 2, []))
        self.assertEqual(self.pipeline.current, '')
        self.pipeline._observe(1, self.native('stay here.', 3))
        seq, _, _, token = self.pipeline.jobs.get_nowait()
        self.assertEqual(token['epoch'], 3)
        self.assertEqual(self.pipeline.plans[seq].text, 'stay here.')
        self.assertEqual(self.pipeline.plans[seq].context, ('I want you to',))

    def run_worker(self, successful=True, bilingual=False):
        pipeline = self.pipeline
        stop = pipeline.stop_event
        calls, deliveries, events = [], [], []
        pipeline.subtitle_mode = 'Bilingual' if bilingual else 'Translated'
        pipeline.events.translated.connect(lambda *event: events.append(event))

        class Engine:
            def __init__(self, _settings, **_kwargs): pass
            def translate(self, text):
                calls.append(text)
                return '译' + text

        def enqueue(sources, epoch):
            pipeline.sequence += 1
            token = {'pid': 456, 'epoch': epoch, 'key': str(epoch), 'sources': sources}
            pipeline.jobs.put_nowait((pipeline.sequence, '\n'.join(sources), time.monotonic(), token))

        class Capture:
            def __init__(self, *_): pass
            def run(self): stop.wait(2)
            def deliver(self, token, texts):
                deliveries.append((token, list(texts)))
                if successful and len(deliveries) == 1:
                    enqueue(['World', 'Next'], 2)
                else:
                    stop.set()
                return successful

        enqueue(['Hello', 'World'], 1)
        with patch('subtitle_app.pipeline.LocalTranslator', Engine), patch('subtitle_app.pipeline.CaptureLoop', Capture):
            pipeline._worker(1, stop, '', 0)
        return calls, deliveries, events

    def test_each_native_group_uses_one_complete_semantic_request(self):
        calls, deliveries, events = self.run_worker()
        self.assertEqual(calls, ['Hello World', 'World Next'])
        self.assertEqual(deliveries[0][1], ['译Hello World', ''])
        self.assertEqual(deliveries[1][1], ['译World Next', ''])
        self.assertTrue(deliveries[0][0]['paragraph'])
        self.assertEqual(deliveries[0][0]['display_source'], 'Hello World')
        self.assertTrue(all(not event[-1] for event in events))

    def test_bilingual_sends_separate_languages_without_per_run_newlines(self):
        _, deliveries, _ = self.run_worker(bilingual=True)
        self.assertEqual(deliveries[0][1], ['译Hello World', ''])
        self.assertEqual(deliveries[0][0]['sources'], ['Hello', 'World'])
        self.assertEqual(deliveries[0][0]['subtitle_mode'], 'Bilingual')

    def test_failed_native_delivery_is_not_reported_as_translation_success(self):
        _, _, events = self.run_worker(successful=False)
        self.assertEqual(events[-1][3], '')
        self.assertIn('未能送达', events[-1][-1])

    def test_preview_and_native_source_include_the_current_incomplete_tail(self):
        output = []
        self.pipeline.caption.connect(lambda *args: output.append(args))
        self.pipeline._observe(1, self.native('The only thing I want you to'))
        self.pipeline._observe(1, self.native('do is stay here. We could', 2))
        seq, source, _, _ = self.pipeline.jobs.get_nowait()
        self.pipeline._translated(1, seq, source, '做的就是待在这里。我们可以……', 1000, '')
        self.assertEqual(output[0][0], 'do is stay here. We could')
        self.assertEqual(self.pipeline.speech.pending, '')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    unittest.main(verbosity=2)
