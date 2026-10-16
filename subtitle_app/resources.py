"""Runtime budgets and text-free process monitoring; never changes preferences."""
from collections import OrderedDict, deque
import ctypes
from ctypes import wintypes
import json
import os
import threading
import time

CACHE_ENTRIES = 128
CACHE_BYTES = 4 * 1024 * 1024
NATIVE_SESSIONS = 2
WORKER_PREFIX = 'ATV-'


def text_bytes(value):
    if isinstance(value, str):
        return len(value.encode('utf-8'))
    if isinstance(value, (tuple, list)):
        return sum(text_bytes(item) for item in value)
    return 0


class TranslationCache:
    def __init__(self, entries=CACHE_ENTRIES, budget=CACHE_BYTES):
        self.entries, self.budget = entries, budget
        self.lock = threading.RLock()
        self.items = OrderedDict()
        self.bytes = 0

    def get(self, key):
        with self.lock:
            entry = self.items.get(key)
            if entry is not None:
                self.items.move_to_end(key)
                return entry[0]

    def __setitem__(self, key, value):
        cost = text_bytes(key) + text_bytes(value)
        with self.lock:
            old = self.items.pop(key, None)
            if old:
                self.bytes -= old[1]
            if cost <= min(self.budget, 64 * 1024):
                self.items[key] = (value, cost)
                self.bytes += cost
            while len(self.items) > self.entries or self.bytes > self.budget:
                _, (_, removed) = self.items.popitem(last=False)
                self.bytes -= removed

    def clear(self):
        with self.lock:
            self.items.clear()
            self.bytes = 0

    def snapshot(self):
        with self.lock:
            return {'entries': len(self.items), 'bytes': self.bytes,
                    'entry_limit': self.entries, 'byte_limit': self.budget}


class LatestObservation:
    """One payload and one Qt wake-up, even while the UI thread is blocked."""
    def __init__(self):
        self.lock = threading.Lock()
        self.value = None
        self.pending = False

    def offer(self, session, value):
        with self.lock:
            self.value = (session, value)
            if self.pending:
                return False
            self.pending = True
            return True

    def take(self):
        with self.lock:
            result, self.value, self.pending = self.value, None, False
            return result

    def clear(self):
        with self.lock:
            # An already queued wake-up still owns notification delivery.
            self.value = None


class ProcessMemory(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
        (name, ctypes.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize',
        'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
        'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage', 'PrivateUsage')]


def process_memory(pid=None):
    """Each opened process handle is closed in this call, including failures."""
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessMemory), wintypes.DWORD]
    handle = kernel.OpenProcess(0x410, False, pid or os.getpid())
    if not handle:
        return None
    try:
        value = ProcessMemory()
        value.cb = ctypes.sizeof(value)
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(value), value.cb):
            return None
        handles = wintypes.DWORD()
        kernel.GetProcessHandleCount(handle, ctypes.byref(handles))
        return {'pid': pid or os.getpid(), 'private_bytes': value.PrivateUsage,
                'working_set_bytes': value.WorkingSetSize,
                'peak_working_set_bytes': value.PeakWorkingSetSize, 'handles': handles.value}
    finally:
        kernel.CloseHandle(handle)


class ResourceMonitor:
    def __init__(self, path):
        self.path = path
        self.history = deque(maxlen=60)
        self.next_sample = 0.0

    def sample(self, state, *, force=False):
        now = time.monotonic()
        if not force and now < self.next_sample:
            return None
        self.next_sample = now + 2
        own = process_memory()
        if own is None:
            return None
        item = {'at': round(time.time(), 3), 'translator': own, **state}
        self.history.append(item)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps({'latest': item, 'samples': list(self.history)},
                                             separators=(',', ':')), 'utf-8')
            temporary.replace(self.path)
        except OSError:
            pass
        return item
