"""Actual renderer control flow with mocked CoreText/geometry, no playback."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from subtitle_app.native_compat import load_profiles, relocate_bridge

ROOT = Path(__file__).resolve().parents[1]


class RendererRuntimeTests(unittest.TestCase):
    def test_renderer_in_actual_frida_runtime(self):
        import frida
        worker = subprocess.Popen([sys.executable, '-c', 'import sys; sys.stdin.read()'],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW)
        session = None
        try:
            session = frida.get_local_device().attach(worker.pid)
            code = (ROOT/'tests/renderer_cases.js').read_text('utf-8')
            source = (ROOT/'native/bilingual-renderer.js').read_text('utf-8')
            bridge = (ROOT/'native/native-renderer.js').read_text('utf-8')
            for profile in load_profiles(ROOT / 'native'):
                fixture = relocate_bridge(code, profile)
                address = profile.get('coremedia_rvas', {}).get('0x954210', 0x954210)
                fixture = fixture.replace('ptr(0xa54210)', f'ptr({hex(0x100000 + address)})')
                script = session.create_script(fixture + '\nconst cases=captionRendererCases(' +
                    json.dumps(relocate_bridge(source, profile)) + ',' + json.dumps(relocate_bridge(bridge, profile)) +
                    ');rpc.exports={names(){return cases.names();},run(n){return cases.run(n);}};')
                script.load()
                try:
                    for name in script.exports_sync.names():
                        with self.subTest(version=profile['package_version'], case=name):
                            self.assertTrue(script.exports_sync.run(name))
                finally:
                    script.unload()
        finally:
            if session:
                session.detach()
            worker.stdin.close()
            worker.wait(timeout=5)


if __name__ == '__main__':
    unittest.main(verbosity=2)
