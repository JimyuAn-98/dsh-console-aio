# -*- coding: utf-8 -*-
# SSH 密钥管理页(PySide6 迁移版)。
# 安全红线: 私钥内容绝不读取/展示/复制/写入; 只显示文件名/时间/指纹(ssh-keygen -lf)。
# 公钥(.pub)为公开信息, 可展示与复制。
# 数据源是本机 ~/.ssh, 不涉及远程部署, 不需要 DshRemote。
# 后台线程做 IO/子进程(list_keys 会对每个密钥跑 ssh-keygen -lf) -> Qt Signal 回主线程, 不直接改 UI。

import io
import os
import subprocess
import threading
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView, QMessageBox, QPlainTextEdit, QInputDialog)

from pyside.base import BasePage


# 私钥文件名模式(不读内容, 只列存在性)
_PRIV_PREFIXES = ("id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",
                  "id_ecdsa_sk", "id_ed25519_sk")


def ssh_dir():
    return os.path.join(os.path.expanduser("~"), ".ssh")


def _key_fingerprint(path):
    # 指纹: ssh-keygen -lf 输出(公钥指纹, 不泄露私钥); 失败返回 None。
    # 吞掉一切异常: 平台差异/ssh-keygen 缺失都只导致指纹显示为占位符。
    try:
        r = subprocess.run(["ssh-keygen", "-lf", path], capture_output=True,
                           text=True, errors="replace", timeout=10,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        if r.returncode == 0:
            parts = r.stdout.split()
            if len(parts) >= 2:
                return parts[1]   # 如 SHA256:xxxx
    except Exception:
        pass
    return None


def list_keys():
    # 返回 [{name, is_pub, fp, mtime}]; 私钥不读内容, 指纹经 ssh-keygen -lf。
    out = []
    d = ssh_dir()
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        fp = os.path.join(d, fn)
        if not os.path.isfile(fp):
            continue
        is_pub = fn.endswith(".pub")
        is_priv = (not is_pub) and fn.startswith(_PRIV_PREFIXES)
        if not (is_pub or is_priv):
            continue
        name = fn[:-4] if is_pub else fn
        out.append({
            "name": name,
            "is_pub": is_pub,
            "fp": _key_fingerprint(fp),
            "mtime": os.path.getmtime(fp),
        })
    return out


def read_pubkey(name):
    # 读公钥内容(.pub, 公开信息); 私钥绝不读。
    p = os.path.join(ssh_dir(), name + ".pub")
    if not os.path.isfile(p):
        return None
    with io.open(p, encoding="utf-8", errors="replace") as fh:
        return fh.read().strip()


def _fmt_time(ts):
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts)))
    except Exception:
        return "-"


class KeysPage(BasePage):
    # SSH 密钥管理: BasePage 范式, app 为 MainWindow。
    _data = Signal(object, str)               # (keys, err) 列表刷新结果
    _pub_loaded = Signal(str, str, str, str)  # (name, pub, err, action) 公钥读取结果
    _gen_done = Signal(str, str)              # (msg, err) 生成结果

    def __init__(self, app, parent=None):
        self._keys = []
        self._cur_pub = None
        self._last_op_msg = None
        super().__init__(app, parent)
        self._data.connect(self._apply_data)
        self._pub_loaded.connect(self._apply_pub)
        self._gen_done.connect(self._after_gen)
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

    def _selected(self):
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        idx = rows[0].row()
        return self._keys[idx] if 0 <= idx < len(self._keys) else None

    def _refresh(self):
        self._set_status("正在读取密钥列表...")
        self._set_btns(False)

        def worker():
            err = None
            keys = None
            try:
                keys = list_keys()
            except Exception as e:
                err = str(e)
            self._data.emit(keys or [], err)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_data(self, keys, err):
        self._set_btns(True)
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
            self._set_status("读取失败: " + err)
            self.app.loge("[SSH密钥] 读取失败: " + err, "err")
        elif self._last_op_msg:
            self._set_status(self._last_op_msg)
            self._last_op_msg = None
        else:
            self._set_status("共 %d 个密钥" % len(keys))

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
        self._load_pub(k["name"])

    def _load_pub(self, name, action=""):
        # 读 .pub 属 IO, 放后台线程; 结果带 name/action, 过期结果在 _apply_pub 丢弃。
        def worker():
            pub = None
            err = None
            try:
                pub = read_pubkey(name)
            except Exception as e:
                err = str(e)
            self._pub_loaded.emit(name, pub, err, action)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_pub(self, name, pub, err, action):
        k = self._selected()
        if k is None or k["name"] != name:
            return  # 结果对应的选择已切换, 丢弃过期数据
        self._cur_pub = pub
        self._pub_text.setPlainText(pub or "(无 .pub 文件)")
        self._btn_copy.setEnabled(bool(k["is_pub"]) and bool(pub))
        if err:
            self._set_status("读取公钥失败: " + err)
            return
        if action == "view":
            self._show_pub_msg(name, pub)
        elif action == "copy":
            self._do_copy(name, pub)

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
        self._load_pub(k["name"], action="view")

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
        self._load_pub(k["name"], action="copy")

    def _do_copy(self, name, pub):
        if not pub:
            QMessageBox.warning(self, "无公钥", "未找到 " + name + ".pub")
            return
        QGuiApplication.clipboard().setText(pub)
        self._set_status("公钥已复制到剪贴板")
        self.app.loge("[SSH密钥] 公钥 " + name + " 已复制", "ok")

    def _gen_key(self):
        name, ok = QInputDialog.getText(self, "生成新密钥", "密钥名称(如 id_ed25519_my):")
        if not ok or not name:
            return
        if not name.startswith("id_"):
            QMessageBox.warning(self, "命名建议", "建议以 id_ 开头(如 id_ed25519_my)")
        path = os.path.join(ssh_dir(), name)
        if QMessageBox.question(
                self, "生成新密钥",
                '将执行: ssh-keygen -t ed25519 -f %s -N ""\n\n'
                '注意: -N "" 表示无口令保护。如需口令保护, 请在终端手动生成。\n是否继续？' % path) != QMessageBox.Yes:
            return
        self._set_btns(False)

        def worker():
            err = None
            msg = ""
            try:
                os.makedirs(ssh_dir(), exist_ok=True)
                r = subprocess.run(["ssh-keygen", "-t", "ed25519", "-f", path, "-N", "",
                                    "-C", "dsh-console-aio"], capture_output=True,
                                   text=True, errors="replace", timeout=30,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
                if r.returncode == 0:
                    msg = "已生成: %s (ed25519)" % name
                else:
                    msg = "生成失败: " + (r.stderr or "").strip()
            except Exception as e:
                err = str(e)
            self._gen_done.emit(msg, err)

        threading.Thread(target=worker, daemon=True).start()

    def _after_gen(self, msg, err):
        self._set_btns(True)
        if err:
            self._set_status("生成异常: " + err)
            self.app.loge("[SSH密钥] 生成异常: " + err, "err")
            return
        if msg.startswith("生成失败"):
            self._set_status(msg)
            self.app.loge("[SSH密钥] " + msg, "err")
            return
        self.app.loge("[SSH密钥] " + msg, "ok")
        self._last_op_msg = msg + "（已刷新）"
        self._refresh()

    def _open_dir(self):
        if QMessageBox.question(
                self, "打开 .ssh 目录",
                '将打开本机 ~/.ssh 目录(含私钥文件)。\n\n'
                '注意: 目录内有私钥, 请勿将其内容泄露或上传。\n\n是否打开？') != QMessageBox.Yes:
            return
        try:
            os.makedirs(ssh_dir(), exist_ok=True)
            os.startfile(ssh_dir())
        except Exception as e:
            QMessageBox.critical(self, "无法打开", str(e))

    def _set_btns(self, on):
        for b in (self._btn_refresh, self._btn_gen, self._btn_view,
                  self._btn_copy, self._btn_open):
            b.setEnabled(on)

    def _set_status(self, text):
        self._status_lbl.setText(text)
