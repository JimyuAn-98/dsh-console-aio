# -*- coding: utf-8 -*-
# ui/pages_overview.py - 部署总览页: 运行状态卡 + 数据速览 + 部署列表 + 隧道速览。
# 数据经 service 信号桥调度回主线程; 接入 core/cache 缓存, 进页秒开+按需刷新。

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton)

from core import cache as core_cache
from core import data as dsh_data
from core import config as dsh_config
from ui.base import BasePage
from ui.widgets import ModernList, RefreshIndicator, card_wrap


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
        head.addWidget(QLabel("部署总览", objectName="cardTitle"))
        self._spinner = RefreshIndicator()
        self._spinner.setToolTip("刷新状态: 绿=无变化 / 黄=数据有变化 / 红=获取错误")
        head.addWidget(self._spinner)
        head.addStretch(1)
        self._status_lbl = QLabel("就绪", objectName="monVal")
        head.addWidget(self._status_lbl)
        refresh = QPushButton("刷新", objectName="primary")
        refresh.clicked.connect(lambda: self.refresh(force=True))
        head.addWidget(refresh)
        root.addLayout(head)
        root.addWidget(QLabel("本机与远程部署的实时状态、数据速览与隧道探测(纯读获取, 进页自动取缓存)。",
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
        dh.addWidget(QLabel("部署", objectName="rightTitle"))
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
        dv.addLayout(dh)
        self._dep_list = ModernList()
        self._dep_list.itemSelectionChanged.connect(self._on_dep_select)
        self._dep_list.itemClicked.connect(lambda _: self._on_dep_select())
        dv.addWidget(self._dep_list, 1)
        root.addWidget(dep_card, 1)

        # 隧道速览(富文本圆点, 与右栏监控同口径)
        self._tunnel_lbl = QLabel("", objectName="monName")
        self._tunnel_lbl.setTextFormat(Qt.RichText)
        self._tunnel_lbl.setWordWrap(True)
        root.addWidget(card_wrap("隧道状态", self._tunnel_lbl))

    def _selected_item_data(self):
        row = self._dep_list.current_data()
        return row.get("data") if (isinstance(row, dict) and "data" in row) else row

    def _on_dep_select(self):
        item = self._selected_item_data()
        if not item:
            self._copy_link_btn.setEnabled(False)
            self._dep_auth_lbl.setText("")
            return
        url = item.get("auth_url") or ""
        tok = item.get("token")
        name = item.get("dep", {}).get("name") or "节点"
        snap = item.get("snap") or {}
        is_local = bool(item.get("local"))
        is_online = (getattr(self, "_last_payload", {}).get("web_ok") if is_local else snap.get("ok"))
        if is_online:
            if tok:
                self._dep_auth_lbl.setText(
                    '<span style="color:#9a9ab0">「%s」免密链接: </span>'
                    '<span style="color:#7ecb6a; font-family:Consolas,monospace;">%s</span>'
                    % (name, url))
            else:
                self._dep_auth_lbl.setText(
                    '<span style="color:#9a9ab0">「%s」免密链接: </span>'
                    '<span style="color:#e0a050; font-family:Consolas,monospace;">%s (信箱未同步Token)</span>'
                    % (name, url))
            self._copy_link_btn.setEnabled(bool(url))
        else:
            self._dep_auth_lbl.setText(
                '<span style="color:#9a9ab0">「%s」: </span>'
                '<span style="color:#e07a7a;">离线 / 未配置</span>' % name)
            self._copy_link_btn.setEnabled(False)

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

    # ── 读取(先读缓存, mtime 变化或强制时后台拉取) ──
    def refresh(self, force=False):
        if self._busy and not force:
            return
        cfg = dsh_config.load_config()
        src_mtime = dsh_data.overview_source_mtime(cfg)
        cache_data, _ = core_cache.read_cache("overview")
        if not force and cache_data is not None and not core_cache.needs_refresh("overview", src_mtime):
            # 缓存已是最新: 秒开直接呈现, 标绿
            self._apply_data(cache_data)
            self._spinner.set_status("ok")
            self._spinner.setToolTip("无变化(缓存已是最新)")
            return

        self._busy = True
        self._set_status("正在读取总览数据...")
        self._spinner.set_loading(True)
        depls = dsh_data.load_deployments()
        smoke = bool(getattr(self.app, "smoke", False))
        self.app.service.read_overview(cfg, depls, smoke=smoke, op="overview-read")

    def _on_result(self, op, payload):
        if op == "overview-read":
            self._busy = False
            self._spinner.set_loading(False)
            err = payload.get("err")
            data = payload.get("data")
            if err or not isinstance(data, dict):
                self._set_status("总览读取失败: " + str(err or "未知错误"))
                self._spinner.set_status("err")
                self._spinner.setToolTip("数据获取错误: " + str(err or "未知错误"))
                return
            changed = core_cache.data_changed("overview", data)
            core_cache.write_cache("overview", data)
            self._apply_data(data)
            if changed:
                self._spinner.set_status("warn")
                self._spinner.setToolTip("数据有变化(已刷新)")
            else:
                self._spinner.set_status("ok")
                self._spinner.setToolTip("无变化(缓存已是最新)")

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
                '<span style="color:#7ecb6a">●</span> dsh web :%s 在线'
                '<span style="color:#9a9ab0">（%d ms）</span>'
                % (p.get("dash_port"), p.get("web_ms") or 0)
                + ('<span style="color:#9a9ab0"> · dsh 本体 v%s</span>' % p["dsh_version"]
                   if p.get("dsh_version") else ""))
            tok = p.get("local_token")
            auth_url = p.get("local_auth_url") or ("http://127.0.0.1:%s" % p.get("dash_port", 3080))
            if tok:
                self._local_token_lbl.setText(
                    '<span style="color:#9a9ab0">鉴权链接: </span>'
                    '<span style="color:#7ecb6a; font-family:Consolas,monospace;">%s</span>'
                    % auth_url)
                self._copy_local_link_btn.setEnabled(True)
            else:
                self._local_token_lbl.setText(
                    '<span style="color:#9a9ab0">鉴权链接: </span>'
                    '<span style="color:#e0a050; font-family:Consolas,monospace;">%s (未捕获到Token)</span>'
                    % auth_url)
                self._copy_local_link_btn.setEnabled(True)
        else:
            self._web_lbl.setText(
                '<span style="color:#e07a7a">●</span> dsh web :%s 离线'
                '<span style="color:#9a9ab0">（可在控制台启动）</span>' % p.get("dash_port"))
            self._local_token_lbl.setText('<span style="color:#9a9ab0">鉴权链接: 离线未生成</span>')
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
            is_online = (p.get("web_ok") if is_local else snap.get("ok"))
            if is_online:
                dot = "#7ecb6a"
                badges = [("在线", "ok")]
                if tok:
                    badges.append(("Token就绪", "ok"))
                else:
                    badges.append(("未同步Token", "warn"))
            else:
                err = str(snap.get("error") or "")
                if "未配置" in err:
                    badge, dot = ("未配置", "dim"), "#9a9ab0"
                else:
                    badge, dot = ("离线", "err"), "#e07a7a"
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

