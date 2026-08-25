# -*- coding: utf-8 -*-
# 备份与运维页(PySide6 迁移版)。
# 三个运维分区: 备份 ~/.dsh 到 zip(数据层自动排除凭据/密钥/sessions/node_modules)、
# 查看 dsh web 日志(目录/尾部, 尾部后台线程读, 防大文件)、凭据只提示存在性与时间(不明文展示)。
# 本页只操作本机 dsh_home 与 %TEMP%/dsh-dash 日志, 与当前部署无关, 不需要 DshRemote。
# 后台线程做 IO -> Qt Signal 回主线程更新控件, 绝不直接改 UI(线程安全)。

import os
import tempfile
import threading
import time

import dsh_data
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView, QMessageBox, QFileDialog, QDialog, QPlainTextEdit)

from pyside.base import BasePage

TAIL_BYTES = 16384   # 查看日志尾部最多读取的字节数


def _fmt_size(n):
    # 字节数转人类可读文本(B/KB/MB/GB)
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            if unit == "B":
                return "%d B" % int(n)
            return "%.1f %s" % (n, unit)
        n /= 1024.0
    return "0 B"


def _fmt_time(ts):
    # 时间戳转本地时间文本; 读取失败返回问号占位
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(ts)))
    except (OSError, ValueError, TypeError):
        return "?"


def _read_tail(path, limit=TAIL_BYTES):
    # 从文件尾部读最多 limit 字节, 避免大文件整读; 截断时丢弃首行残余半行。
    # 统一换行符, 避免 Windows 日志的 \r 残留显示。
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        start = max(0, size - limit)
        fh.seek(start)
        data = fh.read()
    text = data.decode("utf-8", errors="replace")
    text = text.replace("\r\n", "\n")
    if start > 0:
        nl = text.find("\n")
        if nl >= 0:
            text = text[nl + 1:]
    return text


def _log_entries(log_dir):
    # 列出日志目录下 *.log 的文件名/大小/修改时间; 目录不存在或读取失败返回空表。
    out = []
    if not os.path.isdir(log_dir):
        return out
    try:
        names = sorted(os.listdir(log_dir))
    except OSError:
        return out
    for fn in names:
        if not fn.lower().endswith(".log"):
            continue
        fp = os.path.join(log_dir, fn)
        if not os.path.isfile(fp):
            continue
        try:
            st = os.stat(fp)
        except OSError:
            continue
        out.append({"name": fn, "size": st.st_size, "mtime": st.st_mtime})
    return out


class OpsPage(BasePage):
    # 备份与运维: BasePage 范式, app 为 MainWindow。
    _logs_data = Signal(object, str)              # (日志条目表, err) 日志列表刷新结果
    _tail_read = Signal(str, str, str, str)       # (path, name, body, err) 尾部读取结果
    _backup_done = Signal(int, int, str, str)     # (count, size, err, path) 备份完成结果

    def __init__(self, app, parent=None):
        # dsh web 日志目录固定为 %TEMP%/dsh-dash
        self._log_dir = os.path.join(os.environ.get("TEMP") or tempfile.gettempdir(), "dsh-dash")
        self._last_op_msg = None
        super().__init__(app, parent)
        self._logs_data.connect(self._apply_logs)
        self._tail_read.connect(self._show_tail)
        self._backup_done.connect(self._after_backup)
        self._refresh_logs()
        self._refresh_cred()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 12)
        root.setSpacing(8)

        title = QLabel("备份与运维", objectName="cardTitle")
        root.addWidget(title)

        # ---- 备份分区 ----
        bak = QFrame(objectName="card")
        bl = QVBoxLayout(bak)
        bl.setContentsMargins(12, 8, 12, 8)
        bl.setSpacing(6)
        bl.addWidget(QLabel("一键备份 ~/.dsh 到 zip。自动排除：凭据/密钥文件、sessions、node_modules。",
                            objectName="cardHint"))
        brow = QHBoxLayout()
        self._backup_btn = QPushButton("备份 ~/.dsh…")
        self._backup_btn.clicked.connect(self._do_backup)
        brow.addWidget(self._backup_btn)
        self._backup_lbl = QLabel("", objectName="monName")
        brow.addWidget(self._backup_lbl)
        brow.addStretch(1)
        bl.addLayout(brow)
        root.addWidget(bak)

        # ---- 日志分区 ----
        logs_card = QFrame(objectName="card")
        ll = QVBoxLayout(logs_card)
        ll.setContentsMargins(10, 8, 10, 8)
        ll.setSpacing(6)
        ll.addWidget(QLabel("dsh web 日志（%s）" % self._log_dir, objectName="rightTitle"))
        self._logs_table = self._make_table(
            ["文件", "大小", "最后修改"], ["w", "e", "w"], [300, 90, 150], stretch_col=0)
        ll.addWidget(self._logs_table)
        lobs = QHBoxLayout()
        self._btn_refresh = QPushButton("刷新")
        self._btn_refresh.clicked.connect(self._refresh_logs)
        self._btn_open = QPushButton("打开目录")
        self._btn_open.clicked.connect(self._open_log_dir)
        self._btn_tail = QPushButton("查看尾部")
        self._btn_tail.clicked.connect(self._view_tail)
        self._log_btns = (self._btn_refresh, self._btn_open, self._btn_tail)
        for b in self._log_btns:
            lobs.addWidget(b)
        lobs.addStretch(1)
        ll.addLayout(lobs)
        root.addWidget(logs_card, 1)

        # ---- 凭据分区 ----
        cred = QFrame(objectName="card")
        cl = QVBoxLayout(cred)
        cl.setContentsMargins(12, 8, 12, 8)
        cl.setSpacing(6)
        cl.addWidget(QLabel("凭据（只提示存在性，不明文展示）", objectName="rightTitle"))
        self._cred_lbl = QLabel("", objectName="monName")
        cl.addWidget(self._cred_lbl)
        cl.addWidget(QLabel(
            "安全说明：.credentials.yaml 与 apiKeyEnv 引用的密钥只保存在系统环境变量中，\n"
            "控制台不读取、不写入、不展示密钥明文。", objectName="cardHint"))
        root.addWidget(cred)

        self._status_lbl = QLabel("就绪", objectName="statusBar")
        root.addWidget(self._status_lbl)

    def _make_table(self, headers, anchors, widths, stretch_col):
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.verticalHeader().setVisible(False)
        t.setSelectionBehavior(QTableWidget.SelectRows)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.setSelectionMode(QTableWidget.SingleSelection)
        hh = t.horizontalHeader()
        for i, (a, wd) in enumerate(zip(anchors, widths)):
            hh.setSectionResizeMode(i, QHeaderView.ResizeToContents if i != stretch_col
                                    else QHeaderView.Stretch)
            t.setColumnWidth(i, wd)
            if a == "e":
                t.horizontalHeaderItem(i).setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            elif a == "center":
                t.horizontalHeaderItem(i).setTextAlignment(Qt.AlignCenter)
        return t

    def _refresh_logs(self):
        # 列出 %TEMP%/dsh-dash/*.log 的文件名/大小/修改时间(后台线程 IO)
        self._set_status("正在刷新日志列表...")
        self._set_log_btns(False)

        def worker():
            err = None
            entries = None
            try:
                entries = _log_entries(self._log_dir)
            except Exception as e:
                err = str(e)
            self.safe_emit(self._logs_data, entries or [], err)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_logs(self, entries, err):
        self._set_log_btns(True)
        self._logs_table.setRowCount(len(entries))
        for r, e in enumerate(entries):
            self._logs_table.setItem(r, 0, QTableWidgetItem(e["name"]))
            self._logs_table.setItem(r, 1, QTableWidgetItem(_fmt_size(e.get("size"))))
            self._logs_table.setItem(r, 2, QTableWidgetItem(_fmt_time(e.get("mtime"))))
        if err:
            self._set_status("刷新日志失败: " + err)
            self.app.loge("[运维] 刷新日志失败: " + err, "err")
        elif self._last_op_msg:
            self._set_status(self._last_op_msg)
            self._last_op_msg = None
        else:
            self._set_status("日志文件 %d 个" % len(entries))

    def _open_log_dir(self):
        # 用资源管理器打开日志目录
        if not os.path.isdir(self._log_dir):
            QMessageBox.information(self, "提示", "日志目录不存在：\n%s" % self._log_dir)
            return
        try:
            os.startfile(self._log_dir)
        except Exception as e:
            QMessageBox.critical(self, "无法打开", str(e))

    def _view_tail(self):
        # 读取所选日志尾部(后台线程), 完成后弹出只读窗口
        row = self._selected_log_row()
        if row is None:
            QMessageBox.information(self, "提示", "请先在列表中选择一个日志文件。")
            return
        fn = self._logs_table.item(row, 0).text()
        path = os.path.join(self._log_dir, fn)
        self._set_status("正在读取日志尾部: " + fn)

        def worker():
            err = None
            body = None
            try:
                body = _read_tail(path)
            except Exception as e:
                err = str(e)
            self.safe_emit(self._tail_read, path, fn, body or "", err)

        threading.Thread(target=worker, daemon=True).start()

    def _show_tail(self, path, name, body, err):
        # 主线程弹出只读窗口显示日志尾部
        self._set_status("就绪")
        if err:
            self.app.loge("[运维] 读取日志尾部失败: " + err, "err")
            QMessageBox.critical(self, "读取失败", err)
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("日志尾部 - " + name)
        dlg.resize(680, 380)
        dlg.setStyleSheet("background: #1e1e2e; color: #e6e6e6;")
        vl = QVBoxLayout(dlg)
        vl.setContentsMargins(8, 8, 8, 8)
        txt = QPlainTextEdit()
        txt.setReadOnly(True)
        txt.setFont(QFont("Consolas", 9))
        txt.setPlainText(body)
        vl.addWidget(txt)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dlg.accept)
        hl = QHBoxLayout()
        hl.addStretch(1)
        hl.addWidget(close_btn)
        vl.addLayout(hl)
        dlg.exec()

    def _do_backup(self):
        # 选 zip 路径 -> 确认 -> 后台线程备份, 完成后回主线程提示文件数与大小
        default_name = "dsh-backup-" + time.strftime("%Y%m%d-%H%M%S") + ".zip"
        path, _filter = QFileDialog.getSaveFileName(
            self, "选择备份文件", os.path.join(os.path.expanduser("~"), default_name),
            "Zip 压缩包 (*.zip)")
        if not path:
            return
        if QMessageBox.question(
                self, "确认备份",
                "将把 ~/.dsh 备份到：\n%s\n\n"
                "自动排除：凭据/密钥文件、sessions、node_modules。\n是否继续？" % path) != QMessageBox.Yes:
            return
        self._backup_btn.setEnabled(False)
        self._backup_lbl.setText("备份中…")

        def worker():
            count = 0
            size = 0
            err = None
            try:
                count = dsh_data.backup_dsh_home(path)
                size = os.path.getsize(path)
            except Exception as e:
                err = str(e)
            self.safe_emit(self._backup_done, count, size, err, path)

        threading.Thread(target=worker, daemon=True).start()

    def _after_backup(self, count, size, err, path):
        self._backup_btn.setEnabled(True)
        if err:
            self._backup_lbl.setText("备份失败")
            self._set_status("备份失败: " + err)
            self.app.loge("[运维] 备份失败: " + err, "err")
            QMessageBox.critical(self, "备份失败", err)
            return
        msg = "已备份 %d 个文件，大小 %s。\n%s" % (count, _fmt_size(size), path)
        self._backup_lbl.setText("完成：%d 个文件，%s" % (count, _fmt_size(size)))
        self._set_status(msg)
        self.app.loge("[运维] " + msg, "ok")
        QMessageBox.information(self, "备份完成", msg)

    def _refresh_cred(self):
        # 凭据文件只显示存在性与最后修改时间, 不明文展示内容
        home = dsh_data.dsh_home()
        lines = []
        p1 = os.path.join(home, ".credentials.yaml")
        if os.path.isfile(p1):
            lines.append(".credentials.yaml：存在（最后修改 %s，内容不明文展示）" % _fmt_time(os.path.getmtime(p1)))
        else:
            lines.append(".credentials.yaml：不存在")
        p2 = os.path.join(home, ".anonymous-user-id")
        if os.path.isfile(p2):
            lines.append(".anonymous-user-id：存在")
        else:
            lines.append(".anonymous-user-id：不存在")
        self._cred_lbl.setText("\n".join(lines))

    def _selected_log_row(self):
        rows = self._logs_table.selectionModel().selectedRows()
        if not rows:
            return None
        return rows[0].row()

    def _set_log_btns(self, on):
        for b in self._log_btns:
            b.setEnabled(on)

    def _set_status(self, text):
        self._status_lbl.setText(text)
