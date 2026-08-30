# -*- coding: utf-8 -*-
# ui/palette.py - 全局命令面板(Ctrl+K, OTP 式键盘直达): 单行输入过滤 + 结果列表,
# Enter 执行 / 上下键选择 / Esc 关闭, 点击面板外自动关闭(Qt.Popup)。
# 命令由调用方(主窗口)在打开时组装: 页面导航 / 部署切换 / 动作, run 为零参 callable,
# 面板 accept 后才执行(避免弹窗生命周期内改 UI 树)。
# rank_commands 为纯函数(过滤+前缀优先排序), 可脱离 Qt 单测。

from PySide6.QtCore import Qt, QEvent
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem)

from ui.theme import TOKENS
from ui.widgets import ModernList

_PANEL_W = 520
_LIST_H = 340


def rank_commands(cmds, query):
    # 过滤: 大小写不敏感子串匹配 title(含 hint); 前缀命中排前。纯函数。
    q = (query or "").strip().lower()
    if not q:
        return list(cmds)
    starts, contains = [], []
    for c in cmds:
        t = str(c.get("title", "")).lower()
        if t.startswith(q):
            starts.append(c)
        elif q in t or q in str(c.get("meta", "")).lower():
            contains.append(c)
    return starts + contains


class CommandPalette(QDialog):
    # 命令面板: open(cmds) 模态弹出; cmds = [{"title", "meta", "run"}]。
    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)   # Popup: 点外自动关 + 抢焦点
        self._cmds = []
        self.setFixedWidth(_PANEL_W)
        self.setStyleSheet(
            "QDialog { background: %s; border: 1px solid %s; border-radius: 10px; }"
            % (TOKENS["bg_elevated"], TOKENS["border_strong"]))
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(8)
        self._edit = QLineEdit()
        self._edit.setPlaceholderText("输入命令或页面名 (Ctrl+K)")
        self._edit.textChanged.connect(self._refilter)
        self._edit.installEventFilter(self)
        v.addWidget(self._edit)
        self._list = ModernList()
        self._list.setFixedHeight(_LIST_H)
        self._list.itemClicked.connect(self._run_item)
        v.addWidget(self._list)

    def open(self, cmds):
        self._cmds = list(cmds or [])
        self._refilter("")
        parent = self.parent()
        if parent is not None:
            geo = parent.frameGeometry()
            self.move(geo.x() + max(0, (geo.width() - self.width()) // 2),
                      geo.y() + 96)
        self._edit.setFocus()
        self.exec()

    # ── 过滤/选择 ──
    def _refilter(self, text):
        self._list.set_rows([
            {"title": c.get("title", ""), "meta": c.get("meta", ""), "cmd": c}
            for c in rank_commands(self._cmds, text)])
        if self._list.count():
            self._list.setCurrentRow(0)

    def _current(self):
        row = self._list.current_data()
        return (row or {}).get("cmd")

    def _run_item(self, _item):
        cmd = self._current()
        if cmd is None:
            return
        self.accept()
        run = cmd.get("run")
        if callable(run):
            run()   # accept 之后执行: 面板已关, 改 UI 树无生命周期冲突

    # ── 键盘 ──
    def eventFilter(self, obj, event):
        # 输入框上的导航键: 上下移动选择, Enter 执行, Esc 关闭; 其余放行输入
        if obj is not self._edit or event.type() != QEvent.Type.KeyPress:
            return super().eventFilter(obj, event)
        key = event.key()
        if key == Qt.Key.Key_Down:
            self._list.setCurrentRow(min(self._list.count() - 1,
                                         self._list.currentRow() + 1))
            return True
        if key == Qt.Key.Key_Up:
            self._list.setCurrentRow(max(0, self._list.currentRow() - 1))
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._run_item(None)
            return True
        if key == Qt.Key.Key_Escape:
            self.reject()
            return True
        return False
