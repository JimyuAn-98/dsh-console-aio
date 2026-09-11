# -*- coding: utf-8 -*-
# DSH 管理页: 本机 dsh 操控(启动/重启/停止) + 完整更新 + 环境/安装 + 版本信息
# (本机 package.json vs GitHub Releases: 版本列表 + 中文更新日志)。
# 由隧道页(dsh-web/update-dsh 两卡)与顶栏(环境/安装按钮)收敛而来 —— dsh 域操作集中
# 一页, 隧道页回归纯隧道。卡片在线状态经 service.card 信号(接收者=本页, 销毁自动断开)。
#
# 弹窗收敛(小菜②): 原 EnvDialog / InstallDialog 两个模态弹窗退役, 环境检查与安装向导
# 改为本页「页面内分步」(step in place, 愿景 §二.5)。业务全在 core/env.py(纯 Python):
#   环境检查 = core_env.tool_versions / 安装 = core_env.install_dsh(events 回调)。
# 后台线程只调 core 函数, 经类级 Signal + safe_emit 回主线程更新控件(AGENTS 线程约定);
# tags 拉取走页面线程 + safe_emit(同范式)。无真实远程写。

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton, QMessageBox,
    QTextEdit, QLineEdit, QProgressBar, QPlainTextEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QWidget, QFileDialog, QScrollArea, QComboBox)

from core import config as dsh_config
from core import dshctl as core_dshctl
from core import env as core_env
from ui.base import BasePage
from ui.theme import TOKENS
from ui.widgets import ConfirmBanner

_GH_RELEASES_URL = "https://github.com/%s/releases" % core_dshctl.DSH_REPO

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
    # 全部后台任务经 service 信号桥分发(dshctl/env/tags)。

    def __init__(self, app, parent=None):
        self._cards = {}               # key -> 状态圆点(仅 dsh-web 有)
        self.env_rows = {}             # 环境检查表: key -> (版本, 状态) item
        self._releases = []            # GitHub Releases 列表(新->旧)
        self._local_ver = None         # 本机 dsh 版本(package.json)
        self._pin = ""                 # 当前固定的版本 tag(config.dsh_version_pin)
        self._pending_deploy_tag = ""  # 脏工作区确认后待部署的 tag
        self._inst_running = False
        self._uninst_running = False
        self._update_running = False
        self._deploy_running = False
        self._mode_info = {}           # 当前 dsh 安装模式检测结果(core.pkgmgr.detect_mode)
        self._mode_applied = False     # 首次检测后据此预选安装方式
        super().__init__(app, parent)
        self.app.service.card.connect(self._apply_card)
        self.app.service.log.connect(self._on_service_log)
        self.app.service.step.connect(self._on_service_step)
        self.app.service.result.connect(self._on_result)
        self.app.service.finished.connect(self._on_finished)
        for key, on in self.app._card_state.items():
            self._set_card(key, on)
        self._fetch_releases()
        self._detect_mode()

    def on_show(self):
        # 页面实例常驻(见 MainWindow._show_page): 切回本页时刷新版本发布信息;
        # 安装/卸载/更新进行中的进度与日志控件内容保持不变。
        self._fetch_releases()
        self._detect_mode()

    def _on_service_log(self, text, _tag=""):
        if self._inst_running:
            self._on_install_line(text)
        if self._uninst_running:
            self._on_uninstall_line(text)

    def _on_service_step(self, step, text):
        if self._inst_running:
            self._on_install_step(step, text)
        if self._uninst_running:
            self._on_uninstall_step(step, text)
        if self._update_running:
            self._update_bar.setValue(step)
            self._update_step_lbl.setText(text)
        if self._deploy_running:
            self._deploy_bar.setValue(step)
            self._deploy_step_lbl.setText(text)

    def _on_result(self, op, payload):
        if op == "dsh-tool-versions":
            self._apply_env(payload.get("data") or {})
        elif op == "dsh-releases":
            self._on_releases(payload.get("data") or [], payload.get("err", ""))
        elif op == "dsh-mode":
            self._apply_mode(payload.get("data") or {})
        elif op in ("dsh-install", "dsh-install-pkg"):
            self._on_install_done(not payload.get("err"), payload.get("err") or payload.get("msg", ""))
        elif op == "dsh-uninstall":
            self._on_uninstall_done(not payload.get("err"), payload.get("err") or payload.get("msg", ""))
        elif op == "dsh-deploy-version":
            self._on_deploy_result(payload)

    def _on_finished(self, op, ok):
        # 结束信号统一解除对应操作的忙态(update/deploy 走 finished, install/uninstall 走 result)
        if op == "update-dsh":
            self._update_running = False
            self._update_btn.setEnabled(True)
            if ok:
                self._reload_app_config()   # 更新成功可能清除了版本固定
                self._detect_mode()
            else:
                self._update_step_lbl.setText("更新失败(详见日志)")
        elif op == "dsh-deploy-version":
            self._deploy_running = False
            self._btn_rel_deploy.setEnabled(True)
            if not ok:
                self._deploy_step_lbl.setText("部署失败(详见日志)")

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 10)
        root.setSpacing(8)
        title = QLabel("DSH 管理", objectName="cardTitle")
        self._status_lbl = QLabel("就绪", objectName="monVal")
        head = QHBoxLayout()
        head.addWidget(title)
        head.addStretch(1)
        # 当前 dsh 安装方式(源码 / 全局包): 自动探测, 决定启动/更新/卸载走哪条路。
        self._mode_lbl = QLabel("模式: 检测中…", objectName="cardHint")
        head.addWidget(self._mode_lbl)
        # 长操作(安装/更新/卸载/部署)完整输出落盘在 service 侧, 这里给一个打开入口。
        self._btn_oplog = QPushButton("打开操作日志")
        self._btn_oplog.setToolTip("查看最近一次安装/更新/卸载/部署的完整输出")
        self._btn_oplog.clicked.connect(self._open_op_log)
        head.addWidget(self._btn_oplog)
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

    def _open_op_log(self):
        # 打开最近一次长操作的完整日志文件(空/不存在时中文提示, 不弹错误框)。
        path = self.app.service.latest_op_log()
        if not path or not os.path.exists(path):
            self.app.loge("[日志] 本次会话还没有长操作日志(执行安装/更新/卸载/部署后生成)", "warn")
            QMessageBox.information(self, "操作日志",
                                    "本次会话还没有长操作日志。\n"
                                    "执行安装 / 更新 / 卸载 / 部署后会自动生成。")
            return
        try:
            os.startfile(path)   # 交给系统默认程序(记事本)打开
        except OSError as e:
            self.app.loge("[日志] 打开失败: %s" % e, "err")

    def _reload_app_config(self):
        # 安装/卸载/部署/更新都会改 config.json(dash_repo / dsh_install_mode / 版本固定),
        # 必须热重载, 否则 service 的派生配置与模式判定仍是旧值(此前只能手动去设置页点保存)。
        fn = getattr(self.app, "reload_config", None)
        if fn is None:
            return
        try:
            fn()
        except Exception as e:
            # 重载失败不能影响安装/卸载结果展示: 记一条告警, 设置页保存时会再试
            self.app.loge("[配置] 重载失败: %s" % e, "warn")

    # ── 当前安装方式检测(源码模式 / 全局包模式) ──
    def _detect_mode(self):
        # 后台探测: 源码目录是否可用 + 全局是否装了 @deepseek-ai/dsh(约 1s, core 侧有缓存)。
        self.app.service.detect_dsh_mode(op="dsh-mode")

    def _apply_mode(self, info):
        self._mode_info = info or {}
        try:
            from core import pkgmgr
            label = pkgmgr.mode_label(self._mode_info)
        except Exception:
            label = "模式未知"
        self._mode_lbl.setText("模式: " + label)
        self._mode_lbl.setToolTip(self._mode_tooltip())
        self._update_local_ver_label()
        if (self._mode_info or {}).get("mode") == "package":
            self._update_desc.setText(
                "运行一次完整更新: npm install -g @deepseek-ai/dsh@latest -> 重启 web")
            self._uninst_hint.setText(
                "先停 dsh web, 再 npm uninstall -g @deepseek-ai/dsh；二选一决定是否一并删除数据")
        else:
            self._update_desc.setText(
                "运行一次完整更新: git 拉取 -> 依赖 -> 构建 -> 重启 web")
            self._uninst_hint.setText(
                "先停 dsh web, 再删除源码目录并清空 config；二选一决定是否一并删除数据")
        # 首次检测后按检测结果预选安装方式(源码模式则默认源码, 否则全局包)
        if not self._mode_applied:
            self._mode_applied = True
            idx = self._inst_mode.findData(self._mode_info.get("mode") or "package")
            if idx >= 0:
                self._inst_mode.setCurrentIndex(idx)

    def _mode_tooltip(self):
        info = self._mode_info or {}
        s = info.get("source") or {}
        p = info.get("package") or {}
        src = ("是 v%s（%s）" % (s.get("version") or "?", s.get("repo"))) if s.get("ok") else "未检测到"
        pkg = ("是 %s" % (p.get("version") or "?")) if p.get("ok") else (p.get("error") or "未检测到")
        return "当前安装方式:\n源码模式: %s\n全局包模式: %s\n全局 bin: %s" % (
            src, pkg, p.get("bin_dir") or "-")

    def _update_local_ver_label(self):
        # 版本卡的本机版本: package 模式取全局包版本, 否则取源码 package.json。
        cfg = dsh_config.load_config()
        mode = (self._mode_info or {}).get("mode")
        local = core_dshctl.dsh_local_version(cfg, mode=mode)
        self._local_ver = local
        self._pin = str(cfg.get("dsh_version_pin") or "")
        base = ("v%s" % local) if local else "未知(未安装)"
        if mode == "package":
            extra = "全局包模式"
        else:
            extra = ("已固定 @ %s" % self._pin) if self._pin else "跟随默认分支"
        self._local_ver_lbl.setText("本机版本: %s · %s" % (base, extra))

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
        dot.setStyleSheet("color:%s; font-size:15px;" % TOKENS["text_dim"])
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
        self._update_desc = desc
        lv.addWidget(desc)
        btns = QHBoxLayout()
        self._update_btn = QPushButton("运行更新")
        self._update_btn.clicked.connect(self._run_update)
        btns.addWidget(self._update_btn)
        btns.addStretch(1)
        lv.addLayout(btns)
        self._update_step_lbl = QLabel("未开始", objectName="monVal")
        lv.addWidget(self._update_step_lbl)
        self._update_bar = QProgressBar()
        self._update_bar.setRange(0, 7)
        self._update_bar.setValue(0)
        lv.addWidget(self._update_bar)

        self._confirm_update = ConfirmBanner(self)
        lv.addWidget(self._confirm_update)

        return card

    def _run_update(self):
        pinned = str(self._pin or "")
        pkg_mode = (self._mode_info or {}).get("mode") == "package"

        def start(to_main):
            def run():
                self._update_running = True
                self._update_btn.setEnabled(False)
                self._update_bar.setValue(0)
                self._update_step_lbl.setText("正在更新…")
                self.app.loge("[update-dsh] 开始完整更新...", "warn")
                self.app.set_status("正在更新 npm 全局包..." if pkg_mode
                                    else "正在运行更新(构建较久, 请耐心)...")
                self.app.service.update_dsh(to_main=to_main)
            return run

        if pkg_mode:
            # 包模式: 只更新 npm 全局包(不碰 git/构建), 文案必须与实际执行一致
            self._confirm_update.ask(
                "更新 dsh 本体（npm 全局包）",
                "将对本机 dsh（npm 全局包）执行更新：<br>"
                "1. 停止当前 dsh web<br>"
                "2. npm install -g @deepseek-ai/dsh@latest<br>"
                "3. 重启 dsh web",
                start(False),
                level="warn",
                confirm_text="确认开始更新"
            )
            return
        if pinned:
            self._confirm_update.ask(
                "更新 dsh 本体（当前固定版本）",
                "当前已固定到版本 <b>%s</b>。<br>"
                "继续更新将切回默认分支并更新到最新代码（清除版本固定）。<br><br>"
                "将执行：停止 web -> 切回默认分支 -> git 拉取 -> 清理 -> pnpm install -> "
                "构建 -> 重启。" % pinned,
                start(True),
                level="warn",
                confirm_text="切回主线并更新"
            )
            return
        self._confirm_update.ask(
            "更新 dsh 本体",
            "将对本机 dsh 执行完整更新：<br>"
            "1. 停止当前 dsh web<br>"
            "2. git fetch + git pull 拉取最新代码<br>"
            "3. 清理旧构建产物并 pnpm install<br>"
            "4. pnpm run build 构建并重启 dsh web",
            start(False),
            level="warn",
            confirm_text="确认开始更新"
        )

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

        self._confirm_env = ConfirmBanner(self)
        v.addWidget(self._confirm_env)

        self._env_refresh()
        return card

    def _env_refresh(self):
        # 经 service 信号桥探测工具链版本(纯读)
        for key, (ver_item, st_item) in self.env_rows.items():
            ver_item.setText("...")
            st_item.setText("")
        self.app.service.check_tool_versions(TOOLS, op="dsh-tool-versions")

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
        ops = OPS.get(key)
        if ops is None:
            return
        plan = ops.get(kind) or []
        if not plan:
            return

        def do_execute_plan():
            for typ, payload, desc in plan:
                if typ == "cmd":
                    self._env_run_cmd(payload, desc)
                elif typ == "browser":
                    self._env_open_url(payload)
                elif typ == "page":
                    self._env_open_apps_page()
                elif typ == "hint":
                    self._confirm_env.ask(label + " " + ops["name"], payload, lambda: None, level="warn", confirm_text="知道了")

        descs = "<br>".join(desc for _, _, desc in plan)
        self._confirm_env.ask(
            "%s %s" % (label, ops["name"]),
            "将执行操作：<br>%s" % descs,
            do_execute_plan,
            level="warn" if kind != "uninstall" else "danger",
            confirm_text="确认" + label
        )

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
        mrow = QHBoxLayout()
        mrow.addWidget(QLabel("安装方式:", objectName="cardHint"))
        self._inst_mode = QComboBox()
        self._inst_mode.addItem("npm 全局包（推荐，免克隆/免构建）", "package")
        self._inst_mode.addItem("源码克隆（可跑本地未发布代码）", "source")
        self._inst_mode.currentIndexChanged.connect(self._on_inst_mode_changed)
        mrow.addWidget(self._inst_mode, 1)
        v.addLayout(mrow)
        self._inst_mode_hint = QLabel("", objectName="cardHint")
        self._inst_mode_hint.setWordWrap(True)
        v.addWidget(self._inst_mode_hint)
        self._inst_url_lbl = QLabel("dsh 仓库地址（git 克隆源）:", objectName="cardHint")
        v.addWidget(self._inst_url_lbl)
        self._inst_url = QLineEdit("https://github.com/deepseek-ai/deepseek-harness.git")
        v.addWidget(self._inst_url)
        self._inst_dir_lbl = QLabel("安装到的目标目录（留空则默认用户主目录/dsh）:",
                                    objectName="cardHint")
        v.addWidget(self._inst_dir_lbl)
        drow = QHBoxLayout()
        self._inst_dir = QLineEdit()
        self._inst_browse = QPushButton("浏览…")
        self._inst_browse.clicked.connect(self._inst_browse_dir)
        drow.addWidget(self._inst_dir, 1)
        drow.addWidget(self._inst_browse)
        v.addLayout(drow)
        vrow = QHBoxLayout()
        vrow.addWidget(QLabel("安装版本(默认最新):", objectName="cardHint"))
        self._inst_ver = QComboBox()
        self._inst_ver.addItem("最新(默认分支)", "")
        vrow.addWidget(self._inst_ver, 1)
        v.addLayout(vrow)
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
        self._on_inst_mode_changed()
        return card

    def _on_inst_mode_changed(self, _idx=0):
        # 全局包模式无需仓库地址/目标目录, 隐藏这两组输入; 版本下拉两种模式共用。
        pkg = (self._inst_mode.currentData() or "package") == "package"
        for w in (self._inst_url_lbl, self._inst_url, self._inst_dir_lbl,
                  self._inst_dir, self._inst_browse):
            w.setVisible(not pkg)
        self._inst_mode_hint.setText(
            "官方 npm 全局包: npm install -g @deepseek-ai/dsh（更新/卸载走 npm；与官方 npx 同源布局）"
            if pkg else
            "源码克隆: git clone + pnpm install + pnpm build（可跑本地未发布的 DSH 代码）")

    def _inst_browse_dir(self):
        start = self._inst_dir.text().strip() or os.path.expanduser("~")
        chosen = QFileDialog.getExistingDirectory(self, "选择 dsh 安装目录", start)
        if chosen:
            self._inst_dir.setText(chosen)

    def _start_install(self):
        # 校验输入后在后台线程跑安装: 全局包走 core.env.install_dsh_pkg(npm install -g),
        # 源码走 core.env.install_dsh(git clone + build); 本页只把 events 转成信号。
        mode = self._inst_mode.currentData() or "package"
        version = self._inst_ver.currentData() or ""
        if mode == "source":
            url = self._inst_url.text().strip()
            if not url:
                QMessageBox.critical(self, "缺少仓库地址", "请填写 dsh 的 git 仓库地址。")
                return
            target = self._inst_dir.text().strip() or os.path.join(os.path.expanduser("~"), "dsh")
        self._inst_running = True
        self._inst_start.setEnabled(False)
        self._inst_mode.setEnabled(False)
        self._inst_url.setEnabled(False)
        self._inst_dir.setEnabled(False)
        self._inst_ver.setEnabled(False)
        self._inst_bar.setValue(0)
        self._inst_step_lbl.setText("正在安装…")
        self._inst_log.clear()
        if mode == "source":
            self.app.service.install_dsh(url, target, version=version, op="dsh-install")
        else:
            self.app.service.install_dsh_pkg(version=version, op="dsh-install-pkg")

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
        self._inst_mode.setEnabled(True)
        self._inst_url.setEnabled(True)
        self._inst_dir.setEnabled(True)
        self._inst_ver.setEnabled(True)
        if ok:
            self._inst_bar.setValue(4)
            self._inst_step_lbl.setText("完成")
            self.app.loge("[安装] " + msg, "ok")
            self.app.set_status("安装完成，dsh 已就绪")
            # 安装成功: 热重载配置(写入了 dash_repo / dsh_install_mode) -> 再重新检测模式
            self._reload_app_config()
            self._detect_mode()
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
        self._uninst_hint = QLabel(
            "先停 dsh web，再按当前安装方式删除（源码目录 / 全局包）；二选一决定是否一并删除数据",
            objectName="cardHint")
        self._uninst_hint.setWordWrap(True)
        v.addWidget(self._uninst_hint)
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

        self._confirm_uninst = ConfirmBanner(self)
        v.addWidget(self._confirm_uninst)

        return card

    def _start_uninstall(self, keep_data):
        cfg = dsh_config.load_config()
        repo = (cfg.get("dash_repo") or "").strip()
        repo_desc = repo or "(未设置, 跳过)"

        def do_run_uninstall():
            self._uninst_running = True
            self._uninst_bar.setValue(0)
            self._uninst_log.clear()
            self._uninst_bar.setRange(0, 4 if not keep_data else 3)
            self._uninst_step_lbl.setText("正在卸载…")
            self.app.service.uninstall_dsh(keep_data=keep_data, op="dsh-uninstall")

        if keep_data:
            self._confirm_uninst.ask(
                "卸载 dsh（保留数据）",
                "将执行：<br>1. 停止当前 dsh web<br>2. 删除源码目录：%s<br>3. 清空 config.json 的 dash_repo<br>（保留 ~/.dsh 数据目录）" % repo_desc,
                do_run_uninstall,
                level="warn",
                confirm_text="确认卸载(保留数据)"
            )
        else:
            from core import data as dsh_data
            data_dir = dsh_data.dsh_home()
            self._confirm_uninst.ask(
                "彻底卸载 dsh（含全部数据）",
                "⚠️ 危险操作：将停止 web、删除源码目录（%s）、清空 dash_repo 配置，并<b>永久删除数据目录（%s）</b>！所有会话与记录均不可恢复！" % (repo_desc, data_dir),
                do_run_uninstall,
                level="danger",
                confirm_text="确认彻底卸载"
            )

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
            self._reload_app_config()
            self._detect_mode()
            QMessageBox.information(self, "卸载完成", msg)
        else:
            self._uninst_step_lbl.setText("卸载失败")
            self.app.loge("[卸载] 失败: " + msg, "err")
            QMessageBox.warning(self, "卸载失败", msg)

    # ── 卡: 版本信息(本机 package.json vs GitHub Releases + 更新日志) ──
    def _card_version(self):
        card = QFrame(objectName="card")
        lv = QVBoxLayout(card)
        lv.setContentsMargins(16, 14, 16, 14)
        lv.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(QLabel("版本信息(dsh 本体)", objectName="cardTitle"))
        head.addStretch(1)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(lambda: self._fetch_releases(force=True))
        head.addWidget(refresh)
        lv.addLayout(head)
        self._local_ver_lbl = QLabel("本机版本: 读取中…", objectName="cardHint")
        lv.addWidget(self._local_ver_lbl)
        row = QHBoxLayout()
        row.addWidget(QLabel("版本:", objectName="cardHint"))
        self._rel_cb = QComboBox()
        self._rel_cb.setMinimumWidth(260)
        self._rel_cb.currentIndexChanged.connect(self._render_release)
        row.addWidget(self._rel_cb, 1)
        self._btn_rel_open = QPushButton("在浏览器打开")
        self._btn_rel_open.setEnabled(False)
        self._btn_rel_open.clicked.connect(self._open_selected_release)
        row.addWidget(self._btn_rel_open)
        self._btn_rel_deploy = QPushButton("部署此版本")
        self._btn_rel_deploy.setEnabled(False)
        self._btn_rel_deploy.clicked.connect(self._deploy_selected)
        row.addWidget(self._btn_rel_deploy)
        lv.addLayout(row)
        self._deploy_step_lbl = QLabel("未部署", objectName="monVal")
        lv.addWidget(self._deploy_step_lbl)
        self._deploy_bar = QProgressBar()
        self._deploy_bar.setRange(0, 7)
        self._deploy_bar.setValue(0)
        lv.addWidget(self._deploy_bar)
        self._rel_body = QTextEdit()
        self._rel_body.setReadOnly(True)
        self._rel_body.setMinimumHeight(220)
        self._rel_body.setPlaceholderText("选择版本查看更新日志…")
        lv.addWidget(self._rel_body, 1)

        self._confirm_deploy = ConfirmBanner(self)
        lv.addWidget(self._confirm_deploy)
        return card

    def _fetch_releases(self, force=False):
        # 经 service 信号桥拉 GitHub Releases(core 侧 TTL 缓存; force 供「刷新」按钮)
        self._update_local_ver_label()
        self._btn_rel_open.setEnabled(False)
        self._btn_rel_deploy.setEnabled(False)
        self._rel_body.setPlainText("正在获取发布信息(GitHub Releases)…")
        self.app.service.fetch_dsh_releases(force=force, op="dsh-releases")

    def _on_releases(self, releases, err):
        if err:
            self._rel_cb.blockSignals(True)
            self._rel_cb.clear()
            self._rel_cb.blockSignals(False)
            self._rel_body.setPlainText(
                "发布信息获取失败: %s\n检查网络后可点「刷新」重试。" % err)
            self._btn_rel_open.setEnabled(False)
            self._btn_rel_deploy.setEnabled(False)
            return
        self._releases = list(releases or [])
        if not self._releases:
            self._rel_body.setPlainText("上游仓库没有可用的 Release。")
            return
        local = self._local_ver
        self._rel_cb.blockSignals(True)
        self._rel_cb.clear()
        sel = 0
        for i, r in enumerate(self._releases):
            label = "v%s · %s%s%s" % (
                r.get("version") or r.get("tag") or "?",
                (r.get("published_at") or "")[:10] or "日期未知",
                " · 预发布" if r.get("prerelease") else "",
                " · 已装" if local and r.get("version") == local else "")
            self._rel_cb.addItem(label)
            if local and r.get("version") == local:
                sel = i
        self._rel_cb.setCurrentIndex(sel)
        self._rel_cb.blockSignals(False)
        self._render_release(sel)
        self._fill_install_versions()

    def _render_release(self, idx):
        # 单栏: 下拉选中 -> 渲染该版本中文更新日志(HTML 标题转 Markdown 后交给 setMarkdown)
        if not (0 <= idx < len(self._releases)):
            self._rel_body.clear()
            self._btn_rel_open.setEnabled(False)
            return
        r = self._releases[idx]
        body = core_dshctl.html_headings_to_md(
            core_dshctl.cn_section(r.get("body") or ""))
        self._rel_body.setMarkdown(body if body.strip() else "(该版本没有更新日志正文)")
        self._btn_rel_open.setEnabled(bool(r.get("html_url")))
        self._btn_rel_deploy.setEnabled(bool(r.get("tag")))

    def _open_selected_release(self):
        idx = self._rel_cb.currentIndex()
        url = (self._releases[idx].get("html_url")
               if 0 <= idx < len(self._releases) else "") or _GH_RELEASES_URL
        try:
            os.startfile(url)
        except Exception as e:
            QMessageBox.critical(self, "无法打开", str(e))

    def _fill_install_versions(self):
        # 用同一份 Releases 列表填充安装卡的版本下拉(默认最新)
        if not hasattr(self, "_inst_ver"):
            return
        cur = self._inst_ver.currentData()
        self._inst_ver.blockSignals(True)
        self._inst_ver.clear()
        self._inst_ver.addItem("最新(默认分支)", "")
        for r in self._releases:
            tag = r.get("tag") or ""
            if tag:
                self._inst_ver.addItem(
                    "v%s%s" % (r.get("version") or tag,
                               " · 预发布" if r.get("prerelease") else ""), tag)
        idx = self._inst_ver.findData(cur) if cur else 0
        self._inst_ver.setCurrentIndex(idx if idx >= 0 else 0)
        self._inst_ver.blockSignals(False)

    def _deploy_selected(self):
        # 版本卡「部署此版本」: 确认 -> 后台部署; 回退更旧版本时提示先备份
        idx = self._rel_cb.currentIndex()
        if not (0 <= idx < len(self._releases)):
            return
        r = self._releases[idx]
        tag = str(r.get("tag") or "")
        ver = str(r.get("version") or tag)
        if not tag:
            return
        self._pending_deploy_tag = tag
        older = False
        if self._local_ver:
            versions = [x.get("version") for x in self._releases]
            if self._local_ver in versions:
                older = idx > versions.index(self._local_ver)
        warn = ("<br><br>⚠️ 这是比当前本机版本更旧的版本，可能与 ~/.dsh 数据不兼容；"
                "建议先到「备份与凭据」页备份。") if older else ""
        if (self._mode_info or {}).get("mode") == "package":
            # 包模式: 只从 npm 装指定版本并重启, 不碰 git/构建
            self._confirm_deploy.ask(
                "部署版本 " + ver,
                "将把本机 dsh（npm 全局包）切换到 <b>%s</b>：<br>"
                "1. 停止当前 dsh web<br>"
                "2. npm install -g @deepseek-ai/dsh@%s<br>"
                "3. 重启 dsh web%s" % (ver, ver, warn),
                lambda: self._do_deploy(tag),
                level="warn",
                confirm_text="确认部署"
            )
            return
        self._confirm_deploy.ask(
            "部署版本 " + ver,
            "将把本机 dsh 切换到 <b>%s</b>：<br>"
            "1. 停止当前 dsh web<br>"
            "2. git fetch --tags<br>"
            "3. 校验版本<br>"
            "4. git checkout %s<br>"
            "5. pnpm install<br>"
            "6. 清理并重新构建<br>"
            "7. 重启 dsh web<br><br>"
            "构建耗时较长，请耐心等待。%s" % (tag, tag, warn),
            lambda: self._do_deploy(tag),
            level="warn",
            confirm_text="确认部署"
        )

    def _do_deploy(self, tag, allow_dirty=False):
        self._deploy_running = True
        self._btn_rel_deploy.setEnabled(False)
        self._deploy_bar.setValue(0)
        self._deploy_step_lbl.setText("正在部署 %s…" % tag)
        self.app.set_status("正在部署 dsh 版本 " + tag)
        self.app.service.deploy_dsh_version(tag, allow_dirty=allow_dirty)

    def _on_deploy_result(self, payload):
        # dirty 哨兵 = core 检测到工作区有改动且未授权; 二次确认后再以 allow_dirty 重发
        if payload.get("dirty"):
            tag = str(payload.get("tag") or self._pending_deploy_tag)
            self._confirm_deploy.ask(
                "工作区有本地改动",
                "本机 dsh 仓库存在未提交的本地改动，切换版本可能失败或丢失改动。<br><br>"
                "确定仍要继续部署 <b>%s</b> 吗？" % tag,
                lambda: self._do_deploy(tag, allow_dirty=True),
                level="danger",
                confirm_text="仍然继续"
            )
            return
        err = str(payload.get("err") or "")
        if err:
            self._deploy_step_lbl.setText("部署失败(详见日志)")
            self.app.loge("[部署] 失败: " + err, "err")
            QMessageBox.warning(self, "部署失败", err)
            return
        self._deploy_bar.setValue(self._deploy_bar.maximum())
        self._deploy_step_lbl.setText("部署完成")
        self.app.loge("[部署] " + str(payload.get("msg") or "完成"), "ok")
        self.app.set_status("dsh 版本部署完成")
        self._reload_app_config()   # 版本固定等配置可能已变
        self._fetch_releases()      # 刷新本机版本与固定状态

    # ── 卡片状态(service.card 信号槽, 主线程) ──
    def _apply_card(self, key, on):
        self._set_card(key, on)

    def _set_card(self, key, on):
        dot = self._cards.get(key)
        if dot is None:
            return
        dot.setText("●" if on else "○")
        dot.setStyleSheet("color:%s; font-size:15px;"
                          % (TOKENS["ok"] if on else TOKENS["text_dim"]))
