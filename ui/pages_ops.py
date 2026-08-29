# -*- coding: utf-8 -*-
# 备份与运维页(UI 层): 只做展示/确认框/busy 管理, 业务在 core/ops.py(纯 Python)。
# 备份经 app.services 信号桥后台执行: service.backup_dsh_home(path) -> result(op, payload)
# + finished(op, ok) 回页面槽(op key "ops-backup"), 接收者是页面自身, 页面销毁 Qt 自动断开;
# log/status 不在页面 connect —— 主窗口级已 connect 一次(勿叠加)。
# 日志目录/列表/尾部与凭据存在性是本地小 IO, 同步直调(core.ops / dsh_data 纯读,
# 分层设计允许的过渡态; 阶段4 收敛数据层后统一走 service)。本页只操作本机, 与部署无关。

import os
import time

from core import data as dsh_data
import core.ops
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView, QMessageBox, QFileDialog, QDialog, QPlainTextEdit)

from ui.base import BasePage


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


class OpsPage(BasePage):
    # 备份与运维: BasePage 范式, app 为 MainWindow。
    def __init__(self, app, parent=None):
        self._pending = None   # 正在等待的 service op(当前仅 "ops-backup")
        super().__init__(app, parent)
        self.app.service.result.connect(self._on_result)
        self.app.service.finished.connect(self._on_finished)
        self._refresh_logs()
        self._refresh_cred()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 12)
        root.setSpacing(8)

        self._status_lbl = QLabel("就绪", objectName="monVal")
        head = QHBoxLayout()
        head.addWidget(QLabel("备份与运维", objectName="cardTitle"))
        head.addStretch(1)
        head.addWidget(self._status_lbl)
        root.addLayout(head)

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
        self._log_dir = core.ops.log_dir()
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
        for b in (self._btn_refresh, self._btn_open, self._btn_tail):
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

    # ---- 日志(本地小 IO, 同步直调 core; 同步调用无重入, 不需要按钮禁用) ----
    def _refresh_logs(self):
        self._set_status("正在刷新日志列表...")
        try:
            entries = core.ops.log_entries()
            err = ""
        except Exception as e:
            # core 契约是 list_entries 不抛; 这里兜底防御, 失败降级为空表+提示
            entries, err = [], str(e)
        self._logs_table.setRowCount(len(entries))
        for r, e in enumerate(entries):
            self._logs_table.setItem(r, 0, QTableWidgetItem(e["name"]))
            self._logs_table.setItem(r, 1, QTableWidgetItem(_fmt_size(e.get("size"))))
            self._logs_table.setItem(r, 2, QTableWidgetItem(_fmt_time(e.get("mtime"))))
        if err:
            self._set_status("刷新日志失败: " + err)
            self.app.loge("[运维] 刷新日志失败: " + err, "err")
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
        # 读取所选日志尾部(同步小 IO), 完成后弹出只读窗口
        rows = self._logs_table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "提示", "请先在列表中选择一个日志文件。")
            return
        fn = self._logs_table.item(rows[0].row(), 0).text()
        path = os.path.join(self._log_dir, fn)
        try:
            body = core.ops.read_tail(path)
            err = ""
        except Exception as e:
            body, err = "", str(e)
        self._show_tail(fn, body, err)

    def _show_tail(self, name, body, err):
        # 弹出只读窗口显示日志尾部
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

    # ---- 备份(经 service 信号桥; 选路径与确认在 UI, 业务在 core) ----
    def _do_backup(self):
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
        self._pending = "ops-backup"
        self._backup_path = path
        self._backup_btn.setEnabled(False)
        self._backup_lbl.setText("备份中…")
        self._set_status("正在备份 ~/.dsh ...")
        self.app.service.backup_dsh_home(path)

    def _on_result(self, op, payload):
        # result(op, payload) 按 op key 分派; 其他页面的 op 直接忽略。
        if op != "ops-backup":
            return
        self._pending = None
        err = payload.get("err", "")
        count = payload.get("count", 0)
        size = payload.get("size", 0)
        path = getattr(self, "_backup_path", "")
        self._backup_btn.setEnabled(True)
        if err:
            self._backup_lbl.setText("备份失败")
            self._set_status("备份失败: " + err)
            self.app.loge("[运维] 备份失败: " + err, "err")
            QMessageBox.critical(self, "备份失败", err)
            return
        msg = "已备份 %d 个文件，大小 %s。\n%s" % (count, _fmt_size(size), path)
        self._backup_lbl.setText("完成：%d 个文件，%s" % (count, _fmt_size(size)))
        self._set_status("已备份 %d 个文件，大小 %s" % (count, _fmt_size(size)))
        self.app.loge("[运维] " + msg.replace("\n", " "), "ok")
        QMessageBox.information(self, "备份完成", msg)

    def _on_finished(self, op, ok):
        # 兜底: _run_result_op 契约保证 result+finished 成对到达, 正常路径 result 槽
        # 已收尾; 若 result 槽漏执行导致 busy 悬挂, 在这里解除按钮禁用。
        if op == self._pending:
            self._pending = None
            self._backup_btn.setEnabled(True)

    # ---- 凭据(存在性展示, 纯读, 绝不明文) ----
    def _refresh_cred(self):
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

    def _set_status(self, text):
        self._status_lbl.setText(text)
