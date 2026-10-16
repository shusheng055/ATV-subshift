"""One owned local-model process; process exit releases native allocator caches."""
import multiprocessing
import os
import time

from .translation import TranslationError


def _local_main(connection, settings):
    from .translation import LocalTranslator
    engine = None
    try:
        engine = LocalTranslator(settings)
        connection.send(('ready', os.getpid()))
        while True:
            command, value = connection.recv()
            if command == 'close':
                break
            if command != 'translate' or not isinstance(value, str) or len(value) > 800:
                raise ValueError('Invalid local request')
            connection.send(('translated', engine.translate(value)))
    except (EOFError, BrokenPipeError):
        pass
    except Exception:
        try:
            connection.send(('error', None))
        except (EOFError, BrokenPipeError, OSError):
            pass
    finally:
        try:
            if engine is not None:
                engine.close()
        finally:
            connection.close()


class LocalWorkerTranslator:
    supports_cancellation = True

    def __init__(self, settings, cancelled=None):
        self.settings = settings
        self.pending = False
        context = multiprocessing.get_context('spawn')
        self.connection, child = context.Pipe()
        self.process = context.Process(target=_local_main, args=(child, settings),
                                       name='ATV-local-model', daemon=True)
        self.pid = None
        self.closed = False
        try:
            self.process.start()
            child.close()
            kind, value = self._receive(time.monotonic()+20, cancelled)
            if kind != 'ready':
                raise TranslationError('离线模型启动失败，请确认应用文件完整。')
            self.pid = value  # Actual Python PID, including venv launcher indirection.
        except Exception:
            child.close()
            self.close()
            raise

    def _receive(self, deadline, cancelled=None):
        while True:
            if cancelled and cancelled():
                raise InterruptedError()
            if time.monotonic() >= deadline:
                raise TimeoutError()
            if self.connection.poll(.04):
                try:
                    return self.connection.recv()
                except (EOFError, OSError):
                    raise TranslationError('离线推理进程已退出，请停止后重新启动。') from None
            if not self.process.is_alive():
                raise TranslationError('离线推理进程已退出，请停止后重新启动。')

    def translate(self, text, *, cancelled=None, deadline=None):
        if cancelled and cancelled():
            raise InterruptedError()
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError()
        if self.closed:
            self.__init__(self.settings, cancelled)
        try:
            if self.pending:
                # Finish/discard the cancelled cue before queuing another request.
                # There is never more than one inference inside the child.
                self._receive(deadline or time.monotonic()+3, cancelled)
                self.pending = False
            self.connection.send(('translate', text))
            self.pending = True
            kind, value = self._receive(deadline or time.monotonic()+3, cancelled)
            self.pending = False
            if kind != 'translated':
                raise TranslationError('离线翻译失败。')
            return value
        except TimeoutError:
            self.close()
            raise
        except InterruptedError:
            raise
        except TranslationError:
            self.close()
            raise
        except (EOFError, BrokenPipeError, OSError):
            self.close()
            raise TranslationError('离线推理进程已退出，请停止后重新启动。') from None

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            if self.process.pid is not None:
                try:
                    self.connection.send(('close', None))
                except (EOFError, BrokenPipeError, OSError):
                    pass
                self.process.join(timeout=2)
                if self.process.is_alive():
                    self.process.terminate()
                    self.process.join(timeout=2)
                if self.process.is_alive():
                    raise RuntimeError('Local model process did not exit')
                self.process.close()
        finally:
            self.connection.close()
            self.pid = None
