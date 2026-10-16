from dataclasses import asdict, replace
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from subtitle_app.api_widgets import ApiPanel
from subtitle_app.credentials import CredentialStore
from subtitle_app.model_catalog import MODELS, PROVIDERS, models_for, find_model
from subtitle_app.presets import TermPreset
from subtitle_app.settings import Settings, save_key
from subtitle_app.translation import ApiTranslator, TranslationError, api_endpoint, validate_api


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_catalog_lifecycle(self):
        self.assertEqual(len(MODELS), len({(m.provider, m.id) for m in MODELS}))
        retired = {'kimi-k2.5', 'moonshot-v1-8k', 'kimi-k2-thinking', 'deepseek-chat',
                   'deepseek-reasoner', 'gemini-2.0-flash', 'claude-3-5-sonnet-20241022',
                   'claude-opus-4-1-20250805', 'gpt-4.5-preview', 'o1-mini', 'qwen3-max', 'qwen-mt-turbo'}
        visible = {m.id for p in PROVIDERS for m in models_for(p.id, today=date(2026, 10, 14))}
        self.assertFalse(retired & visible)
        self.assertIn('gpt-4o', visible)
        self.assertIn('gpt-4.1-nano', visible)
        self.assertNotIn('gpt-4.1-nano', {m.id for m in models_for('openai', today=date(2026, 10, 23))})
        self.assertNotIn('gpt-4o', {m.id for m in models_for('openai', today=date(2027, 1, 14))})
        self.assertEqual(len(models_for('kimi', 'K2.7', date(2026, 10, 14))), 2)

    def test_credential_isolation_and_legacy_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            old, other = 'https://old.example/v1', 'https://api.moonshot.ai/v1'
            save_key('legacy-test-key', p)
            before = (p / 'credential.dpapi').read_bytes()
            store = CredentialStore(old, p)
            self.assertEqual(store.get(old), 'legacy-test-key')
            self.assertEqual(store.get(other), '')
            store.set(other, 'new-test-key')
            store = CredentialStore(other, p)  # Restart after changing the saved URL.
            self.assertEqual(store.get(old), 'legacy-test-key')
            self.assertEqual(store.get(other), 'new-test-key')
            self.assertEqual((p / 'credential.dpapi').read_bytes(), before)
            encrypted = (p / 'provider-credentials.dpapi').read_bytes()
            self.assertNotIn(b'new-test-key', encrypted)
            store.set(other, '')
            self.assertEqual(CredentialStore(other, p).get(other), '')
            (p / 'provider-credentials.dpapi').write_bytes(b'broken')
            broken = CredentialStore(other, p)
            self.assertEqual(broken.get(other), '')
            with self.assertRaises(OSError):
                broken.set(other, 'replacement')
            self.assertEqual((p / 'provider-credentials.dpapi').read_bytes(), b'broken')
            self.assertEqual((p / 'credential.dpapi').read_bytes(), before)

    def test_selector_preserves_settings_and_search_is_non_destructive(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            original = Settings(mode='API', api_url='https://my.example/custom/v1', api_model='my-model',
                theme='light', font_size=22, subtitle_mode='Bilingual', hotword_weight=3,
                term_presets=[TermPreset(name='赛车', hotwords='track => 赛道  \n', keep_words='F1\n')])
            save_key('legacy-key', p)
            key_bytes = (p / 'credential.dpapi').read_bytes()
            panel = ApiPanel(original, CredentialStore(original.api_url, p))
            self.assertEqual(panel.values()['api_model'], original.api_model)
            self.assertEqual(panel.url.text(), original.api_url)
            self.assertEqual(panel.key.text(), 'legacy-key')
            panel.provider.setCurrentIndex(panel.provider.findData('kimi'))
            self.assertEqual(panel.key.text(), '')
            chosen = panel.values()['api_model']
            panel.search.setText('no-such-model')
            self.assertEqual(panel.models.count(), 0)
            self.assertEqual(panel.values()['api_model'], chosen)
            panel.search.setText('k3')
            panel.models.setCurrentIndex(0)
            panel.models.activated.emit(0)
            self.assertEqual(panel.values()['api_model'], 'kimi-k3')
            panel.key.setText('kimi-test-key')
            panel.save_keys()
            panel.provider.setCurrentIndex(panel.provider.findData('custom'))
            self.assertEqual(panel.values()['api_model'], 'my-model')
            self.assertEqual(panel.url.text(), original.api_url)
            self.assertEqual(panel.key.text(), 'legacy-key')
            saved = replace(original, **panel.values())
            saved.save(p)
            loaded = Settings.load(p)
            for field in ('term_presets', 'hotword_weight', 'theme', 'subtitle_mode', 'font_size'):
                self.assertEqual(getattr(loaded, field), getattr(original, field))
            panel.provider.setCurrentIndex(panel.provider.findData('kimi'))
            self.assertEqual(panel.values()['api_model'], 'kimi-k3')
            self.assertEqual(panel.key.text(), 'kimi-test-key')
            self.assertEqual((p / 'credential.dpapi').read_bytes(), key_bytes)
            self.assertNotIn('kimi-test-key', (p / 'settings.json').read_text('utf-8'))
            panel.close()

    def test_url_key_edits_do_not_move_credentials_to_new_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            settings = Settings(api_url='https://old.example/v1', api_model='old')
            panel = ApiPanel(settings, CredentialStore(settings.api_url, p))
            panel.key.setText('unsaved-old-key')
            panel.url.setText('https://other.example/v1')
            self.assertEqual(panel.key.text(), '')
            panel.key.setText('other-key')
            panel.url.setText(settings.api_url)
            self.assertEqual(panel.key.text(), 'unsaved-old-key')
            self.assertEqual(panel.credentials.get('https://other.example/v1'), 'other-key')
            panel.close()

    def test_protocol_urls_and_expired_selection(self):
        self.assertEqual(api_endpoint('https://example.com/v1/chat/completions', 'responses'), 'https://example.com/v1/responses')
        self.assertEqual(api_endpoint('https://example.com/v1', 'messages'), 'https://example.com/v1/messages')
        self.assertTrue(api_endpoint('https://example.com/v1beta', 'gemini', 'gemini-test').endswith('/models/gemini-test:generateContent'))
        for url in ('https://key:secret@example.com', 'https://example.com?key=secret', 'https://{WorkspaceId}.example.com'):
            with self.assertRaises(TranslationError):
                api_endpoint(url)

    def test_every_catalog_request_and_five_response_formats(self):
        captured = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                captured.append((self.path, dict(self.headers), payload))
                if self.path.endswith('/responses'):
                    response = {'status': 'completed', 'output': [{'type': 'reasoning', 'summary': []},
                        {'type': 'message', 'content': [{'type': 'output_text', 'text': '赛道'}]}]}
                elif self.path.endswith('/messages'):
                    response = {'stop_reason': 'end_turn', 'content': [{'type': 'thinking', 'thinking': 'private'}, {'type': 'text', 'text': '赛道'}]}
                elif self.path.endswith(':generateContent'):
                    response = {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [
                        {'thought': True, 'text': 'private'}, {'text': '赛道'}]}}]}
                else:
                    response = {'choices': [{'finish_reason': 'stop', 'message': {'content': '赛道', 'reasoning_content': 'private'}}]}
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())
        server = HTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            for model in MODELS:
                with self.subTest(model=model.id):
                    settings = Settings(mode='API', api_provider=model.provider, api_model=model.id,
                        api_protocol=model.protocol, api_url=f'http://127.0.0.1:{server.server_port}/v1',
                        hotwords='track => 赛道', hotword_weight=3)
                    api = ApiTranslator(settings, 'mock-secret')
                    try:
                        self.assertEqual(api.translate('On the track'), '赛道')
                    finally:
                        api.close()
                    path, headers, payload = captured[-1]
                    if model.protocol == 'qwen-mt':
                        self.assertEqual(len(payload['messages']), 1)
                        self.assertEqual(payload['messages'][0]['role'], 'user')
                        self.assertEqual(payload['translation_options']['terms'], [{'source': 'track', 'target': '赛道'}])
                        self.assertIn('3/5', payload['translation_options']['domains'])
                    if model.provider == 'deepseek' or model.id == 'kimi-k2.6':
                        self.assertEqual(payload['thinking']['type'], 'disabled')
                    if model.protocol == 'messages':
                        self.assertEqual(headers['x-api-key'], 'mock-secret')
                        self.assertNotIn('Authorization', headers)
                    if model.protocol == 'gemini':
                        self.assertEqual(headers['x-goog-api-key'], 'mock-secret')
                        self.assertNotIn('mock-secret', path)
                        if model.id == 'gemini-4-argon':
                            self.assertEqual(payload['generationConfig']['thinkingConfig']['thinkingLevel'], 'low')
                            self.assertEqual(payload['generationConfig']['maxOutputTokens'], 32768)
                    self.assertNotIn('private', api.settings.api_model)
        finally:
            server.shutdown()
            server.server_close()

    def test_incomplete_and_thought_only_outputs_are_rejected(self):
        import httpx
        cases = (
            ('responses', {'status': 'incomplete', 'output': []}),
            ('messages', {'stop_reason': 'max_tokens', 'content': [{'type': 'text', 'text': 'half'}]}),
            ('gemini', {'candidates': [{'finishReason': 'MAX_TOKENS', 'content': {'parts': [{'text': 'half'}]}}]}),
            ('chat', {'choices': [{'finish_reason': 'length', 'message': {'content': 'half'}}]}),
            ('messages', {'stop_reason': 'end_turn', 'content': [{'type': 'thinking', 'thinking': 'private'}]}),
        )
        for protocol, body in cases:
            api = ApiTranslator(Settings(mode='API', api_model='test', api_protocol=protocol), 'mock-secret')
            api.client.close()
            api.client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)))
            try:
                with self.assertRaises(TranslationError) as error:
                    api.translate('Hello')
                self.assertNotIn('mock-secret', str(error.exception))
                self.assertNotIn('private', str(error.exception))
            finally:
                api.close()
