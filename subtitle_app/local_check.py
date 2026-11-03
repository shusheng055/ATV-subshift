"""Explicit packaged inference check; never attaches to a player or reads API keys."""
import json
from pathlib import Path
import time

from .local_f1 import LocalF1Translator, MODEL
from .settings import Settings
from .terminology import TermTranslator


def run(output: Path):
    report = {'model': MODEL, 'scope': 'packaged real local inference, no player attachment', 'rows': []}
    engine = None
    try:
        settings = Settings(mode='Local', local_engine='enhanced').resolved()
        began = time.perf_counter()
        engine = LocalF1Translator(settings)
        report['load_ms'] = round((time.perf_counter()-began)*1000, 1)
        translator = TermTranslator(engine, settings.keep_words)
        for source in ('Box, box. Box this lap.',
                       'He has to retire the car with a gearbox problem.',
                       'Hamilton is on the softs, while Verstappen is on the hards.',
                       'The stewards have given him a five-second time penalty.'):
            start = time.perf_counter()
            result = translator.translate_segment(source, deadline=time.monotonic()+8)
            report['rows'].append({'source': source, 'translation': result,
                                   'ms': round((time.perf_counter()-start)*1000, 1)})
        report['passed'] = (all(row['translation'] and row['ms'] < 8000 for row in report['rows'])
                            and 'Hamilton' in report['rows'][2]['translation']
                            and 'Verstappen' in report['rows'][2]['translation'])
    except Exception as exc:
        report['passed'] = False
        report['error'] = type(exc).__name__ + ': ' + str(exc)
    finally:
        if engine is not None:
            engine.close()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
    return 0 if report['passed'] else 1
