import copy
import json
from pathlib import Path
import re
import unittest

from subtitle_app.native_compat import load_profiles, select_profile, relocate_bridge, COREMEDIA_RVAS

ROOT = Path(__file__).resolve().parents[1]


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.profiles = load_profiles(ROOT / 'native')
        self.current = select_profile(Path('AppleInc.AppleTVWin_1.1792.39684.0_x64__test'), self.profiles)
        self.legacy = select_profile(Path('AppleInc.AppleTVWin_1.1540.23558.0_x64__test'), self.profiles)

    def test_unknown_build_rejected(self):
        with self.assertRaises(RuntimeError):
            select_profile(Path('AppleInc.AppleTVWin_1.1792.39685.0_x64__test'), self.profiles)

    def test_new_build_requires_complete_mapping(self):
        for fault in ('absent', 'missing', 'duplicate'):
            profile = copy.deepcopy(self.current)
            if fault == 'absent':
                del profile['coremedia_rvas']
            elif fault == 'missing':
                del profile['coremedia_rvas']['0x953e20']
            else:
                profile['coremedia_rvas']['0x953e20'] = profile['coremedia_rvas']['0x954210']
            with self.subTest(fault=fault), self.assertRaises(RuntimeError):
                relocate_bridge('cm.base.add(0x953e20)', profile)

    def test_all_code_and_string_callers_relocated_without_touching_field_offsets(self):
        source = '\n'.join((ROOT / 'native' / name).read_text('utf-8') for name in
                           ('read-captions.js', 'native-renderer.js', 'bilingual-renderer.js'))
        migrated = relocate_bridge(source, self.current)
        self.assertEqual(relocate_bridge(source, self.legacy), source)
        self.assertFalse(set(int(v, 16) for v in re.findall(r'\b0x[0-9a-f]+\b', migrated)) & COREMEDIA_RVAS)
        self.assertIn("'0xa79630','0xa7a3a6'", migrated)
        self.assertIn('layerUser.add(0x30)', migrated)
        self.assertIn('cm.base.add(0xa85b10)', migrated)
        self.assertIn("['start',0x378c50],['duration',0x3788e0]", migrated)

    def test_every_direct_hook_and_sensitive_callsite_has_live_bytes(self):
        checks = {(h['module'], h['rva']) for h in self.current['hooks']}
        for old in (0x953e20,0x9474f0,0x9578b0,0x954210,0x95a350,0x955030,
                    0x9592b0,0xb1d450,0xb1d580,0x289db0,0x289a40,0x8bdc20,
                    0xb14f10,0x954149,0x954171,0x95417c,0x954410):
            self.assertIn(('CoreMedia.dll',self.current['coremedia_rvas'][hex(old)]), checks)
        for old in (0x947960,0x9486d6):
            self.assertIn(('CoreMedia.dll',self.current['coremedia_rvas'][hex(old)]-6), checks)
