"""Actual renderer control flow with mocked CoreText/geometry, no playback."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

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
            script = session.create_script(code + '\nconst cases=captionRendererCases(' +
                json.dumps(source) + ',' + json.dumps(bridge) + ');rpc.exports={names(){return cases.names();},run(n){return cases.run(n);}};')
            script.load()
            for name in script.exports_sync.names():
                with self.subTest(case=name):
                    self.assertTrue(script.exports_sync.run(name))
        finally:
            if session:
                session.detach()
            worker.stdin.close()
            worker.wait(timeout=5)


if __name__ == '__main__':
    unittest.main(verbosity=2)
