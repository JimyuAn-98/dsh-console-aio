# -*- coding: utf-8 -*-
# SSH 密钥管理页(UI 层): 只做展示/确认框/busy 管理, 业务在 dsh_core/keys.py(纯 Python)。
# 列表与生成经 app.services.DshService 信号桥后台执行: list_ssh_keys()/generate_ssh_key(name)
# -> result(op, payload) + finished(op, ok) 回页面槽; 接收者是页面自身, 页面销毁 Qt 自动断开。
# log/status 不在页面 connect —— 主窗口级已 connect 一次(勿叠加)。
# 安全红线: 私钥内容绝不读取/展示/复制/写入; 只显示文件名/时间/指纹(ssh-keygen -lf)。
# 公钥(.pub)为公开信息, 经 dsh_core.keys.read_pubkey 同步直读展示/复制。
# 数据源是本机 ~/.ssh, 不涉及远程部署, 不需要 DshRemote。

import os
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView, QMessageBox, QPlainTextEdit, QInputDialog)

from dsh_core import keys as dsh_keys
from pyside.base import BasePage


def _fmt_time(ts):
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts)))
    except Exception:
        # 时间展示失败只影响该单元格, 显示占位符即可
        return "-"


class KeysPage(BasePage):
    # SSH 密钥管理: BasePage 范式, app 为 MainWindow; 业务经 service 信号桥。
    def __init__(self, app, parent=None):
        self._keys = []
        self._cur_pub = None
        self._last_op_msg = None
        self._pending = None   # 正在等待的 service op: "keys-list" / "keys-gen"
        super().__init__(app, parent)
        self.app.service.result.connect(self._on_result)
        self.app.service.finished.connect(self._on_finished)
        self._refresh()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 12)
        root.setSpacing(8)

        title = QLabel("SSH 密钥管理", objectName="cardTitle")
        root.addWidget(title)
        hint = QLabel("安全说明: 私钥内容绝不展示/复制; 只显示指纹(公钥指纹)。公钥(.pub)为公开信息。",
                      objectName="cardHint")
        root.addWidget(hint)

        self._table = self._make_table(
            ["名称", "类型", "指纹", "修改时间"], ["w", "center", "w", "w"],
            [180, 60, 340, 130], stretch_col=0)
        self._table.itemSelectionChanged.connect(self._on_select)
        root.addWidget(self._wrap_table("密钥列表（~/.ssh）", self._table), 1)

        btns = QHBoxLayout()
        self._btn_refresh = QPushButton("刷新")
        self._btn_refresh.clicked.connect(self._refresh)
        self._btn_gen = QPushButton("生成新密钥")
        self._btn_gen.clicked.connect(self._gen_key)
        self._btn_view = QPushButton("查看公钥")
        self._btn_view.clicked.connect(self._view_pub)
        self._btn_copy = QPushButton("复制公钥")
        self._btn_copy.clicked.connect(self._copy_pub)
        self._btn_open = QPushButton("打开 .ssh 目录")
        self._btn_open.clicked.connect(self._open_dir)
        for b in (self._btn_refresh, self._btn_gen, self._btn_view,
                  self._btn_copy, self._btn_open):
            btns.addWidget(b)
        btns.addStretch(1)
        root.addLayout(btns)

        pub_card = QFrame(objectName="card")
        pub_l = QVBoxLayout(pub_card)
        pub_l.setContentsMargins(10, 8, 10, 8)
        pub_l.setSpacing(4)
        pub_l.addWidget(QLabel("公钥内容（公开）", objectName="rightTitle"))
        self._pub_text = QPlainTextEdit()
        self._pub_text.setReadOnly(True)
        self._pub_text.setFont(QFont("Consolas", 9))
        self._pub_text.setMaximumHeight(96)
        pub_l.addWidget(self._pub_text)
        root.addWidget(pub_card)

        self._status_lbl = QLabel("就绪", objectName="statusBar")
        root.addWidget(self._status_lbl)

    # ---- service 信号槽(接收者=本页, 销毁自动断开) ----
    def _on_result(self, op, payload):
        # result(op, payload) 按 op 分派; 其他页面的 op 直接忽略。
        if op == "keys-list":
            self._apply_keys(payload)
        elif op == "keys-gen":
            self._after_gen(payload)

    def _on_finished(self, op, ok):
        # 兜底: _run_result_op 契约保证 result+finished 成对到达, 正常路径 result 槽
        # 已收尾; 若 result 槽漏执行导致 busy 悬挂, 在这里解除按钮禁用。
        if op == self._pending:
            self._pending = None
            self._set_btns(True)

    # ---- 列表 ----
    def _refresh(self):
        self._set_status("正在读取密钥列表...")
        self._pending = "keys-list"
        self._set_btns(False)
        self.app.service.list_ssh_keys()

    def _apply_keys(self, payload):
        # payload = {"keys": [{name, is_pub, fp, mtime}], "err": ""}; err 文案由 core 出。
        self._pending = None
        self._set_btns(True)
        keys = payload.get("keys") or []
        err = payload.get("err", "")
        self._keys = keys
        self._table.setRowCount(len(keys))
        for r, k in enumerate(keys):
            kind = "私钥" if not k["is_pub"] else "公钥"
            self._table.setItem(r, 0, QTableWidgetItem(k["name"]))
            self._table.setItem(r, 1, QTableWidgetItem(kind))
            self._table.setItem(r, 2, QTableWidgetItem(k["fp"] or "—"))
            self._table.setItem(r, 3, QTableWidgetItem(_fmt_time(k.get("mtime"))))
        self._table.clearSelection()
        self._on_select()
        if err:
            self._set_status(err)
        elif self._last_op_msg:
            self._set_status(self._last_op_msg)
            self._last_op_msg = None
        else:
            self._set_status("共 %d 个密钥" % len(keys))

    # ---- 公钥查看/复制(公开信息, 同步直读) ----
    def _selected(self):
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        idx = rows[0].row()
        return self._keys[idx] if 0 <= idx < len(self._keys) else None

    def _read_pub(self, name):
        # .pub 同步直读: 小文件 IO, 无需后台线程; 异常转 (None, err) 不中断选择流程。
        try:
            return dsh_keys.read_pubkey(name), ""
        except Exception as e:
            return None, str(e)

    def _on_select(self):
        k = self._selected()
        self._cur_pub = None
        self._pub_text.setPlainText("")
        if k is None:
            self._btn_view.setEnabled(False)
            self._btn_copy.setEnabled(False)
            return
        self._btn_view.setEnabled(True)
        self._btn_copy.setEnabled(False)
        pub, err = self._read_pub(k["name"])
        self._cur_pub = pub
        self._pub_text.setPlainText(pub or "(无 .pub 文件)")
        self._btn_copy.setEnabled(bool(k["is_pub"]) and bool(pub))
        if err:
            self._set_status("读取公钥失败: " + err)

    def _view_pub(self):
        k = self._selected()
        if k is None:
            return
        if QMessageBox.question(
                self, "查看公钥",
                '公钥(.pub)为公开信息, 可安全查看。\n\n'
                '注意: 公钥本身不敏感, 但请勿将私钥(id_* 无后缀文件)内容发给任何人。\n\n'
                '是否查看 ' + k["name"] + '.pub ?') != QMessageBox.Yes:
            return
        pub, err = self._read_pub(k["name"])
        if err:
            self._set_status("读取公钥失败: " + err)
            return
        self._show_pub_msg(k["name"], pub)

    def _show_pub_msg(self, name, pub):
        QMessageBox.information(self, "公钥 " + name, pub or "(无 .pub 文件)")

    def _copy_pub(self):
        k = self._selected()
        if k is None:
            return
        if QMessageBox.question(
                self, "复制公钥",
                '将把公钥内容复制到剪贴板(用于 ssh-copy-id 等)。\n\n'
                '注意: 只复制 .pub 公钥(公开信息); 请勿复制私钥内容。\n\n是否继续？') != QMessageBox.Yes:
            return
        pub, err = self._read_pub(k["name"])
        if err:
            self._set_status("读取公钥失败: " + err)
            return
        self._do_copy(k["name"], pub)

    def _do_copy(self, name, pub):
        if not pub:
            QMessageBox.warning(self, "无公钥", "未找到 " + name + ".pub")
            return
        QGuiApplication.clipboard().setText(pub)
        self._set_status("公钥已复制到剪贴板")
        self.app.loge("[SSH密钥] 公钥 " + name + " 已复制", "ok")

    # ---- 生成新密钥(危险操作, 先确认) ----
    def _gen_key(self):
        name, ok = QInputDialog.getText(self, "生成新密钥", "密钥名称(如 id_ed25519_my):")
        if not ok or not name:
            return
        name = name.strip()
        if not name:
            return
        if not name.startswith("id_"):
            QMessageBox.warning(self, "命名建议", "建议以 id_ 开头(如 id_ed25519_my)")
        path = os.path.join(dsh_keys.ssh_dir(), name)
        if QMessageBox.question(
                self, "生成新密钥",
                '将执行: ssh-keygen -t ed25519 -f %s -N ""\n\n'
                '注意: -N "" 表示无口令保护。如需口令保护, 请在终端手动生成。\n是否继续？' % path) != QMessageBox.Yes:
            return
        self._set_status("正在生成密钥...")
        self._pending = "keys-gen"
        self._set_btns(False)
        self.app.service.generate_ssh_key(name)

    def _after_gen(self, payload):
        # 成功: busy 保持, 自动刷新列表(错误文案/日志由 core 经 events 上报)。
        msg = payload.get("msg", "")
        err = payload.get("err", "")
        if err:
            self._pending = None
            self._set_btns(True)
            self._set_status(err)
            return
        self._last_op_msg = msg + "（已刷新）"
        self._pending = "keys-list"
        self.app.service.list_ssh_keys()

    # ---- 打开目录(页面本机动作, 留 UI 层) ----
    def _open_dir(self):
        if QMessageBox.question(
                self, "打开 .ssh 目录",
                '将打开本机 ~/.ssh 目录(含私钥文件)。\n\n'
                '注意: 目录内有私钥, 请勿将其内容泄露或上传。\n\n是否打开？') != QMessageBox.Yes:
            return
        try:
            os.makedirs(dsh_keys.ssh_dir(), exist_ok=True)
            os.startfile(dsh_keys.ssh_dir())
        except Exception as e:
            QMessageBox.critical(self, "无法打开", str(e))

    # ---- 展示工具 ----
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
            if a == "e":
                t.horizontalHeaderItem(i).setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            elif a == "center":
                t.horizontalHeaderItem(i).setTextAlignment(Qt.AlignCenter)
        t.setSelectionMode(QTableWidget.SingleSelection)
        return t

    def _wrap_table(self, caption, table):
        card = QFrame(objectName="card")
        v = QVBoxLayout(card)
        v.setContentsMargins(10, 8, 10, 8)
        cap = QLabel(caption, objectName="rightTitle")
        v.addWidget(cap)
        v.addWidget(table)
        return card

    def _set_btns(self, on):
        for b in (self._btn_refresh, self._btn_gen, self._btn_view,
                  self._btn_copy, self._btn_open):
            b.setEnabled(on)

    def _set_status(self, text):
        self._status_lbl.setText(text)
