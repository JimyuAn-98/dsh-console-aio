# -*- coding: utf-8 -*-
# ui/pages_overview.py - 部署总览页: 运行状态卡 + 数据速览 + 部署列表 + 隧道速览。
# 数据经 service 信号桥调度回主线程; 接入 core/cache 缓存, 进页秒开+按需刷新。

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton, QMessageBox)

from core import data as dsh_data
from core import config as dsh_config
from ui.base import BasePage
from ui.cacheable import CacheableMixin
from ui.theme import TOKENS
from ui.widgets import ModernList, RefreshIndicator


def _ov_size(n):
    # 概览页字节数人性化(与 sessions 页口径一致)
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f%s" % (n, unit)
        n /= 1024.0
    return "0B"


def _c(kind):
    # 富文本状态色与 QSS/徽章同源(明暗自适应); 口径同 widgets._badge_color
    return {"ok": TOKENS["ok"], "warn": TOKENS["warn"], "err": TOKENS["err"],
            "dim": TOKENS["text_dim"]}.get(kind, TOKENS["text_dim"])


class OverviewPage(CacheableMixin, BasePage):
    # 部署总览: 运行状态卡 + 数据速览 + 部署列表 + 隧道速览。
    # 数据经 service 信号桥调度回主线程; 接入 core/cache 缓存, 进页秒开+按需刷新。

    def __init__(self, app, parent=None):
        self._busy = False
        super().__init__(app, parent)
        self.app.service.result.connect(self._on_result)
        self.refresh()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 12)
        root.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(QLabel("节点总览", objectName="cardTitle"))
        self._spinner = RefreshIndicator()
        self._spinner.setToolTip("刷新状态: 绿=无变化 / 黄=数据有变化 / 红=获取错误")
        head.addWidget(self._spinner)
        head.addStretch(1)
        self._status_lbl = QLabel("就绪", objectName="monVal")
        head.addWidget(self._status_lbl)
        self._btn_refresh = QPushButton("刷新", objectName="primary")
        self._btn_refresh.clicked.connect(lambda: self.refresh(force=True))
        head.addWidget(self._btn_refresh)
        root.addLayout(head)
        root.addWidget(QLabel("本机与远程节点的实时状态、数据速览与访问链接(纯读获取, 进页自动取缓存)。",
                              objectName="cardHint"))

        # 运行状态卡: dsh web 探测 + 本体版本 + 鉴权链接与捕获状态
        run = QFrame(objectName="card")
        rl = QHBoxLayout(run)
        rl.setContentsMargins(14, 10, 14, 10)
        rl.setSpacing(10)
        self._web_lbl = QLabel("dsh web 检测中…", objectName="monVal")
        self._web_lbl.setTextFormat(Qt.RichText)
        rl.addWidget(self._web_lbl)
        rl.addSpacing(10)
        self._local_token_lbl = QLabel("", objectName="monName")
        self._local_token_lbl.setTextFormat(Qt.RichText)
        self._local_token_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._local_token_lbl.setWordWrap(True)
        rl.addWidget(self._local_token_lbl, 1)
        self._copy_local_link_btn = QPushButton("复制本机链接")
        self._copy_local_link_btn.setToolTip("复制本机带鉴权 Token 的完整访问链接")
        self._copy_local_link_btn.setEnabled(False)
        self._copy_local_link_btn.clicked.connect(self._copy_local_auth_url)
        rl.addWidget(self._copy_local_link_btn)
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
        dep_card = QFrame(objectName="card")
        dv = QVBoxLayout(dep_card)
        dv.setContentsMargins(12, 10, 12, 10)
        dv.setSpacing(6)
        dh = QHBoxLayout()
        dh.addWidget(QLabel("节点", objectName="rightTitle"))
        dh.addSpacing(10)
        self._dep_auth_lbl = QLabel("", objectName="monName")
        self._dep_auth_lbl.setTextFormat(Qt.RichText)
        self._dep_auth_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._dep_auth_lbl.setWordWrap(True)
        dh.addWidget(self._dep_auth_lbl, 1)
        self._copy_link_btn = QPushButton("复制免密链接")
        self._copy_link_btn.setToolTip("复制选中节点的免密访问链接（含鉴权 Token）")
        self._copy_link_btn.setEnabled(False)
        self._copy_link_btn.clicked.connect(self._copy_selected_auth_url)
        dh.addWidget(self._copy_link_btn)
        self._open_link_btn = QPushButton("在浏览器打开")
        self._open_link_btn.setToolTip("用系统默认浏览器打开选中节点的免密访问链接")
        self._open_link_btn.setEnabled(False)
        self._open_link_btn.clicked.connect(self._open_selected_auth_url)
        dh.addWidget(self._open_link_btn)
        dv.addLayout(dh)
        self._dep_list = ModernList()
        self._dep_list.itemSelectionChanged.connect(self._on_dep_select)
        self._dep_list.itemClicked.connect(lambda _: self._on_dep_select())
        dv.addWidget(self._dep_list, 1)
        root.addWidget(dep_card, 1)

    def _selected_item_data(self):
        row = self._dep_list.current_data()
        return row.get("data") if (isinstance(row, dict) and "data" in row) else row

    def _on_dep_select(self):
        item = self._selected_item_data()
        if not item:
            self._copy_link_btn.setEnabled(False)
            self._open_link_btn.setEnabled(False)
            self._dep_auth_lbl.setText("")
            return
        url = item.get("auth_url") or ""
        tok = item.get("token")
        name = item.get("dep", {}).get("name") or "节点"
        snap = item.get("snap") or {}
        is_local = bool(item.get("local"))
        if is_local:
            is_online = bool(getattr(self, "_last_payload", {}).get("web_ok"))
        else:
            # 远程节点在线以"经隧道/直连的本机访问端口探活"为准; SSH 快照只作详情
            is_online = (bool(item.get("web_ok")) if item.get("web_ok") is not None
                         else bool(snap.get("ok")))
        if is_online:
            if tok:
                self._dep_auth_lbl.setText(
                    '<span style="color:%s">「%s」免密链接: </span>'
                    '<span style="color:%s; font-family:Consolas,monospace;">%s</span>'
                    % (_c("dim"), name, _c("ok"), url))
            else:
                self._dep_auth_lbl.setText(
                    '<span style="color:%s">「%s」免密链接: </span>'
                    '<span style="color:%s; font-family:Consolas,monospace;">%s (信箱未同步Token)</span>'
                    % (_c("dim"), name, _c("warn"), url))
            self._copy_link_btn.setEnabled(bool(url))
            self._open_link_btn.setEnabled(bool(url))
        else:
            self._dep_auth_lbl.setText(
                '<span style="color:%s">「%s」: </span>'
                '<span style="color:%s;">离线 / 未配置</span>' % (_c("dim"), name, _c("err")))
            self._copy_link_btn.setEnabled(False)
            self._open_link_btn.setEnabled(False)

    def _copy_selected_auth_url(self):
        item = self._selected_item_data()
        if not item:
            return
        url = item.get("auth_url")
        name = item.get("dep", {}).get("name") or "节点"
        if url:
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(url)
            self._set_status("已复制「%s」免密访问链接" % name)
            self.app.loge("已复制「%s」免密访问链接至剪贴板: %s" % (name, url), "ok")

    def _open_selected_auth_url(self):
        # 用系统默认浏览器打开选中节点的免密访问链接(本机/远程同源)
        item = self._selected_item_data()
        if not item:
            return
        url = item.get("auth_url") or ""
        name = item.get("dep", {}).get("name") or "节点"
        if not url:
            self._set_status("该节点没有可打开的链接")
            return
        try:
            os.startfile(url)
            self._set_status("已在浏览器打开「%s」" % name)
            self.app.loge("已打开「%s」免密访问链接: %s" % (name, url), "ok")
        except Exception as e:
            QMessageBox.critical(self, "无法打开", str(e))

    # ── 缓存编排钩子(见 ui/cacheable.py); refresh() 由 mixin 提供 ──
    def _cache_kind(self):
        return "overview"

    def _cache_src_mtime(self):
        cfg = dsh_config.load_config()
        self._cfg = cfg
        return dsh_data.overview_source_mtime(cfg)

    def _cache_fetch(self):
        cfg = getattr(self, "_cfg", None) or dsh_config.load_config()
        depls = dsh_data.load_deployments()
        smoke = bool(getattr(self.app, "smoke", False))
        self.app.service.read_overview(cfg, depls, smoke=smoke, op="overview-read")

    def _cache_apply(self, data, err=""):
        if err or not isinstance(data, dict):
            self._set_status("总览读取失败: " + str(err or "未知错误"))
            return
        self._apply_data(data)

    def _cache_begin(self):
        self._set_status("正在读取总览数据...")
        self._btn_refresh.setEnabled(False)

    def _cache_end(self):
        self._btn_refresh.setEnabled(True)

    def _cache_hit_extra(self, data):
        # 命中缓存后再补一次轻量探活刷新"实时"字段(web_ok/token)
        if not getattr(self.app, "smoke", False):
            self._probe_live(getattr(self, "_cfg", None) or dsh_config.load_config())

    def _probe_live(self, cfg):
        # 命中缓存时补一次本机 web 探活(纯 socket, 0.8s 超时), 只刷新运行状态卡等实时字段
        self.app.service.probe_overview_local(cfg, op="overview-live")

    def _on_result(self, op, payload):
        if op == "overview-read":
            self._cache_result(payload.get("data"), payload.get("err") or "")
        elif op == "overview-live":
            live = payload.get("data") or {}
            if live and getattr(self, "_last_payload", None):
                self._last_payload.update(live)
                self._apply_data(self._last_payload)

    def _copy_local_auth_url(self):
        url = getattr(self, "_last_payload", {}).get("local_auth_url")
        if not url:
            from core.dshctl import get_runtime_token
            tok = get_runtime_token("local")
            cfg = dsh_config.load_config()
            port = cfg.get("dash_port") or 3080
            url = ("http://127.0.0.1:%s/?token=%s" % (port, tok)) if tok else ("http://127.0.0.1:%s" % port)
        if url:
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(url)
            self._set_status("已复制本机访问链接")
            self.app.loge("已复制本机访问链接至剪贴板: %s" % url, "ok")

    def _apply_data(self, p):
        # 运行状态卡
        self._last_payload = p
        if p.get("web_ok"):
            self._web_lbl.setText(
                '<span style="color:%s">●</span> dsh web :%s 在线'
                '<span style="color:%s">（%d ms）</span>'
                % (_c("ok"), p.get("dash_port"), _c("dim"), p.get("web_ms") or 0)
                + ('<span style="color:%s"> · dsh 本体 v%s</span>' % (_c("dim"), p["dsh_version"])
                   if p.get("dsh_version") else ""))
            tok = p.get("local_token")
            auth_url = p.get("local_auth_url") or ("http://127.0.0.1:%s" % p.get("dash_port", 3080))
            if tok:
                self._local_token_lbl.setText(
                    '<span style="color:%s">鉴权链接: </span>'
                    '<span style="color:%s; font-family:Consolas,monospace;">%s</span>'
                    % (_c("dim"), _c("ok"), auth_url))
                self._copy_local_link_btn.setEnabled(True)
            else:
                self._local_token_lbl.setText(
                    '<span style="color:%s">鉴权链接: </span>'
                    '<span style="color:%s; font-family:Consolas,monospace;">%s (未捕获到Token)</span>'
                    % (_c("dim"), _c("warn"), auth_url))
                self._copy_local_link_btn.setEnabled(True)
        else:
            self._web_lbl.setText(
                '<span style="color:%s">●</span> dsh web :%s 离线'
                '<span style="color:%s">（可在控制台启动）</span>'
                % (_c("err"), p.get("dash_port"), _c("dim")))
            self._local_token_lbl.setText(
                '<span style="color:%s">鉴权链接: 离线未生成</span>' % _c("dim"))
            self._copy_local_link_btn.setEnabled(False)

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
            tok = item.get("token")
            is_local = bool(item.get("local"))
            if is_local:
                is_online = bool(p.get("web_ok"))
            else:
                is_online = (bool(item.get("web_ok")) if item.get("web_ok") is not None
                             else bool(snap.get("ok")))
            if is_online:
                dot = _c("ok")
                badges = [("在线", "ok")]
                if tok:
                    badges.append(("Token就绪", "ok"))
                else:
                    badges.append(("未同步Token", "warn"))
            else:
                err = str(snap.get("error") or "")
                if "未配置" in err:
                    badge, dot = ("未配置", "dim"), _c("dim")
                else:
                    badge, dot = ("离线", "err"), _c("err")
                badges = [badge]
            rows.append({"title": name, "meta": " · ".join(meta),
                         "dot": dot, "badges": badges, "data": item})
        cur = self._dep_list.currentRow()
        self._dep_list.set_rows(rows)
        if rows:
            target_row = cur if 0 <= cur < len(rows) else 0
            self._dep_list.setCurrentRow(target_row)
        self._on_dep_select()

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

        self._set_status("总览已刷新(数据为只读快照)")

    def _set_status(self, text):
        self._status_lbl.setText(text)

