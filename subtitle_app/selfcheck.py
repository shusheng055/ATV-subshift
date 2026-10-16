"""Packaged-runtime verification, invoked explicitly by the build verifier."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile
import time


def run(output: Path):
    from PIL import Image, ImageDraw, ImageFont
    from PySide6.QtWidgets import QApplication
    from .capture import WindowsOCR, NativeText
    from .settings import Settings, load_key, save_key
    from .translation import LocalTranslator
    from .terminology import TermTranslator
    from .ui import MainWindow
    from .windows import find_player

    app = QApplication.instance() or QApplication([])
    report = {"checks": {}, "scope": "bundled runtime; unprotected synthetic text, not Apple TV playback"}
    started = time.monotonic()
    def checkpoint(stage):
        report["stage"] = stage
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    try:
        checkpoint("ocr")
        image = Image.new("RGB", (960, 200), (15, 17, 20))
        ImageDraw.Draw(image).text((180, 70), "Hello, welcome back.",
            font=ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 40), fill="white")
        text, bounds = asyncio.run(WindowsOCR().recognize(image))
        report["checks"]["windows_ocr"] = text == "Hello, welcome back."
        checkpoint("model")
        engine = LocalTranslator()
        before = time.monotonic()
        translated = engine.translate(text)
        report["local_ms"] = round((time.monotonic() - before) * 1000, 1)
        report["translation"] = translated
        report["checks"]["local_model"] = any("\u4e00" <= c <= "\u9fff" for c in translated)
        report["checks"]["protected_term"] = "Apple TV" in TermTranslator(engine, "Apple TV").translate("Apple TV is here.")
        engine.close()
        report['checks']['local_model_release'] = engine.model is None and engine.tokenizer is None
        from .local_worker import LocalWorkerTranslator
        local = LocalWorkerTranslator(Settings(mode='Local'))
        model_pid = local.pid
        try:
            report['checks']['local_worker_translation'] = any('\u4e00' <= c <= '\u9fff'
                for c in local.translate('Hello, welcome back.'))
        finally:
            local.close()
        from .resources import TranslationCache, process_memory, ResourceMonitor
        report['checks']['local_worker_release'] = process_memory(model_pid) is None
        cache = TranslationCache(entries=3, budget=1000)
        for i in range(1000): cache[(str(i),)] = 'test'*80
        state=cache.snapshot()
        report['checks']['cache_budget'] = state['entries']<=3 and state['bytes']<=1000
        with tempfile.TemporaryDirectory() as folder:
            monitor=ResourceMonitor(Path(folder)/'resources.json')
            sample=monitor.sample({'workers':0},force=True)
            report['checks']['memory_monitor'] = sample['translator']['private_bytes']>0 and monitor.path.is_file()
        from .segments import SpeechBuffer
        speech = SpeechBuffer()
        speech.observe("The only thing I want you to", 10)
        first = speech.take(10)
        immediate = first.text == "The only thing I want you to" and not first.allow_wait
        speech.commit(first, 10.5)
        speech.observe("do is stay here.", 11)
        phrase = speech.take(11)
        report["checks"]["conservative_fragment"] = immediate and phrase.text == "do is stay here." and not phrase.allow_wait
        speech.commit(phrase, 11.1)
        speech.observe("He is waiting.", 12)
        report["checks"]["source_context"] = speech.take(12).context == (first.text, phrase.text)
        checkpoint("credentials")
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            save_key("selfcheck-secret", p)
            report["checks"]["dpapi"] = load_key(p) == "selfcheck-secret"
            from .credentials import CredentialStore
            old_bytes = (p / 'credential.dpapi').read_bytes()
            keys = CredentialStore('https://old.example/v1', p)
            keys.set('https://new.example/v1', 'new-selfcheck-secret')
            keys = CredentialStore('https://new.example/v1', p)
            report['checks']['scoped_credentials'] = (keys.get('https://old.example/v1') == 'selfcheck-secret'
                and keys.get('https://new.example/v1') == 'new-selfcheck-secret'
                and (p / 'credential.dpapi').read_bytes() == old_bytes)
        checkpoint("ui")
        window = MainWindow()
        from . import __version__
        report['checks']['release_version'] = __version__ == '1.0.0'
        report['checks']['default_local_light'] = (window.settings.mode == 'Local'
            and window.mode.currentText() == 'Local' and window.settings.theme == 'light')
        presets = window.settings.term_presets
        report['checks']['racing_preset'] = (len(presets) == 1 and presets[0].name == '赛车'
            and presets[0].enabled and len([x for x in presets[0].hotwords.splitlines() if x.strip()]) == 50
            and len([x for x in presets[0].keep_words.splitlines() if x.strip()]) == 192)
        report['checks']['no_personal_credentials'] = not window.credentials.get(window.settings.api_url)
        from .model_catalog import PROVIDERS, models_for
        report['checks']['model_catalog'] = all(models_for(p.id) for p in PROVIDERS if p.id != 'custom')
        report['catalog_options'] = sum(len(models_for(p.id)) for p in PROVIDERS)
        report['checks']['no_overlay_window'] = not any(type(widget).__name__ == 'SubtitleOverlay'
                                                       for widget in app.topLevelWidgets())
        native = NativeText()
        native.close()
        report["checks"]["uia_runtime"] = True
        from .native_source import verify_package
        from .settings import ROOT
        profile = json.loads((ROOT / 'native' / 'compatibility.json').read_text('utf-8'))
        verify_package(Path(profile['package_root']), profile)
        import frida
        report['checks']['native_reader_runtime'] = bool(frida.get_local_device().id)
        checkpoint('pacing')
        import sys
        from .pacing_checks import verify_pacing_runtime
        worker = [sys.executable]
        if not getattr(sys, 'frozen', False):
            worker.append(str(ROOT / 'main.py'))
        report['checks'].update(verify_pacing_runtime(ROOT / 'native', worker + ['--pacing-check-worker']))
        # A local verifier can supply a loopback mock endpoint. No real service is contacted.
        import os
        mock_api = os.environ.get("ATV_SUBSHIFT_TEST_API", "")
        if mock_api:
            from .translation import ApiTranslator
            api = ApiTranslator(Settings(mode="API", api_url=mock_api, api_model="test"), "test-key")
            try:
                report["checks"]["api_transport"] = api.translate("Hello") == "测试译文"
                report["checks"]["api_segment_transport"] = TermTranslator(api, "").translate_segment(
                    "Hello", ("Earlier subtitle.",)) == "测试译文"
                report["checks"]["api_cancellable_transport"] = TermTranslator(api, "").translate_segment(
                    "Hello", ("Earlier subtitle.",), cancelled=lambda: False,
                    deadline=time.monotonic()+3) == "测试译文"
            finally:
                api.close()
            for protocol in ('responses', 'messages', 'gemini', 'qwen-mt'):
                api = ApiTranslator(Settings(mode='API', api_url=mock_api, api_model='test', api_protocol=protocol), 'test-key')
                try:
                    report['checks']['api_' + protocol] = api.translate('Hello') == '测试译文'
                finally:
                    api.close()
        window.show()
        app.processEvents()
        window.grab().save(str(output.with_suffix(".png")))
        window.pages.setCurrentIndex(1)
        app.processEvents()
        window.grab().save(str(output.with_name(output.stem + '-racing.png')))
        window.close()
        # Drain deferred widget deletion while QApplication is still alive. In
        # a frozen windowless self-check, relying on interpreter GC can finalize
        # the application before widgets retained by bound signal handlers.
        from PySide6.QtCore import QCoreApplication, QEvent
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        report["error"] = str(exc)[:300]
    report["elapsed_s"] = round(time.monotonic() - started, 2)
    report["passed"] = bool(report["checks"]) and all(report["checks"].values()) and "error" not in report
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    return 0 if report["passed"] else 1
