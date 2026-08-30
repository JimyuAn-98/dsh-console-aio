# -*- coding: utf-8 -*-
# DSH 管理页: 本机 dsh 操控(启动/重启/停止) + 完整更新 + 环境/安装入口 + 版本信息
# (本机 package.json vs GitHub deepseek-ai/deepseek-harness tags)。
# 由隧道页(dsh-web/update-dsh 两卡)与顶栏(环境/安装按钮)收敛而来 —— dsh 域操作集中
# 一页, 隧道页回归纯隧道。卡片在线状态经 service.card 信号(接收者=本页, 销毁自动断开);
# tags 拉取走页面自有 daemon 线程 + safe_emit(BUG-008 范式), 不碰真实远程写。

import json
import os
import threading

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton, QMessageBox,
    QTextEdit)

from core import config as dsh_config
from ui.base import BasePage
from ui.dialogs import EnvDialog, InstallDialog

_GH_TAGS_URL = "https://github.com/deepseek-ai/deepseek-harness/tags"


class DshManagePage(BasePage):
    # DSH 管理: BasePage 范式, app 为 MainWindow。仅本机操作; 更新有确认, 无远程写。
    _tags_done = Signal(list, str)   # (tag 名称列表, 错误文案) 后台线程 -> UI

    def __init__(self, app, parent=None):
        self._cards = {}             # key -> 状态圆点(仅 dsh-web 有)
        super().__init__(app, parent)
        self.app.service.card.connect(self._apply_card)
        self._tags_done.connect(self._on_tags)
        for key, on in self.app._card_state.items():
            self._set_card(key, on)
        self._fetch_tags()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(10)
        title = QLabel("DSH 管理", objectName="cardTitle")
        self._status_lbl = QLabel("就绪", objectName="monVal")
        head = QHBoxLayout()
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self._status_lbl)
        root.addLayout(head)

        grid = QVBoxLayout()
        grid.setSpacing(10)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self._card_dsh(), 1)
        row.addWidget(self._card_update(), 1)
        grid.addLayout(row)
        row2 = QHBoxLayout()
        row2.setSpacing(10)
        row2.addWidget(self._card_env_install(), 1)
        row2.addWidget(self._card_version(), 1)
        grid.addLayout(row2)
        root.addLayout(grid)
        root.addStretch(1)

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

    # ── 卡: 环境 / 安装(原顶栏按钮入口收敛至此) ──
    def _card_env_install(self):
        card = QFrame(objectName="card")
        lv = QVBoxLayout(card)
        lv.setContentsMargins(16, 14, 16, 14)
        lv.setSpacing(8)
        lv.addWidget(QLabel("环境与安装", objectName="cardTitle"))
        desc = QLabel("环境检查: git/node/npm/pnpm 版本与推荐基准\n"
                      "安装 dsh: 预检 -> clone -> 依赖 -> 构建 -> 写配置",
                      objectName="cardHint")
        desc.setWordWrap(True)
        lv.addWidget(desc)
        btns = QHBoxLayout()
        env = QPushButton("环境检查...")
        env.clicked.connect(self._open_env)
        inst = QPushButton("安装 dsh...")
        inst.clicked.connect(self._open_install)
        btns.addWidget(env)
        btns.addWidget(inst)
        btns.addStretch(1)
        lv.addLayout(btns)
        return card

    def _open_env(self):
        EnvDialog(self).exec()

    def _open_install(self):
        dlg = InstallDialog(self)
        dlg.exec()
        if getattr(dlg, "result", None):
            self.app._refresh_deploy_list()
            self.app.set_status("安装完成，dash_repo 已更新")

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
