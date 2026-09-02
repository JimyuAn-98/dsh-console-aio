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

