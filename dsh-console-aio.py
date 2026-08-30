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
    QMessageBox, QToolTip, QSplitter, QInputDialog)
from PySide6.QtCore import Qt, Signal, QObject, QTimer, QEvent, QPoint, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import (QTextCursor, QColor, QCursor, QIcon, QPixmap,
                           QShortcut, QKeySequence)

from core import data as dsh_data
from core import config as dsh_config
from core import tunnel_planner as dsh_planner
from app.services import DshService
from ui import theme as dsh_theme
from ui.palette import CommandPalette
from ui.theme import build_qss, apply_window_effects, try_system_blur
from ui.widgets import ModernList, card_wrap

# 白色齿轮 SVG(内嵌, 无需打包资源文件; QSvgRenderer 渲染为 QIcon)
_GEAR_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#e6e6e6">'
             '<path d="M19.14,12.94c0.04,-0.3 0.06,-0.61 0.06,-0.94c0,-0.32 -0.02,-0.64 '
             '-0.07,-0.94l2.03,-1.58c0.18,-0.14 0.23,-0.41 0.12,-0.61l-1.92,-3.32c-0.12,-0.22 '
             '-0.37,-0.29 -0.59,-0.22l-2.39,0.96c-0.5,-0.38 -1.03,-0.7 -1.62,-0.94L14.4,2.81'
             'c-0.04,-0.24 -0.24,-0.41 -0.48,-0.41h-3.84c-0.24,0 -0.43,0.17 -0.47,0.41L9.25,5.35'
             'C8.66,5.59 8.12,5.92 7.63,6.29L5.24,5.33c-0.22,-0.08 -0.47,0 -0.59,0.22L2.74,8.87'
             'C2.62,9.08 2.66,9.34 2.86,9.48l2.03,1.58C4.84,11.36 4.8,11.69 4.8,12s0.02,0.64 '
             '0.07,0.94l-2.03,1.58c-0.18,0.14 -0.23,0.41 -0.12,0.61l1.92,3.32c0.12,0.22 0.37,0.29 '
             '0.59,0.22l2.39,-0.96c0.5,0.38 1.03,0.7 1.62,0.94l0.36,2.54c0.05,0.24 0.24,0.41 '
             '0.48,0.41h3.84c0.24,0 0.44,-0.17 0.47,-0.41l0.36,-2.54c0.59,-0.24 1.13,-0.56 '
             '1.62,-0.94l2.39,0.96c0.22,0.08 0.47,0 0.59,-0.22l1.92,-3.32c0.12,-0.22 0.07,-0.47 '
             '-0.12,-0.61L19.14,12.94zM12,15.6c-1.98,0 -3.6,-1.62 -3.6,-3.6s1.62,-3.6 3.6,-3.6'
             's3.6,1.62 3.6,3.6S13.98,15.6 12,15.6z"/></svg>')


def _svg_icon(svg_text, size):
    # SVG 字符串 -> QIcon(内嵌图标, 免资源文件; QtSvg 缺失时返回 None 由调用方兜底)
    try:
        from PySide6.QtCore import QByteArray
        from PySide6.QtGui import QIcon, QPainter, QPixmap
        from PySide6.QtSvg import QSvgRenderer
        r = QSvgRenderer(QByteArray(svg_text.encode("utf-8")))
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        r.render(p)
        p.end()
        return QIcon(pm)
    except Exception:
        return None

if getattr(sys, 'frozen', False):
    # onefile exe: 用户可见/可写的数据目录 = exe 所在目录(放 config.json 便于分发后编辑)。
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.environ.get('DSH_AIO_CONFIG') or os.path.join(BASE_DIR, 'config.json')
APP_VERSION = '0.7.0'


def _find_logo():
    # Logo 资源定位: 源码运行在仓库根, 打包(onefile)后随 --add-data 解压到 _MEIPASS。
    # 找不到返回 None(顶栏/窗口图标降级为纯文字, 不致命)。
    cands = []
    if getattr(sys, 'frozen', False):
        cands.append(os.path.join(getattr(sys, '_MEIPASS', BASE_DIR), 'logo.png'))
    cands.append(os.path.join(BASE_DIR, 'logo.png'))
    for c in cands:
        if os.path.exists(c):
            return c
    return None


LOGO_PATH = _find_logo()

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
    ('备份与凭据', 'ops'), ('SSH 密钥', 'keys'), ('部署管理', 'deployments'),
    ('日志管理', 'logs'), ('设置', 'settings'), ('主题', 'theme'), ('关于与更新', 'version'),
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
def _ov_size(n):
    # 概览页字节数人性化(与 sessions 页口径一致)
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f%s" % (n, unit)
        n /= 1024.0
    return "0B"


class OverviewPage(BasePage):
    # 部署总览: 运行状态卡 + 数据速览 + 部署列表 + 隧道速览。
    # 数据经页面级 Signal + safe_emit 回主线程(修复旧实现经 bridge 发进底部日志区的 bug);
    # 全部纯读: 本机文件/端口探测 + 远程快照(DshRemote 只读) + 反向隧道 ssh 查监听。
    _data = Signal(object)   # worker 结果 payload(dict)

    def __init__(self, app, parent=None):
        super().__init__(app, parent)
        self._data.connect(self._apply_data)
        self.refresh()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 12)
        root.setSpacing(8)

        head = QHBoxLayout()
        head.addWidget(QLabel("部署总览", objectName="cardTitle"))
        head.addStretch(1)
        self._status_lbl = QLabel("就绪", objectName="monVal")
        head.addWidget(self._status_lbl)
        refresh = QPushButton("刷新", objectName="primary")
        refresh.clicked.connect(self.refresh)
        head.addWidget(refresh)
        root.addLayout(head)
        root.addWidget(QLabel("本机与远程部署的实时状态、数据速览与隧道探测(纯读获取)。",
                              objectName="cardHint"))

        # 运行状态卡: dsh web 探测 + 本体版本
        run = QFrame(objectName="card")
        rl = QHBoxLayout(run)
        rl.setContentsMargins(14, 10, 14, 10)
        rl.setSpacing(10)
        self._web_lbl = QLabel("dsh web 检测中…", objectName="monVal")
        self._web_lbl.setTextFormat(Qt.RichText)
        rl.addWidget(self._web_lbl)
        rl.addStretch(1)
        root.addWidget(run)

        # 数据速览: 四张迷你卡
        quick = QHBoxLayout()
        quick.setSpacing(8)
        self._quick = {}
        for key, cap in (("sessions", "会话"), ("usage", "模型用量"),
                         ("tasks", "任务板"), ("plugins", "插件与预设")):
            mini = QFrame(objectName="card")
            mv = QVBoxLayout(mini)
            mv.setContentsMargins(12, 8, 12, 8)
            mv.setSpacing(2)
            mv.addWidget(QLabel(cap, objectName="rightTitle"))
            val = QLabel("…", objectName="monVal")
            val.setWordWrap(True)
            mv.addWidget(val)
            mv.addStretch(1)
            self._quick[key] = val
            quick.addWidget(mini, 1)
        root.addLayout(quick)

        # 部署列表(本机 + 远程, 快照字段进 meta)
        self._dep_list = ModernList()
        root.addWidget(card_wrap("部署", self._dep_list), 1)

        # 隧道速览(富文本圆点, 与右栏监控同口径)
        self._tunnel_lbl = QLabel("", objectName="monName")
        self._tunnel_lbl.setTextFormat(Qt.RichText)
        self._tunnel_lbl.setWordWrap(True)
        root.addWidget(card_wrap("隧道状态", self._tunnel_lbl))

    def refresh(self):
        self._set_status("正在读取总览数据...")
        cfg = CONFIG
        depls = dsh_data.load_deployments()
        smoke = bool(getattr(self.app, "smoke", False))

        def worker():
            payload = {"dash_port": int(cfg.get("dash_port") or 3080),
                       "deploys": [], "probe": {}, "remote_probe": None,
                       "local_ports": cfg.get("local_ports", []),
                       "remote_tunnels": cfg.get("remote_tunnels", []),
                       "local_name": cfg.get("local_name") or "本机",
                       "ssh_name": cfg.get("ssh_name") or "公网中转"}
            # dsh web 探测 + 本体版本(仓库 package.json, 仅本机)
            try:
                payload["web_ok"], payload["web_ms"] = \
                    self.app.service.ctl.probe("127.0.0.1", payload["dash_port"])
            except Exception:
                payload["web_ok"], payload["web_ms"] = False, -1
            try:
                with open(os.path.join(cfg.get("dash_repo") or "", "package.json"),
                          encoding="utf-8") as f:
                    payload["dsh_version"] = (json.load(f) or {}).get("version")
            except Exception:
                payload["dsh_version"] = None

            # 部署快照: 本机必做; 远程只读(smoke/占位配置跳过)
            def snap_for(dep, is_local):
                if not is_local and (smoke or not dep.get("host")
                                     or str(dep.get("host")).startswith("YOUR_")):
                    return {"ok": False, "error": "未配置/演示模式"}
                try:
                    return dsh_data.deployment_snapshot(
                        dsh_data.DshRemote(None if is_local else dep))
                except Exception as e:
                    return {"ok": False, "error": str(e)}

            payload["deploys"].append({"dep": {"name": payload["local_name"]},
                                       "snap": snap_for(None, True), "local": True})
            for d in depls:
                payload["deploys"].append({"dep": d, "snap": snap_for(d, False),
                                           "local": False})

            # 数据速览(纯读, 单项失败置 None 不拖垮整页)
            try:
                u = dsh_data.usage_stats()
                total, priced, calls = 0.0, False, 0
                for name, m in (u.get("models") or {}).items():
                    if not isinstance(m, dict):
                        continue
                    calls += int(m.get("calls") or 0)
                    c = dsh_data.estimate_cost(name, int(m.get("input") or 0),
                                               int(m.get("output") or 0),
                                               int(m.get("cache") or 0))
                    if c is not None:
                        total += c
                        priced = True
                payload["usage"] = {"ok": bool(u.get("ok")), "models": len(u.get("models") or {}),
                                    "calls": calls,
                                    "cost": ("%.2f 元" % total) if priced else "未定价",
                                    "error": u.get("error")}
            except Exception as e:
                payload["usage"] = {"ok": False, "error": str(e)}
            try:
                payload["tasks"] = len(((dsh_data.read_taskboard().get("ledger") or {})
                                        .get("tasks") or []))
            except Exception:
                payload["tasks"] = None
            try:
                groups = dsh_data.list_sessions()
                payload["sessions"] = {"groups": len(groups),
                                       "count": sum(g.get("count") or 0 for g in groups),
                                       "bytes": sum(g.get("bytes") or 0 for g in groups)}
            except Exception:
                payload["sessions"] = None
            try:
                payload["archived"] = len(dsh_data.read_workspace()
                                          .get("archivedSessionIds") or [])
            except Exception:
                payload["archived"] = None

            # 隧道探测: 本机端口本机探; 反向隧道经 ssh 查公网监听(只读)
            for port, label, note in payload["local_ports"]:
                try:
                    payload["probe"][("L", int(port))] = \
                        self.app.service.ctl.probe("127.0.0.1", int(port))[0]
                except Exception:
                    payload["probe"][("L", int(port))] = False
            try:
                payload["remote_probe"] = self.app.service.ctl.probe_remote_tunnels()
            except Exception:
                payload["remote_probe"] = None
            self.safe_emit(self._data, payload)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_data(self, p):
        # 运行状态卡
        if p.get("web_ok"):
            self._web_lbl.setText(
                '<span style="color:#7ecb6a">●</span> dsh web :%s 在线'
                '<span style="color:#9a9ab0">（%d ms）</span>'
                % (p.get("dash_port"), p.get("web_ms") or 0)
                + ('<span style="color:#9a9ab0"> · dsh 本体 v%s</span>' % p["dsh_version"]
                   if p.get("dsh_version") else ""))
        else:
            self._web_lbl.setText(
                '<span style="color:#e07a7a">●</span> dsh web :%s 离线'
                '<span style="color:#9a9ab0">（未启动时可在隧道页启动）</span>' % p.get("dash_port"))

        # 部署列表
        rows = []
        for item in p.get("deploys") or []:
            snap = item.get("snap") or {}
            dep = item.get("dep") or {}
            name = dep.get("name") or snap.get("name") or "?"
            meta = []
            if item.get("local") and p.get("dsh_version"):
                meta.append("本体 v" + str(p["dsh_version"]))
            if snap.get("version"):
                meta.append("市场 " + str(snap["version"]))
            meta.append("插件 %s" % (snap.get("plugins") or 0))
            meta.append("profile %s" % (snap.get("profiles") or 0))
            meta.append("预设 %s" % (snap.get("presets") or 0))
            meta.append("会话 %s · %s" % (snap.get("sessions") or 0,
                                          _ov_size(snap.get("session_bytes"))))
            if snap.get("ok"):
                badge, dot = ("在线", "ok"), "#7ecb6a"
            else:
                err = str(snap.get("error") or "")
                if "未配置" in err:
                    badge, dot = ("未配置", "dim"), "#9a9ab0"
                else:
                    badge, dot = ("离线", "err"), "#e07a7a"
            rows.append({"title": name, "meta": " · ".join(meta),
                         "dot": dot, "badges": [badge], "data": item})
        self._dep_list.set_rows(rows)

        # 数据速览
        s = p.get("sessions")
        self._quick["sessions"].setText(
            ("%d 个 · %s\n%d 个已归档" % (s["count"], _ov_size(s["bytes"]),
                                          p.get("archived") or 0)) if s else "读取失败")
        u = p.get("usage") or {}
        if u.get("ok"):
            self._quick["usage"].setText("%d 模型 · %s 次\n累计 %s"
                                         % (u.get("models") or 0, u.get("calls") or 0,
                                            u.get("cost") or "-"))
        else:
            self._quick["usage"].setText("不支持: " + str(u.get("error") or "失败")
                                         if "远程" in str(u.get("error")) else "统计失败")
        self._quick["tasks"].setText(
            "%d 个任务" % p["tasks"] if p.get("tasks") is not None else "读取失败")
        local_snap = {}
        for item in p.get("deploys") or []:
            if item.get("local"):
                local_snap = item.get("snap") or {}
                break
        self._quick["plugins"].setText(
            "%d bundles · %d profile\n%d 预设" % (local_snap.get("plugins") or 0,
                                                  local_snap.get("profiles") or 0,
                                                  local_snap.get("presets") or 0))

        # 隧道速览(圆点富文本, 与右栏监控同口径)
        def dot(ok):
            return '<span style="color:%s">●</span>' % ("#7ecb6a" if ok else "#e07a7a")

        segs = []
        for port, label, note in p.get("local_ports") or []:
            segs.append("%s:%s %s" % (label, port, dot(p.get("probe", {}).get(("L", int(port))))))
        ltext = "  ".join(segs) if segs else "（未配置本机监测端口）"
        r = p.get("remote_probe")
        if r is None:
            rtext = '<span style="color:#9a9ab0">公网侧未探测(未配置或中转不可达)</span>'
        else:
            rsegs = ["%s:%s %s" % (label, port, dot(bool(r.get(int(port)))))
                     for port, label, note in p.get("remote_tunnels") or []]
            rtext = "  ".join(rsegs) if rsegs else "（未配置反向隧道）"
        self._tunnel_lbl.setText(
            '<span style="color:#9a9ab0">%s端口</span> %s<br>'
            '<span style="color:#9a9ab0">%s反向隧道</span> %s'
            % (p.get("local_name"), ltext, p.get("ssh_name"), rtext))

        self._set_status("总览已刷新(数据为只读快照)")

    def _set_status(self, text):
        self._status_lbl.setText(text)


# ---------------- 右状态栏(监控点) ----------------
class RightBar(QFrame):
    # 展开/收起共用同一控件: 收起态仅隐藏 备注/延迟/设置, 布局与字体天然一致。
    ROW_H = 36   # 单元格行高固定: 收起态隐藏子标签后高度不变

    def __init__(self, on_toggle=None, on_settings=None, parent=None):
        super().__init__(parent)
        self.setObjectName("rightBar")
        self.setMinimumWidth(210)
        self.setMaximumWidth(280)
        self._compact = False
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)

        head = QHBoxLayout()
        t = QLabel("监控", objectName="rightTitle")
        # 同一个切换按钮: 展开态显示 »(收起), 收起态显示 «(展开)
        self._btn_toggle = QPushButton("»", objectName="collapseBtn")
        self._btn_toggle.setFixedSize(24, 22)
        self._btn_toggle.setToolTip("收起为窄条")
        if on_toggle:
            self._btn_toggle.clicked.connect(on_toggle)
        head.addWidget(t)
        head.addStretch(1)
        self._btn_settings = QPushButton(objectName="collapseBtn")
        icon = _svg_icon(_GEAR_SVG, 16)
        if icon is not None:
            self._btn_settings.setIcon(icon)
        else:
            self._btn_settings.setText("⚙")
        self._btn_settings.setFixedSize(24, 22)
        self._btn_settings.setToolTip("监控设置(端口/命名)")
        if on_settings:
            self._btn_settings.clicked.connect(on_settings)
        head.addWidget(self._btn_settings)
        head.addWidget(self._btn_toggle)
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
        wrap = QWidget()
        wrap.setFixedHeight(self.ROW_H)   # 行高固定(收起态隐藏标签后布局不变)
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
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
        self._content.addWidget(wrap)
        self._cells[key] = (dot, nm, detail, val)

    def set_state(self, key, ok, ms=-1):
        # 实时更新单元格状态: 圆点与数值配色(绿=在线/红=不可达)。
        # ms=None 表示只有 on/off 信息(如远程隧道), 显示 在线/不可达; ms>=0 显示延迟。
        cell = self._cells.get(key)
        if cell is None:
            return
        dot, nm, detail, val = cell
        color = "#43d17f" if ok else "#e5574d"
        dot.setStyleSheet("color:%s;" % color)
        if ms is None:
            val.setText("在线" if ok else "不可达")
        elif ok and ms >= 0:
            val.setText("%dms" % ms)
        else:
            val.setText("未就绪")
        val.setStyleSheet("color:%s;" % color)

    def set_compact(self, on):
        # 收起态 = 同一控件隐藏 备注/延迟/设置按钮; 切换按钮语义; 行高/字体不变。
        self._compact = on
        self._btn_settings.setVisible(not on)
        self._btn_toggle.setText("«" if on else "»")
        self._btn_toggle.setToolTip("展开状态栏" if on else "收起为窄条")
        self.setMinimumWidth(0 if on else 210)
        for dot, nm, detail, val in self._cells.values():
            detail.setVisible(not on)
            val.setVisible(not on)


class StatusPanel(QFrame):
    """右栏容器: RightBar 双态(展开/收起), 宽度动画; 收起 = 同一控件隐藏
    备注/延迟/设置, 布局与字体不变(不再有独立窄条)。"""

    def __init__(self, on_settings=None, parent=None):
        super().__init__(parent)
        self.setObjectName("statusPanel")
        self.setMinimumWidth(210)
        self.setMaximumWidth(280)
        self._collapsed = False
        self.right = RightBar(on_toggle=self._on_toggle, on_settings=on_settings)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.right)
        # min/max 同步动画: 布局按约束强制给宽, 动画期间宽度严格跟随(右锚定顺滑)
        self._anim_max = QPropertyAnimation(self, b"maximumWidth", self)
        self._anim_min = QPropertyAnimation(self, b"minimumWidth", self)
        for a in (self._anim_max, self._anim_min):
            a.setDuration(180)
            a.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_max.finished.connect(self._on_anim_done)
        self._target = None

    def _on_toggle(self):
        if self._collapsed:
            self.expand()
        else:
            self.collapse()

    def collapse(self):
        # 同一控件双态: 收起 = 隐藏元素 + 压缩宽度(动画全程无空白)
        self._target = "collapsed"
        self.right.set_compact(True)
        self._start_anim(100)

    def expand(self):
        self._target = "expanded"
        self.right.set_compact(False)
        self._start_anim(240)

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
            self.setMinimumWidth(100)
            self.setMaximumWidth(100)     # 钉死收起宽度
            self._collapsed = True
        elif self._target == "expanded":
            self.setMinimumWidth(210)
            self.setMaximumWidth(280)
            self._collapsed = False
        self._target = None

    def reload(self, cfg):
        # 热重载: 右栏按新配置重建(端口/命名)
        self.right.reload(cfg)



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
        if LOGO_PATH:
            self.setWindowIcon(QIcon(LOGO_PATH))   # 任务栏/Alt-Tab 图标(无边框窗口同样生效)
        self.resize(1160, 800)
        self.setMinimumSize(960, 620)
        self._normal_geo = None                # 最大化前几何(还原用)
        self._maxed = False                    # 自维护最大化状态(setGeometry 伪最大化)
        self._btn_max = None                   # 最大化按钮(图标切换 □/❐)
        # 平台窗口效果(Win11 22H2+ 分层透明; 失败自动回退纯 QSS)
        self._mica = apply_window_effects(self)
        # 系统级模糊(SetWindowCompositionAttribute, 经典方案); 失败则半透明无模糊
        self._sys_blur = try_system_blur(self) if self._mica else False
        # 自定义主题(config.json["theme"])先激活再生成样式表; 运行中经 apply_theme 实时换肤
        self._custom_theme = bool(CONFIG.get("theme"))
        dsh_theme.set_active(CONFIG.get("theme") or {})
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
        # 全局命令面板(Ctrl+K): 页面/部署/动作键盘直达(OTP 式)
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
                self.loge("模糊: %s" % ("系统级(ACCENT_ENABLE_BLURBEHIND)" if self._sys_blur
                                        else "系统级失败, 半透明无模糊"), "ok")

    # ---- 主题(主题引擎 ui/theme.py, token 驱动; 主题页经 apply_theme 实时换肤) ----
    def _load_theme(self):
        #   Mica 可用(Win11 22H2+) -> 生成半透明 QSS(外部 theme.qss 不参与, 避免盖住 DWM 背景);
        #   有自定义主题(config["theme"] / 运行中 apply_theme) -> 由 TOKENS 实时生成
        #   (外部 theme.qss 是出厂色产物, 会盖掉覆盖);
        #   否则 -> 外部 ui/theme.qss 优先(手动微调), 缺失回退生成的不透明 QSS。
        if self._mica:
            return build_qss(mica=True)
        if self._custom_theme:
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
        # 实时换肤: 原地更新 TOKENS -> 重新生成 QSS setStyleSheet。Qt 立即重抛光全部
        # 控件; 自绘 delegate(逐帧读 TOKENS)随全局重绘生效, 无需重启。
        # 透明度属 rgba token, 仅亚克力(Mica)模式有可见效果。overrides=None 只重建样式。
        dsh_theme.set_active(overrides or {})
        self._custom_theme = self._custom_theme or bool(overrides)
        self.setStyleSheet(build_qss(mica=self._mica))
        if note:
            self.loge(note, "ok")

    # ---- 顶部栏 ----
    def _build_topbar(self):
        bar = _TopBar(self)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(10)

        # Logo(自绘标题栏左侧; 按 DPI 缩放保证高分屏清晰, 资源缺失时隐藏降级)
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
        sep = QFrame(objectName="vsep"); sep.setFixedWidth(1)
        dlab = QLabel("部署:")
        self.deploy = QComboBox(objectName="deploy")
        self.deploy.currentIndexChanged.connect(self._on_deploy_changed)
        poll = QLabel(" 轮询 4s·20s", objectName="verLbl")

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        refresh = QPushButton("立即刷新")
        refresh.clicked.connect(self._force_refresh)
        search = QPushButton("搜索")
        search.setToolTip("命令面板: 搜索页面/部署/动作 (Ctrl+K)")
        search.clicked.connect(self._open_palette)
        env = QPushButton("环境")
        env.clicked.connect(self._open_env)
        install = QPushButton("安装")
        install.clicked.connect(self._open_install)

        for w in (logo, title, ver, sep, dlab, self.deploy, poll):
            lay.addWidget(w)
        lay.addWidget(spacer)
        lay.addWidget(search)
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

    # ---- 顶栏入口(命令面板/环境检查/安装向导) ----
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
        # 左导航选中随页面同步(命令面板/部署切换等编程跳转也一致); 断信号防回环
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
            # 兜底(正常不可达: 16 个导航 key 全部有真实页面)
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
        # 命令面板: 打开时组装(页面随 NAV_ITEMS / 部署随当前清单, 无需注册表);
        # run 在面板 accept 后执行(见 CommandPalette._run_item)。
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
        # P1 弹窗收敛: 右栏 ⚙ -> 设置页"监控与命名"标签(不再弹模态)
        self._pending_settings_tab = "monitor"
        self._show_page("settings")

    def reload_config(self):
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
    if "--diag-config" in sys.argv:
        # 配置诊断(打包调试用): 打印实际生效的解析链路。只输出键名/计数, 不输出值(防真实 IP 入日志)。
        from core import config as dsh_config
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
        import inspect
        print("core.config.__file__ =", getattr(dsh_config, "__file__", "?"))
        print("---- 实际运行的 load_config 源码 ----")
        try:
            print(inspect.getsource(dsh_config.load_config))
        except Exception as e:
            print("(getsource 失败:", e, ")")
        import dis
        print("---- co_consts / co_names ----")
        print("consts =", dsh_config.load_config.__code__.co_consts)
        print("names =", dsh_config.load_config.__code__.co_names)
        der = dsh_config.load_derived(None)
        print("derived dash_port =", der.get("dash_port"))
        print("derived local_ports =", der.get("local_ports"))
        return 0
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
        self._status_lbl = QLabel("就绪", objectName="monVal")
        head = QHBoxLayout()
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self._status_lbl)
        v.addLayout(head)

        # 隧道方案(规划器): 拓扑字段的命名快照, 应用=写回标准字段并热重载;
        # 字段编辑仍走设置页端口表(唯一编辑器), 这里负责 校验/切换/自检
        plan_card = QFrame(objectName="card")
        pv = QVBoxLayout(plan_card)
        pv.setContentsMargins(16, 12, 16, 12)
        pv.setSpacing(6)
        prow = QHBoxLayout()
        prow.addWidget(QLabel("隧道方案", objectName="rightTitle"))
        self._plan_combo = QComboBox()
        self._plan_combo.setMinimumWidth(170)
        self._plan_combo.currentIndexChanged.connect(self._plan_selected)
        prow.addWidget(self._plan_combo)
        for text, fn in (("应用", self._plan_apply), ("存当前为方案", self._plan_save),
                         ("重命名", self._plan_rename), ("删除", self._plan_del),
                         ("校验", self._plan_validate), ("启动自检", self._plan_selfcheck)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            prow.addWidget(b)
        prow.addStretch(1)
        pv.addLayout(prow)
        self._plan_out = QLabel("选择方案后「应用」切换拓扑(自动 .bak + 热重载); "
                                "改端口/加映射请到 设置 页的端口表。", objectName="cardHint")
        self._plan_out.setWordWrap(True)
        pv.addWidget(self._plan_out)
        v.addWidget(plan_card)

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
        self._plan_refresh()

    # ── 隧道方案(规划器): 拓扑字段的命名快照, 应用=写回标准字段+热重载 ──
    def _plan_refresh(self, select=None):
        cfg = _load_config()
        plans = dsh_planner.load_plans(cfg)
        self._plan_combo.blockSignals(True)
        self._plan_combo.clear()
        for p in plans:
            self._plan_combo.addItem(p.get("name"), p)
        cur = select or cfg.get("tunnel_plans_active") or ""
        idx = next((i for i in range(self._plan_combo.count())
                    if self._plan_combo.itemText(i) == cur), 0)
        if self._plan_combo.count():
            self._plan_combo.setCurrentIndex(idx)
        self._plan_combo.blockSignals(False)

    def _selected_plan(self):
        return self._plan_combo.currentData()

    @staticmethod
    def _plan_summary(p):
        return "中继转发: %s | 反向端口: %s | 实验室端口: %s" % (
            ", ".join(str(x) for x in (p.get("forward_ports") or [])) or "无",
            p.get("reverse_port") or "无", p.get("lab_port") or "无")

    def _plan_selected(self, _idx):
        p = self._selected_plan()
        if p:
            self._plan_out.setText(self._plan_summary(p) + " —— 点「应用」生效")

    def _set_plan_out(self, text, err=False):
        self._plan_out.setText(text)
        self._plan_out.setStyleSheet("color: %s;" % ("#e07a7a" if err else "#7ecb6a"))

    def _plan_apply(self):
        p = self._selected_plan()
        if not p:
            self._set_plan_out("先在方案列表中选择一个方案", err=True)
            return
        ret = QMessageBox.question(
            self, "应用方案",
            "将把方案「%s」的端口拓扑写入 config.json(自动 .bak)并热重载。\n"
            "正在运行的隧道不受影响, 新配置在下次启动隧道时生效。继续?" % p["name"])
        if ret != QMessageBox.StandardButton.Yes:
            return
        cfg = dsh_planner.apply_plan(_load_config(), p)
        if not dsh_config.save_config(cfg):
            self._set_plan_out("应用失败: config.json 写入失败(可能被占用)", err=True)
            return
        self.app.reload_config()
        self._plan_refresh(select=p["name"])
        self._set_plan_out("已应用方案「%s」(新端口在下次启动隧道时生效)" % p["name"])

    def _plan_save(self):
        cfg = _load_config()
        default = "方案 %d" % (len(dsh_planner.load_plans(cfg)) + 1)
        name, ok = QInputDialog.getText(self, "存当前为方案", "方案名:", text=default)
        if not ok or not name.strip():
            return
        name = name.strip()
        cfg = dsh_planner.upsert_plan(cfg, dsh_planner.snapshot_plan(cfg, name))
        if not dsh_config.save_config(cfg):
            self._set_plan_out("保存失败: config.json 写入失败(可能被占用)", err=True)
            return
        self._plan_refresh(select=name)
        self._set_plan_out("已保存方案: " + name + " —— " + self._plan_summary(
            dsh_planner.find_plan(cfg, name) or {}))

    def _plan_rename(self):
        p = self._selected_plan()
        if not p:
            self._set_plan_out("先选择要重命名的方案", err=True)
            return
        name, ok = QInputDialog.getText(self, "重命名方案", "新方案名:", text=p["name"])
        if not ok or not name.strip() or name.strip() == p["name"]:
            return
        name = name.strip()
        cfg = dsh_planner.delete_plan(_load_config(), p["name"])
        cfg = dsh_planner.upsert_plan(cfg, dict(p, name=name))
        if cfg.get("tunnel_plans_active") == p["name"]:
            cfg["tunnel_plans_active"] = name
        if not dsh_config.save_config(cfg):
            self._set_plan_out("重命名失败: 写入失败(可能被占用)", err=True)
            return
        self._plan_refresh(select=name)
        self._set_plan_out("已重命名为: " + name)

    def _plan_del(self):
        p = self._selected_plan()
        if not p:
            self._set_plan_out("先选择要删除的方案", err=True)
            return
        ret = QMessageBox.question(self, "删除方案",
                                   "将删除方案「%s」(不影响当前配置与运行中隧道)。继续?" % p["name"])
        if ret != QMessageBox.StandardButton.Yes:
            return
        cfg = dsh_planner.delete_plan(_load_config(), p["name"])
        if not dsh_config.save_config(cfg):
            self._set_plan_out("删除失败: 写入失败(可能被占用)", err=True)
            return
        self._plan_refresh()
        self._set_plan_out("已删除方案: " + p["name"])

    def _plan_validate(self):
        p = self._selected_plan()
        if not p:
            self._set_plan_out("先选择要校验的方案", err=True)
            return
        issues = dsh_planner.validate_plan(p, _load_config())
        if not issues:
            self._set_plan_out("校验通过: 「%s」未发现问题" % p["name"])
            self.app.loge("[隧道] 方案校验通过: " + p["name"], "ok")
            return
        errs = [i for i in issues if i["level"] == "error"]
        text = "校验「%s」: %d 错误 / %d 警告 — %s" % (
            p["name"], len(errs), len(issues) - len(errs),
            " ; ".join(i["msg"] for i in issues))
        self._set_plan_out(text, err=bool(errs))
        self.app.loge("[隧道] 方案校验: %d 错误 / %d 警告" % (len(errs), len(issues) - len(errs)),
                      "err" if errs else "warn")

    def _plan_selfcheck(self):
        rows = dsh_planner.self_check(_load_config(), BASE_DIR)
        text = " | ".join("%s: %s(%s)" % (n, "未配置" if s is None else ("通" if s else "不通"), d)
                          for n, s, d in rows)
        ok = all(s is not False for _, s, _ in rows)
        self._set_plan_out("自检 — " + text, err=not ok)
        self.app.loge("[隧道] 启动自检: " + ("全部通过" if ok else "存在不通项"), "ok" if ok else "warn")

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
