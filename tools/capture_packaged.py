"""启动打包后的 exe，等待窗口出现并截图，然后结束进程。

用于验证 PyInstaller 产物是否真的能启动并完成示例翻译。
不上屏截图依赖：使用 Win32 PrintWindow，可在窗口被遮挡时抓取内容。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from PySide6.QtGui import QImage

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

# 让截图进程也感知 DPI，否则高缩放下 GetWindowRect 会返回逻辑尺寸，
# PrintWindow 只能画满左上角，导致右侧/底部被裁掉。
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
        ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
        ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def find_window(pid: int):
    found = {"hwnd": 0, "rect": RECT()}

    def callback(hwnd, _lparam):
        proc_id = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
        if proc_id.value != pid or not user32.IsWindowVisible(hwnd):
            return True
        class_name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_name, 256)
        if "qwindow" not in class_name.value.lower():
            return True
        rect = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        if rect.right - rect.left < 600 or rect.bottom - rect.top < 300:
            return True
        found["hwnd"] = hwnd
        found["rect"] = rect
        return False

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return found["hwnd"], found["rect"]


def capture(hwnd: int, rect: RECT) -> QImage | None:
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    screen_dc = user32.GetDC(0)
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
    old = gdi32.SelectObject(mem_dc, bitmap)
    try:
        ok = user32.PrintWindow(hwnd, mem_dc, 2)
        if not ok:
            return None
        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = 0
        buffer = ctypes.create_string_buffer(width * height * 4)
        gdi32.GetDIBits(
            mem_dc, bitmap, 0, height, buffer, ctypes.byref(info), 0
        )
        image = QImage(buffer, width, height, width * 4, QImage.Format.Format_ARGB32).copy()
        return image
    finally:
        gdi32.SelectObject(mem_dc, old)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(0, screen_dc)


def main() -> int:
    exe = os.path.join(HERE, "dist", "Fat_fish", "Fat_fish.exe")
    if not os.path.isfile(exe):
        print("missing exe:", exe)
        return 2
    out = os.path.join(HERE, "docs", "packaged.png")
    proc = subprocess.Popen(
        [exe, "--demo"], cwd=os.path.dirname(exe),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    hwnd = 0
    rect = RECT()
    try:
        deadline = time.time() + 15
        while time.time() < deadline:
            hwnd, rect = find_window(proc.pid)
            if hwnd:
                break
            if proc.poll() is not None:
                print("process exited early, rc =", proc.returncode)
                return 1
            time.sleep(0.3)
        if not hwnd:
            print("window not found")
            return 1
        # 等演示翻译和页面栅格化完成
        time.sleep(4.0)
        image = capture(hwnd, rect)
        if image is None or image.isNull():
            print("capture failed")
            return 1
        os.makedirs(os.path.dirname(out), exist_ok=True)
        image.save(out)
        print(f"captured {out} ({image.width()}x{image.height()})")
        title = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title, 512)
        print("window title:", title.value)
        return 0
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=6)
            except Exception:
                proc.kill()
        print("process stopped")


if __name__ == "__main__":
    raise SystemExit(main())
