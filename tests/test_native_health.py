"""Persistent native diagnostics cannot disclose subtitle/config data or stop playback."""
import json
from pathlib import Path
import tempfile
import threading
import unittest

from subtitle_app.native_source import NativeSource


class NativeHealthTests(unittest.TestCase):
    def test_journal_excludes_payload_text_and_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            source = NativeSource(threading.Event(), render=True)
            source.health_path = Path(directory)/'native-health.json'
            for epoch in range(100):
                source._message(123, {'type':'send', 'payload':{
                    'kind':'ready', 'epoch':epoch, 'sources':['private subtitle'],
                    'text':'private translation', 'api_key':'private credential'}}, None)
            text = source.health_path.read_text('utf-8')
            result = json.loads(text)
            self.assertEqual(len(result['events']), 80)
            self.assertEqual(result['last_event']['epoch'], 99)
            self.assertNotIn('private', text)
            self.assertLess(len(text), 32000)

    def test_diagnostic_write_error_does_not_break_native_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            blocked = Path(directory)/'file'
            blocked.write_text('occupied', 'utf-8')
            source = NativeSource(threading.Event(), render=True)
            source.health_path = blocked/'native-health.json'
            source._message(123, {'type':'send','payload':{
                'kind':'draw_error','error':'native context failed'}}, None)
            self.assertIn(123, source.failed)
            self.assertEqual(source.counts['errors'], 1)
