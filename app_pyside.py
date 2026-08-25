# -*- coding: utf-8 -*-
"""
app_pyside.py - dsh-console-aio PySide6 主框架(UI 迁移候选)。
现代暗色主题 + 顶部部署栏 + 左导航 + 页面宿主 + 右状态栏 + 底部日志 + 状态栏。
复用现有数据层 dsh_data.py 与 config.json。目前内置总览页(验证数据联通)。

运行:  C:/ProgramData/miniconda3/pythonw.exe app_pyside.py
离屏验证:  QT_QPA_PLATFORM=offscreen python app_pyside.py --smoke
"""
import os, sys, json, threading
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton, QHBoxLayout,
    QVBoxLayout, QListWidget, QListWidgetItem, QStackedWidget, QTextEdit,
    QComboBox, QFrame, QScrollArea, QSizePolicy, QAbstractItemView)
from PySide6.QtCore import Qt, Signal, QObject, QTimer
from PySide6.QtGui import QFont, QTextCursor, QColor

import dsh_data

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, 'config.json')
APP_VERSION = '0.5.0'


def _load_config():
    try:
        with open(CONFIG_PATH, encoding='utf-8') as f:
            return json.load(f) or {}
    except Exception:
        return {}

CONFIG = _load_config()

NAV_ITEMS = [
    ('总览', 'overview'), ('隧道', 'tunnels'), ('会话与工作区', 'sessions'),
    ('Agent 模式', 'agents'), ('Profile 管理', 'profiles'), ('插件管理', 'plugins'),
    ('任务看板', 'taskboard'), ('模型用量', 'usage'), ('LLM 配置', 'llm'),
    ('备份与运维', 'ops'), ('SSH 密钥', 'keys'), ('关于与更新', 'version'),
    ('部署管理', 'deployments'),
]



# ---------------- 现代暗色 QSS 主题(全控件覆盖, 无系统白色残留) ----------------
QSS = """
* {
    font-family: "Microsoft YaHei UI";
    font-size: 13px;
    color: #e6e6e6;
}
QMainWindow, QWidget#central, QWidget#body { background: #1e1e2e; }

/* 顶部栏 */
QFrame#topbar { background: #252535; border-bottom: 1px solid #33334a; }
QLabel#titleLbl { font-size: 17px; font-weight: bold; color: #ffffff; }
QLabel#verLbl { color: #9a9ab0; font-size: 12px; }
QFrame#vsep { background: #3d3d5c; border: none; width: 1px; }
QComboBox#deploy {
    background: #2f2f45; border: 1px solid #3d3d5c; border-radius: 6px;
    padding: 4px 10px; min-width: 130px; color: #e6e6e6;
}
QComboBox#deploy::drop-down { border: none; width: 22px; }
QComboBox#deploy QAbstractItemView {
    background: #2f2f45; border: 1px solid #3d3d5c; selection-background-color: #4f6ef7;
    selection-color: #ffffff; color: #e6e6e6; outline: 0; padding: 4px;
}

QPushButton {
    background: #2f2f45; border: 1px solid #3d3d5c; border-radius: 6px;
    padding: 5px 14px; color: #e6e6e6;
}
QPushButton:hover { background: #3a3a58; border-color: #5858a0; }
QPushButton:pressed { background: #26263a; }
QPushButton:disabled { color: #6a6a80; background: #2a2a3c; }
QPushButton#primary { background: #4f6ef7; border-color: #4f6ef7; color: #fff; font-weight: bold; }
QPushButton#primary:hover { background: #6179ff; }

/* 左导航 */
QListWidget#nav {
    background: #252535; border: none; border-right: 1px solid #33334a;
    outline: 0; padding-top: 6px;
}
QListWidget#nav::item { padding: 9px 16px; border-left: 3px solid transparent; color: #b8b8cf; }
QListWidget#nav::item:hover { background: #2e2e44; color: #fff; }
QListWidget#nav::item:selected {
    background: #2f3353; color: #ffffff; border-left: 3px solid #4f6ef7; font-weight: bold;
}

/* 右状态栏 */
QFrame#rightBar { background: #252535; border-left: 1px solid #33334a; }
QLabel#rightTitle { color: #9a9ab0; font-size: 12px; padding: 2px 4px; font-weight: bold; }
QLabel#monDot { font-size: 15px; }
QLabel#monName { color: #e6e6e6; font-size: 12px; }
QLabel#monNote { color: #9a9ab0; font-size: 11px; }
QLabel#monVal { color: #e6e6e6; font-size: 12px; font-weight: bold; }

/* 页面卡片 */
QFrame#card {
    background: #252535; border: 1px solid #33334a; border-radius: 10px;
}
QLabel#cardTitle { font-size: 15px; font-weight: bold; color: #ffffff; }
QLabel#cardHint { color: #9a9ab0; font-size: 12px; }
QFrame#pageHostBg { background: #1e1e2e; }

/* 日志区 */
QFrame#logWrap { background: #1e1e2e; border-top: 1px solid #33334a; }
QLabel#logTitle { color: #9a9ab0; font-size: 12px; padding: 2px 4px; }
QTextEdit#log {
    background: #16161f; border: 1px solid #2c2c40; border-radius: 8px;
    padding: 6px; font-family: Consolas; font-size: 12px; color: #e6e6e6;
    selection-background-color: #4f6ef7;
}

/* 底部状态栏 */
QLabel#statusBar {
    background: #252535; border-top: 1px solid #33334a;
    padding: 5px 12px; color: #9a9ab0; font-size: 12px;
}

/* 全局滚动条(修掉白色拖拽条) */
QScrollBar:vertical {
    background: #1a1a28; width: 12px; margin: 0; border: none;
}
QScrollBar::handle:vertical {
    background: #3d3d5c; min-height: 30px; border-radius: 6px; margin: 2px;
}
QScrollBar::handle:vertical:hover { background: #4f5674; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; background: none; border: none; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QScrollBar:horizontal {
    background: #1a1a28; height: 12px; margin: 0; border: none;
}
QScrollBar::handle:horizontal {
    background: #3d3d5c; min-width: 30px; border-radius: 6px; margin: 2px;
}
QScrollBar::handle:horizontal:hover { background: #4f5674; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; background: none; border: none; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: none; }

/* 工具提示/下拉菜单也覆盖掉系统色 */
QToolTip { background: #2f2f45; color: #e6e6e6; border: 1px solid #4f5674; padding: 4px 8px; }
QMenu { background: #2f2f45; border: 1px solid #3d3d5c; }
QMenu::item { padding: 6px 22px; }
QMenu::item:selected { background: #4f6ef7; }
QScrollArea { border: none; }
"""




def _load_theme():
    # 优先读独立 ui/theme.qss(可用 QssStylesheetEditor 等编辑);
    # 打包(exe)时读冻结目录; 缺失/读取失败回退内嵌 QSS(兜底)。
    if getattr(sys, 'frozen', False):
        base = getattr(sys, '_MEIPASS', BASE_DIR)
    else:
        base = BASE_DIR
    for cand in (os.path.join(base, 'ui', 'theme.qss'),
                 os.path.join(BASE_DIR, 'ui', 'theme.qss')):
        try:
            with open(cand, encoding='utf-8') as f:
                return f.read()
        except Exception:
            continue
    return QSS
# ---------------- 线程安全日志桥: 后台线程 -> Qt 主线程 ----------------
class LogBridge(QObject):
    _sig = Signal(str, str)          # (text, tag)
    def __init__(self):
        super().__init__()
        self._view = None
        self._sig.connect(self._append)
    def attach(self, view):
        self._view = view
    def emit(self, text, tag=""):
        self._sig.emit(text, tag)
    def _append(self, text, tag):
        if self._view is None:
            return
        color = "#e6e6e6"
        if tag == "err":
            color = "#e07a7a"
        elif tag == "warn":
            color = "#e5c07b"
        elif tag == "ok":
            color = "#7ecb6a"
        self._view.setTextColor(QColor(color))
        self._view.append(text)
        self._view.setTextColor(QColor("#e6e6e6"))
        self._view.moveCursor(QTextCursor.End)



# ---------------- 页面基类 ----------------
class BasePage(QWidget):
    # 页面基类: 子类实现 _build()。通过 self.app 访问主窗口(日志/部署等)。
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self._build()

    def _build(self):
        pass


# ---------------- 总览页(验证数据联通 + 部署状态) ----------------
class OverviewPage(BasePage):
    def _build(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(14)

        title = QLabel("部署总览", objectName="cardTitle")
        v.addWidget(title)

        card = QFrame(objectName="card")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(18, 16, 18, 16)
        cv.setSpacing(10)

        hint = QLabel("以下为各部署(本机 + 远程)的实时状态快照", objectName="cardHint")
        self.dep_status = QLabel("加载中…", objectName="monVal")
        self.dep_status.setWordWrap(True)
        refresh = QPushButton("刷新部署状态", objectName="primary")

        cv.addWidget(hint)
        cv.addWidget(self.dep_status)
        cv.addWidget(refresh, 0, Qt.AlignRight)
        v.addWidget(card)
        v.addStretch(1)

        refresh.clicked.connect(self.refresh)
        self.refresh()

    def refresh(self):
        # --smoke 模式: 不触发真实 SSH, 用占位演示
        cfg = CONFIG
        ssh = str(cfg.get("ssh_server") or "")
        unconfigured = (not ssh) or ssh.startswith("YOUR_")
        if self.app.smoke or unconfigured:
            self.dep_status.setText("(演示/未配置) 配置服务器地址后可查看真实部署状态")
            return
        self.dep_status.setText("读取中…")
        depls = [{"name": "本机", "host": ""}] + dsh_data.load_deployments()

        def worker():
            rows = []
            for d in depls:
                try:
                    snap = dsh_data.deployment_snapshot(dsh_data.DshRemote(d if d.get("host") else None))
                except Exception as e:
                    snap = {"ok": False, "error": str(e), "name": d.get("name")}
                rows.append(snap)
            # 跨线程回主线程: 用信号桥
            self.app.bridge.emit(self._fmt(rows), "ok")

        threading.Thread(target=worker, daemon=True).start()

    def _fmt(self, rows):
        parts = []
        for s in rows:
            name = s.get("name") or "?"
            if not s.get("ok"):
                parts.append(name + ": 离线")
                continue
            parts.append("%s v%s · 会话%d · 插件%d" % (
                name, s.get("version") or "?", s.get("sessions") or 0, s.get("plugins") or 0))
        return "   |  ".join(parts)


# ---------------- 占位页(尚未迁移的 mgmt 页面) ----------------
class PlaceholderPage(BasePage):
    def __init__(self, app, name, parent=None):
        self._name = name
        super().__init__(app, parent)
    def _build(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 20, 20, 20)
        card = QFrame(objectName="card")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(20, 20, 20, 20)
        cv.setSpacing(8)
        t = QLabel(self._name, objectName="cardTitle")
        d = QLabel("该页面(mgmt_*.py)尚未迁移到 PySide6，仍是占位。", objectName="cardHint")
        d.setWordWrap(True)
        cv.addWidget(t)
        cv.addWidget(d)
        cv.addStretch(1)
        v.addWidget(card)
        v.addStretch(1)


# ---------------- 右状态栏(监控点) ----------------
class RightBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("rightBar")
        self.setFixedWidth(240)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)

        self._add_section("本机端口")
        self._cells = {}
        for port, label, note in CONFIG.get("local_ports", []):
            self._add_cell("L" + str(port), label, note, port)
        v.addSpacing(6)
        self._add_section("公网服务器 反向隧道")
        for port, label, note in CONFIG.get("remote_tunnels", []):
            self._add_cell("R" + str(port), label, note, port)
        v.addStretch(1)

    def _add_section(self, text):
        lbl = QLabel(text, objectName="rightTitle")
        self.layout().addWidget(lbl)

    def _add_cell(self, key, name, note, port):
        row = QHBoxLayout()
        dot = QLabel("●", objectName="monDot")
        dot.setStyleSheet("color:#999;")
        nm = QLabel(name, objectName="monName")
        detail = QLabel("%s" % note, objectName="monNote")
        val = QLabel("--", objectName="monVal")
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(nm)
        col.addWidget(detail)
        row.addWidget(dot)
        row.addLayout(col, 1)
        row.addWidget(val, 0, Qt.AlignRight)
        self.layout().addLayout(row)
        self._cells[key] = (dot, val)



# ---------------- 主窗口 ----------------
class MainWindow(QMainWindow):
    def __init__(self, smoke=False):
        super().__init__()
        self.smoke = smoke
        self.setWindowTitle("dsh 控制台 · PySide6 v" + APP_VERSION)
        self.resize(1160, 800)
        self.setMinimumSize(960, 620)
        self.setStyleSheet(_load_theme())

        self._current_page_key = None
        self._deployments = []
        self.bridge = LogBridge()

        central = QWidget(objectName="central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_topbar())
        root.addWidget(self._build_body(), 1)
        root.addWidget(self._build_log())
        root.addWidget(self._build_statusbar())

        self.bridge.attach(self.log_view)
        self._refresh_deploy_list()
        self._show_page("overview")
        if not smoke:
            self.loge("PySide6 主框架已启动(v" + APP_VERSION + ")", "ok")

    # ---- 顶部栏 ----
    def _build_topbar(self):
        bar = QFrame(objectName="topbar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(10)

        title = QLabel("dsh 控制台", objectName="titleLbl")
        ver = QLabel("  v" + APP_VERSION, objectName="verLbl")
        sep = QFrame(objectName="vsep"); sep.setFixedWidth(1)
        dlab = QLabel("部署:")
        self.deploy = QComboBox(objectName="deploy")
        self.deploy.currentIndexChanged.connect(self._on_deploy_changed)
        poll = QLabel(" 轮询 4s·20s", objectName="verLbl")

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        refresh = QPushButton("立即刷新")
        refresh.clicked.connect(self._force_refresh)
        config = QPushButton("配置")

        for w in (title, ver, sep, dlab, self.deploy, poll):
            lay.addWidget(w)
        lay.addWidget(spacer)
        lay.addWidget(config)
        lay.addWidget(refresh)
        return bar

    # ---- 主体: 左导航 + 页面宿主 ----
    def _build_body(self):
        body = QWidget(objectName="body")
        lay = QHBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.nav = QListWidget(objectName="nav")
        self.nav.setFixedWidth(172)
        self.nav.setSelectionMode(QAbstractItemView.SingleSelection)
        for label, _ in NAV_ITEMS:
            self.nav.addItem(QListWidgetItem(label))
        self.nav.setCurrentRow(0)
        self.nav.currentRowChanged.connect(self._on_nav)

        self.stack = QStackedWidget(objectName="pageHostBg")

        lay.addWidget(self.nav)
        lay.addWidget(self.stack, 1)
        lay.addWidget(self._build_right())
        return body

    def _build_right(self):
        self.right = RightBar()
        return self.right

    # ---- 日志区 ----
    def _build_log(self):
        wrap = QFrame(objectName="logWrap")
        v = QVBoxLayout(wrap)
        v.setContentsMargins(16, 8, 16, 8)
        v.setSpacing(4)
        t = QLabel("控制台输出", objectName="logTitle")
        self.log_view = QTextEdit(objectName="log")
        self.log_view.setReadOnly(True)
        self.log_view.setFixedHeight(140)
        v.addWidget(t)
        v.addWidget(self.log_view)
        return wrap

    def _build_statusbar(self):
        self.status = QLabel("就绪", objectName="statusBar")
        return self.status

    # ---- 页面切换 ----
    def _on_nav(self, row):
        if 0 <= row < len(NAV_ITEMS):
            self._show_page(NAV_ITEMS[row][1])

    def _show_page(self, key):
        self._current_page_key = key
        while self.stack.count():
            w = self.stack.widget(0)
            self.stack.removeWidget(w)
            w.deleteLater()
        if key == "overview":
            page = OverviewPage(self)
        else:
            label = dict(NAV_ITEMS).get(key, key)
            page = PlaceholderPage(self, label)
        self.stack.addWidget(page)

    def _refresh_deploy_list(self):
        self._deployments = [{"name": "本机", "host": ""}] + dsh_data.load_deployments()
        names = [d.get("name") or "?" for d in self._deployments]
        self.deploy.blockSignals(True)
        self.deploy.clear()
        self.deploy.addItems(names)
        self.deploy.setCurrentIndex(0)
        self.deploy.blockSignals(False)
        self._current_deploy = None

    def _on_deploy_changed(self, idx):
        if idx < 0:
            return
        dep = self._deployments[idx]
        self._current_deploy = dep if dep.get("host") else None
        self.loge("切换部署: " + (dep.get("name") or "?"), "warn")
        if self._current_page_key:
            self._show_page(self._current_page_key)

    def _force_refresh(self):
        page = self.stack.currentWidget()
        if isinstance(page, OverviewPage):
            page.refresh()
        self.loge("已请求刷新", "ok")

    # ---- 日志/状态 ----
    def loge(self, text, tag=""):
        self.bridge.emit(text, tag)
        self.status.setText(text)


# ---------------- 入口 ----------------
def main():
    app = QApplication(sys.argv)
    smoke = "--smoke" in sys.argv
    w = MainWindow(smoke=smoke)
    if smoke:
        # 离屏冒烟: 构造即返回, 不进入事件循环
        print("SMOKE_OK pages=", w.stack.count(), "deploys=", len(w._deployments))
        return 0
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

