#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信风格截图工具（Windows / Python + Tk + Pillow，除 Pillow 外零依赖）

功能
----
* 全局热键 Alt+A（可配置）拉起截图，Ctrl+Alt+X 备用
* 全屏冻结 + 遮罩变暗，鼠标悬停自动吸附窗口区域
* 拖拽框选、8 向控制点调整、选区内拖动整体位移、Ctrl+A 全屏
* 标注工具：矩形、椭圆、箭头、画笔、马赛克、文字
* 撤销（Ctrl+Z）、复制到剪贴板（Ctrl+C / Enter）、另存为（Ctrl+S）
* 右键菜单（复制 / 另存为 / 退出），Esc 取消

运行
----
    python wechat_snip.py            # 立即截一次，之后常驻监听热键
    python wechat_snip.py --once     # 截一次就退出
    python wechat_snip.py --daemon   # 不立即截图，只等热键
    python wechat_snip.py --hotkey ctrl+alt+a --theme light
    python wechat_snip.py --selftest out_dir   # 渲染自检，输出预览图
"""

from __future__ import annotations

import argparse
import ctypes
import datetime
import io
import math
import os
import queue
import struct
import sys
import threading
import time
import tkinter as tk
from ctypes import wintypes
from tkinter import filedialog, font as tkfont

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageTk

APP_TITLE = "微信截图"
ICON_FONT = "C:/Windows/Fonts/msyh.ttc"
ICON_FONT_UI_INDEX = 1          # Microsoft YaHei UI
UI_FAMILY = "Microsoft YaHei UI"

# --------------------------------------------------------------------------
# 1. Win32 基础
# --------------------------------------------------------------------------

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000
BI_RGB = 0
CF_DIB = 8
DIB_RGB_COLORS = 0
GA_ROOT = 2
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
SWP_NOACTIVATE = 0x0010
HWND_TOPMOST = -1


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def _declare_prototypes() -> None:
    gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
    gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
    gdi32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    gdi32.SelectObject.restype = ctypes.c_void_p
    gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.BitBlt.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                             ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                             wintypes.DWORD]
    gdi32.BitBlt.restype = wintypes.BOOL
    gdi32.GetDIBits.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT, wintypes.UINT,
                                ctypes.c_void_p, ctypes.POINTER(BITMAPINFO), wintypes.UINT]
    gdi32.GetDIBits.restype = ctypes.c_int
    gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
    gdi32.DeleteDC.argtypes = [ctypes.c_void_p]

    user32.GetDC.restype = ctypes.c_void_p
    user32.GetDC.argtypes = [ctypes.c_void_p]
    user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    user32.SetFocus.argtypes = [ctypes.c_void_p]
    user32.GetAncestor.argtypes = [ctypes.c_void_p, wintypes.UINT]
    user32.GetAncestor.restype = ctypes.c_void_p
    user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(RECT)]
    user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    user32.IsIconic.argtypes = [ctypes.c_void_p]
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]

    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    user32.RegisterClipboardFormatW.restype = wintypes.UINT


_declare_prototypes()


def enable_dpi_awareness() -> None:
    """声明 Per-Monitor V2 DPI 感知，保证画布坐标 == 物理像素。"""
    try:
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def virtual_screen() -> tuple[int, int, int, int]:
    return (user32.GetSystemMetrics(76), user32.GetSystemMetrics(77),
            user32.GetSystemMetrics(78), user32.GetSystemMetrics(79))


def system_dpi() -> int:
    try:
        return user32.GetDpiForSystem() or 96
    except Exception:
        return 96


# --------------------------------------------------------------------------
# 2. 抓屏 / 剪贴板 / 窗口探测
# --------------------------------------------------------------------------

def capture_screen() -> Image.Image:
    """BitBlt 抓取整个虚拟桌面（含分层窗口）。"""
    vx, vy, vw, vh = virtual_screen()
    hdc = user32.GetDC(None)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, vw, vh)
    old = gdi32.SelectObject(mem, bmp)
    gdi32.BitBlt(mem, 0, 0, vw, vh, hdc, vx, vy, SRCCOPY | CAPTUREBLT)
    bi = BITMAPINFO()
    bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.bmiHeader.biWidth = vw
    bi.bmiHeader.biHeight = -vh          # 负高度 = 自上而下
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    bi.bmiHeader.biCompression = BI_RGB
    buf = (ctypes.c_ubyte * (vw * vh * 4))()
    gdi32.GetDIBits(mem, bmp, 0, vh, buf, ctypes.byref(bi), DIB_RGB_COLORS)
    gdi32.SelectObject(mem, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(None, hdc)
    return Image.frombuffer("RGB", (vw, vh), bytes(buf), "raw", "BGRX", 0, 1)


def _dib_bytes(img: Image.Image) -> bytes:
    img = img.convert("RGB")
    w, h = img.size
    header = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, w * h * 3, 0, 0, 0, 0)
    px = img.tobytes()
    out = bytearray()
    for y in range(h - 1, -1, -1):       # DIB 自下而上 + BGR
        row = px[y * w * 3:(y + 1) * w * 3]
        for i in range(0, len(row), 3):
            out += row[i + 2:i + 3]
            out += row[i + 1:i + 2]
            out += row[i:i + 1]
    return header + bytes(out)


def copy_image_to_clipboard(img: Image.Image) -> bool:
    """把图片写入剪贴板：CF_DIB + 注册的 PNG 格式（两路兼容）。"""
    try:
        blob = _dib_bytes(img)
        hmem = kernel32.GlobalAlloc(0x0042, len(blob))
        ptr = kernel32.GlobalLock(hmem)
        ctypes.memmove(ptr, blob, len(blob))
        kernel32.GlobalUnlock(hmem)

        buf = io.BytesIO()
        img.convert("RGB").save(buf, "PNG")
        png = buf.getvalue()
        hmem_png = kernel32.GlobalAlloc(0x0042, len(png))
        ptr_png = kernel32.GlobalLock(hmem_png)
        ctypes.memmove(ptr_png, png, len(png))
        kernel32.GlobalUnlock(hmem_png)
        png_format = user32.RegisterClipboardFormatW("PNG")

        opened = False
        for _ in range(12):
            if user32.OpenClipboard(None):
                opened = True
                break
            time.sleep(0.03)
        if not opened:
            return False
        user32.EmptyClipboard()
        user32.SetClipboardData(CF_DIB, hmem)
        if png_format:
            user32.SetClipboardData(png_format, hmem_png)
        user32.CloseClipboard()
        return True
    except Exception:
        return False


def _is_cloaked(hwnd) -> bool:
    try:
        val = ctypes.c_int(0)
        ctypes.windll.dwmapi.DwmGetWindowAttribute(ctypes.c_void_p(hwnd), 14,
                                                   ctypes.byref(val), ctypes.sizeof(val))
        return bool(val.value)
    except Exception:
        return False


def _window_visible_rect(hwnd):
    """窗口可见区域：优先 DWM 扩展边框（不含隐形缩放边与投影），回退 GetWindowRect。"""
    r = RECT()
    try:
        if ctypes.windll.dwmapi.DwmGetWindowAttribute(
                ctypes.c_void_p(hwnd), 9, ctypes.byref(r), ctypes.sizeof(r)) == 0 \
                and r.right - r.left > 8 and r.bottom - r.top > 8:
            return (r.left, r.top, r.right, r.bottom)
    except Exception:
        pass
    if user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return (r.left, r.top, r.right, r.bottom)
    return None


def top_window_rect_at(x: int, y: int, ignore_pid: int | None = None):
    """返回屏幕坐标 (x0,y0,x1,y1) 下最上层、面积有效的顶层窗口可见矩形。"""
    best = []

    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        if ignore_pid is not None:
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == ignore_pid:
                return True
        rect = _window_visible_rect(hwnd)
        if rect is None:
            return True
        rl, rt, rr, rb = rect
        if not (rl <= x < rr and rt <= y < rb):
            return True
        if rr - rl < 24 or rb - rt < 24:
            return True
        if _is_cloaked(hwnd):
            return True
        best.append(rect)
        return False            # EnumWindows 按 z 序，首个命中即最上层

    CMPFUNC = ctypes.WINFUNCTYPE(wintypes.BOOL, ctypes.c_void_p, ctypes.c_void_p)
    try:
        user32.EnumWindows(CMPFUNC(callback), 0)
    except Exception:
        return None
    return best[0] if best else None


# --------------------------------------------------------------------------
# 3. 主题与图标（Pillow 超采样绘制）
# --------------------------------------------------------------------------

THEMES = {
    "dark": {
        "tb_fill": (40, 40, 42, 240),
        "tb_border": (255, 255, 255, 28),
        "icon": (238, 238, 238, 255),
        "icon_dim": (238, 238, 238, 90),
        "hover": (255, 255, 255, 34),
        "active": (62, 156, 255, 70),
        "menu_bg": "#2c2c2e",
        "menu_fg": "#f2f2f2",
    },
    "light": {
        "tb_fill": (250, 250, 250, 246),
        "tb_border": (0, 0, 0, 26),
        "icon": (58, 58, 60, 255),
        "icon_dim": (58, 58, 60, 90),
        "hover": (0, 0, 0, 26),
        "active": (62, 156, 255, 60),
        "menu_bg": "#f7f7f7",
        "menu_fg": "#1c1c1e",
    },
}

TOOLS = ["rect", "ellipse", "arrow", "pen", "mosaic", "text"]
PALETTE = ["#E64340", "#FF9500", "#FFCC00", "#26B561", "#1E9CFF", "#8C5BD8", "#111111", "#FFFFFF"]

SS = 4                              # 图标超采样倍数


def _draw_icon(kind: str, color, size: int = 22, extra=None) -> Image.Image:
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = s / 22.0
    lw = max(1, int(round(1.7 * u)))

    def P(*pts):
        return [(x * u, y * u) for x, y in pts]

    if kind == "rect":
        d.rounded_rectangle([3.2 * u, 5.2 * u, 18.8 * u, 16.8 * u], radius=1.6 * u,
                            outline=color, width=lw)
    elif kind == "ellipse":
        d.ellipse([3.2 * u, 5.2 * u, 18.8 * u, 16.8 * u], outline=color, width=lw)
    elif kind == "arrow":
        d.line(P((4.4, 17.6), (15.6, 6.4)), fill=color, width=lw)
        d.polygon(P((18.2, 3.8), (11.6, 5.0), (16.0, 9.6)), fill=color)
    elif kind == "pen":
        d.line(P((6.6, 15.4), (15.2, 5.6)), fill=color, width=int(round(3.1 * u)),
               joint="curve")
        d.polygon(P((3.4, 18.6), (7.2, 17.2), (4.6, 14.4)), fill=color)
        d.line(P((12.6, 4.6), (16.4, 8.0)), fill=color, width=lw)
    elif kind == "mosaic":
        cell = 7.4
        for gy in range(2):
            for gx in range(2):
                x0 = 3.6 + gx * (cell + 0.6)
                y0 = 3.4 + gy * (cell + 0.6)
                if (gx + gy) % 2 == 0:
                    d.rounded_rectangle([x0 * u, y0 * u, (x0 + cell) * u, (y0 + cell) * u],
                                        radius=0.8 * u, fill=color)
                else:
                    d.rounded_rectangle([x0 * u, y0 * u, (x0 + cell) * u, (y0 + cell) * u],
                                        radius=0.8 * u, outline=color, width=max(1, lw // 2))
    elif kind == "text":
        try:
            f = ImageFont.truetype(ICON_FONT, int(18 * u), index=ICON_FONT_UI_INDEX)
        except Exception:
            f = ImageFont.load_default()
        d.text((s / 2, s / 2 + 0.6 * u), "T", font=f, fill=color, anchor="mm")
    elif kind == "undo":
        d.arc([4.2 * u, 4.6 * u, 18.4 * u, 18.4 * u], start=20, end=300,
              fill=color, width=lw)
        d.polygon(P((4.0, 3.4), (4.4, 10.0), (10.6, 7.4)), fill=color)
    elif kind == "save":
        d.line(P((11.0, 3.4), (11.0, 13.0)), fill=color, width=lw)
        d.polygon(P((11.0, 17.0), (6.9, 11.4), (15.1, 11.4)), fill=color)
        d.line(P((4.8, 18.6), (17.2, 18.6)), fill=color, width=lw)
    elif kind == "copy":
        d.rounded_rectangle([3.4 * u, 6.6 * u, 14.0 * u, 18.4 * u], radius=1.6 * u,
                            outline=color, width=max(1, lw - 1))
        d.rounded_rectangle([8.2 * u, 3.2 * u, 18.8 * u, 15.0 * u], radius=1.6 * u,
                            outline=color, width=max(1, lw - 1))
    elif kind == "close":
        d.line(P((6.0, 6.0), (16.0, 16.0)), fill=color, width=lw)
        d.line(P((16.0, 6.0), (6.0, 16.0)), fill=color, width=lw)
    elif kind == "swatch":
        d.ellipse([3.6 * u, 3.6 * u, 18.4 * u, 18.4 * u], fill=extra,
                  outline=(255, 255, 255, 220), width=max(1, int(1.2 * u)))
    return img.resize((size, size), Image.LANCZOS)


def _rounded_image(w: int, h: int, radius: int, fill, border=None, border_w: int = 1,
                   shadow: bool = False, pad: int = 12, seps=None):
    """透明圆角面板（可选投影 / 竖分隔线），返回 (图像, pad)。"""
    size = (w + pad * 2, h + pad * 2)
    base = Image.new("RGBA", size, (0, 0, 0, 0))
    if shadow:
        sh = Image.new("RGBA", size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle(
            [pad, pad + 3, pad + w, pad + h + 3], radius=radius, fill=(0, 0, 0, 120))
        sh = sh.filter(ImageFilter.GaussianBlur(5))
        base = Image.alpha_composite(base, sh)
    d = ImageDraw.Draw(base)
    d.rounded_rectangle([pad, pad, pad + w, pad + h], radius=radius, fill=fill,
                        outline=border, width=border_w if border else 0)
    for sx in (seps or []):
        d.line([pad + sx, pad + h / 2 - 9, pad + sx, pad + h / 2 + 9],
               fill=(255, 255, 255, 46), width=1)
    return base, pad


def _arrow_geometry(p1, p2, width: float):
    x1, y1 = p1
    x2, y2 = p2
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length < 2:
        return None
    hl = min(14 + width * 2.0, length * 0.6)
    hw = hl * 0.72
    ux, uy = dx / length, dy / length
    bx, by = x2 - ux * hl, y2 - uy * hl
    px, py = -uy, ux
    head = [(x2, y2), (bx + px * hw / 2, by + py * hw / 2), (bx - px * hw / 2, by - py * hw / 2)]
    return (x1, y1, bx, by), head


# --------------------------------------------------------------------------
# 4. 覆盖层
# --------------------------------------------------------------------------

BTN = 30
GAP = 2
SEP = 9
PADX = 8
PADY = 7
FRAME_COLOR = "#3E9CFF"
HANDLE_SIZE = 7
MAG_SIZE = 96
MAG_ZOOM = 4


def _norm(a, b):
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))


def _in_rect(r, x, y):
    return r is not None and r[0] <= x <= r[2] and r[1] <= y <= r[3]

class SnipOverlay:
    """一次截图会话的全屏交互层。"""

    def __init__(self, app, shot: Image.Image):
        self.app = app
        self.shot = shot
        self.ox, self.oy, self.vw, self.vh = virtual_screen()
        self.scale = max(1.0, app.dpi / 96.0)

        self.win = tk.Toplevel(app.root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.geometry(f"{self.vw}x{self.vh}+0+0")
        self.canvas = tk.Canvas(self.win, width=self.vw, height=self.vh, bd=0,
                                highlightthickness=0, cursor="crosshair", bg="#000000")
        self.canvas.pack(fill="both", expand=True)

        self.theme = THEMES[app.opts.theme]
        self.icons: dict = {}

        # 状态
        self.sel = None
        self.mode = "select"            # select / drag / edit
        self.tool = None
        self.color = PALETTE[0]
        self.text_size = int(18 * self.scale)
        self.annots: list[dict] = []
        self.pending = None
        self.grip = None
        self._drag_origin = None
        self._drag_start = None
        self.entry = None
        self._entry_window = None
        self.hover_rect = None
        self._hover_probe_at = (0, 0)
        self._hover_probe_time = 0.0
        self.tb = None
        self.tb_buttons: dict = {}
        self.hover_btn = None
        self._pressed_btn = None
        self._sel_photo = None
        self._hover_photo = None
        self._mag_photo = None
        self._scene_dirty = False
        self._closed = False

        self._build_base()
        self._bind()
        self.win.update_idletasks()
        self._place_window()
        self.win.deiconify()
        self.win.lift()
        self._activate()

    # ---------------- 窗口定位 / 激活 ----------------

    def _hwnd(self):
        return user32.GetAncestor(ctypes.c_void_p(self.win.winfo_id()), GA_ROOT)

    def _place_window(self):
        hwnd = self._hwnd()
        if hwnd:
            user32.SetWindowPos(ctypes.c_void_p(hwnd), ctypes.c_void_p(HWND_TOPMOST),
                                self.ox, self.oy, self.vw, self.vh, SWP_NOACTIVATE)
        else:
            self.win.geometry(f"{self.vw}x{self.vh}+0+0")

    def _activate(self):
        try:
            self.win.focus_force()
            hwnd = self._hwnd()
            if hwnd:
                user32.SetForegroundWindow(ctypes.c_void_p(hwnd))
                user32.SetFocus(ctypes.c_void_p(hwnd))
        except Exception:
            pass

    # ---------------- 画布初始化 ----------------

    def _build_base(self):
        dim = ImageEnhance.Brightness(self.shot).enhance(0.55)
        self._dim_photo = ImageTk.PhotoImage(dim)
        self.canvas.create_image(0, 0, image=self._dim_photo, anchor="nw", tags=("dim",))
        self.canvas.create_image(0, 0, anchor="nw", tags=("selimg",), state="hidden")
        self.canvas.create_rectangle(0, 0, 0, 0, outline=FRAME_COLOR, width=1,
                                     tags=("frame",), state="hidden")
        for i in range(8):
            self.canvas.create_rectangle(0, 0, 0, 0, fill="#FFFFFF", outline=FRAME_COLOR,
                                         width=1, tags=("handle",), state="hidden")
        self.canvas.create_rectangle(0, 0, 0, 0, outline=FRAME_COLOR, width=1,
                                     dash=(6, 4), tags=("hoverframe",), state="hidden")
        self.canvas.create_image(0, 0, anchor="nw", tags=("hoverimg",), state="hidden")
        self.canvas.create_image(0, 0, anchor="nw", tags=("tbpanel",), state="hidden")
        for _i in range(13):
            self.canvas.create_image(0, 0, anchor="nw", tags=("tbicon",), state="hidden")
            self.canvas.create_image(0, 0, anchor="nw", tags=("tbhov",), state="hidden")
        self.canvas.create_line(0, 0, 0, 0, fill="#101010", tags=("guide",), state="hidden")
        self.canvas.create_line(0, 0, 0, 0, fill="#101010", tags=("guide",), state="hidden")
        self.canvas.create_image(0, 0, anchor="nw", tags=("magimg",), state="hidden")
        self.canvas.create_rectangle(0, 0, 0, 0, outline="#FFFFFF", width=1,
                                     tags=("magframe",), state="hidden")
        self.canvas.create_image(0, 0, anchor="nw", tags=("sizepill",), state="hidden")
        self.canvas.create_text(0, 0, anchor="nw", text="", fill="#FFFFFF", tags=("sizetext",),
                                state="hidden", font=(UI_FAMILY, -int(12 * self.scale)))

        self._sel_img_id = self.canvas.find_withtag("selimg")[0]
        self._frame_id = self.canvas.find_withtag("frame")[0]
        self._hover_img_id = self.canvas.find_withtag("hoverimg")[0]
        self._hover_frame_id = self.canvas.find_withtag("hoverframe")[0]
        self._tb_panel_id = self.canvas.find_withtag("tbpanel")[0]
        self._tb_icon_ids = list(self.canvas.find_withtag("tbicon"))
        self._tb_hov_ids = list(self.canvas.find_withtag("tbhov"))
        self._guide_ids = list(self.canvas.find_withtag("guide"))
        self._mag_img_id = self.canvas.find_withtag("magimg")[0]
        self._mag_frame_id = self.canvas.find_withtag("magframe")[0]
        self._size_pill_id = self.canvas.find_withtag("sizepill")[0]
        self._size_text_id = self.canvas.find_withtag("sizetext")[0]
        self._handle_ids = list(self.canvas.find_withtag("handle"))

    def _bind(self):
        c = self.canvas
        c.bind("<Motion>", self._on_motion)
        c.bind("<ButtonPress-1>", self._on_press)
        c.bind("<ButtonRelease-1>", self._on_release)
        c.bind("<ButtonPress-3>", self._on_right)
        self.win.bind("<Escape>", lambda e: self.cancel())
        self.win.bind("<Return>", lambda e: self.do_copy())
        self.win.bind("<Control-c>", lambda e: self.do_copy())
        self.win.bind("<Control-C>", lambda e: self.do_copy())
        self.win.bind("<Control-s>", lambda e: self.do_save())
        self.win.bind("<Control-S>", lambda e: self.do_save())
        self.win.bind("<Control-z>", lambda e: self.undo())
        self.win.bind("<Control-Z>", lambda e: self.undo())
        self.win.bind("<Control-a>", lambda e: self.select_all())
        self.win.bind("<Control-A>", lambda e: self.select_all())

    # ---------------- 图标缓存 ----------------

    def _icon_photo(self, kind: str, color_key: str = "icon", extra=None) -> ImageTk.PhotoImage:
        if kind == "swatch":
            extra = self.color
        key = (kind, color_key, extra)
        if key in self.icons:
            return self.icons[key]
        img = _draw_icon(kind, self.theme[color_key], 22, extra)
        ph = ImageTk.PhotoImage(img)
        self.icons[key] = ph
        return ph

    # ---------------- 选区工具函数 ----------------

    def _clamp_sel(self, r):
        return (max(0, min(self.vw, r[0])), max(0, min(self.vh, r[1])),
                max(0, min(self.vw, r[2])), max(0, min(self.vh, r[3])))

    def _reset_selection(self):
        self.sel = None
        self.annots.clear()
        self.pending = None
        self.mode = "select"
        self.tool = None
        self._destroy_entry()
        self._clear_preview()
        self._hide_hover()
        self._redraw_scene()

    def _clear_preview(self):
        self.canvas.delete("prev")

    def _hide_hover(self):
        self.canvas.itemconfigure(self._hover_img_id, state="hidden")
        self.canvas.itemconfigure(self._hover_frame_id, state="hidden")

    def select_all(self):
        self.tool = None
        self._destroy_entry()
        self.sel = (0, 0, self.vw, self.vh)
        self.annots.clear()
        self.mode = "edit"
        self._hide_hover()
        self._redraw_scene()

    # ---------------- 标注合成 ----------------

    def _compose(self):
        if not self.sel:
            return None
        x0, y0, x1, y1 = (int(round(v)) for v in self.sel)
        if x1 - x0 < 1 or y1 - y0 < 1:
            return None
        img = self.shot.crop((x0, y0, x1, y1)).copy()
        w, h = img.size
        mosaics = [a for a in self.annots if a["type"] == "mosaic"]
        vectors = [a for a in self.annots if a["type"] != "mosaic"]
        for a in mosaics:
            bx0, by0, bx1, by1 = (int(round(v)) for v in a["box"])
            bx0, by0 = max(0, bx0), max(0, by0)
            bx1, by1 = min(w, bx1), min(h, by1)
            if bx1 - bx0 < 2 or by1 - by0 < 2:
                continue
            block = max(4, a.get("block", 10))
            region = img.crop((bx0, by0, bx1, by1))
            small = region.resize((max(1, (bx1 - bx0) // block), max(1, (by1 - by0) // block)),
                                  Image.NEAREST)
            img.paste(small.resize((bx1 - bx0, by1 - by0), Image.NEAREST), (bx0, by0))
        if vectors:
            layer = Image.new("RGBA", (w * 2, h * 2), (0, 0, 0, 0))
            self._draw_vectors(ImageDraw.Draw(layer), 2, vectors)
            layer = layer.resize((w, h), Image.LANCZOS)
            img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")
        return img

    def _draw_vectors(self, d: ImageDraw.ImageDraw, k: float, annots) -> None:
        for a in annots:
            color = a["color"]
            width = max(1, int(round(a.get("width", 2) * k)))
            t = a["type"]
            if t in ("rect", "ellipse"):
                x0, y0, x1, y1 = [v * k for v in a["box"]]
                if t == "rect":
                    d.rectangle([x0, y0, x1, y1], outline=color, width=width)
                else:
                    d.ellipse([x0, y0, x1, y1], outline=color, width=width)
            elif t == "arrow":
                geo = _arrow_geometry(a["p1"], a["p2"], a.get("width", 2))
                if not geo:
                    continue
                (lx0, ly0, lx1, ly1), head = geo
                d.line([lx0 * k, ly0 * k, lx1 * k, ly1 * k], fill=color, width=width)
                d.polygon([(px * k, py * k) for px, py in head], fill=color)
            elif t == "pen":
                pts = [(px * k, py * k) for px, py in a["points"]]
                if len(pts) > 1:
                    d.line(pts, fill=color, width=width, joint="curve")
                elif pts:
                    r = width / 2
                    d.ellipse([pts[0][0] - r, pts[0][1] - r, pts[0][0] + r, pts[0][1] + r],
                              fill=color)
            elif t == "text":
                px, py = a["pos"][0] * k, a["pos"][1] * k
                fs = max(6, int(round(a.get("size", 18) * k)))
                d.text((px, py), a["text"], font=self._pil_font(fs), fill=color)

    def _pil_font(self, size: int):
        key = ("font", size)
        if key in self.app.font_cache:
            return self.app.font_cache[key]
        try:
            f = ImageFont.truetype(ICON_FONT, size, index=ICON_FONT_UI_INDEX)
        except Exception:
            f = ImageFont.load_default()
        self.app.font_cache[key] = f
        return f

    def _request_scene(self):
        if not self._scene_dirty:
            self._scene_dirty = True
            self.win.after(8, self._do_scene)

    def _do_scene(self):
        self._scene_dirty = False
        self._redraw_scene()

    # ---------------- 场景渲染 ----------------

    def _redraw_scene(self):
        if self._closed:
            return
        c = self.canvas
        big = self.sel and (self.sel[2] - self.sel[0] >= 2) and (self.sel[3] - self.sel[1] >= 2)
        if big:
            img = self._compose()
            if img is not None:
                self._sel_photo = ImageTk.PhotoImage(img)
                c.itemconfigure(self._sel_img_id, image=self._sel_photo, state="normal")
                c.coords(self._sel_img_id, int(round(self.sel[0])), int(round(self.sel[1])))
            else:
                c.itemconfigure(self._sel_img_id, state="hidden")
            x0, y0, x1, y1 = self.sel
            c.coords(self._frame_id, x0, y0, x1, y1)
            c.itemconfigure(self._frame_id, state="normal")
            self._place_handles()
            self._place_size_label()
            self._layout_toolbar()
        else:
            c.itemconfigure(self._sel_img_id, state="hidden")
            c.itemconfigure(self._frame_id, state="hidden")
            self._hide_handles()
            self._hide_toolbar()
            c.itemconfigure(self._size_pill_id, state="hidden")
            c.itemconfigure(self._size_text_id, state="hidden")
        for tag in ("selimg", "frame", "handle", "prev", "sizepill", "sizetext",
                    "tbpanel", "tbicon", "tbhov", "magimg", "magframe"):
            if self.canvas.find_withtag(tag):
                self.canvas.tag_raise(tag)

    def _handle_points(self):
        if not self.sel:
            return []
        x0, y0, x1, y1 = self.sel
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        return [("nw", x0, y0), ("n", mx, y0), ("ne", x1, y0), ("e", x1, my),
                ("se", x1, y1), ("s", mx, y1), ("sw", x0, y1), ("w", x0, my)]

    def _place_handles(self):
        hs = HANDLE_SIZE / 2
        for idx, (_grip, x, y) in enumerate(self._handle_points()):
            self.canvas.coords(self._handle_ids[idx], x - hs, y - hs, x + hs, y + hs)
            self.canvas.itemconfigure(self._handle_ids[idx], state="normal")

    def _hide_handles(self):
        for i in self._handle_ids:
            self.canvas.itemconfigure(i, state="hidden")

    def _place_size_label(self):
        if not self.sel:
            return
        x0, y0, x1, y1 = self.sel
        w, h = int(round(x1 - x0)), int(round(y1 - y0))
        text = f"{w} × {h}"
        f = tkfont.Font(family=UI_FAMILY, size=-int(12 * self.scale))
        tw = f.measure(text)
        th = f.metrics("linespace")
        pw, ph = tw + 16, th + 6
        key = ("pill", pw, ph)
        if key not in self.icons:
            img, pad = _rounded_image(pw, ph, 4, (0, 0, 0, 150))
            self.icons[key] = ImageTk.PhotoImage(img)
            self.icons[key + ("pad",)] = pad
        pill = self.icons[key]
        pad = self.icons[key + ("pad",)]
        lx = min(max(0, x0), self.vw - pw - 4)
        ly = y0 - ph - 4
        if ly < 2:
            ly = min(y1 - ph - 2, y0 + 4)
        ly = max(2, ly)
        self.canvas.coords(self._size_pill_id, lx - pad, ly - pad)
        self.canvas.itemconfigure(self._size_pill_id, image=pill, state="normal")
        self.canvas.coords(self._size_text_id, lx + 8, ly + 3)
        self.canvas.itemconfigure(self._size_text_id, state="normal", text=text)

    # ---------------- 工具栏 ----------------

    def _toolbar_layout(self):
        items = [(t, BTN) for t in TOOLS]
        items += [("swatch", BTN), ("sep", SEP), ("undo", BTN), ("sep", SEP),
                  ("save", BTN), ("copy", BTN), ("close", BTN)]
        w = PADX * 2 + sum(iw for _k, iw in items) + GAP * (len(items) - 1)
        h = BTN + PADY * 2
        x = PADX
        layout, seps = [], []
        for k, iw in items:
            if k == "sep":
                seps.append(x + iw / 2)
                x += iw + GAP
            else:
                layout.append((k, x, PADY, iw, BTN))
                x += iw + GAP
        return w, h, layout, seps

    def _hide_toolbar(self):
        self.tb = None
        self.tb_buttons = {}
        self.canvas.itemconfigure(self._tb_panel_id, state="hidden")
        for i in self._tb_icon_ids:
            self.canvas.itemconfigure(i, state="hidden")
        for i in self._tb_hov_ids:
            self.canvas.itemconfigure(i, state="hidden")

    def _layout_toolbar(self):
        if not self.sel or self.mode in ("drag", "select"):
            self._hide_toolbar()
            return
        w, h, layout, seps = self._toolbar_layout()
        x0, y0, x1, y1 = self.sel
        tx = max(2, min(self.vw - w - 2, x1 - w))
        if y1 + 8 + h <= self.vh - 2:
            ty = y1 + 8
        elif y0 - 8 - h >= 2:
            ty = y0 - 8 - h
        else:
            ty = max(2, min(self.vh - h - 2, y1 - h - 8))
        self.tb = (tx, ty, w, h)
        key = ("tbpanel", w, h, self.app.opts.theme)
        if key not in self.icons:
            img, pad = _rounded_image(w, h, 7, self.theme["tb_fill"],
                                      self.theme["tb_border"], 1, shadow=True, seps=seps)
            self.icons[key] = ImageTk.PhotoImage(img)
            self.icons[key + ("pad",)] = pad
        pad = self.icons[key + ("pad",)]
        self.canvas.itemconfigure(self._tb_panel_id, image=self.icons[key], state="normal")
        self.canvas.coords(self._tb_panel_id, tx - pad, ty - pad)

        self.tb_buttons = {}
        btn_index = 0
        for (k, bx, by, bw, bh) in layout:
            if btn_index >= len(self._tb_icon_ids):
                break
            icon = self._tb_icon_ids[btn_index]
            hov = self._tb_hov_ids[btn_index]
            self.tb_buttons[k] = (tx + bx, ty + by, bw, bh)
            self.canvas.coords(icon, tx + bx + (bw - 22) // 2, ty + by + (bh - 22) // 2)
            self.canvas.itemconfigure(icon, image=self._icon_photo(k, self._icon_key(k)),
                                      state="normal")
            self.canvas.coords(hov, tx + bx, ty + by)
            state = "normal" if self.hover_btn == k else "hidden"
            hkey = ("hover", bw, bh, self.app.opts.theme)
            if hkey not in self.icons:
                img, _p = _rounded_image(bw, bh, 5, self.theme["hover"], pad=0)
                self.icons[hkey] = ImageTk.PhotoImage(img)
            self.canvas.itemconfigure(hov, image=self.icons[hkey], state=state)
            if self.tool == k:
                akey = ("active", bw, bh, self.app.opts.theme)
                if akey not in self.icons:
                    img, _p = _rounded_image(bw, bh, 5, self.theme["active"], pad=0)
                    self.icons[akey] = ImageTk.PhotoImage(img)
                self.canvas.itemconfigure(hov, image=self.icons[akey], state="normal")
            btn_index += 1

    def _icon_key(self, kind: str) -> str:
        if kind == "undo" and not self.annots:
            return "icon_dim"
        return "icon"

    # ---------------- 悬停 / 光标 / 放大镜 ----------------

    def _hit_handle(self, x, y):
        if not self.sel:
            return None
        for grip, hx, hy in self._handle_points():
            if abs(x - hx) <= 7 and abs(y - hy) <= 7:
                return grip
        return None

    def _hit_button(self, x, y):
        for k, (bx, by, bw, bh) in self.tb_buttons.items():
            if bx <= x <= bx + bw and by <= y <= by + bh:
                return k
        return None

    def _in_tb(self, x, y):
        """tb 存储为 (x, y, w, h)。"""
        return (self.tb is not None and self.tb[0] <= x <= self.tb[0] + self.tb[2]
                and self.tb[1] <= y <= self.tb[1] + self.tb[3])

    def _update_cursor(self, x, y):
        cur = "crosshair"
        if self._in_tb(x, y):
            cur = "hand2"
        elif self.mode == "edit" and self.sel:
            grip = self._hit_handle(x, y)
            if grip:
                cur = {"nw": "size_nw_se", "se": "size_nw_se", "ne": "size_ne_sw",
                       "sw": "size_ne_sw", "n": "size_ns", "s": "size_ns",
                       "w": "size_we", "e": "size_we"}[grip]
            elif _in_rect(self.sel, x, y):
                cur = "fleur" if not self.tool else "crosshair"
        try:
            self.canvas.configure(cursor=cur)
        except Exception:
            pass

    def _update_guides(self, x, y, show: bool):
        for gid, horizontal in zip(self._guide_ids, (False, True)):
            if not show:
                self.canvas.itemconfigure(gid, state="hidden")
                continue
            if horizontal:
                self.canvas.coords(gid, 0, y, self.vw, y)
            else:
                self.canvas.coords(gid, x, 0, x, self.vh)
            self.canvas.itemconfigure(gid, state="normal")
        self.canvas.tag_raise("guide")

    def _update_magnifier(self, x: int, y: int, show: bool):
        if not show:
            self.canvas.itemconfigure(self._mag_img_id, state="hidden")
            self.canvas.itemconfigure(self._mag_frame_id, state="hidden")
            return
        src = 24
        half = src // 2
        bx0, by0 = int(x) - half, int(y) - half
        cx0, cy0 = max(0, bx0), max(0, by0)
        cx1, cy1 = min(self.vw, bx0 + src), min(self.vh, by0 + src)
        panel = Image.new("RGBA", (MAG_SIZE, MAG_SIZE), (20, 20, 20, 255))
        if cx1 > cx0 and cy1 > cy0:
            crop = self.shot.crop((cx0, cy0, cx1, cy1)).resize(
                ((cx1 - cx0) * MAG_ZOOM, (cy1 - cy0) * MAG_ZOOM), Image.NEAREST).convert("RGBA")
            panel.paste(crop, ((cx0 - bx0) * MAG_ZOOM, (cy0 - by0) * MAG_ZOOM))
        d = ImageDraw.Draw(panel)
        for gx in range(0, MAG_SIZE + 1, MAG_ZOOM):
            d.line([gx, 0, gx, MAG_SIZE], fill=(255, 255, 255, 38))
        for gy in range(0, MAG_SIZE + 1, MAG_ZOOM):
            d.line([0, gy, MAG_SIZE, gy], fill=(255, 255, 255, 38))
        cxy = (x - bx0) * MAG_ZOOM
        cyy = (y - by0) * MAG_ZOOM
        d.rectangle([cxy, cyy, cxy + MAG_ZOOM, cyy + MAG_ZOOM], outline=(255, 80, 80, 255), width=1)
        d.rectangle([0, 0, MAG_SIZE - 1, MAG_SIZE - 1], outline=(255, 255, 255, 210), width=1)
        self._mag_photo = ImageTk.PhotoImage(panel)
        mx, my = x + 18, y + 18
        if mx + MAG_SIZE > self.vw - 4:
            mx = x - 18 - MAG_SIZE
        if my + MAG_SIZE > self.vh - 4:
            my = y - 18 - MAG_SIZE
        mx, my = max(2, mx), max(2, my)
        self.canvas.itemconfigure(self._mag_img_id, image=self._mag_photo, state="normal")
        self.canvas.coords(self._mag_img_id, mx, my)
        self.canvas.coords(self._mag_frame_id, mx, my, mx + MAG_SIZE, my + MAG_SIZE)
        self.canvas.itemconfigure(self._mag_frame_id, state="normal")
        self.canvas.tag_raise("magimg")
        self.canvas.tag_raise("magframe")

    # ---------------- 事件 ----------------

    def _on_motion(self, e):
        x, y = e.x, e.y
        if self.mode == "drag" and self._drag_start:
            self.sel = self._clamp_sel(_norm(self._drag_start, (x, y)))
            self._hide_hover()
            self._update_guides(x, y, True)
            self._update_magnifier(x, y, True)
            self._request_scene()
            self._update_cursor(x, y)
            return
        if self.grip and self._drag_origin:
            self._apply_grip(x, y)
            self._update_cursor(x, y)
            return
        if self.pending:
            self._drag_annot(x, y)
            self._update_cursor(x, y)
            return
        if self.mode == "select":
            self._hover_probe(x, y)
            self._update_guides(x, y, True)
            self._update_magnifier(x, y, True)
        else:
            self._update_guides(x, y, False)
            self._update_magnifier(x, y, False)
        hover_btn = self._hit_button(x, y) if self._in_tb(x, y) else None
        if hover_btn != self.hover_btn:
            self.hover_btn = hover_btn
            if self.sel:
                self._layout_toolbar()
        self._update_cursor(x, y)

    def _hover_probe(self, x, y):
        if self.app.opts.no_window_detect:
            return
        now = time.time()
        if (abs(x - self._hover_probe_at[0]) < 3 and abs(y - self._hover_probe_at[1]) < 3
                and now - self._hover_probe_time < 0.4):
            return
        if now - self._hover_probe_time < 0.03:
            return
        self._hover_probe_at = (x, y)
        self._hover_probe_time = now
        r = top_window_rect_at(x + self.ox, y + self.oy, os.getpid())
        if r is None:
            if self.hover_rect is not None:
                self.hover_rect = None
                self._hide_hover()
            return
        rect = self._clamp_sel((r[0] - self.ox, r[1] - self.oy, r[2] - self.ox, r[3] - self.oy))
        if rect == self.hover_rect:
            return
        self.hover_rect = rect
        if rect[2] - rect[0] < 2 or rect[3] - rect[1] < 2:
            return
        self._hover_photo = ImageTk.PhotoImage(self.shot.crop(rect))
        self.canvas.itemconfigure(self._hover_img_id, image=self._hover_photo, state="normal")
        self.canvas.coords(self._hover_img_id, rect[0], rect[1])
        self.canvas.itemconfigure(self._hover_frame_id, state="normal")
        self.canvas.coords(self._hover_frame_id, rect[0], rect[1], rect[2], rect[3])
        self.canvas.tag_raise("hoverimg")
        self.canvas.tag_raise("hoverframe")
        self.canvas.tag_raise("guide")
        self.canvas.tag_raise("magimg")

    def _apply_grip(self, x, y):
        ox, oy, sel = self._drag_origin
        x0, y0, x1, y1 = sel
        dx, dy = x - ox, y - oy
        g = self.grip
        if g == "move":
            nx0 = min(max(0, x0 + dx), self.vw - (x1 - x0))
            ny0 = min(max(0, y0 + dy), self.vh - (y1 - y0))
            self.sel = (nx0, ny0, nx0 + (x1 - x0), ny0 + (y1 - y0))
        else:
            nx0, ny0, nx1, ny1 = x0, y0, x1, y1
            if "n" in g:
                ny0 = y
            if "s" in g:
                ny1 = y
            if "w" in g:
                nx0 = x
            if "e" in g:
                nx1 = x
            nx0, ny0, nx1, ny1 = self._clamp_sel((nx0, ny0, nx1, ny1))
            if nx1 - nx0 < 8:
                nx1 = nx0 + 8 if "w" not in g else nx1
                nx0 = nx1 - 8 if "w" in g else nx0
            if ny1 - ny0 < 8:
                ny1 = ny0 + 8 if "n" not in g else ny1
                ny0 = ny1 - 8 if "n" in g else ny0
            self.sel = (nx0, ny0, nx1, ny1)
        self._request_scene()

    def _on_press(self, e):
        x, y = e.x, e.y
        if self.entry is not None:
            self._commit_entry()
        if self._in_tb(x, y):
            btn = self._hit_button(x, y)
            if btn:
                self._pressed_btn = btn
                self._on_button(btn)
            return
        if self.mode == "edit" and self.sel:
            grip = self._hit_handle(x, y)
            if grip:
                self.grip = grip
                self._drag_origin = (x, y, tuple(self.sel))
                return
            if _in_rect(self.sel, x, y):
                if self.tool:
                    self._start_annot(x, y)
                else:
                    self.grip = "move"
                    self._drag_origin = (x, y, tuple(self.sel))
                return
            self._reset_selection()
        self.mode = "drag"
        self._drag_start = (x, y)
        self.sel = (x, y, x, y)
        self._clear_preview()
        self._hide_hover()
        self._redraw_scene()

    def _on_release(self, e):
        x, y = e.x, e.y
        if self._pressed_btn:
            self._pressed_btn = None
            return
        if self.grip:
            self.grip = None
            self._drag_origin = None
            self._redraw_scene()
            return
        if self.pending is not None:
            self._finish_annot(x, y)
            return
        if self.mode == "drag":
            self._drag_start = None
            sel = self.sel
            if sel and sel[2] - sel[0] >= 5 and sel[3] - sel[1] >= 5:
                self.sel = self._clamp_sel(sel)
                self.mode = "edit"
            elif self.hover_rect and self.hover_rect[2] - self.hover_rect[0] >= 5:
                self.sel = self.hover_rect
                self.mode = "edit"
            else:
                self.sel = None
                self.mode = "select"
            self._hide_hover()
            self._update_guides(x, y, False)
            self._update_magnifier(x, y, False)
            self._redraw_scene()

    def _on_right(self, e):
        if self.mode != "edit" or not self.sel:
            self.cancel()
            return
        menu = tk.Menu(self.win, tearoff=0, bg=self.theme["menu_bg"],
                       fg=self.theme["menu_fg"], activebackground=FRAME_COLOR,
                       activeforeground="#ffffff", bd=0)
        menu.add_command(label="复制到剪贴板", command=self.do_copy)
        menu.add_command(label="另存为…", command=self.do_save)
        menu.add_separator()
        menu.add_command(label="退出截图", command=self.cancel)
        try:
            menu.tk_popup(e.x_root, e.y_root)
        finally:
            menu.grab_release()

    # ---------------- 工具栏动作 ----------------

    def _on_button(self, key: str):
        if key in TOOLS:
            if self.entry is not None:
                self._commit_entry()
            self.tool = None if self.tool == key else key
            self._destroy_entry()
            self.hover_btn = key
            self._layout_toolbar()
        elif key == "swatch":
            idx = PALETTE.index(self.color) if self.color in PALETTE else 0
            self.color = PALETTE[(idx + 1) % len(PALETTE)]
            self._layout_toolbar()
        elif key == "undo":
            self.undo()
        elif key == "save":
            self.do_save()
        elif key == "copy":
            self.do_copy()
        elif key == "close":
            self.cancel()

    # ---------------- 标注绘制 ----------------

    def _start_annot(self, x, y):
        t = self.tool
        if t == "text":
            self._open_entry(x, y)
            return
        if t == "mosaic":
            self.pending = {"type": "mosaic", "box": (x, y, x, y),
                            "block": max(6, int(10 * self.scale))}
        elif t == "pen":
            self.pending = {"type": "pen", "points": [(x, y)], "color": self.color,
                            "width": max(2, int(round(3 * self.scale)))}
        elif t == "arrow":
            self.pending = {"type": "arrow", "p1": (x, y), "p2": (x, y), "color": self.color,
                            "width": max(2, int(round(2 * self.scale)))}
        else:
            self.pending = {"type": t, "box": (x, y, x, y), "color": self.color,
                            "width": max(2, int(round(2 * self.scale)))}
        self._drag_annot(x, y)

    def _drag_annot(self, x, y):
        if not self.pending:
            return
        p = self.pending
        self._clear_preview()
        t = p["type"]
        if t in ("rect", "ellipse", "mosaic"):
            box = self._clip_to_sel(_norm((p["box"][0], p["box"][1]), (x, y)))
            p["box"] = box
            if t == "rect":
                self.canvas.create_rectangle(*box, outline=self.color, width=2, tags=("prev",))
            elif t == "ellipse":
                self.canvas.create_oval(*box, outline=self.color, width=2, tags=("prev",))
            else:
                self.canvas.create_rectangle(*box, outline="#FFFFFF", width=1, dash=(4, 3),
                                             tags=("prev",))
        elif t == "pen":
            pt = self._clip_point((x, y))
            p["points"].append(pt)
            flat = [c for xy in p["points"][-64:] for c in xy]
            if len(flat) >= 4:
                self.canvas.create_line(*flat, fill=self.color, width=3, smooth=True,
                                        capstyle="round", joinstyle="round", tags=("prev",))
        elif t == "arrow":
            p2 = self._clip_point((x, y))
            p["p2"] = p2
            geo = _arrow_geometry(p["p1"], p2, p.get("width", 2))
            if geo:
                (lx0, ly0, lx1, ly1), head = geo
                self.canvas.create_line(lx0, ly0, lx1, ly1, fill=self.color, width=2,
                                        tags=("prev",))
                self.canvas.create_polygon([c for xy in head for c in xy], fill=self.color,
                                           outline=self.color, tags=("prev",))
        self.canvas.tag_raise("prev")
        self.canvas.tag_raise("tbpanel")
        self.canvas.tag_raise("tbicon")
        self.canvas.tag_raise("tbhov")

    def _clip_point(self, pt):
        if not self.sel:
            return pt
        x0, y0, x1, y1 = self.sel
        return (min(max(pt[0], x0), x1), min(max(pt[1], y0), y1))

    def _clip_to_sel(self, box):
        if not self.sel:
            return box
        x0, y0, x1, y1 = self.sel
        return (min(max(box[0], x0), x1), min(max(box[1], y0), y1),
                min(max(box[2], x0), x1), min(max(box[3], y0), y1))

    def _finish_annot(self, x, y):
        p = self.pending
        self.pending = None
        self._clear_preview()
        if not p or not self.sel:
            self._redraw_scene()
            return
        x0, y0 = self.sel[0], self.sel[1]
        t = p["type"]
        if t in ("rect", "ellipse", "mosaic"):
            box = p["box"]
            if abs(box[2] - box[0]) < 3 or abs(box[3] - box[1]) < 3:
                self._redraw_scene()
                return
            self.annots.append({"type": t,
                                "box": (box[0] - x0, box[1] - y0, box[2] - x0, box[3] - y0),
                                "color": p.get("color", self.color),
                                "block": p.get("block", 10),
                                "width": p.get("width", 2)})
        elif t == "pen":
            if len(p["points"]) < 2:
                self._redraw_scene()
                return
            self.annots.append({"type": "pen",
                                "points": [(px - x0, py - y0) for px, py in p["points"]],
                                "color": p["color"], "width": p["width"]})
        elif t == "arrow":
            self.annots.append({"type": "arrow",
                                "p1": (p["p1"][0] - x0, p["p1"][1] - y0),
                                "p2": (p["p2"][0] - x0, p["p2"][1] - y0),
                                "color": p["color"], "width": p["width"]})
        self.mode = "edit"
        self._redraw_scene()

    # ---------------- 文字输入 ----------------

    def _open_entry(self, x, y):
        self._destroy_entry()
        if not self.sel:
            return
        px, py = self._clip_point((x, y))
        var = tk.StringVar()

        def _grow(*_a):
            ent.configure(width=max(10, len(var.get()) + 2))

        var.trace_add("write", _grow)
        ent = tk.Entry(self.canvas, textvariable=var, bd=0, highlightthickness=1,
                       highlightbackground=FRAME_COLOR, highlightcolor=FRAME_COLOR,
                       bg="#1c1c1e", fg=self.color, insertbackground=self.color,
                       font=(UI_FAMILY, -self.text_size), relief="flat", width=10)
        ent.bind("<Return>", lambda ev: (self._commit_entry(), "break")[1])
        ent.bind("<Escape>", lambda ev: (self._destroy_entry(), "break")[1])
        ent.bind("<FocusOut>", lambda ev: self._commit_entry())
        self._entry_window = self.canvas.create_window(px, py - 2, window=ent, anchor="nw",
                                                       tags=("entrywin",))
        self.entry = ent
        ent.focus_force()

    def _commit_entry(self):
        if self.entry is None:
            return
        text = self.entry.get()
        pos = list(self.canvas.coords(self._entry_window))
        self._destroy_entry()
        if not self.sel or not text.strip():
            self._redraw_scene()
            return
        x0, y0 = self.sel[0], self.sel[1]
        self.annots.append({"type": "text",
                            "pos": (pos[0] - x0, pos[1] + 2 - y0),
                            "text": text, "color": self.color, "size": self.text_size})
        self._redraw_scene()

    def _destroy_entry(self):
        ent, win_id = self.entry, self._entry_window
        self.entry = None
        self._entry_window = None
        if ent is not None:
            try:
                self.canvas.delete("entrywin")
                ent.destroy()
            except Exception:
                pass

    # ---------------- 撤销 / 输出 ----------------

    def undo(self):
        if self.annots:
            self.annots.pop()
            self._redraw_scene()
            self._layout_toolbar()

    def _final_image(self):
        self._commit_entry()
        return self._compose()

    def do_copy(self):
        img = self._final_image()
        if img is None:
            self.cancel()
            return
        ok = copy_image_to_clipboard(img)
        self.finish(copied=ok)

    def do_save(self):
        img = self._final_image()
        if img is None:
            self.cancel()
            return
        name = f"微信截图_{datetime.datetime.now():%Y%m%d_%H%M%S}.png"
        self.win.withdraw()
        path = filedialog.asksaveasfilename(
            parent=self.app.root, title="保存截图", initialdir=self.app.default_save_dir(),
            initialfile=name, defaultextension=".png",
            filetypes=[("PNG 图片", "*.png"), ("JPEG 图片", "*.jpg"), ("所有文件", "*.*")])
        if not path:
            self.win.deiconify()
            self._place_window()
            self._activate()
            return
        try:
            if path.lower().endswith((".jpg", ".jpeg")):
                img.save(path, quality=95)
            else:
                img.save(path)
            self.finish(saved=path)
        except Exception as exc:
            self.win.deiconify()
            self._place_window()
            self._activate()
            self.app.toast(f"保存失败：{exc}")

    def finish(self, copied: bool = False, saved: str | None = None):
        if self._closed:
            return
        self._closed = True
        try:
            self.win.destroy()
        except Exception:
            pass
        self.app.on_overlay_done(copied, saved)

    def cancel(self):
        self.finish()


# --------------------------------------------------------------------------
# 5. 全局热键
# --------------------------------------------------------------------------

VK_SPECIAL = {"printscreen": 0x2C, "snapshot": 0x2C, "insert": 0x2D, "delete": 0x2E,
              "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22, "space": 0x20}


def parse_hotkey(spec: str):
    parts = [p.strip().lower() for p in spec.replace(" ", "").split("+") if p.strip()]
    if not parts:
        raise ValueError("空的热键")
    mods, vk = 0, None
    for p in parts:
        if p == "alt":
            mods |= MOD_ALT
        elif p in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif p == "shift":
            mods |= MOD_SHIFT
        elif p in ("win", "super", "meta"):
            mods |= MOD_WIN
        elif len(p) == 1 and p.isalnum():
            vk = ord(p.upper())
        elif p.startswith("f") and p[1:].isdigit() and 1 <= int(p[1:]) <= 24:
            vk = 0x70 + int(p[1:]) - 1
        elif p in VK_SPECIAL:
            vk = VK_SPECIAL[p]
        else:
            raise ValueError(f"无法识别的按键: {p}")
    if vk is None:
        raise ValueError("热键缺少主键")
    return mods, vk


class HotkeyThread(threading.Thread):
    def __init__(self, binds, post):
        super().__init__(daemon=True)
        self.binds = binds
        self.post = post
        self.tid = None
        self.id_map: dict[int, str] = {}
        self.registered: list[str] = []
        self.failed: list[str] = []
        self.ready = threading.Event()

    def run(self):
        msg = wintypes.MSG()
        self.tid = kernel32.GetCurrentThreadId()
        for i, (spec, (mods, vk)) in enumerate(self.binds):
            ok = user32.RegisterHotKey(None, 0xB000 + i, mods | MOD_NOREPEAT, vk)
            self.id_map[0xB000 + i] = spec
            (self.registered if ok else self.failed).append(spec)
        self.ready.set()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                self.post(self.id_map.get(int(msg.wParam), "hotkey"))

    def stop(self):
        if self.tid:
            user32.PostThreadMessageW(self.tid, WM_QUIT, 0, 0)


# --------------------------------------------------------------------------
# 6. 应用
# --------------------------------------------------------------------------

class Toast:
    """保存成功后的右下角轻提示。"""

    def __init__(self, root, text, vw, vh, theme):
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        f = tkfont.Font(family=UI_FAMILY, size=-14)
        tw = f.measure(text)
        w, h = tw + 36, 44
        c = tk.Canvas(self.win, width=w, height=h, bd=0, highlightthickness=0,
                      bg="#2c2c2e" if theme == "dark" else "#f2f2f2")
        c.pack()
        c.create_text(w / 2, h / 2, text=text, anchor="center",
                      fill="#FFFFFF" if theme == "dark" else "#1c1c1e", font=f)
        self.win.geometry(f"{w}x{h}+{vw - w - 24}+{vh - h - 60}")
        self.win.lift()

    def destroy(self):
        try:
            self.win.destroy()
        except Exception:
            pass


class SnipApp:
    def __init__(self, opts):
        self.opts = opts
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title(APP_TITLE)
        self.dpi = system_dpi()
        self.font_cache: dict = {}
        self.overlay: SnipOverlay | None = None
        self.hotkey_thread: HotkeyThread | None = None
        self.msg_queue: queue.Queue = queue.Queue()
        self.toasts: list[Toast] = []

    def default_save_dir(self) -> str:
        if self.opts.save_dir:
            os.makedirs(self.opts.save_dir, exist_ok=True)
            return self.opts.save_dir
        home = os.path.expanduser("~")
        for cand in (os.path.join(home, "Pictures"), os.path.join(home, "Desktop"), home):
            if os.path.isdir(cand):
                return cand
        return os.getcwd()

    def start_hotkeys(self):
        binds = []
        for spec in self.opts.hotkeys:
            try:
                binds.append((spec, parse_hotkey(spec)))
            except ValueError as exc:
                print(f"[热键] 忽略 {spec}: {exc}")
        if not binds:
            return
        # 常驻进程无窗口无托盘，必须内置退出热键
        self.quit_hotkey = "ctrl+alt+q"
        binds.append((self.quit_hotkey, parse_hotkey(self.quit_hotkey)))
        self.hotkey_thread = HotkeyThread(binds, self.msg_queue.put)
        self.hotkey_thread.start()
        self.hotkey_thread.ready.wait(1.5)
        hk = self.hotkey_thread
        if hk.registered:
            print(f"[热键] 已注册: {', '.join(hk.registered)}")
        if hk.failed:
            print(f"[热键] 注册失败（可能被其它程序占用）: {', '.join(hk.failed)}")
        if self.quit_hotkey in hk.failed:
            self.quit_hotkey = None
            print("[热键] 退出热键不可用，请用任务管理器结束进程")

    def _poll(self):
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                if msg and msg == getattr(self, "quit_hotkey", None):
                    print("[退出] 收到退出热键，进程结束。")
                    self.quit()
                    return
                self.start_capture()
        except queue.Empty:
            pass
        self.root.after(60, self._poll)

    def start_capture(self):
        if self.overlay is not None:
            return
        self.root.after(self.opts.hide_delay, self._capture_now)

    def _capture_now(self):
        try:
            shot = capture_screen()
        except Exception as exc:
            print("抓屏失败:", exc)
            return
        self.overlay = SnipOverlay(self, shot)

    def on_overlay_done(self, copied: bool, saved: str | None):
        self.overlay = None
        ox, oy, vw, vh = virtual_screen()
        if saved:
            self.toast(f"已保存 {os.path.basename(saved)}")
            print(f"[保存] {saved}")
        elif copied:
            print("[复制] 已写入剪贴板")
        if self.opts.once or self.opts.exit_after:
            if saved:
                self.root.after(1800, self.quit)   # 留时间给"已保存"提示
            else:
                self.quit()
            return
        if not self.hotkey_thread or not self.hotkey_thread.registered:
            self.quit()

    def toast(self, text: str):
        try:
            ox, oy, vw, vh = virtual_screen()
            t = Toast(self.root, text, vw, vh, self.opts.theme)
            self.toasts.append(t)
            self.root.after(1600, t.destroy)
            self.root.after(1800, lambda: self.toasts.remove(t) if t in self.toasts else None)
        except Exception:
            pass

    def quit(self):
        try:
            if self.hotkey_thread:
                self.hotkey_thread.stop()
        except Exception:
            pass
        try:
            self.root.quit()
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        if self.opts.hotkeys:
            self.start_hotkeys()
        if self.opts.daemon:
            # 常驻模式给出可见反馈（exe 双击启动时用户才知道程序已运行）
            self.root.after(900, lambda: self.toast(f"{APP_TITLE}已就绪：Alt+A 截图，Ctrl+Alt+Q 退出"))
        if not self.opts.daemon:
            self.root.after(int(self.opts.delay * 1000), self.start_capture)
        self.root.after(60, self._poll)
        try:
            self.root.mainloop()
        finally:
            if self.hotkey_thread:
                self.hotkey_thread.stop()


# --------------------------------------------------------------------------
# 7. 自检
# --------------------------------------------------------------------------

def selftest(outdir: str) -> int:
    """渲染自检：构造一次完整会话，像素断言 + 事件交互测试，无需人工操作。"""
    os.makedirs(outdir, exist_ok=True)
    opts = argparse.Namespace(theme="dark", no_window_detect=True, hotkeys=[], daemon=True,
                              once=False, exit_after=False, delay=0, hide_delay=0,
                              save_dir=None)
    app = SnipApp.__new__(SnipApp)
    root = tk.Tk()
    root.withdraw()
    app.root = root
    app.opts = opts
    app.dpi = system_dpi()
    app.font_cache = {}
    app.overlay = None
    app.hotkey_thread = None
    app.msg_queue = queue.Queue()
    app.toasts = []

    results: list[tuple[str, bool, str]] = []

    def check(name: str, cond, detail: str = ""):
        results.append((name, bool(cond), detail))
        print(("[PASS] " if cond else "[FAIL] ") + name + (f"  {detail}" if detail else ""))

    def px_close(a, b, tol):
        return all(abs(x - y) <= tol for x, y in zip(a[:3], b[:3]))

    shot = capture_screen()
    # 马赛克测试区注入确定性渐变，使断言不依赖桌面内容
    test_shot = shot.copy()
    g_v = Image.linear_gradient("L").resize((190, 160))
    g_h = Image.linear_gradient("L").transpose(Image.ROTATE_90).resize((190, 160))
    test_shot.paste(Image.merge("RGB", (g_h, g_v, Image.new("L", (190, 160), 128))), (960, 420))
    shot = test_shot
    shot.save(os.path.join(outdir, "selftest_shot.png"))
    ov = SnipOverlay(app, shot)
    root.update()

    # ---------- 1. 静态渲染 ----------
    ov.sel = (260, 180, 1180, 760)
    ov.mode = "edit"
    annots_fixture = [
        {"type": "rect", "box": (30, 30, 360, 190), "color": "#E64340", "width": 2},
        {"type": "ellipse", "box": (400, 30, 700, 190), "color": "#1E9CFF", "width": 2},
        {"type": "arrow", "p1": (60, 460), "p2": (330, 250), "color": "#E64340", "width": 2},
        {"type": "pen", "points": [(380, 430), (430, 400), (470, 450), (520, 395),
                                   (570, 445), (620, 405)], "color": "#26B561", "width": 3},
        {"type": "mosaic", "box": (700, 240, 890, 400), "color": "#FFFFFF", "block": 10},
        {"type": "text", "pos": (60, 520), "text": "微信风格截图 · 自检", "color": "#FFCC00",
         "size": 18},
    ]
    ov.annots = list(annots_fixture)
    ov.tool = "rect"
    ov.hover_btn = "mosaic"
    ov._redraw_scene()
    root.update()
    # 解除真实事件绑定，屏蔽测试期间的物理鼠标干扰（交互阶段走直接调用，不受影响）
    for seq in ("<Motion>", "<ButtonPress-1>", "<ButtonRelease-1>", "<ButtonPress-3>"):
        try:
            ov.canvas.unbind(seq)
        except Exception:
            pass
    time.sleep(0.4)
    # 截图前完整重断言
    ov.sel = (260, 180, 1180, 760)
    ov.mode = "edit"
    ov.tool = "rect"
    ov.hover_btn = "mosaic"
    ov.pending = None
    ov.grip = None
    ov._drag_start = None
    ov.annots = list(annots_fixture)
    ov._redraw_scene()
    root.update()

    overlay_png = os.path.join(outdir, "selftest_overlay.png")
    capture_screen().save(overlay_png)
    final = ov._compose()
    final_path = os.path.join(outdir, "selftest_result.png")
    if final is not None:
        final.save(final_path)
    ovv = Image.open(overlay_png).convert("RGB")
    shv = Image.open(os.path.join(outdir, "selftest_shot.png")).convert("RGB")

    check("选区内为原图亮度", px_close(ovv.getpixel((950, 700)), shv.getpixel((950, 700)), 3))
    dim_expect = tuple(int(round(0.55 * v)) for v in shv.getpixel((100, 100)))
    check("选区外已压暗 0.55", px_close(ovv.getpixel((100, 100)), dim_expect, 4))
    if ov.tb:
        tbx, tby, tbw, tbh = ov.tb
        bg = ovv.getpixel((int(tbx + PADX - 4), int(tby + tbh / 2)))
        check("工具栏深色面板", all(v < 90 for v in bg), str(bg))
        active_img = ov.icons.get(("active", BTN, BTN, "dark"))
        hover_img = ov.icons.get(("hover", BTN, BTN, "dark"))
        check("激活工具高亮(矩形)",
              ov.canvas.itemcget(ov._tb_hov_ids[0], "state") == "normal"
              and active_img is not None
              and str(active_img) == ov.canvas.itemcget(ov._tb_hov_ids[0], "image"))
        check("悬停高亮(马赛克)",
              ov.canvas.itemcget(ov._tb_hov_ids[4], "state") == "normal"
              and hover_img is not None
              and str(hover_img) == ov.canvas.itemcget(ov._tb_hov_ids[4], "image"))
        # 高亮必须与按钮几何对齐（角部采样：高亮色 vs 面板底色）
        act = ovv.getpixel((int(ov.tb_buttons["rect"][0] + 2), int(ov.tb_buttons["rect"][1] + 2)))
        check("激活高亮与按钮对齐", act[2] - bg[2] > 20, f"{act} vs {bg}")
        hpx = ovv.getpixel((int(ov.tb_buttons["mosaic"][0] + 2),
                            int(ov.tb_buttons["mosaic"][1] + 2)))
        check("悬停高亮与按钮对齐", sum(hpx) - sum(bg) > 20, f"{hpx} vs {bg}")
    else:
        check("工具栏已布局", False, "tb is None")
    check("选区边框颜色", px_close(ovv.getpixel((260, 350)), (62, 156, 255), 70),
          str(ovv.getpixel((260, 350))))
    check("矩形标注红线", px_close(ovv.getpixel((465, 210)), (230, 67, 64), 40),
          str(ovv.getpixel((465, 210))))
    has_yellow = False
    for yy in range(0, 50, 2):
        for xx in range(0, 260, 3):
            if px_close(ovv.getpixel((300 + xx, 690 + yy)), (255, 204, 0), 45):
                has_yellow = True
                break
        if has_yellow:
            break
    check("文字标注渲染", has_yellow)
    diff = 0
    for xx in range(960, 1150, 20):
        for yy in range(420, 580, 20):
            a, b = ovv.getpixel((xx, yy)), shv.getpixel((xx, yy))
            diff += sum(abs(p - q) for p, q in zip(a, b))
    check("马赛克已像素化", diff > 200, f"diff={diff}")
    check("成品导出尺寸", final is not None and final.size == (920, 580))
    ok_clip = copy_image_to_clipboard(final) if final is not None else False
    check("剪贴板写入", ok_clip)
    from PIL import ImageGrab
    back = ImageGrab.grabclipboard()
    check("剪贴板回读", back is not None and getattr(back, "size", None) == (920, 580),
          str(getattr(back, "size", None)))

    # ---------- 2. 事件交互（直接调用处理器，绕过系统事件队列，零干扰） ----------
    class _Ev:
        def __init__(self, x, y):
            self.x, self.y = x, y

    def press(x, y):
        ov._on_press(_Ev(x, y))

    def move(x, y):
        ov._on_motion(_Ev(x, y))

    def release(x, y):
        ov._on_release(_Ev(x, y))

    def click_btn(key):
        bx, by, bw, bh = ov.tb_buttons[key]
        press(int(bx + bw / 2), int(by + bh / 2))
        release(int(bx + bw / 2), int(by + bh / 2))

    ov._reset_selection()
    press(300, 200)
    move(900, 600)
    release(900, 600)
    check("拖拽框选生效", ov.mode == "edit" and ov.sel == (300, 200, 900, 600),
          f"mode={ov.mode} sel={ov.sel}")
    check("工具栏可见", ov.tb is not None)

    click_btn("rect")
    check("点选矩形工具", ov.tool == "rect")
    press(400, 300)
    move(700, 450)
    release(700, 450)
    check("绘制矩形标注", len(ov.annots) == 1 and ov.annots[0]["type"] == "rect"
          and ov.annots[0]["box"] == (100, 100, 400, 250), str(ov.annots))

    n_before = len(ov.annots)
    ov.undo()
    check("撤销生效", len(ov.annots) == n_before - 1)

    click_btn("swatch")
    check("取色切换", ov.color == PALETTE[1], ov.color)

    click_btn("text")
    check("点选文字工具", ov.tool == "text")
    press(500, 500)
    check("文字输入框出现", ov.entry is not None)
    if ov.entry:
        ov.entry.insert(0, "测试ABC")
        ov._commit_entry()
    check("文字标注提交", len(ov.annots) == n_before and ov.annots[-1]["type"] == "text"
          and ov.annots[-1]["text"] == "测试ABC", str(ov.annots[-1] if ov.annots else None))

    click_btn("mosaic")
    press(700, 300)
    move(820, 380)
    release(820, 380)
    check("马赛克标注", ov.annots[-1]["type"] == "mosaic")

    click_btn("arrow")
    press(400, 560)
    move(650, 450)
    release(650, 450)
    check("箭头标注", bool(ov.annots) and ov.annots[-1]["type"] == "arrow")

    click_btn("pen")
    press(350, 560)
    move(420, 520)
    move(480, 560)
    release(480, 560)
    check("画笔标注", bool(ov.annots) and ov.annots[-1]["type"] == "pen"
          and len(ov.annots[-1]["points"]) >= 3)

    n_pen = len(ov.annots)
    click_btn("undo")
    check("工具栏撤销", len(ov.annots) == n_pen - 1)

    check("放大镜渲染", (ov._update_magnifier(600, 400, True) or True)
          and ov.canvas.itemcget(ov._mag_img_id, "state") == "normal")
    ov._update_magnifier(600, 400, False)
    check("放大镜可隐藏", ov.canvas.itemcget(ov._mag_img_id, "state") == "hidden")

    check("全屏选择", (ov.select_all() or True) and ov.sel == (0, 0, ov.vw, ov.vh))
    check("全屏选择清空标注", len(ov.annots) == 0)
    ov.undo()
    check("空栈撤销安全", len(ov.annots) == 0)

    ov._reset_selection()
    check("重置回选择态", ov.mode == "select" and ov.sel is None)

    ov.finish()
    try:
        alive = bool(root.winfo_exists())
    except Exception:
        alive = False
    check("会话正常收尾", not alive)

    failed = [r for r in results if not r[1]]
    print(f"[自检] {len(results) - len(failed)}/{len(results)} 项通过")
    if final is not None:
        print("[自检] 覆盖层渲染:", overlay_png)
        print("[自检] 输出成品:", final_path)
    return 1 if failed else 0


# --------------------------------------------------------------------------
# 8. 入口
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="微信风格截图工具")
    p.add_argument("--hotkey", default="alt+a", help="主热键，默认 alt+a（逗号分隔可多个）")
    p.add_argument("--once", action="store_true", help="截一次后退出")
    p.add_argument("--daemon", action="store_true", help="启动时不立即截图，只监听热键")
    p.add_argument("--exit-after", action="store_true", help="完成一次后退出（同 --once）")
    p.add_argument("--delay", type=float, default=0.0, help="启动后延迟 N 秒再截图")
    p.add_argument("--hide-delay", type=int, default=120, help="截图前的等待毫秒")
    p.add_argument("--theme", choices=("dark", "light"), default="dark", help="工具栏主题")
    p.add_argument("--save-dir", default=None, help="另存为的默认目录")
    p.add_argument("--no-window-detect", action="store_true", help="关闭窗口悬停吸附")
    p.add_argument("--no-hotkey", action="store_true", help="不注册全局热键")
    p.add_argument("--selftest", metavar="OUTDIR", default=None, help="渲染自检并输出预览图")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.selftest:
        enable_dpi_awareness()
        return selftest(args.selftest)
    enable_dpi_awareness()
    # 打包成 exe 后双击 = 后台常驻（可用 --once / --daemon 显式覆盖）
    if getattr(sys, "frozen", False) and not (args.daemon or args.once or args.exit_after):
        args.daemon = True
    hotkeys = [] if args.no_hotkey else [h for h in args.hotkey.split(",") if h.strip()]
    if hotkeys and "ctrl+alt+x" not in [h.lower() for h in hotkeys]:
        hotkeys.append("ctrl+alt+x")
    args.hotkeys = hotkeys
    app = SnipApp(args)
    if hotkeys:
        print(f"{APP_TITLE} 已启动：{' / '.join(hotkeys)} 截图，Esc 取消，Ctrl+Alt+Q 退出。")
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
