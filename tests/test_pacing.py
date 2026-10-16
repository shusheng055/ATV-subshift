"""Run the shipped JS policy in Frida on an isolated owned test process, no player."""
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PacingRuntimeTests(unittest.TestCase):
    def test_shipped_pacing_policy_in_actual_frida_runtime(self):
        import frida
        worker = subprocess.Popen([sys.executable, '-c', 'import sys; sys.stdin.read()'],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW)
        session = None
        try:
            session = frida.get_local_device().attach(worker.pid)
            code = (ROOT/'native/caption-pacer.js').read_text('utf-8') + '\n' + \
                   (ROOT/'tests/pacing_cases.js').read_text('utf-8')
            script = session.create_script(code + '\nconst cases=captionPacingCases();'
                'rpc.exports={names(){return cases.names();},run(name){return cases.run(name);}};')
            script.load()
            names = script.exports_sync.names()
            self.assertGreaterEqual(len(names), 19)
            for name in names:
                with self.subTest(case=name):
                    self.assertTrue(script.exports_sync.run(name))
        finally:
            if session:
                session.detach()
            worker.stdin.close()
            worker.wait(timeout=5)


if __name__ == '__main__':
    unittest.main(verbosity=2)
