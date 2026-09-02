# -*- coding: utf-8 -*-
"""
dsh-console-aio.py - dsh 控制台主程序 (PySide6): 主窗口骨架 + 导航路由 + 托盘常驻。
UI 分层: 后端业务在 core/(纯 Python 零 Qt), 信号桥在 app/services.py(DshService),
管理页全部在 ui/pages_*.py, 监控栏在 ui/monitor.py, 主题引擎在 ui/theme.py。

运行(双击 exe 或):  C:/Users/1/.conda/envs/console/pythonw.exe dsh-console-aio.py
离屏验证:  QT_QPA_PLATFORM=offscreen python dsh-console-aio.py --smoke
检查模式: 启动加 --inspect 或运行中按 F12 —— 悬停显示控件身份(类名+objectName),
          左键点击在日志区打印控件完整路径(便于向开发者指认界面元素)。
"""
import ctypes
import ctypes.wintypes
import json
import os
import sys

from PySide6.QtCore import (
    QEvent, QPoint, Qt, QTimer)
from PySide6.QtGui import (
    QCursor, QIcon, QKeySequence, QPixmap, QShortcut)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QFrame, QHBoxLayout,
    QVBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMenu,
    QPushButton, QSizePolicy, QSplitter, QStackedWidget,
    QSystemTrayIcon, QTextEdit, QToolTip, QWidget)

from app.services import DshService
from core import config as dsh_config
from core import data as dsh_data
from ui import theme as dsh_theme
from ui import win32_frame as wframe
from ui.base import BasePage
from ui.monitor import LogBridge, StatusPanel, svg_icon
from ui.pages_overview import OverviewPage
from ui.pages_tunnels import (
    BTN_TEXT, ITEMS, _apply_items, build_items,
    card_states_from_monitor, TunnelsPage)
from ui.palette import CommandPalette
from ui.theme import build_qss

if getattr(sys, 'frozen', False):
    # onefile exe: 用户可见/可写的数据目录 = exe 所在目录(放 config.json 便于分发后编辑)。
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.environ.get('DSH_AIO_CONFIG') or os.path.join(BASE_DIR, 'config.json')
APP_VERSION = '0.7.0'


def _find_logo():
    # Logo 资源定位: 源码运行在仓库根, 打包(onefile)后随 --add-data 解压到 _MEIPASS。
    cands = []
    if getattr(sys, 'frozen', False):
        cands.append(os.path.join(getattr(sys, '_MEIPASS', BASE_DIR), 'logo.png'))
    cands.append(os.path.join(BASE_DIR, 'logo.png'))
    for c in cands:
        if os.path.exists(c):
            return c
    return None


def _find_logo_ico():
    cands = []
    if getattr(sys, 'frozen', False):
        cands.append(os.path.join(getattr(sys, '_MEIPASS', BASE_DIR), 'logo.ico'))
    cands.append(os.path.join(BASE_DIR, 'logo.ico'))
    for c in cands:
        if os.path.exists(c):
            return c
    return None


LOGO_PATH = _find_logo()
LOGO_ICO_PATH = _find_logo_ico()

# frozen 模式下把 exe 目录也加入 sys.path, 保证旁置的可写数据/日志可见。
if getattr(sys, 'frozen', False) and BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


def _load_config():
    try:
        with open(CONFIG_PATH, encoding='utf-8') as f:
            return json.load(f) or {}
    except Exception:
        return {}


CONFIG = _load_config()

NAV_ITEMS = [
    ('总览', 'overview'), ('DSH 管理', 'dsh'), ('隧道', 'tunnels'),
    ('会话与工作区', 'sessions'),
    ('Agent 模式', 'agents'), ('Profile 管理', 'profiles'), ('插件管理', 'plugins'),
    ('任务看板', 'taskboard'), ('模型用量', 'usage'), ('LLM 配置', 'llm'),
    ('备份与凭据', 'ops'), ('SSH 密钥', 'keys'), ('部署管理', 'deployments'),
    ('日志管理', 'logs'), ('设置', 'settings'), ('主题', 'theme'), ('关于与更新', 'version'),
]


# ---------------- 自绘工具栏(保留原生标题栏方案) ----------------
# 原生标题栏负责: 窗口拖动/贴靠/多屏/最小化/最大化/关闭/双击最大化。
class _TopBar(QFrame):
    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.setObjectName("topbar")
        self._win = win


# ---------------- 主窗口 ----------------
class MainWindow(QMainWindow):
    def __init__(self, smoke=False):
        super().__init__()
        self.smoke = smoke
        self.setWindowTitle("DSH Console · v" + APP_VERSION)
        if LOGO_PATH:
            self.setWindowIcon(QIcon(LOGO_PATH))   # 任务栏/Alt-Tab 图标
        self.resize(1160, 800)
        self.setMinimumSize(960, 620)
        self._mica = wframe.set_accent_blur(int(self.winId())) if sys.platform == "win32" else False
        self._sys_blur = self._mica

        # 明/暗变体: 先切 base 色板, 再套用户覆盖图层
        dsh_theme.set_variant(CONFIG.get("theme_variant") or "dark")
        self._theme_variant = dsh_theme.get_variant()
        if sys.platform == "win32":
            wframe.set_immersive_dark(int(self.winId()), dark=(self._theme_variant != "light"))
        self._custom_theme = bool(CONFIG.get("theme"))
        dsh_theme.set_active(CONFIG.get("theme") or {})
        self.setStyleSheet(self._load_theme())

        self._current_page_key = None
        self._deployments = []
        self.bridge = LogBridge()
        self.APP_VERSION = APP_VERSION

        # 业务层信号桥(core 的唯一 UI 入口)
        self.service = DshService.from_env(parent=self)
        self.service.log.connect(self.loge)
        self.service.status.connect(self.set_status)
        self._card_state = {}               # 隧道卡片最近已知状态
        self.service.card.connect(self._on_card)
        self._start_monitor()               # 右侧健康监控(实时探测端口/隧道)

        # ---- 控件检查模式(悬停显示身份, 左键点击打印路径; --inspect 启动 / F12 切换) ----
        self._inspect = "--inspect" in sys.argv
        self._last_inspect_w = None
        self._last_f12 = 0.0
        if not smoke:
            QApplication.instance().installEventFilter(self)
            self._inspect_timer = QTimer(self)
            self._inspect_timer.timeout.connect(self._inspect_tick)
            self._inspect_timer.start(250)
            if self._inspect:
                self.loge("控件检查模式已开启(F12 切换; 悬停看身份, 点击打印路径)", "ok")

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
        self._init_tray()

        # 全局命令面板(Ctrl+K): 页面/部署/动作键盘直达
        sc_palette = QShortcut(QKeySequence("Ctrl+K"), self)
        sc_palette.activated.connect(self._open_palette)
        if not smoke:
            if sys.platform == "win32" and self._mica:
                theme_txt = "亚克力(自绘模糊, build %d)" % sys.getwindowsversion().build
            elif sys.platform == "win32":
                theme_txt = "纯 QSS(build %d)" % sys.getwindowsversion().build
            else:
                theme_txt = "纯 QSS"
            self.loge("DSH Console 已启动(v" + APP_VERSION + ") · 主题: " + theme_txt, "ok")
            if sys.platform == "win32":
                QTimer.singleShot(800, self._log_window_facts)
            if self._mica:
                self.loge("背景: DWM 亚克力(DWMSBT_TRANSIENTWINDOW, 非分层窗口, 保留原生贴靠)", "ok")

    # ---- 主题(主题引擎 ui/theme.py, token 驱动) ----
    def _load_theme(self):
        if self._mica:
            return build_qss(mica=True)
        if self._custom_theme or self._theme_variant != "dark":
            return build_qss(mica=False)
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
        return build_qss(mica=False)

    def apply_theme(self, overrides=None, note="主题已实时应用"):
        dsh_theme.set_active(overrides or {})
        self._custom_theme = self._custom_theme or bool(overrides)
        self.setStyleSheet(build_qss(mica=self._mica))
        if note:
            self.loge(note, "ok")

    def set_theme_variant(self, variant):
        if not dsh_theme.set_variant(variant):
            return False
        self._theme_variant = dsh_theme.get_variant()
        if sys.platform == "win32":
            wframe.set_immersive_dark(int(self.winId()), dark=(self._theme_variant != "light"))
        ov = dsh_theme.current_overrides()
        cfg = dsh_config.load_config()
        if ov:
            cfg["theme"] = ov
        else:
            cfg.pop("theme", None)
        cfg["theme_variant"] = self._theme_variant
        ok = dsh_config.save_config(cfg)
        self._custom_theme = bool(ov)
        self.setStyleSheet(build_qss(mica=self._mica))
        return ok

    # ---- 顶部栏 ----
    def _build_topbar(self):
        bar = _TopBar(self)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(10)

        logo = QLabel(objectName="logoLbl")
        pm = QPixmap(LOGO_PATH) if LOGO_PATH else QPixmap()
        if not pm.isNull():
            dpr = self.devicePixelRatioF() or 1.0
            pm = pm.scaled(int(round(22 * dpr)), int(round(22 * dpr)),
                           Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
            pm.setDevicePixelRatio(dpr)
            logo.setPixmap(pm)
        else:
            logo.hide()

        title = QLabel("DSH Console", objectName="titleLbl")
        ver = QLabel("  v" + APP_VERSION, objectName="verLbl")
        sep = QFrame(objectName="vsep")
        sep.setFixedWidth(1)
        dlab = QLabel("部署:")
        self.deploy = QComboBox(objectName="deploy")
        self.deploy.currentIndexChanged.connect(self._on_deploy_changed)
        poll = QLabel(" 轮询 4s·20s", objectName="verLbl")

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        search = QPushButton("搜索")
        search.setToolTip("命令面板: 搜索页面/部署/动作 (Ctrl+K)")
        search.clicked.connect(self._open_palette)
        refresh = QPushButton("立即刷新")
        refresh.clicked.connect(self._force_refresh)

        for w in (logo, title, ver, sep, dlab, self.deploy, poll):
            lay.addWidget(w)
        lay.addWidget(spacer)
        lay.addWidget(search)
        lay.addWidget(refresh)
        return bar

    # ---- 窗口诊断 ----
    def _log_window_facts(self):
        try:
            hwnd = int(self.winId())
            layered = wframe.is_layered(hwnd)
            dpi = ctypes.windll.user32.GetDpiForWindow(hwnd)
            v = wframe.query_backdrop(hwnd)
            self.loge("窗口: 分层=%s DWM-backdrop=%d DPI=%d 原生caption=%s thickframe=%s"
                      % ("开" if layered else "关", v, dpi,
                         wframe.has_caption(hwnd), wframe.has_thickframe(hwnd)), "ok")
        except Exception as e:
            self.loge("窗口诊断失败: %s" % e, "err")

    def resizeEvent(self, e):
        super().resizeEvent(e)

    def nativeEvent(self, eventType, message):
        return super().nativeEvent(eventType, message)

    # ---- 主体: 左导航 + 页面宿主 ----
    def _build_body(self):
        body = QWidget(objectName="body")
        lay = QHBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.nav = QListWidget(objectName="nav")
        self.nav.setMinimumWidth(140)
        self.nav.setMaximumWidth(320)
        self.nav.setSelectionMode(QAbstractItemView.SingleSelection)
        for label, _ in NAV_ITEMS:
            self.nav.addItem(QListWidgetItem(label))
        self.nav.setCurrentRow(0)
        self.nav.currentRowChanged.connect(self._on_nav)

        self.stack = QStackedWidget(objectName="pageHostBg")

        splitter = QSplitter(Qt.Orientation.Horizontal, objectName="mainSplit")
        splitter.addWidget(self.nav)
        splitter.addWidget(self.stack)
        splitter.setStretchFactor(1, 1)
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setSizes([172, 700])

        lay.addWidget(splitter, 1)
        lay.addWidget(self._build_right())
        return body

    def _build_right(self):
        self._status_panel = StatusPanel(cfg=CONFIG, on_settings=self._open_monitor_settings)
        self.right = self._status_panel.right
        return self._status_panel

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
        idx = next((i for i, (_l, k) in enumerate(NAV_ITEMS) if k == key), -1)
        if idx >= 0 and self.nav.currentRow() != idx:
            self.nav.blockSignals(True)
            self.nav.setCurrentRow(idx)
            self.nav.blockSignals(False)
        while self.stack.count():
            w = self.stack.widget(0)
            self.stack.removeWidget(w)
            w.deleteLater()
        if key == "overview":
            page = OverviewPage(self)
        elif key == "dsh":
            from ui.pages_dsh import DshManagePage
            page = DshManagePage(self)
        elif key == "tunnels":
            page = TunnelsPage(self)
        elif key == "sessions":
            from ui.pages_sessions import SessionPage
            page = SessionPage(self)
        elif key == "profiles":
            from ui.pages_profiles import ProfilePage
            page = ProfilePage(self)
        elif key == "keys":
            from ui.pages_keys import KeysPage
            page = KeysPage(self)
        elif key == "taskboard":
            from ui.pages_taskboard import TaskboardPage
            page = TaskboardPage(self)
        elif key == "agents":
            from ui.pages_agents import AgentPage
            page = AgentPage(self)
        elif key == "plugins":
            from ui.pages_plugins import PluginPage
            page = PluginPage(self)
        elif key == "usage":
            from ui.pages_usage import UsagePage
            page = UsagePage(self)
        elif key == "llm":
            from ui.pages_llm import LlmPage
            page = LlmPage(self)
        elif key == "ops":
            from ui.pages_ops import OpsPage
            page = OpsPage(self)
        elif key == "version":
            from ui.pages_version import VersionPage
            page = VersionPage(self)
        elif key == "deployments":
            from ui.pages_deployments import DeploymentPage
            page = DeploymentPage(self)
        elif key == "logs":
            from ui.pages_logs import LogsPage
            page = LogsPage(self)
        elif key == "settings":
            from ui.pages_settings import SettingsPage
            page = SettingsPage(self)
        elif key == "theme":
            from ui.pages_theme import ThemePage
            page = ThemePage(self)
        else:
            page = QLabel("未知页面: " + key)
        self.stack.addWidget(page)

    def _refresh_deploy_list(self):
        local = CONFIG.get("local_name") or "本机"
        self._deployments = [{"name": local, "host": ""}] + dsh_data.load_deployments()
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

    def _open_palette(self):
        cmds = [{"title": "页面: %s" % label, "meta": "跳转",
                 "run": (lambda key=key: self._show_page(key))}
                for label, key in NAV_ITEMS]
        cmds += [{"title": "部署: %s" % (d.get("name") or "?"), "meta": "切换部署",
                  "run": (lambda idx=idx: self.deploy.setCurrentIndex(idx))}
                 for idx, d in enumerate(self._deployments)]
        cmds.append({"title": "动作: 立即刷新", "meta": "refresh",
                     "run": self._force_refresh})
        CommandPalette(self).open(cmds)

    # ---- P0 配置驱动: 监控设置 + 热重载 ----
    def _open_monitor_settings(self):
        self._pending_settings_tab = "monitor"
        self._show_page("settings")

    def reload_config(self):
        global CONFIG
        CONFIG = _load_config()
        _apply_items(CONFIG)
        self.service.reload_config()
        self._status_panel.reload(CONFIG)
        self._refresh_deploy_list()
        self.loge("配置已重载(端口/命名已生效)", "ok")
        self.set_status("配置已重载")

    # ---- 日志/状态 ----
    def loge(self, text, tag=""):
        self.bridge.emit(text, tag)
        self._set_status(text)

    def set_status(self, text):
        self.bridge.emit_status(text)

    def _set_status(self, text):
        if self.status is not None:
            self.status.setText(text)

    # ---- 控件检查模式 ----
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_F12:
            import time
            now = time.monotonic()
            if event.isAutoRepeat() or now - self._last_f12 < 0.3:
                return False
            self._last_f12 = now
            self._inspect = not self._inspect
            state = "开" if self._inspect else "关"
            self.set_status("控件检查模式: " + state)
            self.loge("控件检查模式: " + state, "warn")
            return False
        if self._inspect and event.type() == QEvent.Type.MouseButtonPress \
                and event.button() == Qt.MouseButton.LeftButton:
            w = self._deep_widget(QCursor.pos())
            if w is not None:
                self.loge("[inspect] 点击控件: " + self._path(w), "warn")
        return False

    def _inspect_tick(self):
        if not self._inspect:
            self._last_inspect_w = None
            return
        w = self._deep_widget(QCursor.pos())
        if w is None or w is self._last_inspect_w:
            return
        self._last_inspect_w = w
        QToolTip.showText(QCursor.pos() + QPoint(14, 18), self._identity(w))

    @staticmethod
    def _deep_widget(pos):
        w = QApplication.widgetAt(pos)
        while w is not None:
            child = w.childAt(w.mapFromGlobal(pos))
            if child is None:
                return w
            w = child
        return None

    @staticmethod
    def _identity(w):
        cls = type(w).__name__
        name = w.objectName() or ""
        txt = ""
        if hasattr(w, "text"):
            t = w.text()
            if t:
                txt = " 文本=%r" % (t[:24],)
        return "%s#%s%s" % (cls, name, txt) if name else "%s%s" % (cls, txt)

    @staticmethod
    def _path(w):
        parts = []
        cur = w
        while cur is not None:
            cls = type(cur).__name__
            name = cur.objectName() or ""
            parts.append("%s#%s" % (cls, name) if name else cls)
            cur = cur.parentWidget() if isinstance(cur, QWidget) else None
        return " > ".join(reversed(parts))

    # ---- 右侧健康监控 ----
    def _start_monitor(self):
        self._monitor_busy = False
        self.service.monitor.connect(self._on_monitor)
        self._monitor_timer = QTimer(self)
        self._monitor_timer.timeout.connect(self._monitor_tick)
        self._monitor_timer.start(3000)
        if not self.smoke:
            self._monitor_tick()

    def _monitor_tick(self):
        if self._monitor_busy:
            return
        self._monitor_busy = True
        self.service.monitor_once()

    def _on_monitor(self, payload):
        self._monitor_busy = False
        if payload is None:
            return
        local, ssh_count, remote = payload
        self._apply_monitor(local, ssh_count, remote)

    def _on_card(self, key, on):
        self._card_state[key] = on

    def _sync_card_states(self, local, remote):
        for key, on in card_states_from_monitor(local, remote, CONFIG).items():
            if self._card_state.get(key) != on:
                self._card_state[key] = on
                self.service.card.emit(key, on)

    def _apply_monitor(self, local, ssh_count, remote):
        self._sync_card_states(local, remote)
        for port, (ok, ms) in (local or {}).items():
            if port == "__ssh__":
                continue
            self.right.set_state("L%d" % port, ok, ms)
        if remote is not None:
            for port, ok in remote.items():
                self.right.set_state("R%d" % port, ok, None)
        local_ok = [p for p, (ok, _) in (local or {}).items() if p != "__ssh__" and ok]
        local_total = len([1 for p, _, _ in CONFIG.get("local_ports", [])])
        ssh_ok = (local or {}).get("__ssh__", (False, -1))[0]
        ssh_txt = "公网服务器 在线" if ssh_ok else "公网服务器 不可达"
        sc = ssh_count if isinstance(ssh_count, int) and ssh_count >= 0 else "?"
        self._set_status("本机端口 %d/%d · %s · ssh.exe %s"
                         % (len(local_ok), local_total, ssh_txt, sc))

        # 动态更新托盘 Tooltip
        if getattr(self, "_tray", None) and self._tray.isVisible():
            dash_port = CONFIG.get("dash_port", 3080)
            dsh_ok = (local or {}).get(dash_port, (False, -1))[0]
            dsh_status_txt = "运行中 (:%d)" % dash_port if dsh_ok else "未运行"
            tun_active = len([1 for p, ok in (remote or {}).items() if ok])
            tun_total = len(CONFIG.get("remote_tunnels", []))
            if tun_active > 0:
                tun_status_txt = "运行中 (%d/%d 活跃)" % (tun_active, tun_total)
            else:
                tun_status_txt = "已停止"
            self._tray.setToolTip("dsh 控制台\n● dsh: %s\n● 隧道: %s" % (dsh_status_txt, tun_status_txt))

    # ---- 系统托盘与后台常驻 ----
    def _init_tray(self):
        self._quitting = False
        self._tray_notified = False
        if self.smoke or os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            self._tray = None
            return
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = None
            return

        self._tray = QSystemTrayIcon(self)
        icon = QIcon(LOGO_ICO_PATH) if (LOGO_ICO_PATH and os.path.isfile(LOGO_ICO_PATH)) else (
            QIcon(LOGO_PATH) if LOGO_PATH else QIcon())
        self._tray.setIcon(icon)
        self._tray.setToolTip("dsh 控制台\n● dsh: 检测中…\n● 隧道: 检测中…")

        menu = QMenu(self)
        act_show = menu.addAction("🐳 显示主窗口")
        font = act_show.font()
        font.setBold(True)
        act_show.setFont(font)
        act_show.triggered.connect(self._restore_from_tray)

        menu.addSeparator()
        act_start_dsh = menu.addAction("🚀 启动本机 dsh")
        act_start_dsh.triggered.connect(lambda: self.service.start_dsh(CONFIG))
        act_stop_dsh = menu.addAction("⏹️ 停止本机 dsh")
        act_stop_dsh.triggered.connect(lambda: self.service.stop_dsh())
        act_restart_dsh = menu.addAction("🔄 重启本机 dsh")
        act_restart_dsh.triggered.connect(lambda: self.service.restart_dsh(CONFIG))

        menu.addSeparator()
        act_start_tun = menu.addAction("🚇 启动隧道")
        act_start_tun.triggered.connect(lambda: self.service.start_tunnels(CONFIG, CONFIG.get("forward_ports", [])))
        act_stop_tun = menu.addAction("⏹️ 停止隧道")
        act_stop_tun.triggered.connect(lambda: self.service.stop_tunnels(CONFIG.get("forward_ports", [])))

        menu.addSeparator()
        act_quit = menu.addAction("❌ 退出控制台")
        act_quit.triggered.connect(self._real_quit)

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self._restore_from_tray()

    def _restore_from_tray(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def closeEvent(self, event):
        if getattr(self, "_quitting", False) or self._tray is None or not self._tray.isVisible():
            event.accept()
        else:
            event.ignore()
            self.hide()
            if not self._tray_notified:
                self._tray_notified = True
                self._tray.showMessage(
                    "dsh 控制台",
                    "控制台已最小化到系统托盘，后台持续监控与隧道运行中。",
                    QSystemTrayIcon.MessageIcon.Information,
                    2000
                )

    def _real_quit(self):
        self._quitting = True
        if getattr(self, "_tray", None):
            self._tray.hide()
        self.close()
        QApplication.quit()


# ---------------- 入口 ----------------
def main():
    app = QApplication(sys.argv)
    smoke = "--smoke" in sys.argv
    if "--diag-config" in sys.argv:
        print("sys.frozen =", getattr(sys, "frozen", False))
        print("sys.executable =", sys.executable)
        print("cwd =", os.getcwd())
        print("env.DSH_AIO_CONFIG =", os.environ.get("DSH_AIO_CONFIG"))
        p = dsh_config.default_config_path()
        print("default_config_path =", p)
        print("_default_config_path =", dsh_config._default_config_path())
        print("config exists =", os.path.isfile(p))
        try:
            with open(p, encoding="utf-8") as f:
                raw = f.read()
            print("read bytes =", len(raw))
            cfg = json.loads(raw)
            print("json keys =", len(cfg))
        except Exception as e:
            import traceback
            print("load EXC:", type(e).__name__, "|", str(e)[:300])
            traceback.print_exc()
        cfg = dsh_config.load_config(None)
        print("load_config keys =", len(cfg), sorted(cfg.keys())[:8])
        return 0
    w = MainWindow(smoke=smoke)
    if smoke:
        print("SMOKE_OK pages=", w.stack.count(), "deploys=", len(w._deployments))
        return 0
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
