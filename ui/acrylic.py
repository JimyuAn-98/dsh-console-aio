# -*- coding: utf-8 -*-
# ui/acrylic.py - 自绘亚克力背景(高斯模糊 + 深色着色), 不依赖 Windows DWM 组件。
#
# 原理: 分层窗口(WA_TranslucentBackground)上, 抓取窗口后方的屏幕区域 -> 缩小 ->
# QGraphicsBlurEffect 高斯模糊 -> 深色着色 -> 放大, 绘制为窗口底层背景;
# 面板用 rgba 半透明, 透出模糊背景, 呈现"深色亚克力"效果。
# 窗口移动/缩放时防抖重绘(120ms)。抓取失败回退纯色。

from PySide6.QtCore import Qt, QTimer, QEvent
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QGraphicsBlurEffect,
                               QGraphicsPixmapItem, QGraphicsScene, QWidget)

# 观感参数(调这里改效果)
BLUR_RADIUS = 12      # 小图(1/3 尺寸)上的模糊半径, 等效全尺寸 ~36px
DOWNSAMPLE = 3        # 抓取图缩小倍数(性能)
TINT = QColor(18, 18, 30, 200)    # 深色亚克力着色(tint)
FALLBACK = QColor(24, 24, 36)     # 抓取失败时的纯色兜底


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
        try:
            scr = self._win.screen() or QApplication.primaryScreen()
            if scr is None:
                return
            geo = self._win.frameGeometry()
            if geo.width() <= 0 or geo.height() <= 0:
                return
            pix = scr.grabWindow(0, geo.x(), geo.y(), geo.width(), geo.height())
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
        except Exception:
            self._img = None
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        if self._img is not None and not self._img.isNull():
            p.drawImage(self.rect(), self._img)
        else:
            p.fillRect(self.rect(), FALLBACK)
        p.end()
