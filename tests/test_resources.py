"""Resource failure paths, real Qt/Frida transport, and overload budgets."""
import asyncio
import gc
import weakref
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication
from subtitle_app.capture import Observation
from subtitle_app.native_source import NativeSource
from subtitle_app.pipeline import Pipeline
from subtitle_app.resources import LatestObservation, TranslationCache, ResourceMonitor, process_memory
from subtitle_app.translation import ApiTranslator, LocalTranslator

ROOT = Path(__file__).resolve().parents[1]


class ResourceTests(unittest.TestCase):
    def test_cache_entry_and_byte_limits_and_large_entry_rejection(self):
        cache = TranslationCache(entries=5, budget=1000)
        for i in range(2000):
            cache[((str(i),), '中文'*20)] = '译文'*20
            self.assertLessEqual(cache.snapshot()['entries'], 5)
            self.assertLessEqual(cache.snapshot()['bytes'], 1000)
        cache[('oversize',)] = 'x'*1001
        self.assertIsNone(cache.get(('oversize',)))
        cache.clear()
        self.assertEqual(cache.snapshot()['bytes'], 0)

    def test_capture_burst_has_one_qt_notification_and_latest_payload(self):
        app = QApplication.instance() or QApplication([])
        pipeline = Pipeline()
        pipeline.timer.stop()
        pipeline.running, pipeline.session = True, 5
        seen = []
        pipeline.events.observation.disconnect(pipeline._observe)
        pipeline.events.observation.connect(lambda session, value: seen.append((session, value.text)))
        thread = threading.Thread(target=lambda: [pipeline._post_observation(5, Observation(str(i)))
                                                   for i in range(10000)])
        thread.start(); thread.join()
        self.assertTrue(pipeline.observations.pending)
        self.assertEqual(pipeline.observations.value[1].text, '9999')
        app.processEvents()
        self.assertEqual(seen, [(5, '9999')])
        pipeline._post_observation(4, Observation('stale'))
        app.processEvents()
        self.assertEqual(len(seen), 1)
        pipeline.stop()

    def test_native_commands_and_errors_are_bounded(self):
        native = NativeSource(threading.Event(), render=True)
        for i in range(10000):
            native.clear_cache()
            native._message(1, {'type':'error', 'description':str(i)}, None)
        self.assertEqual(native.controls.qsize(), 1)
        self.assertEqual(len(native.errors), 15)
        self.assertEqual(native.errors[-1], '9999')

    def test_native_timeout_removes_pending_request_and_still_unloads_detaches(self):
        native = NativeSource(threading.Event(), render=True)
        script, session = Mock(), Mock()
        began = time.monotonic()
        with self.assertRaises(TimeoutError):
            native._rpc(1, script, 'stats', timeout=.05)
        self.assertLess(time.monotonic()-began, .3)
        self.assertEqual(native.rpc_pending, {})
        native.sessions[1] = (session, script)
        script.unload.side_effect = RuntimeError('injected unload error')
        with patch.object(native, '_rpc', side_effect=TimeoutError()):
            native._detach(1)
        script.unload.assert_called_once()
        session.detach.assert_called_once()
        self.assertFalse(native.sessions)

    def test_restart_waits_for_native_cleanup_even_when_capture_worker_ended(self):
        app = QApplication.instance() or QApplication([])
        pipeline = Pipeline(); pipeline.timer.stop()
        release = threading.Event()
        thread = threading.Thread(target=release.wait)
        thread.start()
        pipeline.capture = Mock(direct_source=Mock(thread=thread))
        try:
            self.assertTrue(pipeline.busy())
            with patch.object(pipeline, '_worker') as worker:
                from subtitle_app.settings import Settings
                pipeline.start(Settings(), '')
                worker.assert_not_called()
        finally:
            release.set(); thread.join()
        self.assertFalse(pipeline.busy())

    def test_api_close_failure_still_closes_loop_and_sync_pool(self):
        engine = ApiTranslator.__new__(ApiTranslator)
        engine.loop = loop = asyncio.new_event_loop()
        engine.client = Mock()
        class Broken:
            async def aclose(self): raise RuntimeError('injected close failure')
        engine.async_client = Broken()
        with self.assertRaises(RuntimeError): engine.close()
        self.assertTrue(loop.is_closed())
        engine.client.close.assert_called_once()
        self.assertIsNone(engine.async_client)
        self.assertIsNone(engine.loop)

    def test_local_close_unloads_once_and_drops_model_and_tokenizer(self):
        engine = LocalTranslator.__new__(LocalTranslator)
        engine.model = model = Mock()
        engine.tokenizer = object()
        engine.close(); engine.close()
        model.unload_model.assert_called_once()
        self.assertIsNone(engine.model)
        self.assertIsNone(engine.tokenizer)

    def test_local_cancelled_cue_is_drained_before_next_translation(self):
        from subtitle_app.local_worker import LocalWorkerTranslator
        from subtitle_app.settings import Settings
        engine = LocalWorkerTranslator(Settings(mode='Local'))
        checks = []
        def cancelled():
            checks.append(1)
            return len(checks) >= 2
        pid = engine.pid
        try:
            with self.assertRaises(InterruptedError):
                engine.translate('An obsolete subtitle.', cancelled=cancelled)
            self.assertTrue(engine.pending)
            translated = engine.translate('Hello, welcome back.')
            self.assertFalse(engine.pending)
            self.assertIn('欢迎', translated)
        finally:
            engine.close()
        self.assertIsNone(process_memory(pid))

    def test_actual_local_pipeline_stops_and_releases_model_child(self):
        from subtitle_app.settings import Settings
        from subtitle_app.windows import Player
        app = QApplication.instance() or QApplication([])
        pipeline = Pipeline(); pipeline.timer.stop()
        captions = []
        pipeline.caption.connect(lambda *value: captions.append(value))
        class Capture:
            direct_source = None
            def __init__(self, stop, emit, *_): self.stop,self.emit=stop,emit
            def run(self):
                self.emit(Observation('Hello, welcome back.',Player(1,1,'owned',(0,0,960,540)),
                    'Apple TV 原生字幕 · fixture',native_token={'pid':1,'epoch':1,'key':'test',
                    'sources':['Hello, welcome back.'],'stream_id':1}))
                self.stop.wait()
            def deliver(self, *_): return True
        pid = None
        with patch('subtitle_app.pipeline.CaptureLoop',Capture):
            try:
                pipeline.start(Settings(mode='Local'), '')
                deadline = time.monotonic()+10
                while not captions and time.monotonic()<deadline:
                    app.processEvents();time.sleep(.01)
                    pid = getattr(pipeline.engine,'pid',None) or pid
                self.assertTrue(captions)
                self.assertIn('欢迎', captions[0][1])
            finally:
                pipeline.stop()
                deadline = time.monotonic()+5
                while pipeline.busy() and time.monotonic()<deadline:
                    app.processEvents();time.sleep(.01)
            self.assertFalse(pipeline.busy())
            self.assertIsNone(pipeline.capture)
            self.assertIsNone(pipeline.engine)
            self.assertIsNotNone(pid)
            self.assertIsNone(process_memory(pid))

    def test_monitor_is_bounded_text_free_and_does_not_leak_process_handles(self):
        before = process_memory()
        with tempfile.TemporaryDirectory() as directory:
            monitor = ResourceMonitor(Path(directory)/'resources.json')
            for i in range(200):
                monitor.sample({'workers':0, 'jobs':0}, force=True)
            raw = json.loads(monitor.path.read_text('utf-8'))
            self.assertEqual(len(raw['samples']), 60)
            self.assertLess(monitor.path.stat().st_size, 30000)
            self.assertGreater(raw['latest']['translator']['private_bytes'], 0)
        self.assertLessEqual(process_memory()['handles'], before['handles']+2)

    def test_control_transport_in_real_frida_runtime(self):
        import frida
        worker = subprocess.Popen([sys.executable, '-c', 'import sys;sys.stdin.read()'],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW)
        session = None
        native = NativeSource(threading.Event(), render=True)
        try:
            session = frida.get_local_device().attach(worker.pid)
            channel = (ROOT/'native/native-renderer.js').read_text('utf-8').split('// One request at a time')[1]
            code = "rpc.exports={stats(){return {epoch:7,resources:{heap:Frida.heapSize}};},clearcache(){},stop(){return {restored:true};}};\n// One request at a time"+channel
            script = session.create_script(code)
            native._bind_script(worker.pid,script)
            script.load()
            for _ in range(100):
                result = native._rpc(worker.pid, script, 'stats')
                self.assertEqual(result['epoch'], 7)
            self.assertGreater(result['resources']['heap'], 0)
            self.assertEqual(native.rpc_pending, {})
            native.sessions[worker.pid] = (session,script)
            native._detach(worker.pid)
            self.assertEqual(native.counts['restored'], 1)
            self.assertTrue(session.is_detached)
            reference=weakref.ref(script)
            del script;gc.collect()
            self.assertIsNone(reference(), 'Destroyed Frida wrapper retained its native callbacks')
        finally:
            if session and not session.is_detached: session.detach()
            worker.stdin.close(); worker.wait(timeout=5)


if __name__ == '__main__':
    unittest.main(verbosity=2)
