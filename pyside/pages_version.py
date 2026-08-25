# -*- coding: utf-8 -*-
# 版本管理页(PySide6 迁移版): 当前版本/检查更新/更新日志/一键自动更新。
# 数据源: 远程 GitHub main 分支 version.json + 本地 RELEASE_NOTES.md。
# 后台线程做 IO/子进程(拉远程版本、读本地日志、下载解压并替换程序文件),
# 结果经 Qt Signal 回主线程更新 UI; 自动更新为危险操作, 执行前 QMessageBox 确认。

import io
import json
import os
import shutil
import subprocess
import sys
import threading
import urllib.request
import zipfile

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFrame, QPushButton,
    QMessageBox, QPlainTextEdit)

from pyside.base import BasePage

# 与主程序一致的更新源(检查更新/自动更新共用)
GITHUB_RAW = "https://raw.githubusercontent.com/JimyuAn-98/dsh-console-aio/main/"
GITHUB_ZIP = "https://codeload.github.com/JimyuAn-98/dsh-console-aio/zip/refs/heads/main"
VERSION_URL = GITHUB_RAW + "version.json"
RELEASE_URL = GITHUB_RAW + "RELEASE_NOTES.md"

# 更新时保留的本地文件(用户数据/配置, 不替换)
KEEP_FILES = {"config.json", "dsh使用指南.txt", "tunnel-pids.json"}

# 备份+替换在子进程(python -c)里执行, 不占住 GUI 线程; 脚本纯 ASCII(keep 清单经 argv 传入)
_REPLACE_CODE = (
    "import json, os, shutil, sys\n"
    "src, base, bak, keep_json = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]\n"
    "keep = set(json.loads(keep_json))\n"
    "os.makedirs(bak, exist_ok=True)\n"
    "replaced = 0\n"
    "for fn in os.listdir(src):\n"
    "    if fn in keep or fn == '.git':\n"
    "        continue\n"
    "    s = os.path.join(src, fn)\n"
    "    d = os.path.join(base, fn)\n"
    "    if os.path.isfile(s):\n"
    "        if os.path.exists(d):\n"
    "            shutil.copy2(d, os.path.join(bak, fn))\n"
    "        shutil.copy2(s, d)\n"
    "        replaced += 1\n"
    "print(replaced)\n"
)


def _cmp_ver(a, b):
    # 版本号 "x.y.z" 比较, 返回 -1/0/1
    def t(v):
        try:
            return tuple(int(x) for x in str(v).split("."))
        except ValueError:
            return (0,)
    x, y = t(a), t(b)
    return (x > y) - (x < y)


def _fetch(url, timeout=15):
    # 下载文本(utf-8), 失败抛异常
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _base_dir():
    # 程序所在目录: 打包(exe)后为 exe 目录, 源码模式为仓库根目录(pyside/ 的上级,
    # 与 pages_profiles.py 的 BASE_DIR 一致; 旧 mgmt_version.py 位于仓库根目录时无需上溯)
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resource_dir():
    # 打包资源目录: onefile 下资源在 _MEIPASS(临时解压), 源码模式为仓库根目录
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class VersionPage(BasePage):
    # 版本管理: BasePage 范式, app 为 MainWindow。
    _check_result = Signal(str, str, str)   # (latest, notes, err) 远程检查结果
    _log_ready = Signal(str)                # 本地更新日志文本
    _update_result = Signal(str, str)       # (msg, err) 自动更新结果

    def __init__(self, app, parent=None):
        self._version = str(getattr(app, "APP_VERSION", "") or "0.0.0")
        self._latest = None       # 最新版本号或 None
        self._latest_notes = ""
        super().__init__(app, parent)
        self._check_result.connect(self._apply_check)
        self._log_ready.connect(self._apply_log)
        self._update_result.connect(self._after_update)
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

    # ---- 本地更新日志(离线可用, 后台线程读文件) ----
    def _load_local_log(self):
        self._set_status("正在读取更新日志...")

        def worker():
            base = _resource_dir()
            p = os.path.join(base, "RELEASE_NOTES.md")
            text = ""
            try:
                with io.open(p, encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                text = "(未找到 RELEASE_NOTES.md)"
            self.safe_emit(self._log_ready, text)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_log(self, text):
        self._log_text.setPlainText(text)
        if self._status_lbl.text() == "正在读取更新日志...":
            self._set_status("就绪")

    # ---- 检查更新 ----
    def _check(self):
        self._set_busy(True)
        self._set_status("正在检查…")

        def worker():
            err = None
            latest = ""
            notes = ""
            try:
                data = json.loads(_fetch(VERSION_URL))
                latest = str(data.get("version") or "")
                notes = str(data.get("notes") or "")
            except Exception as e:
                err = str(e)
            self.safe_emit(self._check_result, latest, notes, err)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_check(self, latest, notes, err):
        self._latest = latest or None
        self._latest_notes = notes
        if err:
            self._set_status("检查失败: " + err)
            self.app.loge("[版本管理] 检查更新失败: " + err, "err")
            self._set_busy(False)
            return
        self._latest_lbl.setText("v" + latest)
        cmpv = _cmp_ver(latest, self._version)
        if cmpv > 0:
            self._set_status("发现新版本 v" + latest + "!")
            self.app.loge("[版本管理] 发现新版本 v" + latest, "ok")
        elif cmpv == 0:
            self._set_status("已是最新版本")
            self.app.loge("[版本管理] 已是最新版本", "ok")
        else:
            self._set_status("当前版本高于远程(可能为开发版)")
        self._set_busy(False)

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
        threading.Thread(target=self._do_update, daemon=True).start()

    def _do_update(self):
        # 后台线程: 下载 zip -> 解压 -> python 子进程备份+替换 -> 回主线程收尾
        base = _base_dir()
        tmp = os.path.join(os.environ.get("TEMP", "."), "dsh-aio-update")
        msg = ""
        err = None
        try:
            shutil.rmtree(tmp, ignore_errors=True)
            os.makedirs(tmp, exist_ok=True)
            zip_path = os.path.join(tmp, "update.zip")
            self.app.set_status("下载中(约几百 KB~几 MB)…")
            urllib.request.urlretrieve(GITHUB_ZIP, zip_path)
            self.app.set_status("解压中…")
            extract = os.path.join(tmp, "x")
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(extract)
            # zip 顶层目录: dsh-console-aio-main/
            roots = [d for d in os.listdir(extract)
                     if os.path.isdir(os.path.join(extract, d))]
            src = os.path.join(extract, roots[0]) if roots else extract
            bak = os.path.join(tmp, "backup")
            self.app.set_status("替换程序文件(自动备份)…")
            r = subprocess.run(
                [sys.executable, "-c", _REPLACE_CODE, src, base, bak,
                 json.dumps(sorted(KEEP_FILES))],
                capture_output=True, text=True, errors="replace", timeout=300,
                creationflags=subprocess.CREATE_NO_WINDOW)
            if r.returncode != 0:
                err = (r.stderr or "").strip() or ("替换子进程退出码 %d" % r.returncode)
            else:
                replaced = (r.stdout or "").strip()
                msg = "更新完成(" + replaced + " 个文件), 备份在: " + bak
        except Exception as e:
            err = str(e)
        self.safe_emit(self._update_result, msg, err)

    def _after_update(self, msg, err):
        if err:
            self._set_status("更新失败: " + err)
            self.app.loge("[版本管理] 更新失败: " + err, "err")
            QMessageBox.critical(self, "更新失败", "更新未完成，程序未改动。\n错误: " + err)
            self._set_busy(False)
            return
        self._set_status("更新完成, 正在重启…")
        self.app.loge("[版本管理] " + msg, "ok")
        QMessageBox.information(self, "更新完成", msg + "\n\n将自动重启程序。")
        self._restart()

    def _restart(self):
        # 重启程序: 打包(exe)后直接重启 exe; 源码模式重启 PySide6 主框架 app_pyside.py
        base = _base_dir()
        try:
            if getattr(sys, "frozen", False):
                subprocess.Popen([sys.executable], cwd=base, text=True, errors="replace",
                                 creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                main = os.path.join(base, "app_pyside.py")
                subprocess.Popen([sys.executable, main], cwd=base, text=True,
                                 errors="replace",
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception:
            pass
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
                                        and _cmp_ver(self._latest, self._version) > 0)

    def _set_status(self, text):
        self._status_lbl.setText(text)
