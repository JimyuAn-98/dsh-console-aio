# -*- coding: utf-8 -*-
# Profile 管理页(UI 层): 只做展示/预检/确认框/busy 管理, 复制/删除业务在 core/profiles.py。
# 复制/删除经 app.services 信号桥后台执行: service.copy_profile(src, new)/delete_profile(name)
# -> result(op, payload) + finished(op, ok) 回页面槽(按 op key 分派), 接收者是页面自身,
# 页面销毁 Qt 自动断开; log/status 不在页面 connect —— 主窗口级已 connect 一次(勿叠加)。
# 列表读取暂留页面直连(远程读取可能秒级耗时, 纯读是分层设计允许的过渡态):
# 后台线程 + 本页 _data 信号, 经 BasePage.safe_emit 回主线程(修复页面销毁竞态 RuntimeError)。
# 远程只读红线: 远程部署(self._remote 非 None)下复制/删除一律拒绝, 不触 service。
# 复制排除 node_modules; web 是默认 Profile 不可删除。dsh web 等价 dsh --profile web。

import json
import os
import threading

from core import data as dsh_data
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView, QMessageBox, QInputDialog)

from ui.base import BasePage

# 仓库根目录(本文件位于 ui/ 下, 上溯一级), config.json 存放于此
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

# 名称禁用字符: 与 core.profiles 同源(UI 预检, core 会再防线一次)
_BAD_CHARS = '\\/:*?"<>|'


def _load_dash_cmd():
    # 读取控制台 config.json 的 dash_cmd, 用于判断当前是否以 web Profile 启动
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
        cmd = cfg.get("dash_cmd")
        return cmd if isinstance(cmd, list) else []
    except (OSError, ValueError):
        return []


class ProfilePage(BasePage):
    # Profile 管理: BasePage 范式, app 为 MainWindow; 写操作业务经 service 信号桥。
    _data = Signal(object, str)         # (profiles, err) 列表读取线程回包

    def __init__(self, app, parent=None):
        self._remote = None
        _dep = getattr(app, "_current_deploy", None)
        if _dep and _dep.get("host"):
            self._remote = dsh_data.DshRemote(_dep)
        self._is_web_current = "web" in _load_dash_cmd()
        self._pending = None   # 正在等待的 service op: "profile-copy" / "profile-delete"
        super().__init__(app, parent)
        self._data.connect(self._apply_data)
        self.app.service.result.connect(self._on_result)
        self.app.service.finished.connect(self._on_finished)
        self._refresh()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 12)
        root.setSpacing(8)

        title = QLabel("Profile 管理", objectName="cardTitle")
        root.addWidget(title)
        hint = QLabel("dsh 用 dsh --profile <名> 启动；dsh web 等价 dsh --profile web。"
                      "web 是默认 Profile，不可删除。", objectName="cardHint")
        root.addWidget(hint)

        self._table = self._make_table(
            ["名称", "cordis.yml", "patch", "package.json", "当前"],
            ["w", "center", "center", "center", "center"],
            [150, 80, 80, 110, 60], stretch_col=0)
        card = QFrame(objectName="card")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(10, 8, 10, 8)
        cap = QLabel("Profile 列表", objectName="rightTitle")
        cv.addWidget(cap)
        cv.addWidget(self._table)
        root.addWidget(card, 1)

        btns = QHBoxLayout()
        self._btn_copy = QPushButton("复制 Profile")
        self._btn_copy.clicked.connect(self._copy_profile)
        self._btn_delete = QPushButton("删除 Profile")
        self._btn_delete.clicked.connect(self._delete_profile)
        self._btn_open = QPushButton("打开目录")
        self._btn_open.clicked.connect(self._open_dir)
        self._btn_refresh = QPushButton("刷新")
        self._btn_refresh.clicked.connect(self._refresh)
        for b in (self._btn_copy, self._btn_delete, self._btn_open, self._btn_refresh):
            btns.addWidget(b)
        btns.addStretch(1)
        root.addLayout(btns)

        self._status_lbl = QLabel("就绪", objectName="statusBar")
        root.addWidget(self._status_lbl)

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
        t.setSelectionMode(QTableWidget.SingleSelection)
        return t

    # ---- 列表读取(纯读暂留页面直连: 后台线程 + safe_emit 回主线程) ----
    def _refresh(self):
        self._set_status("正在读取 Profile 列表...")
        self._set_btns(False)

        def worker():
            err = None
            profiles = None
            try:
                profiles = dsh_data.list_profiles(remote=self._remote)
            except Exception as e:
                err = str(e)
            self.safe_emit(self._data, profiles or [], err)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_data(self, profiles, err):
        self._set_btns(True)
        self._table.setRowCount(len(profiles))
        for r, p in enumerate(profiles):
            cur = "✓" if (self._is_web_current and p["name"] == "web") else ""
            self._table.setItem(r, 0, QTableWidgetItem(p["name"]))
            self._table.setItem(r, 1, QTableWidgetItem("✓" if p["cordis"] else "—"))
            self._table.setItem(r, 2, QTableWidgetItem("✓" if p["patch"] else "—"))
            self._table.setItem(r, 3, QTableWidgetItem("✓" if p["pkg"] else "—"))
            self._table.setItem(r, 4, QTableWidgetItem(cur))
        if err:
            self._set_status("读取失败: " + err)
        else:
            self._set_status("已加载 %d 个 Profile" % len(profiles))

    # ---- service 信号槽(接收者=本页, 销毁自动断开) ----
    def _on_result(self, op, payload):
        # result(op, payload) 按 op key 分派; 其他页面的 op 直接忽略。
        if op == "profile-copy":
            self._pending = None
            self._after_op("复制 Profile", payload)
        elif op == "profile-delete":
            self._pending = None
            self._after_op("删除 Profile", payload)

    def _on_finished(self, op, ok):
        # 兜底: _run_result_op 契约保证 result+finished 成对到达, 正常路径 result 槽
        # 已收尾; 若 result 槽漏执行导致 busy 悬挂, 在这里解除按钮禁用。
        if op == self._pending:
            self._pending = None
            self._set_btns(True)

    def _after_op(self, title, payload):
        # payload = {"msg": 成功文案, "err": 中文失败文案}(文案由 core 出, 对称取值)。
        msg = payload.get("msg", "")
        err = payload.get("err", "")
        self._set_btns(True)
        self._refresh()
        if err:
            QMessageBox.critical(self, title, err)
            self._set_status("操作失败: " + err)
        else:
            self.app.loge("[Profile管理] " + msg, "ok")
            self._set_status(msg)
            QMessageBox.information(self, title, msg)

    # ---- 写操作入口(预检 + 确认框在 UI, 校验在 core 再防线一次) ----
    def _refuse_remote_write(self):
        # 远程只读红线: 远程部署下写操作一律拒绝, 不触 service。
        if self._remote is not None:
            QMessageBox.warning(self, "远程只读",
                                "远程部署下暂不支持写操作（远程只读），请切换回本机部署。")
            return True
        return False

    def _selected(self):
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        return self._table.item(rows[0].row(), 0).text()

    def _copy_profile(self):
        if self._refuse_remote_write():
            return
        base = dsh_data.profiles_dir()
        if not os.path.isdir(base):
            QMessageBox.information(self, "目录不存在", "尚未创建任何 Profile。")
            return
        src = self._selected()
        if not src:
            QMessageBox.information(self, "请先选择", "请先在列表中选择要复制的 Profile。")
            return
        new, ok = QInputDialog.getText(self, "复制 Profile", "输入新 Profile 名称：")
        if not ok:
            return
        new = new.strip()
        if not new:
            QMessageBox.warning(self, "名称无效", "Profile 名称不能为空。")
            return
        if any(ch in new for ch in _BAD_CHARS):
            QMessageBox.warning(self, "名称无效", '名称不能包含 \\ / : * ? " < > | 等字符。')
            return
        if new == src:
            QMessageBox.warning(self, "名称无效", "新名称不能与源 Profile 相同。")
            return
        if os.path.isdir(os.path.join(base, new)):
            QMessageBox.warning(self, "已存在", "名为 %s 的 Profile 已存在。" % new)
            return
        if QMessageBox.question(self, "复制 Profile",
                                "将复制 '%s' 到 '%s'（排除 node_modules）。\n是否继续？"
                                % (src, new)) != QMessageBox.Yes:
            return
        self._set_status("正在复制 Profile...")
        self._pending = "profile-copy"
        self._set_btns(False)
        self.app.service.copy_profile(src, new)

    def _delete_profile(self):
        if self._refuse_remote_write():
            return
        base = dsh_data.profiles_dir()
        name = self._selected()
        if not name:
            QMessageBox.information(self, "请先选择", "请先在列表中选择要删除的 Profile。")
            return
        if name == "web":
            QMessageBox.warning(self, "不能删除", "web 是默认 Profile，请勿删除。")
            return
        if not os.path.isdir(os.path.join(base, name)):
            QMessageBox.warning(self, "目录不存在", "Profile 目录不存在，可能已被删除。")
            return
        if QMessageBox.question(self, "删除 Profile",
                                "将永久删除 '%s' 目录及其全部内容。\n是否继续？" % name) != QMessageBox.Yes:
            return
        self._set_status("正在删除 Profile...")
        self._pending = "profile-delete"
        self._set_btns(False)
        self.app.service.delete_profile(name)

    # ---- 打开目录(页面本机动作, 留 UI 层) ----
    def _open_dir(self):
        base = dsh_data.profiles_dir()
        name = self._selected()
        if name and os.path.isdir(os.path.join(base, name)):
            target = os.path.join(base, name)
        else:
            target = base
        if not os.path.isdir(target):
            QMessageBox.information(self, "目录不存在", "尚未创建任何 Profile（%s）" % base)
            return
        try:
            os.startfile(target)
        except Exception as e:
            QMessageBox.critical(self, "无法打开", str(e))

    def _set_btns(self, on):
        for b in (self._btn_copy, self._btn_delete, self._btn_open, self._btn_refresh):
            b.setEnabled(on)

    def _set_status(self, text):
        self._status_lbl.setText(text)
