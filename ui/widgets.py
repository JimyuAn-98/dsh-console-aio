# -*- coding: utf-8 -*-
# ui/widgets.py - 页面通用现代控件(P1 多栏展开 2026-08-29 引入, 插件/会话/用量/部署共用)。
# 视觉语言(与 theme.py token 一致): 无网格表格、行高加大、圆角选中块(accent 低透明)、
# hover 浅白高亮、右侧圆角徽章 chips、状态点; 徽章色沿用主日志区语义色(ok绿/warn黄/err红)。
# 约束: 纯展示控件, 不做业务; 页面用 set_rows 全量刷新(行数据 dict 存 UserRole)。

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QLabel, QListWidget, QListWidgetItem,
    QSplitter, QStyle, QStyledItemDelegate, QVBoxLayout)

ACCENT = "#4f6ef7"
TEXT = "#e6e6e6"
TEXT_DIM = "#9a9ab0"
BADGE_COLORS = {"ok": "#7ecb6a", "warn": "#e5c07b", "err": "#e07a7a",
                "dim": "#9a9ab0", "accent": ACCENT}


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
            painter.setBrush(_tint(ACCENT, 46))
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
        painter.setPen(QColor("#ffffff" if selected else TEXT))
        painter.drawText(x, title_y + 13, row.get("title") or "")
        meta = row.get("meta") or ""
        if meta:
            small = QFont(font)
            small.setPixelSize(11)
            painter.setFont(small)
            painter.setPen(QColor(TEXT_DIM))
            painter.drawText(x, rect.bottom() - 6, meta)
            painter.setFont(font)
        badge_font = QFont(font)
        badge_font.setPixelSize(11)
        bfm = QFontMetrics(badge_font)
        painter.setFont(badge_font)
        bx = rect.right() - 8
        for text, kind in reversed(row.get("badges") or []):
            color = BADGE_COLORS.get(kind, BADGE_COLORS["dim"])
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
