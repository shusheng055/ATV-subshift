"""Read-only window discovery; no injection, process writes or media access."""
from __future__ import annotations

import ctypes
from ctypes import wintypes as W
from dataclasses import dataclass
from pathlib import Path

user = ctypes.WinDLL("user32", use_last_error=True)
kernel = ctypes.WinDLL("kernel32", use_last_error=True)
HWND = W.HWND
user.IsWindow.argtypes = [HWND]
user.IsWindowVisible.argtypes = [HWND]
user.IsIconic.argtypes = [HWND]
user.GetClientRect.argtypes = [HWND, ctypes.POINTER(W.RECT)]
user.ClientToScreen.argtypes = [HWND, ctypes.POINTER(W.POINT)]
user.GetWindowTextLengthW.argtypes = [HWND]
user.GetWindowTextW.argtypes = [HWND, W.LPWSTR, ctypes.c_int]
user.GetWindowThreadProcessId.argtypes = [HWND, ctypes.POINTER(W.DWORD)]
user.GetForegroundWindow.restype = HWND
user.GetAncestor.argtypes = [HWND, W.UINT]
user.GetAncestor.restype = HWND
user.SetWindowPos.argtypes = [HWND, HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, W.UINT]
user.SetWindowDisplayAffinity.argtypes = [HWND, W.DWORD]
user.SetWindowDisplayAffinity.restype = W.BOOL
user.GetWindowDisplayAffinity.argtypes = [HWND, ctypes.POINTER(W.DWORD)]
kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
kernel.OpenProcess.restype = W.HANDLE
kernel.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, ctypes.POINTER(W.DWORD)]
kernel.CloseHandle.argtypes = [W.HANDLE]


@dataclass(frozen=True)
class Player:
    hwnd: int
    pid: int
    title: str
    rect: tuple[int, int, int, int]  # Physical desktop pixels, x/y/width/height.


def image_name(pid: int) -> str:
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return ""
    try:
        buf, size = ctypes.create_unicode_buffer(32768), W.DWORD(32768)
        return buf.value if kernel.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)) else ""
    finally:
        kernel.CloseHandle(handle)


def client_rect(hwnd: int):
    r, p = W.RECT(), W.POINT(0, 0)
    if not user.IsWindow(hwnd) or not user.GetClientRect(hwnd, ctypes.byref(r)):
        return None
    if not user.ClientToScreen(hwnd, ctypes.byref(p)):
        return None
    return p.x, p.y, r.right, r.bottom


def foreground(hwnd: int) -> bool:
    current = user.GetForegroundWindow()
    return bool(current and (current == hwnd or user.GetAncestor(current, 2) == hwnd))


def find_player(test_hwnd: int = 0) -> Player | None:
    found = []
    callback_type = ctypes.WINFUNCTYPE(W.BOOL, HWND, W.LPARAM)

    def visit(hwnd, _):
        if not user.IsWindowVisible(hwnd) or user.IsIconic(hwnd):
            return True
        rect = client_rect(hwnd)
        if not rect or rect[2] < 320 or rect[3] < 180:
            return True
        pid = W.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if test_hwnd:
            match = hwnd == test_hwnd
        else:
            match = Path(image_name(pid.value)).name.lower() == "appletv.exe"
        if match:
            title = ctypes.create_unicode_buffer(user.GetWindowTextLengthW(hwnd) + 1)
            user.GetWindowTextW(hwnd, title, len(title))
            found.append(Player(hwnd, pid.value, title.value, rect))
        return True

    callback = callback_type(visit)
    user.EnumWindows.argtypes = [callback_type, W.LPARAM]
    user.EnumWindows(callback, 0)
    return max(found, key=lambda p: (foreground(p.hwnd), p.rect[2] * p.rect[3]), default=None)


def place_overlay(hwnd: int, rect):
    user.SetWindowPos(hwnd, HWND(-1), *map(int, rect), 0x0010 | 0x0040)  # NOACTIVATE / SHOWWINDOW


def exclude_from_capture(hwnd: int) -> bool:
    return bool(user.SetWindowDisplayAffinity(hwnd, 0x11))  # WDA_EXCLUDEFROMCAPTURE


class InstanceLock:
    def __init__(self):
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, W.BOOL, W.LPCWSTR]
        kernel.CreateMutexW.restype = W.HANDLE
        self.handle = kernel.CreateMutexW(None, False, "Local\\ATVSubshift.v1")
        self.already_running = ctypes.get_last_error() == 183

    def close(self):
        if self.handle:
            kernel.CloseHandle(self.handle)
            self.handle = None
