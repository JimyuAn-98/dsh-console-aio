# -*- coding: utf-8 -*-
# Profile 管理页(PySide6 迁移版): 浏览/复制/删除 ~/.dsh/profiles。
# 复制排除 node_modules; web 是默认 Profile 不可删除。dsh web 等价 dsh --profile web。
# 后台线程做读取/复制/删除 IO, 结果经 Qt Signal 回主线程更新表格与弹窗, 不直接改 UI。

import json
import os
import shutil
import threading

import dsh_data
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView, QMessageBox, QInputDialog)

from pyside.base import BasePage

# 仓库根目录(本文件位于 pyside/ 下, 上溯一级), config.json 存放于此
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


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
    # Profile 管理: BasePage 范式, app 为 MainWindow。
    _data = Signal(object, str)         # (profiles, err)
    _op_done = Signal(str, str, str)    # (title, msg, err)

    def __init__(self, app, parent=None):
        self._remote = None
        _dep = getattr(app, "_current_deploy", None)
        if _dep and _dep.get("host"):
            self._remote = dsh_data.DshRemote(_dep)
        self._is_web_current = "web" in _load_dash_cmd()
        super().__init__(app, parent)
        self._data.connect(self._apply_data)
        self._op_done.connect(self._after_op)
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
            self._data.emit(profiles or [], err)

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

    def _selected(self):
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        return self._table.item(rows[0].row(), 0).text()

    def _copy_profile(self):
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
        if any(ch in new for ch in '\\/:*?"<>|'):
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
        self._set_btns(False)

        def worker():
            err = None
            msg = "已复制 %s → %s" % (src, new)
            try:
                shutil.copytree(os.path.join(base, src), os.path.join(base, new),
                                ignore=shutil.ignore_patterns("node_modules"))
            except Exception as e:
                msg, err = "复制失败", str(e)
            self._op_done.emit("复制 Profile", msg, err)

        threading.Thread(target=worker, daemon=True).start()

    def _delete_profile(self):
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
        self._set_btns(False)

        def worker():
            err = None
            msg = "已删除 %s" % name
            try:
                shutil.rmtree(os.path.join(base, name))
            except Exception as e:
                msg, err = "删除失败", str(e)
            self._op_done.emit("删除 Profile", msg, err)

        threading.Thread(target=worker, daemon=True).start()

    def _after_op(self, title, msg, err):
        self._set_btns(True)
        self._refresh()
        if err:
            QMessageBox.critical(self, title, "%s：%s" % (msg, err))
            self._set_status("操作失败: " + err)
        else:
            self.app.loge("[Profile管理] " + msg, "ok")
            self._set_status(msg)
            QMessageBox.information(self, title, msg)

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