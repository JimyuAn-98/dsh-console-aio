# -*- coding: utf-8 -*-
# 任务看板页(PySide6 迁移版): 只读展示 + 刷新, 不提供任何写操作。
# 定时任务编辑属高级操作, 请使用 dsh web。
# 后台线程读 dsh_data.read_taskboard -> Qt Signal 回主线程重建看板, 绝不直接改 UI。

import datetime
import threading

import dsh_data
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea,
    QVBoxLayout, QWidget)

from pyside.base import BasePage


def _fmt_ts(v):
    # 时间戳(毫秒)转本地时间字符串; 缺失/非法返回"（无数据）"
    try:
        ms = int(v)
        if ms <= 0:
            return "（无数据）"
        return datetime.datetime.fromtimestamp(ms / 1000.0).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return "（无数据）"


class TaskboardPage(BasePage):
    # 任务看板: 调度器信息 + 按状态分列的任务卡片。app 为 MainWindow。
    _data = Signal(object, str)     # (read_taskboard 结果 dict, err)

    def __init__(self, app, parent=None):
        # 部署联动: 当前部署(host 非空)构造 DshRemote, 只读操作走远程; None=本机
        self._remote = None
        _dep = getattr(app, "_current_deploy", None)
        if _dep and _dep.get("host"):
            self._remote = dsh_data.DshRemote(_dep)
        super().__init__(app, parent)
        self._data.connect(self._apply_data)
        self._refresh()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 12)
        root.setSpacing(8)

        title = QLabel("任务看板", objectName="cardTitle")
        root.addWidget(title)
        hint = QLabel("这是 dsh 的定时任务/调度系统数据(~/.dsh/task-board/): ledger 为任务账本,"
                      "scheduler 为定时调度器(时区/最近心跳), recentRequests 为最近请求。\n"
                      "只有创建过定时任务(dsh web 或 CLI)才有内容; 当前为空属正常。",
                      objectName="cardHint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        # 调度器信息(单行: 时区 / 最近心跳 / ledgerId) + 最近请求数量
        info = QFrame(objectName="card")
        il = QHBoxLayout(info)
        il.setContentsMargins(12, 8, 12, 8)
        il.setSpacing(20)
        self._sch_labels = {}
        for key, caption in (("timeZone", "时区"), ("lastTickAt", "最近心跳"), ("ledgerId", "ledgerId")):
            lbl = QLabel(caption + ": --", objectName="monName")
            self._sch_labels[key] = lbl
            il.addWidget(lbl)
        il.addStretch(1)
        self._recent_lbl = QLabel("最近请求: --", objectName="monName")
        il.addWidget(self._recent_lbl)
        root.addWidget(info)

        # 看板: 横向滚动区域, 内部为按状态分列的卡片列
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._board = QWidget()
        self._board_lay = QHBoxLayout(self._board)
        self._board_lay.setContentsMargins(4, 4, 4, 4)
        self._board_lay.setSpacing(10)
        scroll.setWidget(self._board)
        root.addWidget(scroll, 1)

        btns = QHBoxLayout()
        self._btn_refresh = QPushButton("刷新")
        self._btn_refresh.clicked.connect(self._refresh)
        btns.addWidget(self._btn_refresh)
        btns.addStretch(1)
        root.addLayout(btns)

        self._status_lbl = QLabel("就绪", objectName="statusBar")
        root.addWidget(self._status_lbl)

    def _refresh(self):
        # 读取 task-board 两个小 json(本地读文件, 远程经 ssh), 放后台线程
        self._set_status("正在读取任务看板...")
        self._btn_refresh.setEnabled(False)

        def worker():
            err = None
            data = None
            try:
                data = dsh_data.read_taskboard(remote=self._remote)
            except Exception as e:
                err = str(e)
            self._data.emit(data or {}, err)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_data(self, data, err):
        self._btn_refresh.setEnabled(True)
        if err:
            self._set_status("读取失败: " + err)
            self.app.loge("[任务看板] 读取失败: " + err, "err")
            QMessageBox.critical(self, "读取失败", "任务看板读取失败:\n" + err)
            return
        ledger = data.get("ledger") if isinstance(data.get("ledger"), dict) else {}
        tasks = ledger.get("tasks")
        if not isinstance(tasks, list):
            tasks = []

        # 调度器: ledger.scheduler 与 scheduler-v2.json 合并, 后者 lastTickAt 更新时覆盖
        sch = {}
        s1 = ledger.get("scheduler")
        if isinstance(s1, dict):
            sch.update(s1)
        s2 = data.get("scheduler")
        if isinstance(s2, dict):
            sch.update(s2)
        for key, caption in (("timeZone", "时区"), ("lastTickAt", "最近心跳"), ("ledgerId", "ledgerId")):
            v = sch.get(key)
            text = _fmt_ts(v) if key == "lastTickAt" else (str(v) if v not in (None, "") else "（无数据）")
            self._sch_labels[key].setText(caption + ": " + text)

        recent = ledger.get("recentRequests")
        n = len(recent) if isinstance(recent, list) else 0
        self._recent_lbl.setText("最近请求: %d 条" % n)

        ncols = self._rebuild_board(tasks)
        self._set_status("已刷新: %d 个任务, %d 个状态列" % (len(tasks), ncols))

    def _rebuild_board(self, tasks):
        # 按状态分组重建卡片列; 空数据给一个"（暂无任务）"占位列
        self._clear_board()
        if not tasks:
            self._add_column("（暂无任务）", [{"id": "（无数据）", "title": "（暂无任务）", "createdAt": 0}])
            self._board_lay.addStretch(1)
            return 1
        groups = {}
        for t in tasks:
            if not isinstance(t, dict):
                t = {}
            status = str(t.get("status") or "（无数据）")
            groups.setdefault(status, []).append(t)
        for status, items in groups.items():
            self._add_column("%s (%d)" % (status, len(items)), items)
        self._board_lay.addStretch(1)
        return len(groups)

    def _clear_board(self):
        while self._board_lay.count():
            item = self._board_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _add_column(self, header, tasks):
        col = QFrame(objectName="card")
        col.setMinimumWidth(220)
        vl = QVBoxLayout(col)
        vl.setContentsMargins(10, 8, 10, 8)
        vl.setSpacing(8)
        vl.addWidget(QLabel(header, objectName="rightTitle"))
        for t in tasks:
            vl.addWidget(self._make_card(t))
        vl.addStretch(1)
        self._board_lay.addWidget(col)
        return col

    def _make_card(self, t):
        card = QFrame(objectName="card")
        v = QVBoxLayout(card)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(4)
        title = QLabel(str(t.get("title") or "（无数据）"), objectName="cardTitle")
        title.setWordWrap(True)
        v.addWidget(title)
        tid = t.get("id")
        v.addWidget(QLabel("ID: " + (str(tid) if tid not in (None, "") else "（无数据）"), objectName="monName"))
        v.addWidget(QLabel("创建时间: " + _fmt_ts(t.get("createdAt")), objectName="monNote"))
        return card

    def _set_status(self, text):
        self._status_lbl.setText(text)
