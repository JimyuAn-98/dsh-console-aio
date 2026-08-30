# -*- coding: utf-8 -*-
# ui/chart.py - 主题感知的堆叠柱状图(自绘, 零新依赖; 不引入 QtCharts 以控包体并完全
# 跟随主题 token)。数据: set_series(days=[(标签, {模型: 值})], models=[堆叠顺序])。
# 视觉: 文字/网格取 TOKENS, 模型配色用与暗色主题同族的固定 8 色板(首色=accent);
# hover 悬停显示当日分模型明细(模型短名 = 去 provider 前缀); 空数据显示占位文案。

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from ui.theme import TOKENS

# 模型配色板(按堆叠序循环取用): 首色=accent, 余为与暗色主题协调的柔和色
PALETTE = ("#5686fe", "#7ecb6a", "#e5c07b", "#e07a7a",
           "#4bbfd6", "#d68fb8", "#9fb46a", "#b0a1e8")

# 布局常量(像素): 左轴标签 / 右距 / 顶部图例 / 底部日期
_M_L, _M_R, _M_T, _M_B = 56, 10, 26, 22


def _fmt(v):
    # 整数千分位; 轴标签用 k 缩写
    v = int(v or 0)
    return "{:,}".format(v)


def _axis_label(v):
    if v >= 1000000:
        s = "%.1fM" % (v / 1000000.0)
    elif v >= 1000:
        s = "%.1fk" % (v / 1000.0)
    else:
        s = str(v)
    return s.rstrip("0").rstrip(".") if "." in s else s


def _nice_max(v):
    # 纵轴上限取 1/2/2.5/5×10^k 的"好看"值
    if v <= 0:
        return 1
    mag = 10 ** max(0, len(str(int(v))) - 1)
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * mag:
            return int(m * mag)
    return v


def short_model(name):
    # 模型显示名: 去 provider 前缀(org/model → model), 过长截断
    s = str(name or "?").split("/")[-1]
    return s if len(s) <= 22 else s[:21] + "…"


class StackedBarChart(QWidget):
    # 纯展示控件: set_series 后自绘; hover 高亮柱并弹 QToolTip 明细。不做业务。
    def __init__(self, parent=None):
        super().__init__(parent)
        self._days = []      # [(标签, {模型: 值})]
        self._models = []    # 堆叠顺序(与 PALETTE 序号对应)
        self._hover = -1
        self.setMinimumHeight(160)
        self.setMouseTracking(True)

    def set_series(self, days, models):
        self._days = list(days or [])
        self._models = list(models or [])
        self._hover = -1
        self.update()

    # ── 交互 ──
    def _slot_width(self, pw, n):
        return pw / float(n) if n else 0.0

    def _hit(self, x):
        # 命中测试: 返回 x 落在第几根柱(越界 -1)
        n = len(self._days)
        if n == 0:
            return -1
        pw = self.width() - _M_L - _M_R
        i = int((x - _M_L) / self._slot_width(pw, n))
        return i if 0 <= i < n else -1

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        idx = self._hit(pos.x())
        if idx != self._hover:
            self._hover = idx
            self.update()
        if 0 <= idx < len(self._days):
            label, stack = self._days[idx]
            lines = ["<b>%s</b>  合计 %s" % (label, _fmt(sum(int(v) for v in stack.values())))]
            for m in self._models:
                v = int(stack.get(m) or 0)
                if v:
                    lines.append("%s  %s" % (short_model(m), _fmt(v)))
            QToolTip.showText(e.globalPosition().toPoint(), "<br>".join(lines), self)
        else:
            QToolTip.hideText()

    def leaveEvent(self, e):
        self._hover = -1
        self.update()

    # ── 绘制 ──
    def paintEvent(self, e):
        p = QPainter(self)
        w, h = self.width(), self.height()
        if not self._days:
            p.setPen(QColor(TOKENS["text_dim"]))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "统计后显示每日 token 趋势(输入+输出, 按模型堆叠)")
            return
        pw, ph = w - _M_L - _M_R, h - _M_T - _M_B
        if pw <= 10 or ph <= 10:
            return
        totals = [sum(int(v) for v in stack.values()) for _, stack in self._days]
        vmax = _nice_max(max(totals))

        # 网格 + 纵轴刻度(5 段)
        small = QFont(self.font())
        small.setPixelSize(10)
        for i in range(5):
            y = _M_T + ph - ph * i / 4.0
            p.setPen(QPen(QColor(TOKENS["border"]), 1))
            p.drawLine(_M_L, int(y), _M_L + pw, int(y))
            p.setPen(QColor(TOKENS["text_dim"]))
            p.setFont(small)
            p.drawText(0, int(y) - 6, _M_L - 6, 12, Qt.AlignmentFlag.AlignRight,
                       _axis_label(vmax * i / 4))

        # 柱(按模型堆叠; hover 列加高亮底)
        slot = self._slot_width(pw, len(self._days))
        barw = max(3, min(34, slot * 0.62))
        for i, (_label, stack) in enumerate(self._days):
            x = _M_L + i * slot + (slot - barw) / 2.0
            if i == self._hover:
                p.fillRect(QRect(int(_M_L + i * slot), _M_T, int(slot) + 1, ph),
                           QColor(255, 255, 255, 14))
            acc = 0.0
            for mi, m in enumerate(self._models):
                v = int(stack.get(m) or 0)
                if v <= 0:
                    continue
                seg = ph * float(v) / vmax
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(self._color(mi))
                p.drawRect(QRect(int(round(x)), int(round(_M_T + ph - acc - seg)),
                                 int(round(barw)), max(1, int(round(seg)))))
                acc += seg

        # 横轴日期(按宽度自动跳步)
        p.setPen(QColor(TOKENS["text_dim"]))
        p.setFont(small)
        step = max(1, int(len(str(self._days[0][0])) * len(self._days) * 7.2 / pw) + 1)
        for i, (label, _stack) in enumerate(self._days):
            if i % step:
                continue
            x = _M_L + i * slot
            p.drawText(QRect(int(x), h - _M_B + 4, int(slot), 14),
                       Qt.AlignmentFlag.AlignHCenter, str(label))

        # 图例(顶部横排, 超出宽度截断)
        p.setFont(small)
        lx = _M_L
        for mi, m in enumerate(self._models):
            text = short_model(m)
            tw = QFontMetrics(small).horizontalAdvance(text)
            if lx + 14 + tw > w - _M_R:
                break
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self._color(mi))
            p.drawRect(lx, 8, 10, 10)
            p.setPen(QColor(TOKENS["text_dim"]))
            p.drawText(lx + 14, 8, tw + 4, 12, Qt.AlignmentFlag.AlignLeft, text)
            lx += 14 + tw + 12

    @staticmethod
    def _color(i):
        return QColor(PALETTE[i % len(PALETTE)])
