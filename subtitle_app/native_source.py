"""Version-gated native caption reading and optional original-renderer translation."""
from __future__ import annotations

from dataclasses import dataclass
from collections import deque
import hashlib
import json
import queue
from pathlib import Path
import threading
import time

from .settings import ROOT, DATA
from . import __version__
from .windows import image_name
from .resources import NATIVE_SESSIONS
from .frida_cleanup import release_destroyed_script


@dataclass(frozen=True)
class NativeCaption:
    text: str
    route: str
    pid: int
    received: float
    updated_ms: int
    token: dict | None = None


def verify_package(package: Path, profile: dict) -> dict:
    expected = profile['package_name'] + '_' + profile['package_version'] + '_x64__'
    if not package.name.startswith(expected):
        raise RuntimeError('此 Apple TV 版本尚未验证，已回退 OCR。')
    for module in profile['modules']:
        with (package / module['name']).open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != module['sha256']:
            raise RuntimeError('Apple TV 模块已更新，直接读取已停用，回退 OCR。')
    return {**profile, 'package_root': str(package)}


class NativeSource:
    def __init__(self, stop: threading.Event, render=False, layout_proof=None):
        self.stop = stop
        self.render = render
        self.layout_proof = layout_proof
        self.controls = queue.Queue(maxsize=1)
        self.closed = threading.Event()
        self.lock = threading.Lock()
        self.latest = None
        # Bounded, text-free evidence: a translation preview is not a draw receipt.
        self.coverage = {}
        self.active_cues = {}
        self.presentations = {}
        self.pacing_events = deque(maxlen=256)
        self.pacing = {}
        self.sessions = {}
        self.failed = set()
        self.errors = []
        self.notice = '正在连接 Apple TV 字幕文本'
        self.counts = {'captions': 0, 'attached': 0, 'errors': 0, 'native_draws': 0, 'restored': 0}
        self.thread = threading.Thread(target=self._run, name='ATV-native', daemon=True)
        self.rpc_lock = threading.Lock()
        self.rpc_pending = {}
        self.rpc_sequence = 0
        self.native_resources = {}
        self.cancellable = None
        self.message_handlers = {}
        self.health_path = None
        self.health_events = deque(maxlen=80)
        self.health_lock = threading.Lock()

    def start(self):
        if self.render:
            self.health_path = DATA / 'diagnostics' / 'native-health.json'
            self._health(0, {'kind': 'starting'})
        self.thread.start()
        return self

    def _health(self, pid, value):
        """Small text-free bridge journal survives leaving playback to report a bug."""
        if self.health_path is None:
            return
        allowed = ('kind', 'event', 'epoch', 'stream_id', 'source_epoch', 'source_stream_id',
                   'presentation_id', 'reason', 'operation', 'request_to_draw_ms')
        event = {'at': round(time.time(), 3), 'pid': pid,
                 **{key: value[key] for key in allowed if key in value}}
        phase = (value.get('layout') or {}).get('paint_phase')
        if phase:
            event['paint_phase'] = phase
        if value.get('error'):
            event['error'] = str(value['error'])[:500]
        with self.health_lock:
            self.health_events.append(event)
            try:
                self.health_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.health_path.with_suffix('.tmp')
                temporary.write_text(json.dumps({'version': __version__, 'last_event': event,
                    'counts': dict(self.counts), 'events': list(self.health_events)},
                    ensure_ascii=False, indent=2), 'utf-8')
                temporary.replace(self.health_path)
            except OSError:
                pass  # Diagnostics must never stop translation or change the profile.

    def snapshot(self):
        with self.lock:
            latest = self.latest
            # A disconnected process must never retain a source indefinitely.
            return latest if latest and latest.pid in self.sessions and latest.pid not in self.failed and time.monotonic() - latest.received < 1.5 else None

    def coverage_snapshot(self):
        with self.lock:
            return [{key: value for key, value in entry.items() if not key.startswith('_')}
                    for entry in self.coverage.values()]

    def presentation_snapshot(self):
        with self.lock:
            return [dict(value) for value in self.presentations.values()]

    def pacing_snapshot(self):
        with self.lock:
            return dict(self.pacing)

    def pacing_events_snapshot(self):
        with self.lock:
            return list(self.pacing_events)

    def _message(self, pid, message, _data):
        if message.get('type') != 'send':
            self.errors.append(str(message.get('description', message.get('type')))[:500])
            self.errors[:] = self.errors[-15:]
            self.counts['errors'] += 1
            self.failed.add(pid)
            self.notice = '字幕文本读取异常，回退 OCR'
            self._health(pid, {'kind': 'script_error', 'error': self.errors[-1]})
            return
        value = message['payload']
        kind = value.get('kind')
        if kind == 'control_result':
            with self.rpc_lock:
                pending = self.rpc_pending.get(value.get('id'))
                if pending and pending['pid'] == pid:
                    pending['reply'] = value
                    pending['event'].set()
            return
        if kind in ('subtitle_pacing', 'presentation_draw_complete'):
            with self.lock:
                self.pacing_events.append({'pid': pid, **value})
                identity = (pid, value['presentation_id'])
                entry = self.presentations.setdefault(identity, {'pid': pid,
                    'presentation_id': value['presentation_id'], 'drawn': False, 'ended': False})
                entry.update({key: value[key] for key in ('source_epoch', 'source_stream_id',
                    'characters', 'base_duration_ms', 'duration_ms', 'lag_ms', 'mode') if key in value})
                if kind == 'presentation_draw_complete':
                    entry.update(drawn=True, host_epoch=value.get('host_epoch'),
                                 request_to_draw_ms=value.get('request_to_draw_ms'), layout=value.get('layout'))
                    self.counts['presentation_draws'] = self.counts.get('presentation_draws', 0) + 1
                elif value.get('event') in ('ended', 'dropped'):
                    entry.update(ended=True, reason=value.get('reason'), shown_ms=value.get('shown_ms'),
                                 dropped=value['event'] == 'dropped')
                if len(self.presentations) > 128:
                    self.presentations.pop(next(iter(self.presentations)))
        if kind == 'bilingual_layout_image' and self.layout_proof and _data:
            from PIL import Image
            folder = Path(self.layout_proof)
            folder.mkdir(parents=True, exist_ok=True)
            Image.frombytes('RGBA', (value['width'], value['height']), bytes(_data)).save(
                folder / f"layout-{pid}-{value['epoch']}.png")
        if kind in ('caption_generation', 'caption_observed', 'native_draw_complete'):
            identity = (pid, value['epoch'])
            with self.lock:
                if kind == 'caption_generation' and self.latest and self.latest.pid == pid:
                    self.latest = NativeCaption('', value.get('route', self.latest.route), pid,
                        time.monotonic(), int(time.time()*1000),
                        {'pid': pid, 'epoch': value['epoch'], 'stream_id': value.get('stream_id',
                            (self.latest.token or {}).get('stream_id', 0)), 'key': '', 'sources': []})
                active = self.active_cues.get(pid)
                if kind in ('caption_generation', 'caption_observed') and active != identity and active in self.coverage:
                    previous = self.coverage[active]
                    if not previous['ended']:
                        previous['ended'] = True
                        previous['duration_ms'] = round((time.monotonic() - previous.pop('_began')) * 1000, 1)
                if kind == 'caption_observed':
                    self.coverage[identity] = {'pid': pid, 'epoch': value['epoch'], 'route': value.get('route'),
                                               'lines': value.get('lines', 0),
                                               'drawn': False, 'ended': False, '_began': time.monotonic()}
                    self.active_cues[pid] = identity
                    if len(self.coverage) > 128:
                        self.coverage.pop(next(iter(self.coverage)))
                elif kind == 'native_draw_complete' and identity in self.coverage:
                    self.coverage[identity]['drawn'] = True
                    self.coverage[identity]['draw_latency_ms'] = value.get('request_to_draw_ms')
                    self.coverage[identity]['drawn_lines'] = value.get('drawn_lines', 0)
                    if value.get('layout'):
                        self.coverage[identity]['layout'] = value['layout']
        if kind in ('caption', 'translate_group'):
            with self.lock:
                if kind == 'caption' and self.latest and int(value.get('updated_ms', 0)) < self.latest.updated_ms:
                    return
                token = {**value, 'pid': pid} if kind == 'translate_group' else None
                text = '\n'.join(value['sources']) if token else str(value.get('text', ''))
                self.latest = NativeCaption(text[:800], value.get('route', ''), pid,
                                            time.monotonic(), int(value.get('updated_ms', value.get('requested_ms', 0))), token)
                self.counts['captions'] += 1
        elif kind == 'native_draw_complete':
            self.counts['native_draws'] += 1
        elif kind == 'bilingual_geometry_restored':
            self.counts['geometry_restored'] = self.counts.get('geometry_restored', 0) + 1
        elif kind in ('read_error', 'bridge_error', 'draw_error', 'measurement_error', 'cleanup_error'):
            self.errors.append(str(value.get('error'))[:500])
            self.errors[:] = self.errors[-15:]
            self.counts['errors'] += 1
            if self.render:
                self.failed.add(pid)
        if kind in ('ready', 'draw_error', 'bridge_error', 'measurement_error', 'read_error',
                    'presentation_draw_complete', 'native_clear_held', 'bilingual_geometry_restored', 'cleanup_error'):
            self._health(pid, value)

    def submit(self, token, texts):
        if not self.render or not token or self.stop.is_set():
            return False
        if not texts or len(texts) != len(token.get('sources', [])) or token['pid'] in self.failed:
            return False
        entry = self.sessions.get(token['pid'])
        if not entry:
            return False
        try:
            entry[1].post({'type': 'translation', 'payload': {**token, 'text': texts[0], 'texts': texts}})
            self.counts['posted'] = self.counts.get('posted', 0) + 1
            return True
        except Exception:
            return False

    def clear_cache(self):
        try:
            self.controls.put_nowait('clear_cache')
        except queue.Full:
            pass  # Repeated mode/cache resets coalesce into one command.

    def resource_snapshot(self):
        return {'sessions': len(self.sessions), 'session_limit': NATIVE_SESSIONS,
                'controls': self.controls.qsize(), 'control_limit': 1,
                'errors': len(self.errors), 'coverage': len(self.coverage),
                'presentations': len(self.presentations), 'pacing_events': len(self.pacing_events),
                'rpc_pending': len(self.rpc_pending), 'scripts': dict(self.native_resources)}

    def _rpc(self, pid, script, method, timeout=1.0, cleanup=False):
        # Public post/message transport. Frida's sync exports wait without a deadline.
        # No per-request threads and no private Frida internals.
        with self.rpc_lock:
            self.rpc_sequence += 1
            identity = self.rpc_sequence
            pending = {'pid': pid, 'event': threading.Event()}
            self.rpc_pending[identity] = pending
        try:
            script.post({'type': 'control', 'payload': {'id': identity, 'method': method}})
            deadline = time.monotonic() + timeout
            while not pending['event'].wait(min(.05, max(0, deadline-time.monotonic()))):
                if not cleanup and (self.stop.is_set() or self.closed.is_set()):
                    raise InterruptedError()
                if time.monotonic() >= deadline:
                    raise TimeoutError('Native caption control timed out')
            reply = pending['reply']
            if reply.get('error'):
                raise RuntimeError('Native caption control failed')
            return reply.get('value')
        finally:
            with self.rpc_lock:
                self.rpc_pending.pop(identity, None)

    def _operation(self, function, *args):
        with self.cancellable:
            return function(*args)

    def _bind_script(self, pid, script):
        callback = lambda message, data: self._message(pid, message, data)
        self.message_handlers[pid] = callback
        script.on('message', callback)

    def _release_script(self, pid, script):
        callback = self.message_handlers.pop(pid, None)
        if callback:
            try:
                script.off('message', callback)
            except Exception:
                pass
        release_destroyed_script(script)

    def _detach(self, pid):
        entry = self.sessions.pop(pid, None)
        if entry:
            session, script = entry
            try:
                self._rpc(pid, script, 'stop', timeout=2, cleanup=True)
                self.counts['restored'] += 1
            except Exception:
                self._health(pid, {'kind': 'cleanup_warning', 'reason': 'stop_unacknowledged'})
            # One failed cleanup must never skip the remaining release operations.
            try:
                script.unload()
            except Exception:
                pass
            try:
                session.detach()
            except Exception:
                pass
            try:
                self._release_script(pid, script)
            except Exception:
                self._health(pid, {'kind': 'cleanup_warning', 'reason': 'callback_release_failed'})
            self.native_resources.pop(pid, None)
            self.active_cues.pop(pid, None)
            self._health(pid, {'kind': 'detached', 'reason': 'native_error' if pid in self.failed else 'stop_or_disconnect'})

    def _run(self):
        try:
            import frida
            self.cancellable = frida.Cancellable()
            device = self._operation(frida.get_local_device)
            profile = json.loads((ROOT / 'native' / 'compatibility.json').read_text('utf-8'))
            bridge = (ROOT / 'native' / ('native-renderer.js' if self.render else 'read-captions.js')).read_text('utf-8')
            if self.render:
                bridge = '\n'.join((ROOT / 'native' / name).read_text('utf-8')
                                   for name in ('caption-pacer.js', 'bilingual-renderer.js')) + '\n' + bridge
            verified = {}
            retry = {}
            processes = []
            next_scan = 0.0
            while not self.stop.is_set() and not self.closed.is_set():
                alive = set()
                if time.monotonic() >= next_scan:
                    processes = self._operation(device.enumerate_processes)
                    next_scan = time.monotonic() + 1.0
                for process in processes:
                    if process.name.lower() != 'amplibraryagent.exe':
                        continue
                    image = Path(image_name(process.pid))
                    if not image.parent.name.startswith(profile['package_name'] + '_'):
                        continue
                    alive.add(process.pid)
                    if process.pid in self.sessions or process.pid in self.failed or time.monotonic() < retry.get(process.pid, 0):
                        continue
                    if len(self.sessions) >= NATIVE_SESSIONS:
                        continue
                    session = script = None
                    try:
                        package = image.parent
                        if package not in verified:
                            verified[package] = verify_package(package, profile)
                        if self.stop.is_set() or self.closed.is_set():
                            break
                        session = self._operation(device.attach, process.pid)
                        script = self._operation(session.create_script, 'const PROFILE=' + json.dumps({**verified[package], 'layout_proof': bool(self.layout_proof)}) + ';\n' + bridge)
                        self._bind_script(process.pid, script)
                        self._operation(script.load)
                        self.sessions[process.pid] = (session, script)
                        self.counts['attached'] += 1
                        self.notice = '已连接 Apple TV 字幕文本，等待字幕'
                    except Exception as exc:
                        self.notice = '当前播放进程暂不能直接读取，回退 OCR'
                        self._health(process.pid, {'kind': 'attach_error', 'error': str(exc)})
                        retry[process.pid] = time.monotonic() + 8
                        if script:
                            try:
                                script.unload()
                            except Exception:
                                pass
                        if session:
                            try:
                                session.detach()
                            except Exception:
                                pass
                        if script:
                            self._release_script(process.pid, script)
                for pid in list(self.sessions):
                    if pid not in alive or pid in self.failed or self.sessions[pid][0].is_detached:
                        self._detach(pid)
                    elif self.render:
                        try:
                            stats = self._rpc(pid, self.sessions[pid][1], 'stats')
                            sources = stats.get('source_group', [])
                            self.native_resources[pid] = stats.get('resources', {})
                            with self.lock:
                                self.pacing = stats.get('pacing', {})
                                if self.latest is None or self.latest.pid == pid or sources:
                                    token = {'pid': pid, 'sources': sources, 'key': stats.get('key'),
                                             'epoch': stats['epoch'], 'route': stats.get('route') or '',
                                             'stream_id': stats.get('stream_id', 0),
                                             'caption_time': stats.get('caption_time'),
                                             'requested_ms': stats.get('requested_ms') or int(time.time() * 1000)}
                                    self.latest = NativeCaption('\n'.join(sources)[:800], token['route'], pid,
                                                                time.monotonic(), token['requested_ms'], token)
                        except Exception:
                            self._detach(pid)
                try:
                    if self.controls.get_nowait() == 'clear_cache':
                        for pid, (_session, script) in list(self.sessions.items()):
                            self._rpc(pid, script, 'clearcache')
                except queue.Empty:
                    pass
                except Exception:
                    pass
                self.failed.intersection_update(alive)
                retry = {pid: value for pid, value in retry.items() if pid in alive}
                self.closed.wait(.1 if self.render else 1.0)
        except Exception:
            self.notice = '直接读取组件不可用，回退 OCR'
        finally:
            for pid in list(self.sessions):
                self._detach(pid)
            with self.lock:
                self.latest = None
                self.pacing.clear()
                self.active_cues.clear()
            self._health(0, {'kind': 'closed'})

    def close(self):
        self.closed.set()
        if self.cancellable:
            self.cancellable.cancel()
        self.thread.join(timeout=4)
        return not self.thread.is_alive()
