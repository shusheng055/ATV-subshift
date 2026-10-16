"""Legacy smoke-test entry point; now validates the original native renderer.

Requires real Apple TV playback. The removed external-overlay fixture must not
be used as evidence of native subtitle replacement.
"""
from pathlib import Path
import runpy

if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'tools' / 'live_native_acceptance.py'),
                   run_name='__main__')
