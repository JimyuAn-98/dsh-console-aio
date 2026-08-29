# -*- coding: utf-8 -*-
# 日志查看页(UI 层): 双 tab(out/err) + QTimer 轮询 + 过滤/跟随/清屏。
# 文件读取/行分类/脱敏/过滤在 core/logs.py(纯 Python, 可单测), 页面只渲染。
# 数据源边界: 只覆盖控制台拉起的 dsh web(%TEMP%/dsh-dash/*.log); 用户自己终端
# 启动的 dsh 不落盘, 页面顶部有提示。
# 轮询在 UI 线程: 纯本地小 IO(stat + 增量读, 微秒级), 不起后台线程, 故不经
# services.py 信号桥——该约束针对"后台线程", 此处没有。
# token=*** 展示层脱敏(web 登录 token), 日志文件本身不动。

import os

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTabWidget, QTextEdit,
    QLineEdit, QCheckBox, QMessageBox, QFrame)

from ui.base import BasePage
from core import logs as core_logs

TAG_COLORS = {"err": "#e07a7a", "warn": "#e5c07b", "ok": "#7ecb6a", "": "#e6e6e6"}


def _escape(text):
    # HTML 转义 + 保留行首缩进(HTML 折叠空白, 堆栈缩进有语义)
    t = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    stripped = t.lstrip(" ")
    return "&nbsp;" * (len(t) - len(stripped)) + stripped


def _line_html(text, tag):
    color = TAG_COLORS.get(tag, TAG_COLORS[""])
    return '<span style="color:%s">%s</span>' % (color, _escape(text))


class _StreamView:
    # 单个日志文件(tab)的视图状态: 行缓冲 + 增量 tailer + 文本控件
    def __init__(self, stream):
        self.stream = stream
        self.path = core_logs.log_path(stream)
        self.tailer = core_logs.Tailer(self.path)
        self.rows = []          # [(text, tag)], 已脱敏, 上限 MAX_BUFFER_ROWS
        self.hinted = False     # 缺文件提示是否已显示(首行到达前不清)
        self.view = QTextEdit()
        self.view.setReadOnly(True)
        self.view.setFont(QFont("Consolas", 9))


class LogsPage(BasePage):
    # 日志查看: BasePage 范式, app 为 MainWindow。页面每次进入重建(主窗口范式),
    # QTimer 挂 self 随页面销毁, 无跨页状态。
    def __init__(self, app, parent=None):
        self._views = {"out": _StreamView("out"), "err": _StreamView("err")}
        super().__init__(app, parent)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(2000)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 12)
        root.setSpacing(8)

        title = QLabel("日志管理", objectName="cardTitle")
        root.addWidget(title)
        root.addWidget(QLabel(
            "数据源: 控制台启动的 dsh web 输出(%TEMP%\\dsh-dash)。自行在终端启动的 dsh 不落盘, 此处看不到。",
            objectName="cardHint"))

        bar = QHBoxLayout()
        bar.setSpacing(6)
        bar.addWidget(QLabel("包含:"))
        self._inc = QLineEdit()
        self._inc.setPlaceholderText("关键字(大小写不敏感)")
        self._inc.setMaximumWidth(180)
        self._inc.textChanged.connect(self._render_current)
        bar.addWidget(self._inc)
        bar.addWidget(QLabel("排除:"))
        self._exc = QLineEdit()
        self._exc.setPlaceholderText("剔除含关键字的行")
        self._exc.setMaximumWidth(180)
        self._exc.textChanged.connect(self._render_current)
        bar.addWidget(self._exc)
        self._follow = QCheckBox("跟随滚动")
        self._follow.setChecked(True)
        bar.addWidget(self._follow)
        clear_btn = QPushButton("清屏")
        clear_btn.clicked.connect(self._clear_current)
        bar.addWidget(clear_btn)
        open_btn = QPushButton("打开日志目录")
        open_btn.clicked.connect(self._open_dir)
        bar.addWidget(open_btn)
        bar.addStretch(1)
        root.addLayout(bar)

        self._tabs = QTabWidget(objectName="card")
        for stream in ("out", "err"):
            sv = self._views[stream]
            self._tabs.addTab(sv.view, "dsh-web." + stream + ".log")
        self._tabs.currentChanged.connect(lambda _i: self._render_current())
        root.addWidget(self._tabs, 1)

        self._status_lbl = QLabel("就绪", objectName="statusBar")
        root.addWidget(self._status_lbl)

        for sv in self._views.values():
            self._bootstrap(sv)

    # ── 数据(经 core/logs, 全在 UI 线程) ──
    def _bootstrap(self, sv):
        # 初始/重置: 尾部载入 + tailer 对齐到当前文件尾(此后 poll 只看新增)
        sv.rows = [(core_logs.mask_tokens(t), core_logs.classify_stream(sv.stream, t))
                   for t in core_logs.read_tail(sv.path)]
        try:
            sv.tailer.offset = os.path.getsize(sv.path)
        except OSError:
            sv.tailer.offset = 0
        self._render(sv)

    def _poll(self):
        for stream in ("out", "err"):
            sv = self._views[stream]
            lines, reset = sv.tailer.read_new()
            if reset:
                self._bootstrap(sv)
                continue
            if not lines:
                continue
            if sv.hinted:
                sv.view.clear()
                sv.hinted = False
            current = self._views[self._current_stream()]
            for text in lines:
                text = core_logs.mask_tokens(text)
                row = (text, core_logs.classify_stream(sv.stream, text))
                sv.rows.append(row)
                if sv is current:
                    self._append_row(sv, row)
            if len(sv.rows) > core_logs.MAX_BUFFER_ROWS:
                sv.rows = sv.rows[-core_logs.MAX_BUFFER_ROWS:]
        self._update_status()

    # ── 渲染 ──
    def _current_stream(self):
        return "out" if self._tabs.currentIndex() == 0 else "err"

    def _append_row(self, sv, row):
        if not core_logs.filter_rows([row], self._inc.text(), self._exc.text()):
            return
        sv.view.appendHtml(_line_html(*row))
        if self._follow.isChecked():
            sv.view.moveCursor(QTextCursor.End)

    def _render(self, sv):
        # 全量重渲(初始/切换 tab/过滤变化): 单次 setHtml, 来源=行缓冲
        rows = core_logs.filter_rows(sv.rows, self._inc.text(), self._exc.text())
        if rows:
            sv.view.setHtml("<p>%s</p>" % "</p><p>".join(
                _line_html(t, tag) for t, tag in rows))
            sv.hinted = False
        else:
            hint = "暂无匹配行" if sv.rows else (
                "日志文件不存在或为空: %s\n控制台启动 dsh web 后生成, 约 2 秒内自动出现。" % sv.path)
            sv.view.setHtml('<span style="color:#888">%s</span>' % _escape(hint)
                            .replace("\n", "<br>"))
            sv.hinted = not sv.rows
        if self._follow.isChecked():
            sv.view.moveCursor(QTextCursor.End)

    def _render_current(self):
        self._render(self._views[self._current_stream()])

    def _clear_current(self):
        sv = self._views[self._current_stream()]
        sv.rows = []
        sv.view.clear()
        sv.hinted = False
        self._update_status()

    def _open_dir(self):
        d = core_logs.log_dir()
        if not os.path.isdir(d):
            QMessageBox.information(self, "目录不存在",
                                    "日志目录还没有生成:\n%s\n控制台启动一次 dsh web 即会创建。" % d)
            return
        try:
            os.startfile(d)
        except OSError as e:
            QMessageBox.critical(self, "无法打开", str(e))

    def _update_status(self):
        self._status_lbl.setText("out %d 行 · err %d 行 · 数据源: %s"
                                 % (len(self._views["out"].rows),
                                    len(self._views["err"].rows),
                                    core_logs.log_dir()))
