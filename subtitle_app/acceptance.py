"""Explicit live acceptance with per-cue native draw coverage.

Reads preferences without saving them. Reports timings/counts without subtitle
text. Normal app must be closed to avoid duplicate native hooks.
"""
from dataclasses import replace
import json
from pathlib import Path
import time
from unittest.mock import patch


def finalize_report(report, min_cues):
    ended = [row for row in report['cue_coverage'] if row['ended']]
    immediate_missed = [row for row in ended if not row['drawn'] or row.get('lines', 0) < 1
                        or row.get('drawn_lines', 0) != row['lines']]
    presentations = {(row.get('pid'), row.get('source_epoch')): row
                     for row in report.get('presentations', []) if row.get('drawn')
                     and all(isinstance(row.get(key), int) for key in ('pid', 'source_epoch', 'host_epoch'))}
    # Timed reading may draw an original source on a later native host cue.
    # Match by ORIGINAL identity; a held translation cannot cover the host's source.
    def presentation(row):
        return presentations.get((row.get('pid'), row.get('epoch')), {})
    def full_layout(layout):
        return (layout.get('complete') is True and layout.get('characters', 0) > 0
                and layout.get('visible_characters') == layout['characters'])
    missed = [row for row in immediate_missed if not full_layout(presentation(row).get('layout', {}))]
    report.update(ended_cues=len(ended), missed_cues=len(missed),
                  ended_cues_drawn=len(ended) - len(missed),
                  missed_in_original_cue=len(immediate_missed),
                  delayed_original_cues_drawn=len(immediate_missed)-len(missed),
                  expected_rows=sum(row.get('lines', 0) for row in ended),
                  drawn_rows=sum(row.get('drawn_lines', 0) for row in ended))
    report['passed'] = (len(ended) >= min_cues and not missed and report['chinese_output']
                        and (report['native_draws'] > 0 or bool(presentations)) and report['overlay_windows'] == 0
                        and report['errors'] == 0 and report.get('restored_sessions', 0) > 0
                        and all(route.startswith('Apple TV 原生字幕') for route in report['native_routes']))
    if report.get('subtitle_mode') == 'Bilingual':
        layouts = [presentation(row).get('layout') or row.get('layout', {}) for row in ended]
        report['bilingual_complete_cues'] = sum(v.get('complete') is True and v.get('order') == 'zh-then-en'
            and v.get('characters', 0) > 0 and v.get('visible_characters') == v.get('characters') for v in layouts)
        report['passed'] &= report['bilingual_complete_cues'] == len(ended)
    return report


def run(output: Path, seconds=90, min_cues=20):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from .pipeline import Pipeline
    from .settings import Settings
    from .windows import InstanceLock

    lock = InstanceLock()
    if lock.already_running:
        lock.close()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({'passed': False, 'error': 'application_already_running'}), 'utf-8')
        return 1

    class NoOCR:
        def __init__(self, *_):
            raise RuntimeError('OCR deliberately disabled for native acceptance')

    class NoUIA:
        def read(self, _player): return '', None
        def close(self): pass

    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    pipeline = Pipeline()
    settings = replace(Settings.load(), mode='Local', source='en', target='zh-Hans')
    report = {'scope': 'live Apple TV -> local model -> original native renderer; OCR/UIA disabled',
              'seconds': seconds, 'minimum_ended_cues': min_cues, 'translated_results': 0,
              'native_routes': [], 'chinese_output': False, 'native_draws': 0,
              'overlay_windows': 0, 'errors': 0, 'cue_coverage': [], 'subtitle_mode': settings.subtitle_mode}

    def translated(_source, target, _bounds):
        report['translated_results'] += 1
        if pipeline.origin not in report['native_routes']:
            report['native_routes'].append(pipeline.origin)
        report['chinese_output'] |= any('\u3400' <= c <= '\u9fff' for c in target)

    pipeline.caption.connect(translated)
    began = time.monotonic()
    closing = False

    def tick():
        nonlocal closing
        source = pipeline.capture.direct_source if pipeline.capture else None
        if source:
            report['native_draws'] = source.counts['native_draws']
            report['errors'] = source.counts['errors']
            report['native_errors'] = list(source.errors)
            report['restored_sessions'] = source.counts['restored']
            report['geometry_restored'] = source.counts.get('geometry_restored', 0)
            report['cue_coverage'] = source.coverage_snapshot()
            report['presentations'] = source.presentation_snapshot()
            report['pacing_events'] = source.pacing_events_snapshot()
            report['pacing_status'] = source.pacing_snapshot()
        report['overlay_windows'] = sum(type(w).__name__ == 'SubtitleOverlay' for w in app.topLevelWidgets())
        if not closing and time.monotonic() - began >= seconds:
            closing = True
            pipeline.stop()
        if closing and not pipeline.busy():
            timer.stop()
            app.quit()

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(100)
    try:
        from .native_source import NativeSource
        with patch('subtitle_app.capture.WindowsOCR', NoOCR), patch('subtitle_app.capture.NativeText', NoUIA), \
             patch('subtitle_app.capture.NativeSource', lambda stop, render=False: NativeSource(stop, render, output.parent / 'bilingual-layout-proofs')):
            pipeline.start(settings, '')
            app.exec()
        finalize_report(report, min_cues)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
        return 0 if report['passed'] else 1
    finally:
        pipeline.stop()
        lock.close()
