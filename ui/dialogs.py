# -*- coding: utf-8 -*-
# dsh-console-aio PySide6 迁移: 配置向导 / 安装向导 / 环境检查 三个 QDialog。
# 阶段3 分层: 子进程业务全部下沉 core/env.py 与 core/config.py(纯 Python 可单测),
# 本模块只保留 UI/表单校验/内容配置表(TEMPLATES/OPS)与线程调度。线程约定: 对话框自有
# 后台线程只调 core 函数(不碰子进程细节), 经类级 Signal + safe_emit 回主线程更新控件;
# 有主窗口(service 可用)时 EnvDialog 工具命令走 service.run_cmd 流式进主日志。
# 子进程细节(CREATE_NO_WINDOW/text=errors=/超时)统一在 core/env.py(AGENTS.md 约定)。

import json
import os
import shutil
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from core import env as core_env

# 配置文件在本包上一级(仓库根目录); 对话框读它做表单回填(写回业务在 core.config)。
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(_BASE_DIR, "config.json")


def _resolve_app(app, parent):
    # app 显式传入优先; 否则 parent 若是主窗口(有 loge)则复用; 兼容 None。
    if app is not None:
        return app
    if parent is not None and hasattr(parent, "loge"):
        return parent
    return None


def _load_config():
    # 读 config.json; 缺失/损坏返回 {} (防御模式, 缺 key 不崩)。
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        pass
    return {}


class _DialogBase(QDialog):
    # QDialog 公共基类: 提供与 BasePage.safe_emit 一致的线程安全发射。
    # 对话框销毁后对已删 QObject emit 会抛 RuntimeError, 吞掉防后台线程崩溃。
    def safe_emit(self, sig, *args):
        try:
            sig.emit(*args)
        except RuntimeError:
            pass


class ConfigDialog(_DialogBase):
    # 配置向导: 分组 + 场景模板 + SSH 测试 + 完整隧道参数编辑。
    # 保存后 self.result 持有用户改动字段(dict), 由上层合并写回 config.json。

    _ssh_done = Signal(str, bool)   # (结果文案, 是否成功)

    HELP = {
        "ssh_server": "公网可达的中转服务器 IP/域名(需已配置免密 SSH 登录)",
        "ssh_user": "中转服务器上用于建隧道的用户名(需已配置免密)",
        "ssh_port": "SSH 连接端口(仅用于测试, 默认 22)",
        "dash_repo": "本机 dsh 仓库绝对路径, 如 D:/Applications/deepseek-harness",
        "dash_port": "本机 dsh GUI 端口(默认 3080)",
        "dash_cmd": "启动命令(空格分隔): pnpm.cmd dsh web",
        "forward_ports": "在家正向隧道本机端口, 逗号分隔: 8090,8022,8091",
        "lab_server": "实验室服务器 IP(局域网直连用)",
        "lab_user": "实验室服务器 SSH 用户名",
        "lab_port": "实验室 dsh 本机映射端口(默认 3090)",
        "reverse_port": "本机 dsh 暴露到中继的端口(公网服务器:端口 → 本机)",
        "poll_seconds": "本机健康检查间隔(秒)",
        "remote_poll_seconds": "SSH 直查中继监听状态的间隔(秒)",
    }

    TEMPLATES = {
        "在家→中继隧道": {"ssh_server": "YOUR_PUBLIC_IP", "ssh_user": "YOUR_USER",
                          "forward_ports": "8090,8022,8091", "reverse_port": "8091"},
        "实验室→直连实验室dsh": {"lab_server": "YOUR_LAB_IP", "lab_user": "YOUR_USER",
                           "lab_port": "3090"},
        "本机→中继反向": {"reverse_port": "8091"},
    }

    LABELS = {
        "ssh_server": "服务器 IP/域名", "ssh_user": "用户名", "ssh_port": "SSH 端口",
        "dash_repo": "仓库路径", "dash_port": "端口", "dash_cmd": "启动命令",
        "forward_ports": "在家正向端口", "lab_server": "实验室 IP",
        "lab_user": "实验室用户", "lab_port": "实验室映射端口",
        "reverse_port": "反向端口", "poll_seconds": "本机轮询(秒)",
        "remote_poll_seconds": "远端轮询(秒)",
    }

    def __init__(self, cfg, parent=None, app=None):
        super().__init__(parent)
        self.app = _resolve_app(app, parent)
        self.setWindowTitle("隧道配置向导")
        self.result = None
        self._cfg = cfg if isinstance(cfg, dict) else {}
        self._vars = {}
        self._build()
        self._ssh_done.connect(self._on_ssh_done)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(15, 12, 15, 12)
        root.setSpacing(8)

        root.addWidget(QLabel("场景模板 (一键填充, 把占位符改成真实 IP/用户名)"))
        tpl_row = QHBoxLayout()
        for name in list(self.TEMPLATES) + ["自定义"]:
            btn = QPushButton(name)
            btn.clicked.connect(lambda _=False, n=name: self._apply(n))
            tpl_row.addWidget(btn)
        tpl_row.addStretch(1)
        root.addLayout(tpl_row)

        form = QFormLayout()
        self._form = form
        self._sec("① 公网中转服务器")
        self._field("ssh_server", None)
        self._field("ssh_user", None)
        self._field("ssh_port", "22")
        self._test_btn = QPushButton("测试 SSH 连接")
        self._test_btn.clicked.connect(self._test_ssh)
        self._test_lbl = QLabel("")
        self._test_lbl.setWordWrap(True)
        form.addRow(self._test_btn, self._test_lbl)
        self._sec("② 本机 dsh")
        self._field("dash_repo", None)
        self._field("dash_port", None)
        self._field("dash_cmd", None)
        self._sec("③ 隧道参数")
        self._field("forward_ports", None)
        self._field("lab_server", None)
        self._field("lab_user", None)
        self._field("lab_port", None)
        self._field("reverse_port", None)
        self._sec("④ 轮询与超时")
        self._field("poll_seconds", None)
        self._field("remote_poll_seconds", None)
        root.addLayout(form)

        bbox = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bbox.button(QDialogButtonBox.Save).setText("保存")
        bbox.button(QDialogButtonBox.Cancel).setText("取消")
        bbox.accepted.connect(self._on_save)
        bbox.rejected.connect(self.reject)
        root.addWidget(bbox)
        self.resize(560, 660)

    def _sec(self, title):
        # 分组标题(跨整行显示, 与旧版 ① ② ③ ④ 分段一致)。
        lbl = QLabel(title)
        lbl.setStyleSheet("font-weight: bold; color: #0af;")
        self._form.addRow(lbl)

    def _field(self, key, placeholder):
        # 一个配置字段: QFormLayout 行, 帮助文本做成鼠标悬停 tooltip。
        label = QLabel(self.LABELS[key] + ":")
        default = self._cfg.get(key)
        if key == "dash_cmd" and isinstance(default, list):
            default = " ".join(default)
        if placeholder and default in (None, ""):
            default = placeholder
        edit = QLineEdit()
        edit.setText(str(default if default is not None else ""))
        label.setToolTip(self.HELP[key])
        edit.setToolTip(self.HELP[key])
        self._vars[key] = edit
        self._form.addRow(label, edit)

    def _apply(self, name):
        # 场景模板一键填充; 自定义/未知模板不动作。
        tpl = self.TEMPLATES.get(name)
        if not tpl:
            return
        for k, val in tpl.items():
            if k in self._vars:
                self._vars[k].setText(val)

    def _test_ssh(self):
        # SSH 测试: 后台线程调 core(免密/超时细节在 core.env), 信号回主线程更新标签。
        host = self._vars["ssh_server"].text().strip()
        user = self._vars["ssh_user"].text().strip()
        port = self._vars["ssh_port"].text().strip() or "22"
        if not host or not user:
            self._set_test("请先填服务器 IP 和用户名", False)
            return
        self._test_btn.setEnabled(False)
        self._set_test("测试中…", None)

        def worker():
            r = core_env.test_ssh(host, user, port)
            if r["err"]:
                msg, ok = "测试异常: " + r["err"], False
            elif r["ok"]:
                msg, ok = "✅ SSH 连接成功, 免密可用", True
            else:
                msg, ok = "❌ 失败 - 检查 IP/用户名/免密配置: " + r["detail"], False
            self.safe_emit(self._ssh_done, msg, ok)

        threading.Thread(target=worker, daemon=True).start()

    def _set_test(self, msg, ok):
        # 主线程更新测试结果标签: ok=None 灰色, True 绿, False 红。
        self._test_lbl.setText(msg)
        if ok is None:
            self._test_lbl.setStyleSheet("color: #888;")
        elif ok:
            self._test_lbl.setStyleSheet("color: #3c3;")
        else:
            self._test_lbl.setStyleSheet("color: #c33;")

    def _on_ssh_done(self, msg, ok):
        self._test_btn.setEnabled(True)
        self._set_test(msg, ok)

    def _on_save(self):
        # 收集用户改动字段(与旧版逐字段解析一致); 非法整数提示并不关闭。
        try:
            cfg = {}
            cfg["ssh_server"] = self._vars["ssh_server"].text().strip() or "YOUR_PUBLIC_IP"
            cfg["ssh_user"] = self._vars["ssh_user"].text().strip() or "tunnel"
            cfg["dash_repo"] = self._vars["dash_repo"].text().strip()
            cfg["dash_port"] = int(self._vars["dash_port"].text().strip())
            cfg["dash_cmd"] = self._vars["dash_cmd"].text().strip().split()
            # forward_ports 支持 "8090,8022,8091" 或 "[8090, 8022, 8091]" 两种写法
            _fp_raw = self._vars["forward_ports"].text().strip().strip("[]").replace(" ", "")
            cfg["forward_ports"] = [int(x) for x in _fp_raw.split(",") if x]
            cfg["poll_seconds"] = int(self._vars["poll_seconds"].text().strip())
            cfg["remote_poll_seconds"] = int(self._vars["remote_poll_seconds"].text().strip())
            cfg["lab_server"] = self._vars["lab_server"].text().strip()
            cfg["lab_user"] = self._vars["lab_user"].text().strip()
            lp = self._vars["lab_port"].text().strip()
            cfg["lab_port"] = int(lp) if lp else int(self._cfg.get("lab_port", 3090))
            rp = self._vars["reverse_port"].text().strip()
            cfg["reverse_port"] = int(rp) if rp else int(self._cfg.get("reverse_port", 8091))
        except ValueError:
            QMessageBox.critical(self, "输入错误", "端口/轮询间隔/端口列表必须为整数.")
            return
        self.result = cfg
        self.accept()


class InstallDialog(_DialogBase):
    # 安装向导: 环境预检 -> git clone -> pnpm install -> pnpm build -> 写 config。
    # 安装命令在后台线程执行, 逐行经信号回主线程更新进度/日志。

    DEFAULT_URL = "https://github.com/deepseek-ai/deepseek-harness.git"

    _env_done = Signal(str)            # 环境预检结果文本
    _step = Signal(int, str)           # (进度值, 步骤文案)
    _line = Signal(str)                # 流式日志行
    _done = Signal(bool, str)          # (是否成功, 结果文案)

    def __init__(self, parent=None, app=None):
        super().__init__(parent)
        self.app = _resolve_app(app, parent)
        self.setWindowTitle("安装 dsh")
        self.result = None
        self._url = QLineEdit(self.DEFAULT_URL)
        self._dir = QLineEdit()
        self._build()
        self._env_done.connect(self._on_env_done)
        self._step.connect(self._on_step)
        self._line.connect(self._on_line)
        self._done.connect(self._on_done)
        self._check_env()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(15, 12, 15, 12)
        root.setSpacing(8)

        title = QLabel("一键安装本机 dsh（无需求会提前提示）")
        title.setStyleSheet("font-weight: bold;")
        root.addWidget(title)

        root.addWidget(QLabel("dsh 仓库地址（git 克隆源）:"))
        root.addWidget(self._url)
        hint1 = QLabel("默认使用官方 deepseek-harness，可改成你自己的仓库。")
        hint1.setStyleSheet("color: #888;")
        root.addWidget(hint1)

        root.addWidget(QLabel("安装到的目标目录（如 C:/Users/你的名字/dsh）:"))
        drow = QHBoxLayout()
        drow.addWidget(self._dir, 1)
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse_dir)
        drow.addWidget(browse)
        root.addLayout(drow)
        hint2 = QLabel("留空则默认安装到用户主目录下的 dsh 文件夹。")
        hint2.setStyleSheet("color: #888;")
        root.addWidget(hint2)

        env_title = QLabel("环境预检:")
        env_title.setStyleSheet("font-weight: bold;")
        root.addWidget(env_title)
        self._env_lbl = QLabel("检查中…")
        self._env_lbl.setWordWrap(True)
        root.addWidget(self._env_lbl)

        step_title = QLabel("安装进度:")
        step_title.setStyleSheet("font-weight: bold;")
        root.addWidget(step_title)
        self._step_lbl = QLabel("未开始")
        root.addWidget(self._step_lbl)
        self._bar = QProgressBar()
        self._bar.setRange(0, 4)
        self._bar.setValue(0)
        root.addWidget(self._bar)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(500)
        root.addWidget(self._log, 1)

        btns = QHBoxLayout()
        self._start_btn = QPushButton("开始安装")
        self._start_btn.clicked.connect(self._start)
        self._cancel_btn = QPushButton("取消")
        self._cancel_btn.clicked.connect(self.reject)
        btns.addWidget(self._start_btn)
        btns.addWidget(self._cancel_btn)
        btns.addStretch(1)
        root.addLayout(btns)
        self.resize(620, 520)

    def _check_env(self):
        # 异步检查 git / node / npm / pnpm 是否可用(旧 InstallDialog 逻辑照搬)。
        def worker():
            lines = []
            for tool in ("git", "node", "npm", "pnpm"):
                path = shutil.which(tool)
                status = "OK" if path else "缺失"
                lines.append("  %-5s: %s" % (tool, status) + ("  (%s)" % path if path else ""))
            text = "\n".join(lines)
            missing = [l.split(":")[0].strip() for l in lines if "缺失" in l]
            if missing:
                text += "\n\n⚠ 缺少: " + ", ".join(missing) + "  — 请先安装后再安装 dsh。"
            self.safe_emit(self._env_done, text)
        threading.Thread(target=worker, daemon=True).start()

    def _on_env_done(self, text):
        self._env_lbl.setText(text)

    def _browse_dir(self):
        start = self._dir.text().strip() or os.path.expanduser("~")
        chosen = QFileDialog.getExistingDirectory(self, "选择 dsh 安装目录", start)
        if chosen:
            self._dir.setText(chosen)

    def _start(self):
        # 校验输入后后台线程跑安装: 业务全在 core.env.install_dsh(预检/clone/install/
        # build/写 config), 本线程只把 events 转成对话框信号(step/line), 完成经 _done 收尾。
        url = self._url.text().strip()
        target = self._dir.text().strip()
        if not url:
            QMessageBox.critical(self, "缺少仓库地址", "请填写 dsh 的 git 仓库地址。")
            return
        # target 默认: 用户主目录/dsh
        target = target or os.path.join(os.path.expanduser("~"), "dsh")
        self._set_running(True)
        self._bar.setValue(0)
        self._step_lbl.setText("正在安装…")
        self._log.clear()

        def events(kind, payload):
            if kind == "log":
                self.safe_emit(self._line, payload)
            elif kind == "step":
                self.safe_emit(self._step, payload[0], payload[1])

        def worker():
            r = core_env.install_dsh(events, url, target)
            self.safe_emit(self._done, not r["err"], r["err"] or r["msg"])

        threading.Thread(target=worker, daemon=True).start()

    def _on_step(self, step, text):
        self._bar.setValue(step)
        self._step_lbl.setText(text)

    def _on_line(self, text):
        self._log.appendPlainText(text)
        sb = self._log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_done(self, ok, msg):
        self._set_running(False)
        if ok:
            self._bar.setValue(4)
            self._step_lbl.setText("完成")
            self.result = (self._url.text().strip(),
                           self._dir.text().strip() or os.path.join(os.path.expanduser("~"), "dsh"))
            QMessageBox.information(self, "安装完成", msg)
            self.accept()
        else:
            self._step_lbl.setText("安装失败")
            QMessageBox.warning(self, "安装失败", msg)

    def _set_running(self, on):
        self._start_btn.setEnabled(not on)
        self._cancel_btn.setEnabled(not on)
        self._url.setEnabled(not on)
        self._dir.setEnabled(not on)


class EnvDialog(_DialogBase):
    # 独立"环境检查"窗口: 展示 git/node/npm/pnpm 版本与推荐基准,
    # 提供 更新/安装/卸载 操作(点击确认后执行)。

    TOOLS = [
        ("git",  "git",  ["git", "--version"]),
        ("node", "node", ["node", "--version"]),
        ("npm",  "npm",  ["npm.cmd", "--version"]),
        ("pnpm", "pnpm", ["pnpm.cmd", "--version"]),
    ]
    # 推荐基准版本(作者开发机实测可跑 dsh 的版本)
    RECOMMENDED = {
        "git":  "2.53",
        "node": "v24.19",
        "npm":  "11.17",
        "pnpm": "11.7",
    }
    # 每个工具的操作定义:
    #   install/uninstall: 安装/卸载引导
    #   update: 更新操作(可多条)
    #   每条: (类型, 内容, 描述)
    #   类型: cmd=执行命令 / browser=打开网页 / page=打开设置页 / hint=仅提示
    OPS = {
        "git": dict(
            name="Git",
            install=[("browser", "https://git-scm.com/download/win", "打开官网下载 Git 安装包")],
            update=[("cmd", ["git", "update-git-for-windows"], "运行 Git 自带升级器 (git update-git-for-windows)")],
            uninstall=[("page", "ms-settings:appsfeatures", "打开 Windows 设置 - 应用 - 安装的应用，找到 Git 卸载")],
        ),
        "node": dict(
            name="Node.js",
            install=[("browser", "https://nodejs.org/zh-cn/download", "打开官网下载 Node.js LTS 安装包")],
            update=[("hint", "Node.js 无官方自升级命令。\n建议用 nvm-windows 管理版本, 或到官网 https://nodejs.org 下载新版安装包。")],
            uninstall=[("page", "ms-settings:appsfeatures", "打开 Windows 设置 - 应用 - 安装的应用，找到 Node.js 卸载")],
        ),
        "npm": dict(
            name="npm",
            install=[("hint", "npm 随 Node.js 一起安装, 装好 Node.js 即自带 npm。")],
            update=[("cmd", ["npm.cmd", "install", "-g", "npm@latest"], "npm install -g npm@latest")],
            uninstall=[("cmd", ["npm.cmd", "uninstall", "-g", "npm"], "npm uninstall -g npm（移除 npm 自身，Node.js 保留）")],
        ),
        "pnpm": dict(
            name="pnpm",
            install=[("cmd", ["npm.cmd", "install", "-g", "pnpm"], "npm install -g pnpm")],
            update=[("cmd", ["pnpm.cmd", "self-update"], "pnpm self-update（官方推荐的 pnpm 更新方式）")],
            uninstall=[("cmd", ["npm.cmd", "uninstall", "-g", "pnpm"], "npm uninstall -g pnpm（卸载全局 pnpm 包）")],
        ),
    }

    _env_done = Signal(object)           # dict: key -> 版本行(None=未安装)
    _cmd_result = Signal(str, bool, str)  # (描述, 成功, 尾部输出)

    def __init__(self, parent=None, app=None):
        super().__init__(parent)
        self.app = _resolve_app(app, parent)
        self.setWindowTitle("环境检查")
        self._rows = {}
        self._cmd_desc = ""
        self._build()
        self._env_done.connect(self._apply)
        self._cmd_result.connect(self._show_cmd_result)
        # 有主窗口时工具命令走 service.run_cmd(逐行进主日志), finished 回本对话框收尾;
        # 接收者=本对话框, 关闭时 Qt 自动断开。
        service = getattr(self.app, "service", None) if self.app is not None else None
        if service is not None:
            service.finished.connect(self._on_env_cmd_finished)
        self._refresh()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(15, 12, 15, 12)
        root.setSpacing(8)

        title = QLabel("开发环境检查（git / node / npm / pnpm）")
        title.setStyleSheet("font-weight: bold;")
        root.addWidget(title)

        table = QTableWidget(len(self.TOOLS), 5)
        table.setHorizontalHeaderLabels(["工具", "当前版本", "推荐基准", "状态", "操作"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)
        hh = table.horizontalHeader()
        for col in (0, 1, 2, 3):
            hh.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        act = {"update": "更新", "install": "安装", "uninstall": "卸载"}
        for i, (key, name, _cmd) in enumerate(self.TOOLS):
            table.setItem(i, 0, QTableWidgetItem(name))
            ver_item = QTableWidgetItem("...")
            table.setItem(i, 1, ver_item)
            table.setItem(i, 2, QTableWidgetItem(self.RECOMMENDED.get(key, "")))
            st_item = QTableWidgetItem("")
            table.setItem(i, 3, st_item)
            ops = QHBoxLayout()
            ops.setContentsMargins(0, 0, 0, 0)
            for text, kind in (("更新", "update"), ("安装", "install"), ("卸载", "uninstall")):
                b = QPushButton(text)
                b.clicked.connect(lambda _=False, k=key, kd=kind: self._do_action(k, kd, act[kd]))
                ops.addWidget(b)
            ops.addStretch(1)
            holder = QWidget()
            holder.setLayout(ops)
            table.setCellWidget(i, 4, holder)
            self._rows[key] = (ver_item, st_item)
        root.addWidget(table, 1)

        hint = QLabel("点“更新/安装/卸载”会先说明将执行什么, 确认后才执行。")
        hint.setStyleSheet("color: #888;")
        root.addWidget(hint)

        btns = QHBoxLayout()
        btns.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.reject)
        btns.addWidget(close_btn)
        root.addLayout(btns)
        self.resize(720, 400)

    def _get_version(self, cmd):
        # 版本探测在 core(env.get_version): 命令缺失/超时返回 None
        return core_env.get_version(cmd)

    def _refresh(self):
        # 后台线程顺序跑版本命令(core), 结果经信号回主线程填表。
        def worker():
            res = core_env.tool_versions(self.TOOLS)
            self.safe_emit(self._env_done, res)
        threading.Thread(target=worker, daemon=True).start()

    def _apply(self, res):
        for key, (ver_item, st_item) in self._rows.items():
            v = res.get(key)
            if v is None:
                ver_item.setText("未安装")
                ver_item.setForeground(Qt.red)
                st_item.setText("缺失")
                st_item.setForeground(Qt.red)
            else:
                ver_item.setText(v)
                ver_item.setForeground(Qt.black)
                st_item.setText("OK")
                st_item.setForeground(Qt.darkGreen)

    def _do_action(self, key, kind, label):
        # 每个动作先确认将执行什么, 确认后才执行(危险操作确认约定)。
        ops = self.OPS.get(key)
        if ops is None:
            return
        name = ops["name"]
        plan = ops.get(kind) or []
        if not plan:
            return
        for typ, payload, desc in plan:
            if QMessageBox.question(
                    self, label + " " + name,
                    "将执行：\n" + desc + "\n\n是否继续？") != QMessageBox.Yes:
                return
            if typ == "cmd":
                self._run_cmd(payload, desc)
            elif typ == "browser":
                self._open_url(payload)
            elif typ == "page":
                self._open_apps_page()
            elif typ == "hint":
                QMessageBox.information(self, label + " " + name, payload)

    def _run_cmd(self, cmd, desc):
        # 有主窗口(service 可用): service.run_cmd 流式执行, 逐行进主日志, finished 回本对话框;
        # 无主界面(独立窗口场景): 对话框线程内 core.run_capture 捕获兜底。
        app = self.app
        if app is not None and getattr(app, "service", None) is not None:
            env = core_env.pnpm_env() if cmd and str(cmd[0]).lower().startswith("pnpm") else None
            self._cmd_desc = desc
            app.loge("[环境] " + desc + " 开始执行...", "warn")
            app.service.run_cmd(cmd, env=env, op="env-tool")
            return

        def worker():
            ok, tail = core_env.run_capture(cmd)
            self.safe_emit(self._cmd_result, desc, ok, tail)

        threading.Thread(target=worker, daemon=True).start()

    def _on_env_cmd_finished(self, op, ok):
        # service.run_cmd 只发 finished(无 result): 逐行输出已进主日志区, 这里收尾弹窗。
        if op != "env-tool":
            return
        self._show_cmd_result(self._cmd_desc, ok, "详见主界面日志区")

    def _show_cmd_result(self, desc, ok, tail):
        body = "已" + ("完成" if ok else "失败")
        if tail:
            body += "\n\n" + tail
        if ok:
            QMessageBox.information(self, "结果: " + desc, body)
        else:
            QMessageBox.warning(self, "结果: " + desc, body)

    def _open_url(self, url):
        try:
            os.startfile(url)
        except Exception as e:
            QMessageBox.critical(self, "无法打开", str(e))

    def _open_apps_page(self):
        try:
            os.startfile("ms-settings:appsfeatures")
        except Exception as e:
            QMessageBox.critical(self, "无法打开", str(e))
