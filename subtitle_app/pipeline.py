from __future__ import annotations

import queue
import threading
import time

from PySide6.QtCore import QObject, Signal, QTimer

from .capture import CaptureLoop, Observation, clean_text
from .settings import Settings
from .translation import ApiTranslator, TranslationError
from .local_worker import LocalWorkerTranslator as LocalTranslator
from .terminology import TermTranslator
from .segments import SpeechBuffer, Segment, flatten
from .resources import TranslationCache, LatestObservation, ResourceMonitor, process_memory
from .settings import DATA


class Events(QObject):
    observation = Signal(int, object)
    observation_wake = Signal()
    translated = Signal(int, int, str, str, float, str)
    ready = Signal(int)
    failed = Signal(int, str)


class Pipeline(QObject):
    status = Signal(str)
    state = Signal(bool)
    preview = Signal(str, str)
    caption = Signal(str, str, object)
    clear = Signal()
    player = Signal(object)
    metrics = Signal(str)
    telemetry = Signal(object)
    resources = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.events = Events(self)
        self.events.observation.connect(self._observe)
        self.events.observation_wake.connect(self._drain_observation)
        self.events.translated.connect(self._translated)
        self.events.ready.connect(self._ready)
        self.events.failed.connect(self._failed)
        self.running = False
        self.session = self.sequence = 0
        self.current = self.candidate = ""
        self.origin = ""
        self.native_identity = None
        self.current_player = None
        self.last_seen = self.candidate_since = 0.0
        self.started = 0.0
        self.group_cache = TranslationCache()
        self.observations = LatestObservation()
        self.resource_monitor = ResourceMonitor(DATA / 'diagnostics' / 'resources.json')
        self.speech = SpeechBuffer()
        self.plans = {}
        self.stream_identity = None
        self.latest_token = None
        self.latest_bounds = None
        self.active_plan = None
        self.capture = None
        self.engine = None
        self.subtitle_mode = 'Translated'
        self.threads = []
        self.stop_event = threading.Event()
        self.jobs = queue.Queue(maxsize=1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._expire)
        self.timer.start(100)

    def start(self, settings: Settings, key: str, test_hwnd=0):
        if self.running:
            return
        if self.busy():
            self.status.emit("正在结束上次任务，请稍候再开始。")
            return
        self.settings = settings.resolved()
        self.subtitle_mode = settings.subtitle_mode
        self.running = True
        self.session += 1
        session = self.session
        self.stop_event = threading.Event()
        self.jobs = queue.Queue(maxsize=1)
        self.group_cache.clear()
        self.speech.reset()
        self.plans.clear()
        self.stream_identity = None
        self.latest_token = None
        self.active_plan = None
        self.native_identity = None
        self.origin = ""
        self.current_player = None
        self.current = self.candidate = ""
        self.sequence += 1
        self.started = time.monotonic()
        self.last_seen = self.started
        self.state.emit(True)
        self.preview.emit("", "")
        self.status.emit("正在载入内置离线模型…" if settings.mode == "Local" else "正在准备 API 翻译…")
        self.threads = [threading.Thread(target=self._worker, args=(session, self.stop_event, key, test_hwnd),
                                         name='ATV-translate', daemon=True)]
        self.threads[0].start()

    def _worker(self, session, stop, key, test_hwnd):
        engine = capture = capture_thread = None
        try:
            engine = LocalTranslator(self.settings, cancelled=stop.is_set) if self.settings.mode == "Local" else ApiTranslator(self.settings, key)
            self.engine = engine
            translator = TermTranslator(engine, self.settings.keep_words)
            if stop.is_set():
                return
            self.events.ready.emit(session)
            capture = CaptureLoop(stop, lambda o: self._post_observation(session, o),
                                  self.settings.source, test_hwnd)
            self.capture = capture
            capture_thread = threading.Thread(target=capture.run, name='ATV-capture', daemon=True)
            self.threads.append(capture_thread)
            capture_thread.start()
            while not stop.is_set():
                try:
                    seq, text, requested, native_token = self.jobs.get(timeout=.15)
                except queue.Empty:
                    continue
                began = time.monotonic()
                plan = self.plans.pop(seq, None)
                if seq != self.sequence or began - requested > 2.5:
                    continue
                if plan is None:
                    plan = Segment(flatten('\n'.join(native_token['sources']) if native_token else text),
                                   (), requested, requested, requested, seq)
                try:
                    limit = 3.0 if self.settings.mode == "Local" else 8.0
                    result = self.group_cache.get(plan.cache_key)
                    cached = result is not None
                    if result is None:
                        result = translator.translate_segment(plan.text, context=plan.context,
                            allow_wait=plan.allow_wait,
                            cancelled=lambda: stop.is_set() or seq != self.sequence,
                            deadline=began+limit)
                        if not result.strip():
                            raise TranslationError("未生成完整译文，本句保留原文。")
                        self.group_cache[plan.cache_key] = result
                    texts = [result] + [''] * (len(native_token['sources'])-1) if native_token else None
                    elapsed = time.monotonic() - began
                    if elapsed > limit:
                        self.events.translated.emit(session, seq, text, "", elapsed * 1000, "本句翻译耗时过长，保留原文。")
                    elif not result.strip():
                        raise TranslationError("未生成译文，本句保留原文。")
                    else:
                        if native_token and seq == self.sequence and not stop.is_set():
                            # Keep languages separate. CEA-608 draws individual runs with
                            # CTLine; embedding newlines in each run cannot make bilingual rows.
                            delivery = {**native_token, 'subtitle_mode': self.subtitle_mode,
                                        'paragraph': True, 'display_source': plan.text}
                            if not capture.deliver(delivery, texts):
                                raise TranslationError("译文未能送达 Apple TV，本句保留原文。")
                        self.events.translated.emit(session, seq, text, result,
                                                    (time.monotonic()-plan.observed)*1000, "")
                        self.telemetry.emit({'event': 'translated', 'session': session, 'sequence': seq,
                            'hold_ms': round((plan.ready_at-plan.observed)*1000, 1),
                            'assembly_ms': round((plan.ready_at-plan.started)*1000, 1),
                            'queue_ms': round((began-requested)*1000, 1),
                            'request_ms': round(elapsed*1000, 1),
                            'total_ms': round((time.monotonic()-plan.observed)*1000, 1),
                            'sentence_total_ms': round((time.monotonic()-plan.started)*1000, 1),
                            'context_entries': len(plan.context), 'reason': plan.reason, 'cached': cached})
                except InterruptedError:
                    continue
                except TimeoutError:
                    self.events.translated.emit(session, seq, text, "", 0, "本句翻译超时，保留原文。")
                except TranslationError as exc:
                    self.events.translated.emit(session, seq, text, "", 0, str(exc))
                except Exception:
                    self.events.translated.emit(session, seq, text, "", 0, "翻译失败，本句保留原文。")
        except TranslationError as exc:
            self.events.failed.emit(session, str(exc))
        except Exception:
            self.events.failed.emit(session, "翻译引擎启动失败，请确认应用文件完整。")
        finally:
            stop.set()
            try:
                if engine is not None and hasattr(engine, 'close'):
                    engine.close()
            finally:
                if capture_thread:
                    capture_thread.join()
                native = getattr(capture, 'direct_source', None)
                if native and native.thread.is_alive():
                    # Keep this worker alive until native cleanup really completes.
                    # The restart guard must never hide an orphan bridge thread.
                    native.thread.join()
                if self.capture is capture:
                    self.capture = None
                if self.engine is engine:
                    self.engine = None
                self.group_cache.clear()
                self._discard_jobs()
                self.observations.clear()

    def _post_observation(self, session, observation):
        if session == self.session and not self.stop_event.is_set():
            if self.observations.offer(session, observation):
                self.events.observation_wake.emit()

    def _drain_observation(self):
        entry = self.observations.take()
        if entry and entry[0] == self.session and self.running:
            # Keep the existing instrumentation signal, now emitted on the UI thread.
            self.events.observation.emit(*entry)

    def _discard_jobs(self):
        while True:
            try:
                self.jobs.get_nowait()
            except queue.Empty:
                break

    def _ready(self, session):
        if session == self.session and self.running:
            self.status.emit("已启动，等待 Apple TV 的可读取字幕。")

    def _failed(self, session, message):
        if session == self.session:
            self.stop()
            self.status.emit(message)

    def stop(self):
        self.running = False
        self.stop_event.set()
        self.session += 1
        self.sequence += 1
        self.current = self.candidate = ""
        self.current_player = None
        self.speech.reset()
        self.plans.clear()
        self.active_plan = None
        self.latest_token = self.latest_bounds = self.native_identity = None
        self.stream_identity = None
        self.origin = ''
        self.group_cache.clear()
        self._discard_jobs()
        self.observations.clear()
        self.clear.emit()
        self.player.emit(None)
        self.preview.emit("", "")
        self.state.emit(False)
        self.status.emit("已停止，正在恢复 Apple TV 原始字幕。")

    def _invalidate(self):
        self.sequence += 1
        self.current = self.candidate = ""
        self.clear.emit()
        self.preview.emit("", "")

    def _observe(self, session, observation: Observation):
        if session != self.session or not self.running:
            return
        now = time.monotonic()
        continuous = now-self.last_seen < .8
        previous = self.current_player.hwnd if self.current_player else None
        actual = observation.player.hwnd if observation.player else None
        if previous != actual:
            self._invalidate()
            self.speech.reset()
            self.stream_identity = None
        self.current_player = observation.player
        self.player.emit(observation.player)
        if observation.notice:
            self.status.emit(observation.notice)
            # Never keep old output when capture becomes inaccessible or the window leaves foreground.
            self._invalidate()
            self.speech.reset()
            return
        text = clean_text(observation.text)
        identity = (observation.native_token['pid'], observation.native_token['epoch'], observation.native_token['key']) \
            if observation.native_token else None
        if identity != self.native_identity and self.current:
            self._invalidate()
        self.native_identity = identity
        stream = (actual, observation.origin, observation.native_token.get('pid'),
                  observation.native_token.get('stream_id', 0)) if observation.native_token \
                 else (actual, observation.origin)
        if self.stream_identity is not None and stream != self.stream_identity:
            self.speech.reset()
        self.stream_identity = stream
        if observation.origin != self.origin and self.current:
            self._invalidate()
        self.origin = observation.origin
        self.latest_token = observation.native_token
        if not text:
            self.candidate = ""
            if observation.native_token and self.current:
                self._invalidate()
            if now - self.last_seen > .7:
                if self.current:
                    self._invalidate()
                if now - self.started > 12:
                    self.status.emit("暂未识别到字幕。请开启英文字幕；无对白、暂停或受保护画面也可能没有可读文本。")
            return
        self.last_seen = now
        if text == self.current:
            self.latest_bounds = observation.bounds
            return
        if observation.native_token:
            # Native objects already identify an exact cue. OCR stability debounce
            # would discard short cues and rolling CEA-608 updates before translation.
            self._invalidate()
        else:
            if text != self.candidate:
                self._invalidate()
                self.candidate, self.candidate_since = text, now
                return
            if now - self.candidate_since < .15:
                return
        self.current, self.candidate = text, ""
        self.latest_bounds = observation.bounds
        self.speech.observe(text, now, continuous=continuous)
        self.preview.emit(text, "正在翻译…")
        self.status.emit(f"正在翻译 · {observation.origin}")
        self._queue_segment(now)

    def _queue_segment(self, now):
        if not self.current or now-self.last_seen > .8:
            return
        plan = self.speech.take(now)
        if plan is None:
            return
        self.sequence += 1
        self.plans[self.sequence] = plan
        self.active_plan = (self.sequence, plan)
        # Only the newest queued request can run; context lives independently in speech.
        while len(self.plans) > 8:
            self.plans.pop(next(iter(self.plans)))
        job = (self.sequence, self.current, now, self.latest_token)
        self.preview.emit(self.current, "正在翻译…")
        self.status.emit(f"正在翻译 · {self.origin}")
        try:
            self.jobs.put_nowait(job)
        except queue.Full:
            try:
                self.jobs.get_nowait()
            except queue.Empty:
                pass
            self.jobs.put_nowait(job)

    def _translated(self, session, seq, source, result, latency, error):
        if not self.running or session != self.session or seq != self.sequence or source != self.current:
            return
        if time.monotonic() - self.last_seen > .8:
            return
        if error:
            self.clear.emit()
            self.preview.emit(source, "")
            self.status.emit(error)
            return
        translated_source = source
        if self.active_plan and self.active_plan[0] == seq:
            translated_source = self.active_plan[1].text
            self.speech.commit(self.active_plan[1], time.monotonic())
            self.active_plan = None
        self.preview.emit(translated_source, result)
        self.caption.emit(translated_source, result, self.latest_bounds)
        self.metrics.emit(f"{self.origin}  ·  {self.settings.mode}  ·  译文就绪 {latency:.0f} ms")
        if not self.origin.startswith('Apple TV 原生字幕'):
            self.status.emit('当前只能预览识别结果，原生字幕尚未连接；Apple TV 保留原文。')

    def _expire(self):
        self._sample_resources()
        # Covers hung capture providers, window destruction and delayed queued signals.
        if self.running and self.current and time.monotonic() - self.last_seen > 1.3:
            self._invalidate()
        if self.running:
            self._queue_segment(time.monotonic())
            native = getattr(self.capture, 'direct_source', None)
            pacing = native.pacing_snapshot() if native else {}
            active = pacing.get('active')
            if active and active.get('shown_ms') is not None:
                mode = ('保留当前字幕，等待下一条' if active.get('holding_for_next') else
                        '加速追赶' if active['mode'] == 'catchup' else '正常阅读')
                self.metrics.emit(f"{active['characters']} 字 · 停留 {active['duration_ms']/1000:.1f}s"
                    f" · 滞后 {active['lag_ms']/1000:.1f}s · {mode} · 待显示 {pacing['queue_depth']}")

    def busy(self):
        native = getattr(self.capture, 'direct_source', None)
        return any(thread.is_alive() for thread in self.threads) or bool(native and native.thread.is_alive())

    def _sample_resources(self):
        if time.monotonic() < self.resource_monitor.next_sample:
            return
        native = getattr(self.capture, 'direct_source', None)
        workers = sum(t.is_alive() for t in self.threads)
        if native:
            workers += int(native.thread.is_alive())
        cache = self.group_cache.snapshot()
        state = {'running': self.running, 'workers': workers, 'worker_limit': 3,
                 'jobs': self.jobs.qsize(), 'job_limit': 1,
                 'observations': int(self.observations.value is not None),
                 'cache': cache, 'players': [m for pid in list(native.sessions) if (m := process_memory(pid))]
                 if native else []}
        model_pid = getattr(self.engine, 'pid', None)
        state['local_model'] = process_memory(model_pid) if model_pid else None
        state['local_process_limit'] = 1
        if native:
            state['native'] = native.resource_snapshot()
        sample = self.resource_monitor.sample(state)
        if sample:
            mb = sample['translator']['private_bytes'] / 1048576
            if state['local_model']:
                mb += state['local_model']['private_bytes'] / 1048576
            threshold = 1536 if getattr(getattr(self, 'settings', None), 'mode', '') == 'Local' else 512
            pressure = mb > threshold
            if pressure:
                self.group_cache.clear()  # Never clears the displayed native frame.
            self.resources.emit(f'内存 {mb:.0f} MB · 后台 {workers}/3 · 待译 {self.jobs.qsize()}/1'
                                f' · 缓存 {cache["entries"]}/128' + (' · 内存偏高，已释放历史缓存' if pressure else ''))

    def set_subtitle_mode(self, mode):
        self.subtitle_mode = mode
        if self.running:
            self._invalidate()
            if self.capture:
                self.capture.clear_native_cache()
