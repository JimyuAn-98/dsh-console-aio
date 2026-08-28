# -*- coding: utf-8 -*-
# 版本管理页: 只做展示/危险操作确认(QMessageBox.question)/按钮 busy 管理。
# 业务全部在 core/version.py(纯 Python 零 Qt), 经 app.services.DshService 信号桥
# 调用: 检查更新 -> service.check_console_update(), 一键更新 -> service.update_console();
# 页面 connect service.result/finished(接收者=页面自身, 按操作 key 分派, 页面销毁时
# Qt 自动断开); 不 connect service.log/status —— 主窗口级已接, 页面级再接会重复输出。
# 本地更新日志是小文件, 经 core.version.read_local_notes 同步直读(不起线程);
# 下载/解压/替换等 IO 与子进程一律在 core, 页面不再 import subprocess/urllib/zipfile。
# 重启程序是 UI 生命周期动作: 调 core.spawn_restart 成功后页面才关窗退出。

import os
import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFrame, QPushButton,
    QMessageBox, QPlainTextEdit)

from core import version as core_version
from ui.base import BasePage


class VersionPage(BasePage):
    # 版本管理: BasePage 范式, app 为 MainWindow; service 结果按操作 key 分派。
    def __init__(self, app, parent=None):
        self._version = str(getattr(app, "APP_VERSION", "") or "0.0.0")
        self._latest = None       # 最新版本号或 None
        self._latest_notes = ""
        super().__init__(app, parent)
        # connect 层级约定(见 app/services._run_result_op): 接收者是页面自身槽,
        # 页面随导航销毁重建时 Qt 自动断开, 不会像 app 级槽那样叠加连接。
        self.app.service.result.connect(self._on_result)
        self.app.service.finished.connect(self._on_finished)
        self._load_local_log()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 12)
        root.setSpacing(8)

        title = QLabel("dsh-console-aio · 版本管理", objectName="cardTitle")
        root.addWidget(title)
        hint = QLabel("检查更新读取 GitHub main 分支 version.json; "
                      "一键更新会下载代码并替换本地程序文件(自动备份)。",
                      objectName="cardHint")
        root.addWidget(hint)

        info = QFrame(objectName="card")
        il = QGridLayout(info)
        il.setContentsMargins(12, 8, 12, 8)
        il.setHorizontalSpacing(14)
        il.setVerticalSpacing(4)
        il.addWidget(QLabel("当前版本:", objectName="monName"), 0, 0)
        self._cur_lbl = QLabel("v" + self._version, objectName="monVal")
        il.addWidget(self._cur_lbl, 0, 1)
        il.addWidget(QLabel("最新版本:", objectName="monName"), 1, 0)
        self._latest_lbl = QLabel("(未检查)", objectName="monName")
        il.addWidget(self._latest_lbl, 1, 1)
        il.setColumnStretch(1, 1)
        root.addWidget(info)

        btns = QHBoxLayout()
        self._btn_check = QPushButton("检查更新")
        self._btn_check.clicked.connect(self._check)
        self._btn_update = QPushButton("一键更新")
        self._btn_update.setEnabled(False)
        self._btn_update.clicked.connect(self._update)
        self._btn_github = QPushButton("打开 GitHub")
        self._btn_github.clicked.connect(self._open_github)
        for b in (self._btn_check, self._btn_update, self._btn_github):
            btns.addWidget(b)
        btns.addStretch(1)
        root.addLayout(btns)

        log_card = QFrame(objectName="card")
        lv = QVBoxLayout(log_card)
        lv.setContentsMargins(10, 8, 10, 8)
        lv.setSpacing(4)
        lv.addWidget(QLabel("更新日志", objectName="rightTitle"))
        self._log_text = QPlainTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setFont(QFont("Consolas", 9))
        self._log_text.setMinimumHeight(150)
        self._log_text.setStyleSheet(
            "QPlainTextEdit { background: #16161f; color: #e6e6e6; "
            "border: 1px solid #2c2c40; border-radius: 8px; padding: 4px; }")
        lv.addWidget(self._log_text)
        root.addWidget(log_card, 1)

        self._status_lbl = QLabel("就绪", objectName="statusBar")
        root.addWidget(self._status_lbl)

    # ---- 本地更新日志(离线可用, 小文件同步直读) ----
    def _load_local_log(self):
        self._set_status("正在读取更新日志...")
        self._log_text.setPlainText(core_version.read_local_notes())
        self._set_status("就绪")

    # ---- service 结果分派(契约见 app/services._run_result_op) ----
    def _on_result(self, op, payload):
        # result(op, payload): payload 至少含 "err"(成功为空字符串)。
        if op == "version-check":
            self._apply_check(payload)
        elif op == "version-update":
            self._after_update(payload)

    def _on_finished(self, op, ok):
        # finished(op, ok) 每次操作恰好一发, 统一在此解除 busy(无论成败);
        # err 文案展示由 _on_result 先行处理。
        if op in ("version-check", "version-update"):
            self._set_busy(False)

    # ---- 检查更新 ----
    def _check(self):
        self._set_busy(True)
        self._set_status("正在检查…")
        self.app.service.check_console_update()

    def _apply_check(self, payload):
        latest = str(payload.get("latest") or "")
        notes = str(payload.get("notes") or "")
        err = str(payload.get("err") or "")
        self._latest = latest or None
        self._latest_notes = notes
        if err:
            self._set_status("检查失败: " + err)
            self.app.loge("[版本管理] 检查更新失败: " + err, "err")
            return
        self._latest_lbl.setText("v" + latest)
        cmpv = core_version.cmp_ver(latest, self._version)
        if cmpv > 0:
            self._set_status("发现新版本 v" + latest + "!")
            self.app.loge("[版本管理] 发现新版本 v" + latest, "ok")
        elif cmpv == 0:
            self._set_status("已是最新版本")
            self.app.loge("[版本管理] 已是最新版本", "ok")
        else:
            self._set_status("当前版本高于远程(可能为开发版)")

    # ---- 一键更新(危险操作, 先确认) ----
    def _update(self):
        if not self._latest:
            return
        if getattr(sys, "frozen", False):
            # 打包(exe)版: 更新 = 打开 GitHub Releases 下载新安装包(天然支持升级安装)
            ok = QMessageBox.question(
                self, "检查到新版本 v" + self._latest,
                "当前为安装版。\n将打开 GitHub Releases 页面下载新安装包，\n"
                "下载后运行安装器即可完成升级(配置与数据保留)。\n\n是否打开下载页？")
            if ok == QMessageBox.Yes:
                self._open_releases()
            return
        ok = QMessageBox.question(
            self, "一键更新",
            "将执行：\n1. 下载 v" + self._latest + " 更新包(GitHub)\n"
            "2. 解压并替换程序文件(自动备份旧文件, config.json 等本地配置保留)\n"
            "3. 重启 dsh-console-aio\n\n是否继续？")
        if ok != QMessageBox.Yes:
            return
        self._set_busy(True)
        self._set_status("正在下载更新…")
        self.app.service.update_console()

    def _after_update(self, payload):
        msg = str(payload.get("msg") or "")
        err = str(payload.get("err") or "")
        if err:
            self._set_status("更新失败: " + err)
            self.app.loge("[版本管理] 更新失败: " + err, "err")
            QMessageBox.critical(self, "更新失败", "更新未完成，程序未改动。\n错误: " + err)
            return
        self._set_status("更新完成, 正在重启…")
        self.app.loge("[版本管理] " + msg, "ok")
        QMessageBox.information(self, "更新完成", msg + "\n\n将自动重启程序。")
        self._restart()

    def _restart(self):
        # 重启程序: core.spawn_restart 成功(新进程已起)才关窗退出; 失败留在旧进程
        # 并给出手动重启提示(不再静默吞异常 —— 旧实现正是因此掩盖了入口文件错误)。
        res = core_version.spawn_restart()
        if res.get("err"):
            self._set_status("重启失败: " + res["err"])
            self.app.loge("[版本管理] 重启失败: " + res["err"], "err")
            QMessageBox.critical(
                self, "重启失败",
                "程序已更新，但自动重启失败。\n错误: " + res["err"]
                + "\n请手动重新启动程序。")
            return
        self.app.loge("[版本管理] 新进程已启动, 关闭当前窗口", "ok")
        # 关闭承载页面的主窗口(新进程已启动); 页面可能已销毁, 吞掉 RuntimeError
        try:
            w = self.window()
            if w is not None:
                w.close()
        except RuntimeError:
            pass

    def _open_releases(self):
        try:
            os.startfile("https://github.com/JimyuAn-98/dsh-console-aio/releases")
        except Exception as e:
            QMessageBox.critical(self, "无法打开", str(e))

    def _open_github(self):
        try:
            os.startfile("https://github.com/JimyuAn-98/dsh-console-aio")
        except Exception as e:
            QMessageBox.critical(self, "无法打开", str(e))

    def _set_busy(self, busy):
        # busy=True 禁用检查/更新(后台任务进行中); False 恢复(一键更新仅在新版本时可用)
        self._btn_check.setEnabled(not busy)
        if busy:
            self._btn_update.setEnabled(False)
        else:
            self._btn_update.setEnabled(bool(self._latest)
                                        and core_version.cmp_ver(self._latest, self._version) > 0)

    def _set_status(self, text):
        self._status_lbl.setText(text)
