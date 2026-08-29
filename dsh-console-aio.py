# -*- coding: utf-8 -*-
"""
dsh-console-aio.py - dsh 控制台主程序 (PySide6): 主窗口骨架 + 总览/隧道页 + 日志桥。
UI 分层: 后端业务在 core/(纯 Python 零 Qt), 信号桥在 app/services.py(DshService),
管理页在 ui/pages_*.py, 对话框在 ui/dialogs.py, 主题引擎在 ui/theme.py(token 生成 QSS,
Win11 Mica 支持; 外部 ui/theme.qss 为非 Mica 模式的可选覆盖)。
兼容 shim: dsh_data.py(转发 core.data); 隧道管理: tunnel_mgr.py(被 core.tunnels 使用)。

运行(双击 exe 或):  C:/Users/1/.conda/envs/console/pythonw.exe dsh-console-aio.py
离屏验证:  QT_QPA_PLATFORM=offscreen python dsh-console-aio.py --smoke
检查模式: 启动加 --inspect 或运行中按 F12 —— 悬停显示控件身份(类名+objectName),
          左键点击在日志区打印控件完整路径(便于向开发者指认界面元素)。
"""
import os, sys, json, threading, ctypes
import ctypes.wintypes
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton, QHBoxLayout,
    QVBoxLayout, QListWidget, QListWidgetItem, QStackedWidget, QTextEdit,
    QComboBox, QFrame, QSizePolicy, QAbstractItemView,
    QMessageBox, QToolTip, QSplitter)
from PySide6.QtCore import Qt, Signal, QObject, QTimer, QEvent, QPoint, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QTextCursor, QColor, QCursor

from core import data as dsh_data
from app.services import DshService
from ui.theme import build_qss, apply_window_effects, try_system_blur

if getattr(sys, 'frozen', False):
    # onefile exe: 用户可见/可写的数据目录 = exe 所在目录(放 config.json 便于分发后编辑)。
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.environ.get('DSH_AIO_CONFIG') or os.path.join(BASE_DIR, 'config.json')
APP_VERSION = '0.5.0'

# frozen 模式下把 exe 目录也加入 sys.path, 保证旁置的可写数据/日志可见(仅当需要时)。
if getattr(sys, 'frozen', False) and BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


def _load_config():
    try:
        with open(CONFIG_PATH, encoding='utf-8') as f:
            return json.load(f) or {}
    except Exception:
        return {}

CONFIG = _load_config()

# ---------------- 业务常量(从 config.json 派生) ----------------
BTN_TEXT = {"start": "启动", "restart": "重启", "persist": "常驻",
           "stop": "停止", "run": "运行更新"}

def build_items(cfg):
    # 隧道卡片清单(名字可配置, P0): local/lab/ssh 三处命名来自 config。
    local = cfg.get("local_name") or "本机"
    lab = cfg.get("lab_name") or "实验室"
    ssh = cfg.get("ssh_name") or "公网中转"
    port = cfg.get("dash_port") or 3080
    return [
        {"type": "dsh", "key": "dsh-web", "title": local + " dsh", "port": port,
         "actions": ["start", "restart", "stop"],
         "desc": "启动/重启/停止%s dsh GUI\n(后台 pnpm dsh web,\n访问 http://127.0.0.1:%d)" % (local, port)},
        {"type": "py", "key": "dsh-tunnel", "port": 8090, "backend": "python",
         "actions": ["start", "persist", "stop"],
         "desc": "在家 -> 打通三个转发口\n8090->%sGUI / 8022->SSH / 8091->本机GUI" % lab},
        {"type": "py", "key": "connect-lab-dsh", "port": 3090, "backend": "python",
         "actions": ["start", "persist", "stop"],
         "desc": "%s局域网 -> 直连%s dsh GUI (本机 3090)" % (lab, lab)},
        {"type": "py", "key": "dsh-tunnel-reverse", "port": 0, "backend": "python",
         "actions": ["start", "persist", "stop"],
         "desc": "%s dsh -> %s反向隧道\n%s:8091 -> 本机 3080" % (local, ssh, ssh)},
        {"type": "py", "key": "update-dsh", "port": -1, "backend": "python",
         "actions": ["run"],
         "desc": "运行一次完整更新:\ngit 拉取->依赖->构建->重启"},
    ]


ITEMS = build_items(CONFIG)


def _apply_items(cfg):
    # 热重载: 原地重建卡片清单(TunnelsPage 重建时读取)
    ITEMS.clear()
    ITEMS.extend(build_items(cfg))

NAV_ITEMS = [
    ('总览', 'overview'), ('隧道', 'tunnels'), ('会话与工作区', 'sessions'),
    ('Agent 模式', 'agents'), ('Profile 管理', 'profiles'), ('插件管理', 'plugins'),
    ('任务看板', 'taskboard'), ('模型用量', 'usage'), ('LLM 配置', 'llm'),
    ('备份与运维', 'ops'), ('SSH 密钥', 'keys'), ('关于与更新', 'version'),
    ('部署管理', 'deployments'),
]


def card_states_from_monitor(local, remote, cfg):
    # 把监控探测结果翻译为隧道卡片状态(纯函数, 可单测): 返回 {key: bool}。
    # 本机 dsh / 本机隧道卡片看本机端口探测; 反向隧道看公网侧 reverse_port 是否在监听
    # (remote 探测); 探测无数据(如 remote 为 None)的 key 不下结论, 保持上次状态。
    states = {}
    for item in ITEMS:
        key, port = item["key"], item.get("port")
        if key in ("dsh-web", "dsh-tunnel", "connect-lab-dsh"):
            states[key] = bool(local and local.get(port, (False, -1))[0])
        elif key == "dsh-tunnel-reverse" and remote is not None:
            rp = (cfg or {}).get("reverse_port") or 8091
            states[key] = bool(remote.get(rp, False))
    return states



# ---------------- 主题: 由 ui/theme.py 主题引擎生成(token 驱动, 见 build_qss) ----------------




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

    def safe_emit(self, sig, *args):
        # 后台线程回 UI 的安全发射: 页面销毁后对已删 QObject emit 抛 RuntimeError, 此处吞掉。
        try:
            sig.emit(*args)
        except RuntimeError:
            pass

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


# ---------------- 右状态栏(监控点) ----------------
class RightBar(QFrame):
    def __init__(self, on_collapse=None, on_settings=None, parent=None):
        super().__init__(parent)
        self.setObjectName("rightBar")
        self.setMinimumWidth(210)
        self.setMaximumWidth(280)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)

        head = QHBoxLayout()
        t = QLabel("监控", objectName="rightTitle")
        btn = QPushButton("»", objectName="collapseBtn")   # 右栏收起: 朝右(滑向右缘)
        btn.setFixedSize(24, 22)
        btn.setToolTip("收起为窄条")
        if on_collapse:
            btn.clicked.connect(on_collapse)
        head.addWidget(t)
        head.addStretch(1)
        if on_settings:
            btn_set = QPushButton("⚙", objectName="collapseBtn")
            btn_set.setFixedSize(24, 22)
            btn_set.setToolTip("监控设置(端口/命名)")
            btn_set.clicked.connect(on_settings)
            head.addWidget(btn_set)
        head.addWidget(btn)
        v.addLayout(head)

        # 内容区独立容器: 热重载时整体清空重建(命名/端口跟随配置)
        self._content = QVBoxLayout()
        self._content.setSpacing(8)
        v.addLayout(self._content)
        self._build_content(CONFIG)

    def _clear_layout(self, lay):
        while lay.count():
            item = lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _build_content(self, cfg):
        self._clear_layout(self._content)
        local = cfg.get("local_name") or "本机"
        ssh = cfg.get("ssh_name") or "公网中转"
        self._add_section(local + "端口")
        self._cells = {}
        for port, label, note in cfg.get("local_ports", []):
            self._add_cell("L" + str(port), label, note, port)
        self._content.addSpacing(6)
        self._add_section(ssh + " 反向隧道")
        for port, label, note in cfg.get("remote_tunnels", []):
            self._add_cell("R" + str(port), label, note, port)
        self._content.addStretch(1)

    def reload(self, cfg):
        self._build_content(cfg)

    def _add_section(self, text):
        lbl = QLabel(text, objectName="rightTitle")
        self._content.addWidget(lbl)

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
        self._content.addLayout(row)
        self._cells[key] = (dot, val)

    def set_state(self, key, ok, ms=-1):
        # 实时更新单元格状态: 圆点与数值配色(绿=在线/红=不可达)。
        # ms=None 表示只有 on/off 信息(如远程隧道), 显示 在线/不可达; ms>=0 显示延迟。
        cell = self._cells.get(key)
        if cell is None:
            return
        dot, val = cell
        color = "#43d17f" if ok else "#e5574d"
        dot.setStyleSheet("color:%s;" % color)
        if ms is None:
            val.setText("在线" if ok else "不可达")
        elif ok and ms >= 0:
            val.setText("%dms" % ms)
        else:
            val.setText("未就绪")
        val.setStyleSheet("color:%s;" % color)


# ---------------- 右栏收起窄条(隧道状态迷你视图) ----------------
class MiniStatusStrip(QFrame):
    """右栏收起态: 每行「状态点 + 端口号」, 通断一目了然; 点击任意处展开。"""

    def __init__(self, on_expand=None, parent=None):
        super().__init__(parent)
        self.setObjectName("miniStrip")
        self.setFixedWidth(44)
        self._on_expand = on_expand
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 6, 4, 6)
        v.setSpacing(4)
        if on_expand:
            btn = QPushButton("«", objectName="collapseBtn")   # 窄条展开: 朝左(滑出内容)
            btn.setFixedSize(26, 22)
            btn.setToolTip("展开状态栏")
            btn.clicked.connect(on_expand)
            v.addWidget(btn, 0, Qt.AlignHCenter)
        # 内容区独立容器: 热重载时重建(命名/端口跟随配置)
        self._content = QVBoxLayout()
        self._content.setSpacing(4)
        v.addLayout(self._content)
        self._build_content(CONFIG)

    def _clear_layout(self, lay):
        while lay.count():
            item = lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _build_content(self, cfg):
        self._clear_layout(self._content)
        local = cfg.get("local_name") or "本机"
        ssh = cfg.get("ssh_name") or "公网中转"
        # 与右栏同构: 分组中文间隔 + 同顺序的「状态点+端口号」(点/号左对齐, 位置一致)
        self._rows = {}   # ("L"|"R", port) -> (dot, num)
        for tag, title, ports in (("L", local + "端口", cfg.get("local_ports", [])),
                                  ("R", ssh, cfg.get("remote_tunnels", []))):
            if not ports:
                continue
            sec = QLabel(title, objectName="miniSection")
            self._content.addWidget(sec, 0, Qt.AlignLeft)
            for port, _, _ in ports:
                row = QHBoxLayout()
                row.setSpacing(3)
                dot = QLabel("●", objectName="miniDot")
                dot.setStyleSheet("color:#555;")
                num = QLabel(str(port), objectName="miniNum")
                row.addWidget(dot)
                row.addWidget(num)
                row.addStretch(1)
                self._content.addLayout(row)
                self._rows[(tag, port)] = (dot, num)
        self._content.addStretch(1)

    def reload(self, cfg):
        self._build_content(cfg)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._on_expand:
            self._on_expand()
        super().mousePressEvent(e)

    def update_states(self, local, remote):
        # 与 RightBar 同一数据源(monitor 探测结果): 本机端口 + 远程隧道通断。
        for (tag, port), (dot, num) in self._rows.items():
            if tag == "L":
                ok = bool(local and local.get(port, (False, -1))[0])
            else:
                if remote is None:
                    ok = None          # 探测无数据 -> 保持灰
                else:
                    ok = bool(remote.get(port, False))
            color = "#43d17f" if ok is True else ("#e5574d" if ok is False else "#555")
            dot.setStyleSheet("color:%s;" % color)


class StatusPanel(QFrame):
    """右栏容器: 全量 RightBar <-> 窄条 MiniStatusStrip, 展开/收起带宽度动画。"""

    def __init__(self, on_settings=None, parent=None):
        super().__init__(parent)
        self.setObjectName("statusPanel")
        self.setMinimumWidth(44)
        self.setMaximumWidth(280)
        self._mini = MiniStatusStrip(on_expand=self.expand)
        self.right = RightBar(on_collapse=self.collapse, on_settings=on_settings)
        # 普通布局 + 显式右对齐(窄条贴面板右缘; QStackedLayout 的 alignment 实测不生效)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(0)
        self._lay.addWidget(self.right)
        self._lay.setAlignment(self._mini, Qt.AlignRight)
        # min/max 同步动画: 布局按约束强制给宽, 动画期间宽度严格跟随(右锚定顺滑)
        self._anim_max = QPropertyAnimation(self, b"maximumWidth", self)
        self._anim_min = QPropertyAnimation(self, b"minimumWidth", self)
        for a in (self._anim_max, self._anim_min):
            a.setDuration(180)
            a.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_max.finished.connect(self._on_anim_done)
        self._target = None

    def collapse(self):
        # 先动画(RightBar 保持可见被压缩), 动画结束时才切换窄条 —— 避免动画期间
        # 面板区域露空(露出页面底色)
        self._target = "collapsed"
        self._start_anim(44)

    def expand(self):
        # 先切回全量(44px 处开始压缩态), 再动画展开 —— 窄条不参与展开动画
        self._target = "expanded"
        self._swap_to_right()
        self._start_anim(240)

    def _swap_to_mini(self):
        self._lay.removeWidget(self.right)
        self._lay.addWidget(self._mini)
        self.right.hide()
        self._mini.show()

    def _swap_to_right(self):
        self._lay.removeWidget(self._mini)
        self._lay.addWidget(self.right)
        self._mini.hide()
        self.right.show()

    def _start_anim(self, end):
        w = self.width()
        self._anim_max.stop()
        self._anim_min.stop()
        self._anim_max.setStartValue(w)
        self._anim_max.setEndValue(end)
        self._anim_min.setStartValue(w)
        self._anim_min.setEndValue(end)
        self._anim_max.start()
        self._anim_min.start()

    def _on_anim_done(self):
        if self._target == "collapsed":
            self.setMinimumWidth(44)
            self.setMaximumWidth(44)     # 钉死窄条
            self._swap_to_mini()         # 44px 处无缝替换为窄条
        elif self._target == "expanded":
            self.setMinimumWidth(210)
            self.setMaximumWidth(280)
        self._target = None

    def update_states(self, local, remote):
        self._mini.update_states(local, remote)

    def reload(self, cfg):
        # 热重载: 右栏与窄条按新配置重建(端口/命名)
        self.right.reload(cfg)
        self._mini.reload(cfg)



# ---------------- 自绘标题栏(无边框窗口): 手动拖拽 + 双击最大化 ----------------
# 不用 HTCAPTION: 分层(WS_EX_LAYERED)窗口上 WM_NCHITTEST 拖拽不可靠(实测), 手动
# mouse 事件纯 Qt 实现; 控件(按钮/下拉)自己消费点击, 空白/标签区自然冒泡到本栏。
class _TopBar(QFrame):
    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.setObjectName("topbar")
        self._win = win
        self._drag = None

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and not self._win._maxed:
            self._drag = e.globalPosition().toPoint() - self._win.frameGeometry().topLeft()
            e.accept()
        else:
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self._win.move(e.globalPosition().toPoint() - self._drag)
            e.accept()
        else:
            super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag = None
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._win._toggle_maximize()
            e.accept()
        else:
            super().mouseDoubleClickEvent(e)


# ---------------- 主窗口 ----------------
class MainWindow(QMainWindow):
    def __init__(self, smoke=False):
        super().__init__()
        self.smoke = smoke
        # 无边框窗口仅 Windows(自绘标题栏 + 分层透明 + DWM Mica); 拖拽/拉伸走 WM_NCHITTEST。
        # 其他平台保留原生标题栏(跨平台策略, 见 docs/VISION_部署子工具组.md)。
        self._frameless = sys.platform == "win32"
        if self._frameless:
            self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setWindowTitle("DSH Console · v" + APP_VERSION)
        self.resize(1160, 800)
        self.setMinimumSize(960, 620)
        self._normal_geo = None                # 最大化前几何(还原用)
        self._maxed = False                    # 自维护最大化状态(setGeometry 伪最大化)
        self._btn_max = None                   # 最大化按钮(图标切换 □/❐)
        # 平台窗口效果(Win11 22H2+ 分层透明; 失败自动回退纯 QSS)
        self._mica = apply_window_effects(self)
        # 系统级模糊(SetWindowCompositionAttribute, 经典方案); 失败则半透明无模糊
        self._sys_blur = try_system_blur(self) if self._mica else False
        self.setStyleSheet(self._load_theme())

        self._current_page_key = None
        self._deployments = []
        self.bridge = LogBridge()
        self.APP_VERSION = APP_VERSION
        # 业务层信号桥(core 的唯一 UI 入口): config 走 DSH_AIO_CONFIG, 与本模块一致。
        self.service = DshService.from_env(parent=self)
        # service -> 主窗口的日志/状态只在窗口级 connect 一次: 页面会随导航反复销毁重建,
        # 若在页面里 connect 到 app 的槽(接收者是长命的 MainWindow), 会导致连接叠加重复输出。
        self.service.log.connect(self.loge)
        self.service.status.connect(self.set_status)
        self._card_state = {}               # 隧道卡片最近已知状态(监控/启停事件累计)
        self.service.card.connect(self._on_card)
        self._start_monitor()               # 右侧健康监控(实时探测端口/隧道)

        # ---- 控件检查模式(悬停显示身份, 左键点击打印路径; --inspect 启动 / F12 切换) ----
        self._inspect = "--inspect" in sys.argv
        self._last_inspect_w = None
        self._last_f12 = 0.0                   # F12 去抖(驱动可能重复投递按键)
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
                self.loge("模糊: %s" % ("系统级(ACCENT_ENABLE_BLURBEHIND)" if self._sys_blur
                                        else "系统级失败, 半透明无模糊"), "ok")

    # ---- 主题(主题引擎 ui/theme.py, token 驱动) ----
    def _load_theme(self):
        #   Mica 可用(Win11 22H2+) -> 生成半透明 QSS(外部 theme.qss 不参与, 避免盖住 DWM 背景);
        #   否则 -> 外部 ui/theme.qss 优先(手动微调), 缺失回退生成的不透明 QSS。
        if self._mica:
            return build_qss(mica=True)
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

    # ---- 顶部栏 ----
    def _build_topbar(self):
        bar = _TopBar(self)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(10)

        title = QLabel("DSH Console", objectName="titleLbl")
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
        config.clicked.connect(self._open_config)
        env = QPushButton("环境")
        env.clicked.connect(self._open_env)
        install = QPushButton("安装")
        install.clicked.connect(self._open_install)

        for w in (title, ver, sep, dlab, self.deploy, poll):
            lay.addWidget(w)
        lay.addWidget(spacer)
        lay.addWidget(config)
        lay.addWidget(env)
        lay.addWidget(install)
        lay.addWidget(refresh)

        # 无边框窗口控制按钮(自绘标题栏; 仅 Windows 无边框模式)
        if self._frameless:
            btn_min = QPushButton("—", objectName="winBtn")
            self._btn_max = QPushButton("□", objectName="winBtn")
            btn_close = QPushButton("×", objectName="winBtnClose")
            btn_min.clicked.connect(self.showMinimized)
            self._btn_max.clicked.connect(self._toggle_maximize)
            btn_close.clicked.connect(self.close)
            for b in (btn_min, self._btn_max, btn_close):
                b.setFixedSize(34, 28)
                lay.addWidget(b)
        return bar

    # ---- 无边框窗口: 最大化/还原(自维护状态, setGeometry 伪最大化不可靠) ----
    def _toggle_maximize(self):
        if self._maxed:
            self.setGeometry(self._normal_geo)
            self._maxed = False
            self._btn_max.setText("□")
        else:
            self._normal_geo = self.geometry()
            scr = self.screen() or QApplication.primaryScreen()
            if scr is not None:
                self.setGeometry(scr.availableGeometry())
            self._maxed = True
            self._btn_max.setText("❐")

    def _log_window_facts(self):
        # 启动后诊断: 分层窗口/DPI/DWM backdrop 实际状态(半透明排查用)
        try:
            hwnd = int(self.winId())
            style = ctypes.windll.user32.GetWindowLongPtrW(hwnd, -20)
            layered = bool(style & 0x80000)
            dpi = ctypes.windll.user32.GetDpiForWindow(hwnd)
            v = ctypes.c_int(0)
            r = ctypes.windll.dwmapi.DwmGetWindowAttribute(
                hwnd, 38, ctypes.byref(v), ctypes.sizeof(v))
            self.loge("窗口: 分层=%s DWM-backdrop=%d DPI=%d"
                      % ("开" if layered else "关", v.value if r == 0 else -1, dpi), "ok")
        except Exception as e:
            self.loge("窗口诊断失败: %s" % e, "err")

    def resizeEvent(self, e):
        super().resizeEvent(e)

    def nativeEvent(self, eventType, message):
        # WM_NCHITTEST: 标题栏空白区拖拽(HTCAPTION), 边缘 6px 拉伸, 控件区放行。
        # ⚠ 坐标换算: lParam 是物理像素, Qt geometry() 是逻辑像素(高分屏 DPI 缩放下
        # 直接比较会导致热区错位——实测 150% 缩放下右缘热区膨胀到半屏、左/上缘消失)。
        if sys.platform == "win32" and not self.smoke:
            try:
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == 0x0084:  # WM_NCHITTEST
                    dpi = ctypes.windll.user32.GetDpiForWindow(int(self.winId())) or 96
                    dpr = dpi / 96.0
                    x = ctypes.c_short(msg.lParam & 0xFFFF).value / dpr
                    y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value / dpr
                    geo = self.geometry()  # 逻辑坐标
                    if self._maxed:
                        # 最大化时不拉伸(热区关闭); 标题栏拖拽由 _TopBar 手动处理
                        return True, 1
                    ex, ey, ew, eh = geo.x(), geo.y(), geo.width(), geo.height()
                    EDGE = 6
                    left = x <= ex + EDGE
                    right = x >= ex + ew - EDGE
                    top = y <= ey + EDGE
                    bottom = y >= ey + eh - EDGE
                    if left and top:
                        hit = 13
                    elif right and top:
                        hit = 14
                    elif left and bottom:
                        hit = 16
                    elif right and bottom:
                        hit = 17
                    elif left:
                        hit = 10
                    elif right:
                        hit = 11
                    elif top:
                        hit = 12
                    elif bottom:
                        hit = 15
                    elif y <= ey + 52:
                        # 标题栏区: 统一 HTCLIENT, 拖拽由 _TopBar 手动 mouse 事件处理
                        # (分层窗口上 HTCAPTION 不可靠, 实测)
                        hit = 1
                    else:
                        hit = 1
                    return True, hit
            except Exception:
                pass
        return super().nativeEvent(eventType, message)

    # ---- 顶栏对话框入口(配置向导/环境检查/安装向导) ----
    def _open_config(self):
        global CONFIG
        import copy
        from ui.dialogs import ConfigDialog
        dlg = ConfigDialog(copy.deepcopy(CONFIG), parent=self, app=self)
        dlg.exec()
        if not getattr(dlg, "result", None):
            return
        try:
            dsh_data.backup_file(CONFIG_PATH)
            with open(CONFIG_PATH, encoding='utf-8') as f:
                cfg = json.load(f) or {}
        except Exception:
            cfg = {}
        cfg.update(dlg.result)
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        CONFIG = cfg
        self.loge("配置已保存", "ok")
        self._refresh_deploy_list()
        self.set_status("配置已保存（隧道/端口等参数完整生效需重启）")

    def _open_env(self):
        from ui.dialogs import EnvDialog
        EnvDialog(self).exec()

    def _open_install(self):
        from ui.dialogs import InstallDialog
        dlg = InstallDialog(self)
        dlg.exec()
        if getattr(dlg, "result", None):
            self._refresh_deploy_list()
            self.set_status("安装完成，dash_repo 已更新")

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

        # 左导航 | 页面 用分栏(可拖拽); 右状态栏独立放布局 -> 天然右锚定,
        # 收起动画只动它自己的宽度, 不依赖 splitter 的右缘行为(实测 splitter 右缘不可靠)
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
        self._status_panel = StatusPanel(on_settings=self._open_monitor_settings)
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
        while self.stack.count():
            w = self.stack.widget(0)
            self.stack.removeWidget(w)
            w.deleteLater()
        if key == "overview":
            page = OverviewPage(self)
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
        else:
            # 兜底(正常不可达: 13 个导航 key 全部有真实页面)
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

    # ---- P0 配置驱动: 监控设置 + 热重载 ----
    def _open_monitor_settings(self):
        from ui.dialogs import MonitorSettingsDialog
        dlg = MonitorSettingsDialog(CONFIG, CONFIG_PATH, parent=self)
        if dlg.exec() and dlg.saved:
            self._reload_config()

    def _reload_config(self):
        # 热重载: 重读 config -> 重建卡片/右栏/窄条/部署列表, service 探测点跟随。
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
        # 跨线程安全(经 LogBridge status 信号回到主线程)
        self.bridge.emit_status(text)

    def _set_status(self, text):
        if self.status is not None:
            self.status.setText(text)

    # ---- 控件检查模式 ----
    def eventFilter(self, obj, event):
        # F12 开关; 开启时左键点击把控件完整路径打进日志区。
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_F12:
            import time
            now = time.monotonic()
            if event.isAutoRepeat() or now - self._last_f12 < 0.3:
                return False              # 去抖: 一次物理按键只切换一次
            self._last_f12 = now
            self._inspect = not self._inspect
            state = "开" if self._inspect else "关"
            self.set_status("控件检查模式: " + state)
            self.loge("控件检查模式: " + state, "warn")   # 日志区持久可见(状态栏会被监控覆盖)
            return False
        if self._inspect and event.type() == QEvent.Type.MouseButtonPress \
                and event.button() == Qt.MouseButton.LeftButton:
            w = self._deep_widget(QCursor.pos())
            if w is not None:
                self.loge("[inspect] 点击控件: " + self._path(w), "warn")
        return False

    def _inspect_tick(self):
        # 轮询悬停: widgetAt 做命中测试, 不依赖控件的鼠标跟踪/悬停属性。
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
        # 从 widgetAt 的命中控件向下钻取到最深层子控件。
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

    # ---- 右侧健康监控(探测业务在 core, 经 service.monitor 信号回主线程) ----
    def _start_monitor(self):
        self._monitor_busy = False
        self.service.monitor.connect(self._on_monitor)
        self._monitor_timer = QTimer(self)
        self._monitor_timer.timeout.connect(self._monitor_tick)
        self._monitor_timer.start(3000)
        if not self.smoke:
            self._monitor_tick()   # 启动即探一次

    def _monitor_tick(self):
        if self._monitor_busy:
            return
        self._monitor_busy = True
        self.service.monitor_once()

    def _on_monitor(self, payload):
        # service.monitor 回包(主线程): payload 为 (local, ssh_count, remote) 元组;
        # None 哨兵 = 本轮探测线程异常, 仅解除 busy, 下轮定时器重试。
        self._monitor_busy = False
        if payload is None:
            return
        local, ssh_count, remote = payload
        self._apply_monitor(local, ssh_count, remote)

    def _on_card(self, key, on):
        # 任何来源的卡片事件(启停/监控)都记入状态快照, 页面重建后可恢复。
        self._card_state[key] = on

    def _sync_card_states(self, local, remote):
        # 监控探测 -> 卡片状态: 仅广播"有数据且变化"的 key(页面在 service.card 上订阅)。
        for key, on in card_states_from_monitor(local, remote, CONFIG).items():
            if self._card_state.get(key) != on:
                self._card_state[key] = on
                self.service.card.emit(key, on)

    def _apply_monitor(self, local, ssh_count, remote):
        # 主线程 UI 更新(无 IO): 右侧栏单元格配色 + 底部状态栏汇总 + 隧道卡片状态同步
        self._sync_card_states(local, remote)
        self._status_panel.update_states(local, remote)
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





# ---------------- 隧道页(导航第 2 项) ----------------
class TunnelsPage(BasePage):
    def _build(self):
        # 卡片在线状态经 service.card 信号回本页(接收者=本页, 页面销毁时 Qt 自动断开)。
        self.app.service.card.connect(self._apply_card)
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

        # 应用已知状态快照(监控/启停事件持续更新; 页面重建后不丢状态)
        for key, on in self.app._card_state.items():
            self._set_card(key, on)

    def _make_card(self, item):
        card = QFrame(objectName="card")
        lv = QVBoxLayout(card)
        lv.setContentsMargins(16, 14, 16, 14)
        lv.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel(item.get("title") or item["key"], objectName="cardTitle")
        head.addWidget(title)
        head.addStretch(1)
        # 状态圆点只对可探测的卡片显示(update-dsh 是纯动作卡, 无在线状态)
        dot = None
        if item.get("port", -1) >= 0:
            dot = QLabel("○", objectName="monDot")
            dot.setStyleSheet("color:#999; font-size:15px;")
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
        entry = self._cards.get(key)
        if entry is None or entry[0] is None:
            return
        d, item = entry
        d.setText("●" if on else "○")
        d.setStyleSheet("color:#7ecb6a; font-size:15px;" if on else "color:#999; font-size:15px;")

    # ---- 动作分派: 页面只分派与提示, 业务经 service 信号桥在后台线程执行 ----
    def _on_action(self, item, mode):
        t = item["type"]
        key = item["key"]
        if t == "dsh":
            self.app.set_status("正在 %s 本机 dsh ..." % mode)
            self.app.service.start_dsh(mode)
            return
        if key == "update-dsh":
            # 更新的是 dsh 本体(dash_repo), 不是本控制台(控制台更新在「关于与更新」页)。
            # 流程: 停 web -> git 拉取 -> 清理旧构建 -> 依赖 -> 构建 -> 重启, 业务在 core.dshctl。
            # 危险操作约定: 先确认"将执行什么", 用户点是才执行。
            ans = QMessageBox.question(
                self, "更新 dsh",
                "将对本机 dsh 执行一次完整更新:\n\n"
                "  1) 停止当前 dsh web\n"
                "  2) git 拉取最新代码\n"
                "  3) 清理旧构建产物\n"
                "  4) 安装依赖 (pnpm install)\n"
                "  5) 构建 (pnpm run build, 耗时较长)\n"
                "  6) 重启 dsh web\n\n"
                "期间 dsh 页面会短暂不可用。是否继续?")
            if ans != QMessageBox.StandardButton.Yes:
                self.app.set_status("已取消更新")
                return
            self.app.loge("[update-dsh] 开始完整更新...", "warn")
            self.app.set_status("正在运行更新(构建较久, 请耐心)...")
            self.app.service.update_dsh()
            return
        # python 隧道: 启停/常驻重连业务在 core.tunnels; persist 停止标志由 service
        # 持有(窗口生命周期), 不再随页面重建丢失导致"停止后又被重连"。
        self.app.loge("[%s] 模式: %s (Python)" % (key, mode), "warn")
        self.app.set_status("正在执行 %s -> %s (Python) ..." % (mode, key))
        self.app.service.start_tunnel(key, mode)

    def _apply_card(self, key, on):
        # service.card 信号槽(主线程): 更新卡片圆点。
        self._set_card(key, on)


if __name__ == "__main__":
    sys.exit(main())
