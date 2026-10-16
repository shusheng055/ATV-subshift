"""Text-free coverage and delivery checks; no live attachment."""
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from subtitle_app.native_source import NativeSource
from subtitle_app.native_source import NativeCaption
from subtitle_app.acceptance import finalize_report


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.source = NativeSource(threading.Event(), render=True)

    def event(self, kind, epoch):
        self.source._message(123, {'type': 'send', 'payload': {
            'kind': kind, 'epoch': epoch, 'route': 'cea608', 'request_to_draw_ms': 25}}, None)

    def report(self, coverage):
        return {'cue_coverage': coverage, 'chinese_output': True, 'native_draws': 1,
                'overlay_windows': 0, 'errors': 0, 'restored_sessions': 1,
                'native_routes': ['Apple TV 原生字幕 · CEA-608']}

    def test_acceptance_rejects_partial_multiline_draw(self):
        value = finalize_report(self.report([{'ended': True, 'drawn': True, 'lines': 2, 'drawn_lines': 1}]), 1)
        self.assertFalse(value['passed'])
        self.assertEqual(value['missed_cues'], 1)

    def test_bilingual_requires_full_character_layout_not_just_row_draws(self):
        row = {'ended': True, 'drawn': True, 'lines': 2, 'drawn_lines': 2}
        report = {**self.report([row]), 'subtitle_mode': 'Bilingual'}
        self.assertFalse(finalize_report(report, 1)['passed'])
        row['layout'] = {'mode': 'Bilingual', 'order': 'zh-then-en', 'complete': True,
                         'characters': 90, 'visible_characters': 80}
        self.assertFalse(finalize_report(report, 1)['passed'])
        row['layout']['visible_characters'] = 90
        self.assertTrue(finalize_report(report, 1)['passed'])
        row['layout']['order'] = 'interleaved'
        self.assertFalse(finalize_report(report, 1)['passed'])

    def test_acceptance_rejects_no_cues_and_unverified_old_receipts(self):
        self.assertFalse(finalize_report(self.report([]), 1)['passed'])
        self.assertFalse(finalize_report(self.report([{'ended': True, 'drawn': True}]), 1)['passed'])

    def test_acceptance_requires_every_row_and_restoration(self):
        rows = [{'ended': True, 'drawn': True, 'lines': 2, 'drawn_lines': 2}]
        self.assertTrue(finalize_report(self.report(rows), 1)['passed'])
        value = self.report(rows)
        value['restored_sessions'] = 0
        self.assertFalse(finalize_report(value, 1)['passed'])

    def test_received_cue_without_draw_is_reported_as_missed(self):
        self.event('caption_observed', 1)
        self.event('caption_generation', 2)
        self.event('caption_observed', 2)
        self.event('native_draw_complete', 2)
        first, second = self.source.coverage_snapshot()
        self.assertTrue(first['ended'])
        self.assertFalse(first['drawn'])
        self.assertTrue(second['drawn'])
        self.assertGreaterEqual(first['duration_ms'], 0)
        self.assertNotIn('_began', first)

    def test_timeline_reset_clears_stale_source_and_propagates_stream_identity(self):
        self.source.latest = NativeCaption('old subtitle', 'cea608', 123, 0, 0,
                                           {'stream_id': 1})
        self.source._message(123, {'type': 'send', 'payload': {
            'kind': 'caption_generation', 'epoch': 2, 'stream_id': 2,
            'reset_context': True}}, None)
        self.assertEqual(self.source.latest.text, '')
        self.assertEqual(self.source.latest.token['stream_id'], 2)

    def test_all_completed_cues_are_counted_beyond_three(self):
        for epoch in range(1, 21):
            self.event('caption_generation', epoch)
            self.event('caption_observed', epoch)
            self.event('native_draw_complete', epoch)
        self.assertEqual(self.source.counts['native_draws'], 20)
        self.assertEqual(sum(row['drawn'] for row in self.source.coverage_snapshot()), 20)

    def test_coverage_history_is_bounded(self):
        for epoch in range(1200):
            self.event('caption_generation', epoch)
            self.event('caption_observed', epoch)
        self.assertEqual(len(self.source.coverage_snapshot()), 128)

    def test_incomplete_or_failed_delivery_is_rejected(self):
        posts = []
        class Script:
            def post(self, value): posts.append(value)
        self.source.sessions[123] = (None, Script())
        token = {'pid': 123, 'epoch': 1, 'key': 'fixture', 'sources': ['First', 'Second']}
        self.assertFalse(self.source.submit(token, ['译文']))
        self.assertEqual(posts, [])
        self.assertTrue(self.source.submit(token, ['一', '二']))
        self.assertEqual(posts[0]['payload']['texts'], ['一', '二'])
        self.source.failed.add(123)
        self.assertFalse(self.source.submit(token, ['一', '二']))
        self.assertEqual(len(posts), 1)

    def test_held_translation_receipt_does_not_claim_newer_source_coverage(self):
        self.event('caption_observed', 2)
        self.source._message(123, {'type': 'send', 'payload': {
            'kind': 'presentation_draw_complete', 'presentation_id': '1:1',
            'source_epoch': 1, 'source_stream_id': 1, 'host_epoch': 2,
            'request_to_draw_ms': 1200}}, None)
        self.assertFalse(self.source.coverage_snapshot()[0]['drawn'])
        receipt = self.source.presentation_snapshot()[0]
        self.assertTrue(receipt['drawn'])
        self.assertEqual((receipt['source_epoch'], receipt['host_epoch']), (1, 2))

    def test_queued_translation_is_not_a_draw_and_duration_requires_receipt(self):
        for event in ('queued', 'selected'):
            self.source._message(123, {'type': 'send', 'payload': {
                'kind': 'subtitle_pacing', 'event': event, 'presentation_id': '1:1',
                'source_epoch': 1, 'characters': 24, 'base_duration_ms': 4650}}, None)
        self.assertFalse(self.source.presentation_snapshot()[0]['drawn'])
        self.source._message(123, {'type': 'send', 'payload': {
            'kind': 'subtitle_pacing', 'event': 'dropped', 'presentation_id': '1:1',
            'reason': 'no_native_draw'}}, None)
        value = self.source.presentation_snapshot()[0]
        self.assertTrue(value['dropped'])
        self.assertIsNone(value['shown_ms'])

    def test_display_duration_and_lag_end_up_in_audit(self):
        self.source._message(123, {'type': 'send', 'payload': {
            'kind': 'subtitle_pacing', 'event': 'ended', 'presentation_id': '1:1',
            'source_epoch': 1, 'characters': 24, 'shown_ms': 900, 'lag_ms': 5100,
            'duration_ms': 1000, 'reason': 'reading_complete'}}, None)
        value = self.source.presentation_snapshot()[0]
        self.assertEqual((value['shown_ms'], value['lag_ms'], value['characters']), (900, 5100, 24))
        self.assertTrue(value['ended'])

    def test_delayed_draw_covers_original_identity_but_not_host_identity(self):
        layout = {'complete': True, 'characters': 20, 'visible_characters': 20,
                  'mode': 'Bilingual', 'order': 'zh-then-en'}
        original = {'pid': 123, 'epoch': 1, 'ended': True, 'drawn': False, 'lines': 1}
        report = {**self.report([original]), 'subtitle_mode': 'Bilingual',
                  'presentations': [{'pid': 123, 'source_epoch': 1, 'host_epoch': 2,
                                     'drawn': True, 'layout': layout}]}
        value = finalize_report(report, 1)
        self.assertTrue(value['passed'])
        self.assertEqual(value['delayed_original_cues_drawn'], 1)
        host = {**original, 'epoch': 2}
        report['cue_coverage'] = [original, host]
        self.assertFalse(finalize_report(report, 1)['passed'])
        self.assertEqual(report['missed_cues'], 1)

    def test_partial_delayed_frame_never_counts_as_original_coverage(self):
        original = {'pid': 123, 'epoch': 1, 'ended': True, 'drawn': False, 'lines': 1}
        report = {**self.report([original]), 'presentations': [
            {'pid': 123, 'source_epoch': 1, 'host_epoch': 2, 'drawn': True,
             'layout': {'complete': False, 'characters': 30, 'visible_characters': 20}}]}
        self.assertFalse(finalize_report(report, 1)['passed'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
