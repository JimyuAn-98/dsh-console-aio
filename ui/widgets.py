# -*- coding: utf-8 -*-
# ui/widgets.py - 页面通用现代控件(P1 多栏展开 2026-08-29 引入, 插件/会话/用量/部署共用)。
# 视觉语言(与 theme.py token 一致): 无网格表格、行高加大、圆角选中块(accent 低透明)、
# hover 浅白高亮、右侧圆角徽章 chips、状态点; 徽章色沿用主日志区语义色(ok绿/warn黄/err红)。
# 约束: 纯展示控件, 不做业务; 页面用 set_rows 全量刷新(行数据 dict 存 UserRole)。

from PySide6.QtCore import QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QLabel, QListWidget, QListWidgetItem,
    QSplitter, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)

from ui.theme import TOKENS


def _badge_color(kind):
    # 徽章/状态色与 QSS 同源(逐帧读 TOKENS, 实时换肤后随重绘自动生效)
    return {"ok": TOKENS["ok"], "warn": TOKENS["warn"], "err": TOKENS["err"],
            "dim": TOKENS["text_dim"], "accent": TOKENS["accent"]}.get(
                kind, TOKENS["text_dim"])


def _tint(hex_color, alpha):
    c = QColor(hex_color)
    c.setAlpha(alpha)
    return c


class _RowDelegate(QStyledItemDelegate):
    # 一行 = 状态点(可选) + 标题 + meta 弱化行 + 右侧徽章 chips, 圆角选中/hover 底。
    ROW_H = 52

    def sizeHint(self, option, index):
        return QSize(120, self.ROW_H)

    def paint(self, painter, option, index):
        row = index.data(Qt.UserRole) or {}
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = option.rect.adjusted(3, 3, -3, -3)
        selected = bool(option.state & QStyle.State_Selected)
        if selected:
            painter.setPen(Qt.NoPen)
            painter.setBrush(_tint(TOKENS["accent"], 46))
            painter.drawRoundedRect(rect, 8, 8)
        elif option.state & QStyle.State_MouseOver:
            painter.setPen(Qt.NoPen)
            painter.setBrush(_tint("#ffffff", 12))
            painter.drawRoundedRect(rect, 8, 8)
        x = rect.left() + 10
        dot = row.get("dot")
        if dot:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(dot))
            painter.drawEllipse(x, rect.top() + 18, 8, 8)
            x += 16
        font = painter.font()
        title_y = rect.top() + 8 if row.get("meta") else rect.top() + (rect.height() - 17) // 2
        painter.setPen(QColor("#ffffff" if selected else TOKENS["text"]))
        painter.drawText(x, title_y + 13, row.get("title") or "")
        meta = row.get("meta") or ""
        if meta:
            small = QFont(font)
            small.setPixelSize(11)
            painter.setFont(small)
            painter.setPen(QColor(TOKENS["text_dim"]))
            painter.drawText(x, rect.bottom() - 6, meta)
            painter.setFont(font)
        badge_font = QFont(font)
        badge_font.setPixelSize(11)
        bfm = QFontMetrics(badge_font)
        painter.setFont(badge_font)
        bx = rect.right() - 8
        for text, kind in reversed(row.get("badges") or []):
            color = _badge_color(kind)
            w = bfm.horizontalAdvance(text) + 14
            br = QRect(bx - w, rect.center().y() - 9, w, 18)
            painter.setPen(QColor(color))
            painter.setBrush(_tint(color, 26))
            painter.drawRoundedRect(br, 9, 9)
            painter.drawText(br, Qt.AlignCenter, text)
            bx = br.left() - 6
        painter.restore()


class ModernList(QListWidget):
    # 现代列表: set_rows(rows) 全量刷新; 行 dict 支持 title/meta/badges[(text,kind)]/dot。
    # 业务数据放行 dict 的 "data" 键, current_data()/row_data(idx) 取原始 dict。
    # 注意: Python 侧自持 self._rows(浅拷贝, 保对象身份) —— setData 进 Qt 的行 dict 会被
    # QVariantMap 深拷贝, 身份断裂, 只能供 delegate 绘制, 不得作为业务数据来源。
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("modernList")
        self.setItemDelegate(_RowDelegate(self))
        self.setMouseTracking(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._rows = []

    def set_rows(self, rows):
        self.blockSignals(True)
        self.clear()
        self._rows = list(rows)
        for row in self._rows:
            it = QListWidgetItem()
            it.setData(Qt.UserRole, row)
            it.setSizeHint(QSize(10, _RowDelegate.ROW_H))
            self.addItem(it)
        self.blockSignals(False)

    def row_data(self, idx):
        return self._rows[idx] if 0 <= idx < len(self._rows) else None

    def current_data(self):
        return self.row_data(self.currentRow())


def three_split(left, mid, right, widths=(300, 430, 360), mins=(250, 320, 340)):
    # 页面三栏(列表|详情|配置): 可拖拽 QSplitter; 手柄样式沿用全局 QSplitter::handle 规则。
    # mins = 每栏固定最小宽度: 某栏内容再宽也不压缩其他栏(QSplitter 缩不破最小值),
    # 拖宽某栏时由其右侧各栏吸收(QSplitter 拖拽语义即"向右变")。
    sp = QSplitter(Qt.Orientation.Horizontal, objectName="pageSplit")
    for w, mn in zip((left, mid, right), mins):
        w.setMinimumWidth(mn)
        sp.addWidget(w)
        sp.setCollapsible(sp.indexOf(w), False)
    sp.setSizes(list(widths))
    sp.setStretchFactor(0, 0)
    sp.setStretchFactor(1, 1)
    sp.setStretchFactor(2, 1)
    return sp


def card_wrap(caption, widget):
    # 标题卡片包装(各页原 _wrap_table 的共享版, 接受任意控件)
    card = QFrame(objectName="card")
    v = QVBoxLayout(card)
    v.setContentsMargins(10, 8, 10, 8)
    v.setSpacing(4)
    v.addWidget(QLabel(caption, objectName="rightTitle"))
    v.addWidget(widget)
    return card


class RefreshIndicator(QWidget):
    # 页面标题右侧的"刷新状态指示": loading 时画旋转弧(spinner), 结束后显示状态点。
    # 三种状态点语义(与主日志区 ok/warn/err 色一致): 绿=无变化 / 黄=数据有变化 / 红=获取错误。
    # 用法: set_loading(True/False) 控制转圈; set_status("ok"|"warn"|"err") 设结束状态点,
    #       None 清空状态点。setToolTip 提供文字说明(由页面按语义设置)。
    SIZE = 16
    FRAME_MS = 40   # 25fps 转圈, 增量 12°(约 0.5s 一圈)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self._loading = False
        self._angle = 0
        self._status = None
        self._timer = QTimer(self)
        self._timer.setInterval(self.FRAME_MS)
        self._timer.timeout.connect(self._advance)

    def set_loading(self, loading):
        # 开始/停止转圈: 转圈时隐藏状态点, 结束后停在当前状态点。
        if loading == self._loading:
            return
        self._loading = loading
        if loading:
            self._status = None
            self._angle = 0
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def set_status(self, kind):
        # kind: "ok"(绿/无变化) | "warn"(黄/有变化) | "err"(红/错误) | None(清除)。
        self._status = kind
        self.set_loading(False)
        self.update()

    def _advance(self):
        self._angle = (self._angle + 12) % 360
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        margin = 2
        if self._loading:
            # 旋转圆弧(绘制一条渐隐的弧线): 画一个不闭合的圆环缺口, 借旋转营造转圈感。
            pen = QPen(_tint("#ffffff", 200))
            pen.setWidthF(2.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            r = QRect(margin, margin, self.width() - 2 * margin,
                      self.height() - 2 * margin)
            p.drawArc(r, self._angle * 16, 120 * 16)
        elif self._status:
            color = _badge_color(self._status)
            p.setBrush(QColor(color))
            p.drawEllipse(QRect(margin + 2, margin + 2,
                                self.width() - 2 * (margin + 2),
                                self.height() - 2 * (margin + 2)))
        p.end()
