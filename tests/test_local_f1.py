import asyncio
import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import httpx

from subtitle_app.local_f1 import LocalF1Translator, MODEL, build_prompt, normalize_protected_terms, racing_quantity_hints
from subtitle_app.presets import TermPreset
from subtitle_app.settings import Settings
from subtitle_app.terminology import TermTranslator
from subtitle_app.translation import TranslationError


class LocalF1Tests(unittest.TestCase):
    def test_domain_follows_enabled_presets_and_terms(self):
        settings = Settings().resolved()
        self.assertIn('一级方程式', build_prompt(settings, 'Box this lap.'))
        self.assertIn('Box 翻译成 进站', build_prompt(settings, 'Box this lap.'))
        settings.term_presets = []
        settings.hotwords = ''
        self.assertNotIn('一级方程式', build_prompt(settings, 'A box.'))

    def test_context_is_bounded_and_separate_from_current_subtitle(self):
        prompt = build_prompt(Settings().resolved(), 'current subtitle', ['old '+str(i) for i in range(9)])
        self.assertNotIn('old 0', prompt)
        self.assertIn('old 8', prompt)
        self.assertTrue(prompt.endswith('current subtitle'))
        self.assertIn('不翻译', prompt)

    def test_template_and_requests_never_contain_remote_key(self):
        body = LocalF1Translator._body('test')
        self.assertEqual(body['prompt'], '<|startoftext|>test<|extra_0|>')
        self.assertTrue(body['raw'])
        self.assertEqual(body['options']['num_ctx'], 4096)
        self.assertEqual(body['options']['num_predict'], 400)
        self.assertNotIn('api_key', body)

    def make_engine(self, handler):
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        override = patch('subtitle_app.local_f1.SERVER', f'http://127.0.0.1:{server.server_port}')
        override.start()
        self.addCleanup(override.stop)
        engine = LocalF1Translator.__new__(LocalF1Translator)
        engine.settings = Settings().resolved()
        engine.loop = asyncio.new_event_loop()
        engine.client = httpx.AsyncClient(timeout=2, trust_env=False, follow_redirects=False)
        engine.closed = False
        engine.loaded = False
        self.addCleanup(engine.close)
        return engine

    def test_cancelled_http_request_releases_connection_for_next_cue(self):
        class Handler(BaseHTTPRequestHandler):
            calls = 0
            def log_message(self, *_): pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                type(self).calls += 1
                if type(self).calls == 1:
                    time.sleep(.5)
                data = json.dumps({'done': True, 'done_reason': 'stop', 'response': '进站'}).encode()
                try:
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    pass
        engine = self.make_engine(Handler)
        start = time.monotonic()
        with self.assertRaises(InterruptedError):
            engine.translate('Box', cancelled=lambda: time.monotonic()-start > .12)
        self.assertLess(time.monotonic()-start, .4)
        self.assertEqual(engine.translate('Box this lap'), '进站')

    def test_truncated_generation_is_never_delivered(self):
        engine = LocalF1Translator.__new__(LocalF1Translator)
        engine.settings = Settings().resolved()
        engine.closed = False
        with patch.object(engine, '_request', return_value={'done': True, 'done_reason': 'length', 'response': '半句'}):
            with self.assertRaises(TranslationError):
                engine.translate('Text')

    def test_no_request_after_cancel_or_expired_deadline(self):
        with self.assertRaises(InterruptedError):
            LocalF1Translator._check(lambda: True, None)
        with self.assertRaises(TimeoutError):
            LocalF1Translator._check(None, time.monotonic()-1)

    def test_one_complete_sentence_preserves_names_and_checks_missing_markers(self):
        engine = LocalF1Translator.__new__(LocalF1Translator)
        engine.settings = Settings().resolved()
        engine.closed = False
        terms = TermTranslator(engine, 'Hamilton\nVerstappen')
        response = {'done': True, 'done_reason': 'stop', 'response': '⟦ATV_KEEP_0⟧领先于⟦ATV_KEEP_1⟧。'}
        with patch.object(engine, '_request', return_value=response) as request:
            self.assertEqual(terms.translate_segment('Hamilton leads Verstappen.'), 'Hamilton领先于Verstappen。')
            self.assertEqual(request.call_count, 1)
            payload = request.call_args.args[2]
            self.assertIn('Hamilton leads Verstappen.', payload['prompt'])
            self.assertIn('⟦ATV_KEEP_0⟧ leads ⟦ATV_KEEP_1⟧.', payload['prompt'])
        with patch.object(engine, '_request', return_value={**response, 'response': '他领先。'}):
            with self.assertRaises(TranslationError):
                terms.translate_segment('Hamilton leads Verstappen.')

    def test_exact_unmasked_names_are_allowed_but_translated_or_duplicate_names_are_not(self):
        names = {'⟦ATV_KEEP_0⟧': 'Norris', '⟦ATV_KEEP_1⟧': 'Norris'}
        self.assertEqual(normalize_protected_terms('Norris进攻，Norris反击。', names),
                         '⟦ATV_KEEP_0⟧进攻，⟦ATV_KEEP_1⟧反击。')
        self.assertEqual(normalize_protected_terms('诺里斯进攻。', names), '诺里斯进攻。')
        self.assertEqual(normalize_protected_terms('Norris进攻。', names), 'Norris进攻。')

    def test_protected_strategy_term_is_explained_without_ordering_it_translated(self):
        prompt = build_prompt(Settings().resolved(), 'Cover the ⟦ATV_KEEP_0⟧.', (),
                              {'⟦ATV_KEEP_0⟧': 'Undercut'})
        self.assertIn('应对对手提前进站的策略', prompt)
        self.assertNotIn('Undercut 翻译成', prompt)

    def test_racing_time_units_do_not_change_explicit_distance_fractions(self):
        self.assertIn('0.3秒', racing_quantity_hints('three tenths ahead')[0])
        self.assertIn('0.7秒', racing_quantity_hints('seven tenths of a second')[0])
        self.assertEqual(racing_quantity_hints('two tenths of a lap'), [])

    def test_saved_api_profile_is_not_rebound_by_local_settings(self):
        original = Settings(api_provider='deepseek', api_url='https://api.deepseek.com/v1', api_model='deepseek-flash',
                            local_engine='enhanced')
        resolved = original.resolved()
        self.assertEqual((resolved.api_provider, resolved.api_url, resolved.api_model),
                         ('deepseek', 'https://api.deepseek.com/v1', 'deepseek-flash'))


if __name__ == '__main__':
    unittest.main()
