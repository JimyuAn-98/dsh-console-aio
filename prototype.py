# -*- coding: utf-8 -*-
"""
prototype.py — PySide6 主框架原型(观感验证用, 非最终产品)
现代暗色主题 + 顶部部署栏 + 左导航 + 中栏页面 + 右状态 + 底部日志。

运行:  /c/ProgramData/miniconda3/python.exe prototype.py
依赖:  pip install pyside6  (已安装 6.11)
本文件不依赖 dsh-console-aio 现有代码，用于评估 UI 观感。
"""
import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton, QHBoxLayout,
    QSizePolicy,
    QVBoxLayout, QListWidget, QListWidgetItem, QStackedWidget, QTextEdit,
    QComboBox, QFrame, QScrollArea)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPalette, QColor

APP_VERSION = "0.5.0p"

NAV_ITEMS = [
    "总览", "隧道", "会话与工作区", "Agent 模式", "Profile 管理",
    "插件管理", "任务看板", "模型用量", "LLM 配置", "备份与运维",
    "SSH 密钥", "关于与更新", "部署管理",
]

# ─────────────────────── 现代暗色 QSS 主题 ───────────────────────
QSS = """
* {
    font-family: "Microsoft YaHei UI";
    font-size: 13px;
    color: #e6e6e6;
}
QMainWindow, QWidget#central {
    background: #1e1e2e;
}
/* 顶部栏 */
QFrame#topbar {
    background: #252535;
    border-bottom: 1px solid #33334a;
}
QLabel#titleLbl { font-size: 17px; font-weight: bold; color: #ffffff; }
QLabel#verLbl   { color: #9a9ab0; font-size: 12px; }
QComboBox#deploy {
    background: #2f2f45; border: 1px solid #3d3d5c; border-radius: 6px;
    padding: 4px 10px; min-width: 120px;
}
QComboBox#deploy::drop-down { border: none; width: 22px; }
QPushButton {
    background: #2f2f45; border: 1px solid #3d3d5c; border-radius: 6px;
    padding: 5px 14px; color: #e6e6e6;
}
QPushButton:hover { background: #3a3a58; border-color: #5858a0; }
QPushButton:pressed { background: #26263a; }
QPushButton#primary { background: #4f6ef7; border-color: #4f6ef7; color: #fff; font-weight: bold; }
QPushButton#primary:hover { background: #6179ff; }
/* 左导航 */
QListWidget#nav {
    background: #252535; border: none; border-right: 1px solid #33334a;
    outline: 0; padding-top: 6px;
}
QListWidget#nav::item {
    padding: 9px 16px; border-left: 3px solid transparent; color: #b8b8cf;
}
QListWidget#nav::item:hover { background: #2e2e44; color: #fff; }
QListWidget#nav::item:selected {
    background: #2f3353; color: #ffffff; border-left: 3px solid #4f6ef7;
    font-weight: bold;
}
/* 状态栏提示 */
QLabel#statusBar {
    background: #252535; border-top: 1px solid #33334a;
    padding: 5px 12px; color: #9a9ab0; font-size: 12px;
}
/* 日志区 */
QTextEdit#log {
    background: #16161f; border: 1px solid #2c2c40; border-radius: 8px;
    padding: 8px; font-family: Consolas; font-size: 12px;
}
QLabel#logTitle { color: #9a9ab0; font-size: 12px; padding: 2px 4px; }
QLabel#statusTitle { color: #9a9ab0; font-size: 12px; padding: 2px 4px; font-weight: bold; }
/* 页面占位卡片 */
QFrame#card {
    background: #252535; border: 1px solid #33334a; border-radius: 10px;
}
QLabel#cardTitle { font-size: 15px; font-weight: bold; color: #fff; }
QFrame#emptyHost { background: transparent; }
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("dsh 控制台 (PySide6 原型)")
        self.resize(1100, 720)
        self.setStyleSheet(QSS)

        central = QWidget(objectName="central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_topbar())
        root.addWidget(self._build_body(), 1)
        root.addWidget(self._build_log())
        root.addWidget(self._build_statusbar())

    # ── 顶部栏 ──
    def _build_topbar(self):
        bar = QFrame(objectName="topbar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(10)

        title = QLabel("dsh 控制台", objectName="titleLbl")
        ver = QLabel("  v" + APP_VERSION, objectName="verLbl")
        sep = QFrame(); sep.setFixedWidth(1); sep.setFrameShape(QFrame.VLine)

        deploy_lbl = QLabel("部署:")
        self.deploy = QComboBox(objectName="deploy")
        self.deploy.addItems(["本机", "lab-dsh", "prod-server"])
        self.deploy.setCurrentIndex(0)

        poll = QLabel(" 轮询 4s·20s", objectName="verLbl")

        spacer = QWidget();
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        refresh = QPushButton("立即刷新")
        config = QPushButton("配置")

        for w in (title, ver, sep, deploy_lbl, self.deploy, poll):
            lay.addWidget(w)
        lay.addWidget(spacer)
        for b in (config, refresh):
            lay.addWidget(b)

        return bar

    # ── 主体: 左导航 + 页面 ──
    def _build_body(self):
        body = QWidget()
        lay = QHBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.nav = QListWidget(objectName="nav")
        self.nav.setFixedWidth(168)
        for name in NAV_ITEMS:
            self.nav.addItem(QListWidgetItem(name))
        self.nav.setCurrentRow(0)
        self.nav.currentRowChanged.connect(self._on_nav)

        self.stack = QStackedWidget(objectName="emptyHost")
        for i, name in enumerate(NAV_ITEMS):
            self.stack.addWidget(self._make_placeholder(name, i))

        lay.addWidget(self.nav)
        lay.addWidget(self.stack, 1)
        return body

    def _make_placeholder(self, name, i):
        host = QWidget(objectName="emptyHost")
        v = QVBoxLayout(host)
        v.setContentsMargins(20, 20, 20, 20)
        card = QFrame(objectName="card")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(20, 20, 20, 20)
        cv.setSpacing(10)
        t = QLabel(name, objectName="cardTitle")
        d = QLabel(("此处是各 mgmt_*.py 页面(会话/插件/用量…)迁入后的占位。\n"
                   "本原型只验证观感，不包含业务逻辑。"), objectName="verLbl")
        d.setWordWrap(True)
        cv.addWidget(t)
        cv.addWidget(d)
        cv.addStretch(1)
        v.addWidget(card)
        v.addStretch(1)
        return host

    def _on_nav(self, row):
        self.stack.setCurrentIndex(row)

    # ── 日志区 ──
    def _build_log(self):
        wrap = QFrame()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(16, 8, 16, 8)
        v.setSpacing(4)
        t = QLabel("控制台输出", objectName="logTitle")
        self.log = QTextEdit(objectName="log")
        self.log.setReadOnly(True)
        self.log.setFixedHeight(140)
        self.log.append("· PySide6 原型已启动(离屏构造可验证)"
                        " — 观感评估用，非最终产品。")
        v.addWidget(t)
        v.addWidget(self.log)
        return wrap

    def _build_statusbar(self):
        self.status = QLabel("就绪", objectName="statusBar")
        return self.status


def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
