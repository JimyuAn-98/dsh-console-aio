# -*- coding: utf-8 -*-
# Agent 模式管理页(UI 层): 只读浏览 .agent-presets 各模式并展示 preset.yml。
# 列表读取走 service.list_agent_presets(remote) 信号桥(result "agents-list" 回包);
# preset.yml 详情是本机小文件, 同步直读 core.data.read_yaml(纯读过渡态约定)。
# 部署联动: 当前部署(host 非空)构造 DshRemote, 列表走远程; 目录打开为本机操作。
# 不做任何写入。log/status 不在页面 connect(主窗口级已接一次)。

import os

from core import data as core_data
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView, QMessageBox, QPlainTextEdit)

from ui.base import BasePage


def _fmt_scalar(v):
    # 把解析后的标量转成展示文本
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    return str(v)


def _fmt_yaml(data, indent=0):
    # 把 read_yaml 解析结果渲染成易读的 YAML 风格文本(只读展示用)
    pad = "  " * indent
    lines = []
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, dict):
                lines.append(pad + str(k) + ":")
                lines.extend(_fmt_yaml(v, indent + 1))
            elif isinstance(v, list):
                if not v:
                    lines.append(pad + str(k) + ": []")
                    continue
                lines.append(pad + str(k) + ":")
                for item in v:
                    if isinstance(item, dict):
                        items = list(item.items())
                        if not items:
                            lines.append(pad + "  - {}")
                            continue
                        k0, v0 = items[0]
                        if isinstance(v0, (dict, list)):
                            lines.append(pad + "  - " + str(k0) + ":")
                            lines.extend(_fmt_yaml(v0, indent + 2))
                        else:
                            lines.append(pad + "  - " + str(k0) + ": " + _fmt_scalar(v0))
                        for kk, vv in items[1:]:
                            if isinstance(vv, (dict, list)):
                                lines.append(pad + "    " + str(kk) + ":")
                                lines.extend(_fmt_yaml(vv, indent + 1))
                            else:
                                lines.append(pad + "    " + str(kk) + ": " + _fmt_scalar(vv))
                    else:
                        lines.append(pad + "  - " + _fmt_scalar(item))
            else:
                lines.append(pad + str(k) + ": " + _fmt_scalar(v))
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                items = list(item.items())
                if not items:
                    lines.append(pad + "- {}")
                    continue
                k0, v0 = items[0]
                if isinstance(v0, (dict, list)):
                    lines.append(pad + "- " + str(k0) + ":")
                    lines.extend(_fmt_yaml(v0, indent + 1))
                else:
                    lines.append(pad + "- " + str(k0) + ": " + _fmt_scalar(v0))
                for kk, vv in items[1:]:
                    if isinstance(vv, (dict, list)):
                        lines.append(pad + "  " + str(kk) + ":")
                        lines.extend(_fmt_yaml(vv, indent + 1))
                    else:
                        lines.append(pad + "  " + str(kk) + ": " + _fmt_scalar(vv))
            else:
                lines.append(pad + "- " + _fmt_scalar(item))
    else:
        lines.append(pad + _fmt_scalar(data))
    return lines


class AgentPage(BasePage):
    # Agent 模式管理: BasePage 范式, app 为 MainWindow。

    def __init__(self, app, parent=None):
        self._remote = None
        _dep = getattr(app, "_current_deploy", None)
        if _dep and _dep.get("host"):
            self._remote = core_data.DshRemote(_dep)
        self._presets = []
        self._pending = None
        super().__init__(app, parent)
        self.app.service.result.connect(self._on_result)
        self.app.service.finished.connect(self._on_finished)
        self._refresh()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 12)
        root.setSpacing(8)

        self._status_lbl = QLabel("就绪", objectName="monVal")
        head = QHBoxLayout()
        head.addWidget(QLabel("Agent 模式管理", objectName="cardTitle"))
        head.addStretch(1)
        head.addWidget(self._status_lbl)
        root.addLayout(head)
        hint = QLabel("Agent 模式是会话级选择（session 记录 agent-preset/selected），控制台仅做浏览与说明。",
                      objectName="cardHint")
        root.addWidget(hint)

        body = QHBoxLayout()
        body.setSpacing(10)
        root.addLayout(body, 1)

        self._table = self._make_table(
            ["名称", "描述", "文件数"], ["w", "w", "center"],
            [150, 210, 60], stretch_col=0)
        self._table.itemSelectionChanged.connect(self._on_select)
        body.addWidget(self._wrap_table("现有模式", self._table), 1)

        right = QFrame(objectName="card")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(10, 8, 10, 8)
        rv.setSpacing(4)
        rv.addWidget(QLabel("preset.yml（只读）", objectName="rightTitle"))
        self._info_lbl = QLabel("请在左侧选择一个模式", objectName="monName")
        rv.addWidget(self._info_lbl)
        self._detail_text = QPlainTextEdit()
        self._detail_text.setReadOnly(True)
        self._detail_text.setFont(QFont("Consolas", 9))
        self._detail_text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._detail_text.setPlainText("请在左侧选择一个模式")
        rv.addWidget(self._detail_text, 1)
        body.addWidget(right, 2)

        btns = QHBoxLayout()
        self._btn_open = QPushButton("打开 .agent-presets 目录")
        self._btn_open.clicked.connect(self._open_dir)
        self._btn_refresh = QPushButton("刷新")
        self._btn_refresh.clicked.connect(self._refresh)
        for b in (self._btn_open, self._btn_refresh):
            btns.addWidget(b)
        btns.addStretch(1)
        root.addLayout(btns)


    def _make_table(self, headers, anchors, widths, stretch_col):
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.verticalHeader().setVisible(False)
        t.setSelectionBehavior(QTableWidget.SelectRows)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        hh = t.horizontalHeader()
        for i, (a, wd) in enumerate(zip(anchors, widths)):
            hh.setSectionResizeMode(i, QHeaderView.ResizeToContents if i != stretch_col
                                    else QHeaderView.Stretch)
            t.setColumnWidth(i, wd)
            if a == "center":
                t.horizontalHeaderItem(i).setTextAlignment(Qt.AlignCenter)
        return t

    def _wrap_table(self, caption, table):
        card = QFrame(objectName="card")
        v = QVBoxLayout(card)
        v.setContentsMargins(10, 8, 10, 8)
        cap = QLabel(caption, objectName="rightTitle")
        v.addWidget(cap)
        v.addWidget(table)
        return card

    # ── 列表(service 信号桥) ──
    def _refresh(self):
        self._set_status("正在读取 Agent 模式列表...")
        self._set_btns(False)
        self._pending = "agents-list"
        self.app.service.list_agent_presets(self._remote)

    def _on_result(self, op, payload):
        if op == "agents-list":
            self._pending = None
            self._apply_data(payload.get("data") or [], payload.get("err", ""))

    def _on_finished(self, op, ok):
        # 兜底: result 槽漏执行导致 busy 悬挂时解除
        if op == self._pending:
            self._pending = None
            self._set_btns(True)

    def _apply_data(self, presets, err):
        self._set_btns(True)
        self._presets = presets
        self._table.setRowCount(len(presets))
        for r, p in enumerate(presets):
            self._table.setItem(r, 0, QTableWidgetItem(p["name"]))
            self._table.setItem(r, 1, QTableWidgetItem(p["desc"] or "—"))
            self._table.setItem(r, 2, QTableWidgetItem(str(p["files"])))
        self._table.clearSelection()
        self._reset_detail()
        if err:
            self._set_status("读取失败: " + err)
            self.app.loge("[Agent模式] 读取失败: " + err, "err")
        else:
            self._set_status("已加载 %d 个 Agent 模式" % len(presets))

    # ── 详情(本机小文件, 同步直读; 无过期回包问题) ──
    def _on_select(self):
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return
        name = self._table.item(rows[0].row(), 0).text()
        preset = None
        for p in self._presets:
            if p["name"] == name:
                preset = p
                break
        if preset is None:
            return
        self._info_lbl.setText("模式: %s   ·   描述: %s   ·   文件数: %d"
                               % (name, preset["desc"] or "—", preset["files"]))
        pp = os.path.join(core_data.dsh_home(), ".agent-presets", name, "preset.yml")
        try:
            data = core_data.read_yaml(pp)
            if data is None:
                text = "(preset.yml 不存在或为空)"
            else:
                text = "\n".join(_fmt_yaml(data))
            err = ""
        except Exception as e:
            text, err = "", str(e)
        if err:
            self._detail_text.setPlainText("读取失败: " + err)
            self._set_status("读取 preset.yml 失败: " + err)
            self.app.loge("[Agent模式] 读取 " + name + " 失败: " + err, "err")
            return
        self._detail_text.setPlainText(text)

    def _reset_detail(self):
        self._info_lbl.setText("请在左侧选择一个模式")
        self._detail_text.setPlainText("请在左侧选择一个模式")

    def _open_dir(self):
        base = os.path.join(core_data.dsh_home(), ".agent-presets")
        if not os.path.isdir(base):
            QMessageBox.information(self, "目录不存在",
                                    "尚未创建任何 Agent 模式（%s）" % base)
            return
        try:
            os.startfile(base)
        except Exception as e:
            QMessageBox.critical(self, "无法打开", str(e))

    def _set_btns(self, on):
        for b in (self._btn_open, self._btn_refresh):
            b.setEnabled(on)

    def _set_status(self, text):
        self._status_lbl.setText(text)
