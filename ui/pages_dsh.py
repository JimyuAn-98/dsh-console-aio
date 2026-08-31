# -*- coding: utf-8 -*-
# DSH 管理页: 本机 dsh 操控(启动/重启/停止) + 完整更新 + 环境/安装 + 版本信息
# (本机 package.json vs GitHub deepseek-ai/deepseek-harness tags)。
# 由隧道页(dsh-web/update-dsh 两卡)与顶栏(环境/安装按钮)收敛而来 —— dsh 域操作集中
# 一页, 隧道页回归纯隧道。卡片在线状态经 service.card 信号(接收者=本页, 销毁自动断开)。
#
# 弹窗收敛(小菜②): 原 EnvDialog / InstallDialog 两个模态弹窗退役, 环境检查与安装向导
# 改为本页「页面内分步」(step in place, 愿景 §二.5)。业务全在 core/env.py(纯 Python):
#   环境检查 = core_env.tool_versions / 安装 = core_env.install_dsh(events 回调)。
# 后台线程只调 core 函数, 经类级 Signal + safe_emit 回主线程更新控件(AGENTS 线程约定);
# tags 拉取走页面线程 + safe_emit(同范式)。无真实远程写。

import json
import os
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton, QMessageBox,
    QTextEdit, QLineEdit, QProgressBar, QPlainTextEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QWidget, QFileDialog, QScrollArea)

from core import config as dsh_config
from core import env as core_env
from ui.base import BasePage
from ui.theme import TOKENS

_GH_TAGS_URL = "https://github.com/deepseek-ai/deepseek-harness/tags"

# 环境检查工具定义(版本命令 + 推荐基准 + 操作表; 与退役的 EnvDialog 同源)
TOOLS = [
    ("git",  "git",  ["git", "--version"]),
    ("node", "node", ["node", "--version"]),
    ("npm",  "npm",  ["npm.cmd", "--version"]),
    ("pnpm", "pnpm", ["pnpm.cmd", "--version"]),
]
RECOMMENDED = {
    "git":  "2.53", "node": "v24.19", "npm": "11.17", "pnpm": "11.7",
}
# 每个工具 更新/安装/卸载 的动作(类型: cmd=执行命令 / browser=开网页 / page=开设置页 /
# hint=仅提示); 危险操作确认后再执行。
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


class DshManagePage(BasePage):
    # DSH 管理: BasePage 范式, app 为 MainWindow。仅本机操作; 更新有确认, 无远程写。
    _tags_done = Signal(list, str)     # (tag 名称列表, 错误文案) 后台线程 -> UI
    _env_done = Signal(dict)           # 工具版本 dict -> UI(填环境检查表)
    _install_step = Signal(int, str)   # 安装进度 (n, 文案)
    _install_line = Signal(str)        # 安装流式日志行
    _install_done = Signal(bool, str)  # (是否成功, 结果文案)
    _uninstall_step = Signal(int, str)  # 卸载进度 (n, 文案)
    _uninstall_line = Signal(str)       # 卸载流式日志行
    _uninstall_done = Signal(bool, str)  # (是否成功, 结果文案)

    def __init__(self, app, parent=None):
        self._cards = {}               # key -> 状态圆点(仅 dsh-web 有)
        self.env_rows = {}             # 环境检查表: key -> (版本, 状态) item
        self._inst_running = False
        self._uninst_running = False
        super().__init__(app, parent)
        self.app.service.card.connect(self._apply_card)
        self._tags_done.connect(self._on_tags)
        self._env_done.connect(self._apply_env)
        self._install_step.connect(self._on_install_step)
        self._install_line.connect(self._on_install_line)
        self._install_done.connect(self._on_install_done)
        self._uninstall_step.connect(self._on_uninstall_step)
        self._uninstall_line.connect(self._on_uninstall_line)
        self._uninstall_done.connect(self._on_uninstall_done)
        for key, on in self.app._card_state.items():
            self._set_card(key, on)
        self._fetch_tags()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 10)
        root.setSpacing(8)
        title = QLabel("DSH 管理", objectName="cardTitle")
        self._status_lbl = QLabel("就绪", objectName="monVal")
        head = QHBoxLayout()
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self._status_lbl)
        root.addLayout(head)

        content = QWidget()
        v = QVBoxLayout(content)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self._card_dsh(), 1)
        row.addWidget(self._card_update(), 1)
        v.addLayout(row)
        v.addWidget(self._card_version())
        v.addWidget(self._card_env_check())
        v.addWidget(self._card_install())
        v.addWidget(self._card_uninstall())
        v.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

    # ── 卡: 本机 dsh 操控(与原隧道页 dsh-web 卡同源: service.start_dsh) ──
    def _card_dsh(self):
        card = QFrame(objectName="card")
        lv = QVBoxLayout(card)
        lv.setContentsMargins(16, 14, 16, 14)
        lv.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(QLabel("本机 dsh", objectName="cardTitle"))
        head.addStretch(1)
        dot = QLabel("○", objectName="monDot")
        dot.setStyleSheet("color:#999; font-size:15px;")
        head.addWidget(dot)
        lv.addLayout(head)
        self._cards["dsh-web"] = dot
        desc = QLabel("启动/重启/停止本机 dsh GUI\n(后台 pnpm dsh web)",
                      objectName="cardHint")
        desc.setWordWrap(True)
        lv.addWidget(desc)
        btns = QHBoxLayout()
        for act, text in (("start", "启动"), ("restart", "重启"), ("stop", "停止")):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, m=act: self._dsh_action(m))
            btns.addWidget(b)
        btns.addStretch(1)
        lv.addLayout(btns)
        return card

    def _dsh_action(self, mode):
        self.app.set_status("正在 %s 本机 dsh ..." % mode)
        self.app.service.start_dsh(mode)

    # ── 卡: 完整更新(update-dsh 流程, 与原隧道页同源: service.update_dsh) ──
    def _card_update(self):
        card = QFrame(objectName="card")
        lv = QVBoxLayout(card)
        lv.setContentsMargins(16, 14, 16, 14)
        lv.setSpacing(8)
        lv.addWidget(QLabel("更新 dsh 本体", objectName="cardTitle"))
        desc = QLabel("运行一次完整更新:\ngit 拉取 -> 依赖 -> 构建 -> 重启 web",
                      objectName="cardHint")
        desc.setWordWrap(True)
        lv.addWidget(desc)
        btns = QHBoxLayout()
        b = QPushButton("运行更新")
        b.clicked.connect(self._run_update)
        btns.addWidget(b)
        btns.addStretch(1)
        lv.addLayout(btns)
        return card

    def _run_update(self):
        # 危险操作约定: 先确认"将执行什么", 用户点是才执行; 业务在 core.dshctl。
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

    # ── 卡: 开发环境检查(页面内分步, 退役 EnvDialog 弹窗) ──
    def _card_env_check(self):
        card = QFrame(objectName="card")
        v = QVBoxLayout(card)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(QLabel("开发环境检查", objectName="cardTitle"))
        head.addStretch(1)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self._env_refresh)
        head.addWidget(refresh)
        v.addLayout(head)
        hint = QLabel("git / node / npm / pnpm 版本与推荐基准(缺哪个装哪个); "
                      "点「更新/安装/卸载」会先说明将执行什么, 确认后才执行。",
                      objectName="cardHint")
        hint.setWordWrap(True)
        v.addWidget(hint)
        table = QTableWidget(len(TOOLS), 5)
        table.setHorizontalHeaderLabels(["工具", "当前版本", "推荐基准", "状态", "操作"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)
        hh = table.horizontalHeader()
        for col in (0, 1, 2, 3):
            hh.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        act = {"update": "更新", "install": "安装", "uninstall": "卸载"}
        for i, (key, name, _cmd) in enumerate(TOOLS):
            table.setItem(i, 0, QTableWidgetItem(name))
            ver_item = QTableWidgetItem("...")
            table.setItem(i, 1, ver_item)
            table.setItem(i, 2, QTableWidgetItem(RECOMMENDED.get(key, "")))
            st_item = QTableWidgetItem("")
            table.setItem(i, 3, st_item)
            ops = QHBoxLayout()
            ops.setContentsMargins(0, 0, 0, 0)
            for text, kind in (("更新", "update"), ("安装", "install"), ("卸载", "uninstall")):
                b = QPushButton(text)
                # 表格单元格内的按钮若不设高会被行高裁切、字显不全; 抬高到标准按钮高
                b.setMinimumHeight(28)
                b.clicked.connect(lambda _=False, k=key, kd=kind: self._env_action(k, kd, act[kd]))
                ops.addWidget(b)
            ops.addStretch(1)
            holder = QWidget()
            holder.setLayout(ops)
            table.setCellWidget(i, 4, holder)
            table.setRowHeight(i, 34)
            self.env_rows[key] = (ver_item, st_item)
        v.addWidget(table, 1)
        self._env_refresh()
        return card

    def _env_refresh(self):
        # 后台线程顺序探测版本(core, 纯读), 结果经信号回主线程填表
        for key, (ver_item, st_item) in self.env_rows.items():
            ver_item.setText("...")
            st_item.setText("")
        def worker():
            try:
                res = core_env.tool_versions(TOOLS)
            except Exception as e:
                res = {}
                self.app.loge("[环境] 版本探测失败: %s" % e, "err")
            self.safe_emit(self._env_done, res)
        threading.Thread(target=worker, daemon=True).start()

    def _apply_env(self, res):
        # 语义色逐帧读 TOKENS(明/暗变体实时自适应, 不硬编码 Qt.black/绿, 否则暗色下版本黑字看不清)
        c_err, c_ok, c_text = (QColor(TOKENS[k]) for k in ("err", "ok", "text"))
        for key, (ver_item, st_item) in self.env_rows.items():
            v = res.get(key)
            if v is None:
                ver_item.setText("未安装")
                ver_item.setForeground(c_err)
                st_item.setText("缺失")
                st_item.setForeground(c_err)
            else:
                ver_item.setText(v)
                ver_item.setForeground(c_text)
                st_item.setText("OK")
                st_item.setForeground(c_ok)

    def _env_action(self, key, kind, label):
        # 每个动作先确认将执行什么, 确认后才执行(危险操作确认约定, 暂不收敛为确认条)
        ops = OPS.get(key)
        if ops is None:
            return
        plan = ops.get(kind) or []
        if not plan:
            return
        for typ, payload, desc in plan:
            if QMessageBox.question(
                    self, label + " " + ops["name"],
                    "将执行：\n" + desc + "\n\n是否继续？") != QMessageBox.Yes:
                return
            if typ == "cmd":
                self._env_run_cmd(payload, desc)
            elif typ == "browser":
                self._env_open_url(payload)
            elif typ == "page":
                self._env_open_apps_page()
            elif typ == "hint":
                QMessageBox.information(self, label + " " + ops["name"], payload)

    def _env_run_cmd(self, cmd, desc):
        # 有主窗口(service): service.run_cmd 流式执行逐行进主日志, finished 收尾
        if getattr(self.app, "service", None) is not None:
            env = core_env.pnpm_env() if cmd and str(cmd[0]).lower().startswith("pnpm") else None
            self.app.loge("[环境] " + desc + " 开始执行...", "warn")
            self.app.service.run_cmd(cmd, env=env, op="env-tool")
            self.app.set_status("正在执行: " + desc)
            return
        self.app.loge("[环境] " + desc, "warn")

    def _env_open_url(self, url):
        try:
            os.startfile(url)
        except Exception as e:
            QMessageBox.critical(self, "无法打开", str(e))

    def _env_open_apps_page(self):
        try:
            os.startfile("ms-settings:appsfeatures")
        except Exception as e:
            QMessageBox.critical(self, "无法打开", str(e))

    # ── 卡: 安装 dsh(页面内分步, 退役 InstallDialog 弹窗) ──
    def _card_install(self):
        card = QFrame(objectName="card")
        v = QVBoxLayout(card)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(8)
        v.addWidget(QLabel("安装 dsh（本机）", objectName="cardTitle"))
        v.addWidget(QLabel("dsh 仓库地址（git 克隆源）:",
                           objectName="cardHint"))
        self._inst_url = QLineEdit("https://github.com/deepseek-ai/deepseek-harness.git")
        v.addWidget(self._inst_url)
        v.addWidget(QLabel("安装到的目标目录（留空则默认用户主目录/dsh）:",
                           objectName="cardHint"))
        drow = QHBoxLayout()
        self._inst_dir = QLineEdit()
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._inst_browse_dir)
        drow.addWidget(self._inst_dir, 1)
        drow.addWidget(browse)
        v.addLayout(drow)
        row = QHBoxLayout()
        self._inst_start = QPushButton("开始安装", objectName="primary")
        self._inst_start.clicked.connect(self._start_install)
        row.addWidget(self._inst_start)
        self._inst_step_lbl = QLabel("未开始", objectName="monVal")
        row.addWidget(self._inst_step_lbl, 1)
        v.addLayout(row)
        self._inst_bar = QProgressBar()
        self._inst_bar.setRange(0, 4)
        self._inst_bar.setValue(0)
        v.addWidget(self._inst_bar)
        self._inst_log = QPlainTextEdit()
        self._inst_log.setReadOnly(True)
        self._inst_log.setMaximumBlockCount(500)
        self._inst_log.setMinimumHeight(140)
        self._inst_log.setPlaceholderText("安装日志(流式显示在这里)...")
        v.addWidget(self._inst_log)
        return card

    def _inst_browse_dir(self):
        start = self._inst_dir.text().strip() or os.path.expanduser("~")
        chosen = QFileDialog.getExistingDirectory(self, "选择 dsh 安装目录", start)
        if chosen:
            self._inst_dir.setText(chosen)

    def _start_install(self):
        # 校验输入后在后台线程跑安装: 业务全在 core.env.install_dsh(events 回调),
        # 本页只把 events 转成信号 -> 更新进度/日志。
        url = self._inst_url.text().strip()
        target = self._inst_dir.text().strip()
        if not url:
            QMessageBox.critical(self, "缺少仓库地址", "请填写 dsh 的 git 仓库地址。")
            return
        target = target or os.path.join(os.path.expanduser("~"), "dsh")
        self._inst_running = True
        self._inst_start.setEnabled(False)
        self._inst_url.setEnabled(False)
        self._inst_dir.setEnabled(False)
        self._inst_bar.setValue(0)
        self._inst_step_lbl.setText("正在安装…")
        self._inst_log.clear()

        def events(kind, payload):
            if kind == "log":
                self.safe_emit(self._install_line, payload)
            elif kind == "step":
                self.safe_emit(self._install_step, payload[0], payload[1])

        def worker():
            r = core_env.install_dsh(events, url, target)
            self.safe_emit(self._install_done, not r["err"], r["err"] or r["msg"])

        threading.Thread(target=worker, daemon=True).start()

    def _on_install_step(self, step, text):
        self._inst_bar.setValue(step)
        self._inst_step_lbl.setText(text)

    def _on_install_line(self, text):
        self._inst_log.appendPlainText(text)
        sb = self._inst_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_install_done(self, ok, msg):
        self._inst_running = False
        self._inst_start.setEnabled(True)
        self._inst_url.setEnabled(True)
        self._inst_dir.setEnabled(True)
        if ok:
            self._inst_bar.setValue(4)
            self._inst_step_lbl.setText("完成")
            self.app.loge("[安装] " + msg, "ok")
            self.app.set_status("安装完成，dash_repo 已更新")
            # 安装成功: 刷新部署列表(新仓库可被部署联动), 收尾提示
            if hasattr(self.app, "_refresh_deploy_list"):
                self.app._refresh_deploy_list()
            QMessageBox.information(self, "安装完成", msg)
        else:
            self._inst_step_lbl.setText("安装失败")
            self.app.loge("[安装] 失败: " + msg, "err")
            QMessageBox.warning(self, "安装失败", msg)

    # ── 卡: 卸载 dsh(保留 ~/.dsh 数据 / 一并删除), 危险操作双确认 ──
    def _card_uninstall(self):
        card = QFrame(objectName="card")
        v = QVBoxLayout(card)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(QLabel("卸载 dsh（本机）", objectName="cardTitle"))
        head.addStretch(1)
        v.addLayout(head)
        v.addWidget(QLabel("先停 dsh web，再删除源码目录并清空 config；二选一决定是否一并删除数据",
                           objectName="cardHint"))
        hint2 = QLabel("「保留数据」只删源码(~/.dsh 数据保留)；「彻底卸载」连 ~/.dsh 数据一起删。",
                       objectName="cardHint")
        hint2.setWordWrap(True)
        v.addWidget(hint2)
        row = QHBoxLayout()
        for text, keep, is_danger in (("保留数据卸载", True, False),
                                       ("彻底卸载(含数据)", False, True)):
            b = QPushButton(text, objectName="danger" if is_danger else "")
            b.setMinimumHeight(30)
            b.clicked.connect(lambda _=False, k=keep: self._start_uninstall(k))
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        self._uninst_step_lbl = QLabel("未开始", objectName="monVal")
        v.addWidget(self._uninst_step_lbl)
        self._uninst_bar = QProgressBar()
        self._uninst_bar.setValue(0)
        v.addWidget(self._uninst_bar)
        self._uninst_log = QPlainTextEdit()
        self._uninst_log.setReadOnly(True)
        self._uninst_log.setMaximumBlockCount(300)
        self._uninst_log.setMinimumHeight(110)
        self._uninst_log.setPlaceholderText("卸载日志(流式显示在这里)...")
        v.addWidget(self._uninst_log)
        return card

    def _start_uninstall(self, keep_data):
        # 危险操作: 先在确认框列出将删的具体路径, 点是才执行。
        # 彻底卸载(删 ~/.dsh 数据)再加一道二次确认(防手滑)。
        cfg = dsh_config.load_config()
        repo = (cfg.get("dash_repo") or "").strip()
        repo_desc = repo or "(未设置, 跳过)"

        if keep_data:
            lines = ["将执行(不可恢复)：", ""]
            lines.append("  1) 停止当前 dsh web")
            lines.append("  2) 删除源码目录: " + repo_desc)
            lines.append("  3) 清空 config.json 的 dash_repo")
            lines.append("")
            lines.append("保留 ~/.dsh 数据目录(对话/会话/配置等不删)。")
            if QMessageBox.question(self, "卸载 dsh（保留数据）", "\n".join(lines)) \
                    != QMessageBox.Yes:
                return
        else:
            from core import data as dsh_data
            data_dir = dsh_data.dsh_home()
            confirm = QMessageBox.question(
                self, "彻底卸载 dsh",
                "将执行(不可恢复)：\n\n"
                "  1) 停止当前 dsh web\n"
                "  2) 删除源码目录: %s\n"
                "  3) 清空 config.json 的 dash_repo\n"
                "  4) 删除数据目录: %s\n\n"
                "~/.dsh 包含所有对话记录/会话/工作区/配置, 删除后无法找回!\n"
                "是否继续?" % (repo_desc, data_dir))
            if confirm != QMessageBox.Yes:
                return
            double = QMessageBox.warning(
                self, "最后确认", "再次确认：真的删除全部数据(~/.dsh)吗？\n此操作不可撤销。",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if double != QMessageBox.Yes:
                return

        self._uninst_running = True
        self._uninst_bar.setValue(0)
        self._uninst_log.clear()
        # 进度条范围: 保留数据=3 步, 删数据=4 步
        self._uninst_bar.setRange(0, 4 if not keep_data else 3)
        self._uninst_step_lbl.setText("正在卸载…")

        def events(kind, payload):
            if kind == "log":
                self.safe_emit(self._uninstall_line, payload)
            elif kind == "step":
                self.safe_emit(self._uninstall_step, payload[0], payload[1])

        def worker():
            r = core_env.uninstall_dsh(events, keep_data)
            self.safe_emit(self._uninstall_done, not r["err"], r["err"] or r["msg"])

        threading.Thread(target=worker, daemon=True).start()

    def _on_uninstall_step(self, step, text):
        self._uninst_bar.setValue(step)
        self._uninst_step_lbl.setText(text)

    def _on_uninstall_line(self, text):
        self._uninst_log.appendPlainText(text)
        sb = self._uninst_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_uninstall_done(self, ok, msg):
        self._uninst_running = False
        if ok:
            self._uninst_bar.setValue(self._uninst_bar.maximum())
            self._uninst_step_lbl.setText("完成")
            self.app.loge("[卸载] " + msg, "ok")
            self.app.set_status("本机 dsh 已卸载")
            self.app._refresh_deploy_list()
            QMessageBox.information(self, "卸载完成", msg + "\n\n重启控制台后侧栏部署将不再包含本机。")
        else:
            self._uninst_step_lbl.setText("卸载失败")
            self.app.loge("[卸载] 失败: " + msg, "err")
            QMessageBox.warning(self, "卸载失败", msg)

    # ── 卡: 版本信息(本机 package.json vs GitHub tags) ──
    def _card_version(self):
        card = QFrame(objectName="card")
        lv = QVBoxLayout(card)
        lv.setContentsMargins(16, 14, 16, 14)
        lv.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(QLabel("版本信息(dsh 本体)", objectName="cardTitle"))
        head.addStretch(1)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self._fetch_tags)
        head.addWidget(refresh)
        lv.addLayout(head)
        self._tags_view = QTextEdit()
        self._tags_view.setReadOnly(True)
        self._tags_view.setFont(QFont("Consolas", 9))
        self._tags_view.setMinimumHeight(150)
        self._tags_view.setPlainText("正在获取 GitHub tags...")
        lv.addWidget(self._tags_view, 1)
        return card

    def _local_version(self):
        # 本机 dsh 版本 = dash_repo/package.json 的 version(与概览页同源); 读不到为 None
        try:
            cfg = dsh_config.load_config()
            with open(os.path.join(cfg.get("dash_repo") or "", "package.json"),
                      encoding="utf-8") as f:
                return (json.load(f) or {}).get("version")
        except Exception:
            return None   # 未配置仓库/未安装/文件损坏, 版本显示为未知

    def _fetch_tags(self):
        self._tags_view.setPlainText("正在获取 GitHub tags(api.github.com)...")
        def run():
            from core.dshctl import fetch_dsh_tags
            try:
                self.safe_emit(self._tags_done, fetch_dsh_tags(), "")
            except Exception as e:
                self.safe_emit(self._tags_done, [], "获取失败: %s" % e)
        threading.Thread(target=run, daemon=True).start()

    def _on_tags(self, tags, err):
        if err:
            self._tags_view.setPlainText(err + "\n检查网络后可点「刷新」重试。")
            return
        lines = []
        if tags:
            latest = str(tags[0])
            lines.append("GitHub 最新 tag: %s" % latest)
            local = self._local_version()
            if not local:
                lines.append("本机版本: 未知(未配置 dash_repo 或未安装)")
            elif local.lstrip("v") in latest.lstrip("v"):
                lines.append("本机版本: v%s —— 与最新 tag 一致" % local)
            else:
                lines.append("本机版本: v%s —— 可能落后于最新 tag(可点「运行更新」)"
                             % local)
            lines.append("")
            lines.extend("· " + str(t) for t in tags)
        else:
            lines.append("仓库还没有任何 tag")
        lines.append("")
        lines.append("全部 tags: " + _GH_TAGS_URL)
        self._tags_view.setPlainText("\n".join(lines))

    # ── 卡片状态(service.card 信号槽, 主线程) ──
    def _apply_card(self, key, on):
        self._set_card(key, on)

    def _set_card(self, key, on):
        dot = self._cards.get(key)
        if dot is None:
            return
        dot.setText("●" if on else "○")
        dot.setStyleSheet("color:#7ecb6a; font-size:15px;" if on
                          else "color:#999; font-size:15px;")
