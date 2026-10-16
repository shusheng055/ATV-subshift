from dataclasses import asdict
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from subtitle_app.settings import Settings
from subtitle_app.presets import TermPreset, active_terms, append_terms, remove_term
from subtitle_app.preset_widgets import PresetManager
from subtitle_app.terminology import TermTranslator, parse_hotwords, choose_candidate


class PresetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_legacy_migration_is_lossless_and_does_not_write_on_load(self):
        raw = {'hotwords': 'track => 赛道\nDownforce => 下压力  \n',
               'keep_words': 'F1\nLewis Hamilton  \n', 'font_size': 22,
               'hotword_weight': 3, 'subtitle_mode': 'Bilingual', 'theme': 'light'}
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            text = json.dumps(raw, ensure_ascii=False)
            (p / 'settings.json').write_text(text, 'utf-8')
            (p / 'credential.dpapi').write_bytes(b'opaque-existing-credential')
            value = Settings.load(p)
            self.assertEqual((p / 'settings.json').read_text('utf-8'), text)
            self.assertEqual(value.term_presets[0].hotwords, raw['hotwords'])
            self.assertEqual(value.term_presets[0].keep_words, raw['keep_words'])
            value.save(p)
            again = Settings.load(p)
            self.assertEqual(again, value)
            self.assertEqual((again.font_size, again.hotword_weight, again.theme), (22, 3, 'light'))
            self.assertEqual((p / 'credential.dpapi').read_bytes(), b'opaque-existing-credential')

    def test_disabled_terms_are_retained_but_do_not_reach_translation(self):
        presets = [TermPreset(name='赛车', hotwords='track => 赛道', keep_words='F1'),
                   TermPreset(name='AI', enabled=False, hotwords='model => 模型', keep_words='GPT')]
        settings = Settings(term_presets=presets).resolved()
        self.assertEqual(settings.hotwords, 'track => 赛道')
        self.assertEqual(settings.keep_words, 'F1')
        seen = []
        class Engine:
            def translate(self, text):
                seen.append(text)
                return '译文'
        TermTranslator(Engine(), settings.keep_words).translate('F1 and GPT')
        self.assertTrue(any('GPT' in line for line in seen))
        self.assertFalse(any('F1' in line for line in seen))
        with tempfile.TemporaryDirectory() as directory:
            settings.save(Path(directory))
            loaded = Settings.load(Path(directory))
            self.assertEqual(loaded.term_presets[1].keep_words, 'GPT')
            self.assertFalse(loaded.term_presets[1].enabled)
            loaded.term_presets[1].enabled = True
            self.assertIn('GPT', loaded.resolved().keep_words)

    def test_enabled_presets_combine_without_double_weighting_duplicates(self):
        presets = [TermPreset(hotwords='track => 赛道', keep_words='F1'),
                   TermPreset(hotwords='TRACK => 赛道\n下压力', keep_words='f1\nGPT')]
        hot, keep = active_terms(presets)
        self.assertEqual(hot, 'track => 赛道\n下压力')
        self.assertEqual(keep, 'F1\nGPT')
        words = parse_hotwords(hot)
        self.assertEqual(choose_candidate([('轨道', -.5), ('赛道', -.8)], words, 'track', 3), '赛道')

    def test_add_remove_and_limit_do_not_rewrite_existing_whitespace(self):
        raw = 'Lewis Hamilton  \nF1\n'
        value = append_terms(raw, ' f1，GPT\nClaude, GPT ')
        self.assertEqual(value, raw + 'GPT\nClaude')
        self.assertEqual(remove_term(value, 2), raw + 'Claude')
        self.assertEqual(append_terms(raw, 'F1'), raw)
        with self.assertRaises(ValueError):
            append_terms('x' * 5999, 'GPT')

    def test_empty_presets_do_not_resurrect_legacy_fields(self):
        settings = Settings(hotwords='old => 旧', keep_words='old', term_presets=[])
        self.assertEqual(active_terms(settings.term_presets), ('', ''))
        with tempfile.TemporaryDirectory() as directory:
            settings.save(Path(directory))
            self.assertEqual(Settings.load(Path(directory)).hotwords, '')

    def test_manager_counts_edit_toggle_delete_undo_and_roundtrip(self):
        original = TermPreset(name='赛车', hotwords='track => 赛道', keep_words='F1\nLewis Hamilton  \n')
        manager = PresetManager([original], 3)
        try:
            drawer = manager.drawers[0]
            self.assertIn('2 不翻译', drawer.count.text())
            drawer.enabled.setChecked(False)
            self.assertEqual(active_terms(manager.values()), ('', ''))
            self.assertEqual(manager.values()[0].keep_words, original.keep_words)
            drawer.enabled.setChecked(True)
            drawer.hotwords.input.setPlainText('downforce => 下压力')
            drawer.hotwords.add()
            drawer.name.setText('F1 赛车')
            manager.remove_preset(drawer)
            self.assertEqual(manager.values(), [])
            manager.undo_delete()
            self.assertEqual(manager.values()[0].name, 'F1 赛车')
            self.assertIn('downforce => 下压力', manager.values()[0].hotwords)
            manager.new_name.setText('AI')
            manager.add_preset()
            self.assertEqual(len(manager.values()), 2)
            with tempfile.TemporaryDirectory() as directory:
                Settings(term_presets=manager.values(), hotword_weight=3).save(Path(directory))
                again = Settings.load(Path(directory))
                self.assertEqual(again.term_presets, manager.values())
        finally:
            manager.deleteLater()


if __name__ == '__main__':
    unittest.main(verbosity=2)
