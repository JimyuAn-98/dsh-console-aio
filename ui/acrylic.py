# -*- coding: utf-8 -*-
# ui/acrylic.py - 自绘亚克力背景(高斯模糊 + 深色着色), 不依赖 Windows DWM 组件。
#
# 原理: 分层窗口(WA_TranslucentBackground)上, 抓取窗口后方的屏幕区域 -> 缩小 ->
# QGraphicsBlurEffect 高斯模糊 -> 深色着色 -> 放大, 绘制为窗口底层背景;
# 面板用 rgba 半透明, 透出模糊背景, 呈现"深色亚克力"效果。
# 窗口移动/缩放时防抖重绘(120ms)。抓取失败回退纯色。
# 调试: 设环境变量 DSH_ACRYLIC_TEST=1 时画亮色渐变测试图, 验证渲染链路。

import os

from PySide6.QtCore import Qt, QTimer, QEvent
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QGraphicsBlurEffect,
                               QGraphicsPixmapItem, QGraphicsScene, QWidget)

# 观感参数(调这里改效果)
BLUR_RADIUS = 12      # 小图(1/3 尺寸)上的模糊半径, 等效全尺寸 ~36px
DOWNSAMPLE = 3        # 抓取图缩小倍数(性能)
TINT = QColor(18, 18, 30, 150)    # 深色亚克力着色(tint); alpha 越浅, 模糊背景越明显


def _desktop_hwnd():
    """返回桌面壁纸层窗口句柄(Progman 或其 WorkerW 兄弟), 不含任何应用窗口。
    经典做法: Progman + 0x052C 消息确保 WorkerW 存在; WorkerW 需带 SHELLDLL_DefView 子窗。
    """
    import ctypes.wintypes as wt
    u = ctypes.windll.user32
    progman = u.FindWindowW("Progman", None)
    if progman:
        u.SendMessageTimeoutW(progman, 0x052C, 0xD, 0, 0x0002, 1000,
                              ctypes.byref(ctypes.c_ulong()))
        if u.FindWindowExW(progman, None, "SHELLDLL_DefView", None):
            return progman
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def _cb(h, l):
        cls = ctypes.create_unicode_buffer(64)
        u.GetClassNameW(h, cls, 64)
        if cls.value == "WorkerW" and u.FindWindowExW(h, None, "SHELLDLL_DefView", None):
            found.append(h)
            return False
        return True

    u.EnumWindows(_cb, 0)
    return found[0] if found else None


def capture_wallpaper():
    """捕获桌面壁纸层(不含应用窗口, 避免亚克力自反馈)。返回 QPixmap 或 None。"""
    import ctypes.wintypes as wt
    u = ctypes.windll.user32
    g = ctypes.windll.gdi32
    hwnd = _desktop_hwnd()
    if not hwnd:
        return None
    hdc = u.GetWindowDC(hwnd)
    if not hdc:
        return None
    try:
        rect = wt.RECT()
        u.GetWindowRect(hwnd, ctypes.byref(rect))
        w, h = rect.right - rect.left, rect.bottom - rect.top
        if w <= 0 or h <= 0:
            return None
        mem = g.CreateCompatibleDC(hdc)
        bmp = g.CreateCompatibleBitmap(hdc, w, h)
        g.SelectObject(mem, bmp)
        g.BitBlt(mem, 0, 0, w, h, hdc, 0, 0, 0x00CC0020)  # SRCCOPY
        pm = QPixmap.fromWinHBITMAP(int(bmp))
        g.DeleteObject(bmp)
        g.DeleteDC(mem)
        return pm
    finally:
        u.ReleaseDC(hwnd, hdc)


class AcrylicBackdrop(QWidget):
    """窗口底层背景: 抓取屏幕后方 -> 高斯模糊 + 深色着色 -> 绘制。"""

    def __init__(self, window, parent=None):
        super().__init__(parent or window)
        self._win = window
        self._img = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.refresh)
        window.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if obj is self._win and ev.type() in (QEvent.Type.Move, QEvent.Type.Resize):
            self._timer.start(120)   # 防抖: 停稳后 120ms 再抓
        return False

    def refresh(self):
        self._timer.stop()
        # 调试开关: DSH_ACRYLIC_TEST=1 时用亮色渐变代替抓屏, 验证 backdrop 渲染链路
        if os.environ.get("DSH_ACRYLIC_TEST"):
            w, h = self._win.width(), self._win.height()
            img = QImage(max(1, w), max(1, h), QImage.Format.Format_ARGB32)
            p = QPainter(img)
            p.fillRect(img.rect(), QColor(255, 80, 160))
            p.fillRect(img.rect(), QColor(0, 220, 255))
            # 左粉右青渐变(便于肉眼确认是否渲染)
            for i in range(max(1, w)):
                t = i / max(1, w - 1)
                p.setPen(QColor(int(255 * (1 - t)), int(80 + 140 * t), int(160 + 95 * t)))
                p.drawLine(i, 0, i, h)
            p.end()
            self._img = img
            self._win.loge("亚克力: 测试渐变模式(WxH=%dx%d)" % (w, h), "ok")
            self.update()
            return
        try:
            pix = capture_wallpaper()
            if pix is None or pix.isNull():
                # 回退: 窗口透明化后抓屏(避免抓到自己的亚克力背景形成反馈)
                scr = self._win.screen() or QApplication.primaryScreen()
                if scr is None:
                    self._win.loge("亚克力: 壁纸层与屏幕均不可用", "err")
                    return
                geo = self._win.frameGeometry()
                self._win.setWindowOpacity(0.0)
                QApplication.processEvents()
                try:
                    pix = scr.grabWindow(0, geo.x(), geo.y(), geo.width(), geo.height())
                finally:
                    self._win.setWindowOpacity(1.0)
                if pix.isNull():
                    self._win.loge("亚克力: 抓屏返回空图", "err")
                    self._img = None
                    self.update()
                    return
            img = pix.toImage()
            w, h = img.width(), img.height()
            sw = max(1, w // DOWNSAMPLE)
            sh = max(1, h // DOWNSAMPLE)
            small = img.scaled(sw, sh, Qt.AspectRatioMode.IgnoreAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            # 高斯模糊(经 QGraphicsScene 渲染, 自带抗锯齿)
            blur = QGraphicsBlurEffect()
            blur.setBlurRadius(BLUR_RADIUS)
            item = QGraphicsPixmapItem(QPixmap.fromImage(small))
            item.setGraphicsEffect(blur)
            scene = QGraphicsScene()
            scene.addItem(item)
            out = QImage(small.size(), QImage.Format.Format_ARGB32)
            out.fill(Qt.GlobalColor.transparent)
            p = QPainter(out)
            scene.render(p)
            p.end()
            # 深色着色(亚克力 tint)
            p = QPainter(out)
            p.fillRect(out.rect(), TINT)
            p.end()
            # 放大回原尺寸
            self._img = out.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
            self._win.loge("亚克力: 抓屏 %dx%d 模糊完成" % (w, h), "ok")
        except Exception as e:
            self._win.loge("亚克力抓屏失败: %s" % e, "err")
            self._img = None
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        if self._img is not None and not self._img.isNull():
            p.drawImage(self.rect(), self._img)
        else:
            # 兜底用半透明 tint(保持透明通道, 避免不透明盖住分层窗口)
            p.fillRect(self.rect(), TINT)
        p.end()
