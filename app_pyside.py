# -*- coding: utf-8 -*-
"""
app_pyside.py - dsh-console-aio PySide6 主框架(UI 迁移候选)。
现代暗色主题 + 顶部部署栏 + 左导航 + 页面宿主 + 右状态栏 + 底部日志 + 状态栏。
复用现有数据层 dsh_data.py 与 config.json。目前内置总览页(验证数据联通)。

运行:  C:/ProgramData/miniconda3/pythonw.exe app_pyside.py
离屏验证:  QT_QPA_PLATFORM=offscreen python app_pyside.py --smoke
"""
import os, sys, json, time, subprocess, socket, threading
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton, QHBoxLayout,
    QVBoxLayout, QListWidget, QListWidgetItem, QStackedWidget, QTextEdit,
    QComboBox, QFrame, QScrollArea, QSizePolicy, QAbstractItemView)
from PySide6.QtCore import Qt, Signal, QObject, QTimer
from PySide6.QtGui import QFont, QTextCursor, QColor

import dsh_data
import tunnel_mgr
from tunnel_mgr import tcp_ok

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

# ---------------- 业务常量(从 config.json 派生) ----------------
DASH_REPO  = CONFIG.get("dash_repo") or ""
DASH_PORT  = CONFIG.get("dash_port") or 3080
DASH_CMD   = list(CONFIG.get("dash_cmd") or ["pnpm.cmd", "dsh", "web"])
POLL_SECONDS = CONFIG.get("poll_seconds") or 4

BTN_TEXT = {"start": "启动", "restart": "重启", "persist": "常驻",
           "stop": "停止", "run": "运行更新"}

ITEMS = [
    {"type": "dsh", "key": "dsh-web", "title": "本机 dsh", "port": DASH_PORT,
     "actions": ["start", "restart", "stop"],
     "desc": "启动/重启/停止本机 dsh GUI\n(后台 pnpm dsh web,\n访问 http://127.0.0.1:%d)" % DASH_PORT},
    {"type": "py", "key": "dsh-tunnel", "port": 8090, "backend": "python",
     "actions": ["start", "persist", "stop"],
     "desc": "在家 -> 打通三个转发口\n8090->实验室GUI / 8022->SSH / 8091->本机GUI"},
    {"type": "py", "key": "connect-lab-dsh", "port": 3090, "backend": "python",
     "actions": ["start", "persist", "stop"],
     "desc": "实验室局域网 -> 直连实验室 dsh GUI (本机 3090)"},
    {"type": "py", "key": "dsh-tunnel-reverse", "port": 0, "backend": "python",
     "actions": ["start", "persist", "stop"],
     "desc": "本机 dsh -> 公网反向隧道\n公网:8091 -> 本机 3080"},
    {"type": "py", "key": "update-dsh", "port": -1, "backend": "python",
     "actions": ["run"],
     "desc": "运行一次完整更新:\ngit 拉取->依赖->构建->重启"},
]

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
    _status = Signal(str)            # 状态栏文本(跨线程安全)
    def __init__(self):
        super().__init__()
        self._view = None
        self._status_cb = None
        self._sig.connect(self._append)
        self._status.connect(self._apply_status)
    def attach(self, view):
        self._view = view
    def on_status(self, cb):
        self._status_cb = cb
    def emit(self, text, tag=""):
        self._sig.emit(text, tag)
    def emit_status(self, text):
        self._status.emit(text)
    def _apply_status(self, text):
        if self._status_cb is not None:
            self._status_cb(text)
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
        self.bridge.on_status(self._set_status)
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
        elif key == "tunnels":
            page = TunnelsPage(self)
        elif key == "sessions":
            from pyside.pages_sessions import SessionPage
            page = SessionPage(self)
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
        self._set_status(text)

    def set_status(self, text):
        # 跨线程安全(经 LogBridge status 信号回到主线程)
        self.bridge.emit_status(text)

    def _set_status(self, text):
        if self.status is not None:
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





# ---------------- 隧道配置常量(从 config.json 派生) ----------------
SSH_SERVER   = CONFIG.get("ssh_server") or ""
SSH_USER     = CONFIG.get("ssh_user") or ""
LAB_SERVER   = CONFIG.get("lab_server") or ""
LAB_USER     = CONFIG.get("lab_user") or ""
LAB_PORT     = CONFIG.get("lab_port") or 3090
REVERSE_PORT = CONFIG.get("reverse_port") or 8091
FORWARD_PORTS = CONFIG.get("forward_ports") or [8090, 8022, 8091]
TCP_TIMEOUT  = CONFIG.get("tcp_timeout") or 0.8


def _build_tunnel_obj(app, cfg_item):
    # 依据 config 构造一条 tunnel_mgr.Tunnel
    key = cfg_item["key"]
    if key == "dsh-tunnel":
        forwards = [(p, "127.0.0.1", p) for p in FORWARD_PORTS]
        host, user, mode = SSH_SERVER, SSH_USER, "forward"
        watch = FORWARD_PORTS[0] if FORWARD_PORTS else None
    elif key == "connect-lab-dsh":
        forwards = [(LAB_PORT, "127.0.0.1", LAB_PORT)]
        host, user, mode = LAB_SERVER, LAB_USER, "forward"
        watch = LAB_PORT
    elif key == "dsh-tunnel-reverse":
        forwards = [(REVERSE_PORT, "127.0.0.1", DASH_PORT)]
        host, user, mode = SSH_SERVER, SSH_USER, "reverse"
        watch = None
    else:
        raise ValueError("unknown tunnel: " + key)
    t = tunnel_mgr.Tunnel(BASE_DIR, key, host, user,
                          mode=mode, forwards=forwards, watch_port=watch)
    t.set_logger(lambda msg, tag="": app.loge("  " + msg, tag))
    return t


# ---------------- 隧道页(导航第 2 项) ----------------
class TunnelsPage(BasePage):
    def _build(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(6)
        title = QLabel("隧道 / dsh 服务操控", objectName="cardTitle")
        v.addWidget(title)

        self._cards = {}
        grid = QVBoxLayout()
        grid.setSpacing(10)
        row = QHBoxLayout()
        row.setSpacing(10)
        for i, item in enumerate(ITEMS):
            card = self._make_card(item)
            row.addWidget(card, 1)
            if (i + 1) % 2 == 0:
                grid.addLayout(row)
                row = QHBoxLayout(); row.setSpacing(10)
        if row.count():
            row.addStretch(1)
            grid.addLayout(row)
        v.addLayout(grid)
        v.addStretch(1)

    def _make_card(self, item):
        card = QFrame(objectName="card")
        lv = QVBoxLayout(card)
        lv.setContentsMargins(16, 14, 16, 14)
        lv.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel(item.get("title") or item["key"], objectName="cardTitle")
        dot = QLabel("○", objectName="monDot")
        dot.setStyleSheet("color:#999; font-size:15px;")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(dot)
        lv.addLayout(head)

        desc = QLabel(item["desc"], objectName="cardHint")
        desc.setWordWrap(True)
        lv.addWidget(desc)

        btns = QHBoxLayout()
        for act in item["actions"]:
            b = QPushButton(BTN_TEXT[act])
            b.clicked.connect(lambda _=False, it=item, a=act: self._on_action(it, a))
            btns.addWidget(b)
        btns.addStretch(1)
        lv.addLayout(btns)

        self._cards[item["key"]] = (dot, item)
        return card

    def _set_card(self, key, on, label=None):
        dot = self._cards.get(key)
        if dot is None:
            return
        d, item = dot
        d.setText("●" if on else "○")
        d.setStyleSheet("color:#7ecb6a; font-size:15px;" if on else "color:#999; font-size:15px;")

    # ---- 动作分派(后台线程执行, 经信号回 UI) ----
    def _on_action(self, item, mode):
        t = item["type"]
        key = item["key"]
        if t == "dsh":
            self.app.set_status("正在 %s 本机 dsh ..." % mode)
            threading.Thread(target=self._run_dsh, args=(mode,), daemon=True).start()
            return
        if key == "update-dsh":
            self.app.set_status("正在运行更新(构建较久, 请耐心)...")
            threading.Thread(target=self._run_update, daemon=True).start()
            return
        # python 隧道
        self.app.loge("[%s] 模式: %s (Python)" % (key, mode), "warn")
        self.app.set_status("正在执行 %s -> %s (Python) ..." % (mode, key))
        threading.Thread(target=self._run_python_tunnel, args=(item, mode), daemon=True).start()

    # ---- 本机 dsh ----
    def _run_dsh(self, mode):
        if mode in ("start", "restart"):
            self._dsh_start()
        if mode in ("stop", "restart"):
            self._dsh_stop()
            if mode == "restart":
                self.app.loge("  停止完成, 重新启动...", "warn")
                self._dsh_start()

    def _dsh_start(self):
        if not os.path.isdir(DASH_REPO):
            self.app.loge("  仓库不存在: %s" % DASH_REPO, "err")
            self.app.set_status("启动失败: 仓库目录不存在")
            return
        self.app.loge("  $ cd %s && %s" % (DASH_REPO, " ".join(DASH_CMD)))
        try:
            logdir = os.path.join(os.environ.get("TEMP", "."), "dsh-dash")
            os.makedirs(logdir, exist_ok=True)
            out = open(os.path.join(logdir, "dsh-web.out.log"), "ab")
            err = open(os.path.join(logdir, "dsh-web.err.log"), "ab")
            subprocess.Popen(DASH_CMD, cwd=DASH_REPO, stdout=out, stderr=err,
                             creationflags=subprocess.CREATE_NO_WINDOW)
            self.app.loge("  已在后台启动, 等待 %d 端口就绪..." % DASH_PORT, "ok")
            self.app.set_status("已触发本机 dsh 启动 -> http://127.0.0.1:%d" % DASH_PORT)
            self._set_card("dsh-web", True)
        except FileNotFoundError:
            self.app.loge("  找不到 %s, 请确认 pnpm 在 PATH 或修改配置" % DASH_CMD[0], "err")
            self.app.set_status("启动失败: 找不到启动命令")
        except Exception as e:
            self.app.loge("  异常: %s" % e, "err")
            self.app.set_status("启动出错: %s" % e)

    def _dsh_stop(self):
        ps = ("$n=0\n"
              "Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" -ErrorAction SilentlyContinue |\n"
              "  Where-Object { $_.CommandLine -match 'dsh' -and $_.CommandLine -match 'web' } |\n"
              "  ForEach-Object { Write-Output ('stop node ' + $_.ProcessId); taskkill /PID $_.ProcessId /T /F | Out-Null; $n++ }\n"
              "if($n -eq 0){ Write-Output 'no dsh web process' }\n")
        self.app.loge("  $ stopping dsh web (node, 匹配 dsh+web)...")
        try:
            r = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy",
                                "Bypass", "-Command", ps],
                               capture_output=True, text=True, errors="replace",
                               timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
            for ln in ((r.stdout or "").splitlines() or ["(无输出)"]):
                self.app.loge("    " + ln, "ok" if r.returncode == 0 else "err")
            self.app.set_status("已停止本机 dsh web" if r.returncode == 0 else "停止本机 dsh 出错")
            self._set_card("dsh-web", False)
        except subprocess.TimeoutExpired:
            self.app.loge("  [停止] 超时(60s)", "err")
            self.app.set_status("停止本机 dsh 超时")
        except Exception as e:
            self.app.loge("  异常: %s" % e, "err")
            self.app.set_status("停止出错: %s" % e)

    # ---- python 隧道 ----
    def _run_python_tunnel(self, item, mode):
        key = item["key"]
        if mode == "stop":
            self._stop_py_tunnel(item)
            return
        t = _build_tunnel_obj(self.app, item)
        ok = t.start()
        if not ok:
            self.app.set_status("启动失败: %s" % key)
            self._set_card(key, False)
            return
        self.app.set_status("%s 已启动 (Python)" % key)
        self._set_card(key, True)
        if mode == "persist":
            self._start_persist(item, t)

    def _start_persist(self, item, t):
        key = item["key"]
        stop_flag = threading.Event()
        if not hasattr(self, "_py_persist"):
            self._py_persist = {}
        old = self._py_persist.get(key)
        if old:
            old.set()
        self._py_persist[key] = stop_flag

        def loop():
            while not stop_flag.is_set():
                if not t.is_running():
                    self.app.loge("  [%s] 隧道断开, 尝试重连..." % key, "warn")
                    t.start()
                stop_f


if __name__ == "__main__":
    sys.exit(main())
