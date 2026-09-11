# -*- coding: utf-8 -*-
# 部署管理页(UI 层): 上半区部署列表(本机 + config.json deployments), 下半区只读快照详情。
# 业务在 core/deployments.py(纯 Python): 刷新总览/测试连接/保存走 service 信号桥 ——
#   刷新总览: service.refresh_deployments([None] + deployments) 单线程串行快照, 每完成一个
#   经 result("deploy-snap", {"idx","snap"}) 回包(替代旧"每部署一线程+代数/计数"编排);
#   测试连接: result("deploy-test", {"host","msg","err"}); 保存: result("deploy-save", {...})。
#   接收者是页面自身, 页面销毁 Qt 自动断开; log/status 不在页面 connect(主窗口级已接)。
# 部署列表读取(config.json 本地小 IO)同步直调 dsh_data.load_deployments(纯读过渡态)。
# 部署信息只写本地 config.json(gitignored); 远程操作只读; 写操作留待后续版本。
# DshRemote 走 ssh BatchMode(免密), 不收集/保存密码明文(AGENTS.md 安全约定)。

import os
import re

from core import config as dsh_config
from core import data as dsh_data
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPlainTextEdit, QScrollArea,
    QPushButton, QMessageBox, QDialog, QLineEdit, QFormLayout,
    QGridLayout, QWidget, QComboBox, QListWidget, QListWidgetItem)

from core import deployments as core_deployments
from ui.base import BasePage
from ui.widgets import ModernList, ConfirmBanner, card_wrap, three_split


_LOCAL_NAME = "本机"


def _human_size(n):
    # 字节数人性化: B / KB / MB / GB(会话大小展示用)
    n = int(n or 0)
    if n < 1024:
        return "%d B" % n
    if n < 1024 * 1024:
        return "%.1f KB" % (n / 1024.0)
    if n < 1024 * 1024 * 1024:
        return "%.1f MB" % (n / 1024.0 / 1024.0)
    return "%.1f GB" % (n / 1024.0 / 1024.0 / 1024.0)


class _AddDeployDialog(QDialog):
    # 添加/编辑"节点"的对话框(独立 QDialog, 非 BasePage):
    # SSH 连接(name/host/user/port/dsh_home) + 远端 web 端口 + 关联正向隧道 +
    # 本机访问端口 + 节点标识(node_key, 公网信箱 key, ASCII)。
    # 只收集字段并返回 result dict; 写 config.json 由页面负责(save_deployments 自动备份)。
    def __init__(self, deployments, cfg=None, parent=None, edit=None, prefill=None):
        super().__init__(parent)
        self.setWindowTitle("编辑节点" if edit else "添加节点")
        self.setModal(True)
        self._deployments = deployments or []
        self._cfg = cfg or {}
        self._edit = edit or None
        self.result = None
        e = edit or prefill or {}
        self._name = QLineEdit(e.get("name") or "")
        self._host = QLineEdit(e.get("host") or "")
        self._user = QLineEdit(e.get("user") or "")
        self._port = QLineEdit(str(e.get("port") or 22))
        self._home = QLineEdit(e.get("dsh_home") or "~/.dsh")
        self._web_port = QLineEdit(str(e.get("web_port") or ""))
        self._tunnel = QComboBox()
        self._tunnel.addItem("(不关联隧道)", "")
        for tun in dsh_config.normalize_tunnels(self._cfg):
            if (tun.get("mode") or "forward") == "forward":
                self._tunnel.addItem(tun.get("name") or tun.get("id") or "隧道",
                                     tun.get("id") or "")
        idx = self._tunnel.findData(str(e.get("tunnel_id") or ""))
        self._tunnel.setCurrentIndex(idx if idx >= 0 else 0)
        self._access = QLineEdit(str(e.get("access_port") or ""))
        self._node_key = QLineEdit(str(e.get("node_key") or ""))
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)
        root.addWidget(QLabel("编辑远程节点" if self._edit else "添加远程节点",
                              objectName="cardTitle"))
        root.addWidget(QLabel("节点信息只写本地 config.json（自动备份 .bak），不会连接远程。",
                              objectName="cardHint"))
        form = QFormLayout()
        form.addRow("名称", self._name)
        form.addRow("主机", self._host)
        form.addRow("user", self._user)
        form.addRow("SSH 端口", self._port)
        form.addRow("dsh_home", self._home)
        form.addRow("远端 web 端口", self._web_port)
        form.addRow("关联正向隧道", self._tunnel)
        form.addRow("本机访问端口", self._access)
        form.addRow("节点标识(信箱 key)", self._node_key)
        root.addLayout(form)
        hint = QLabel("局域网直连：填「主机 + user」。跨网：主机与 user 留空，填「节点标识」"
                      "（经公网信箱取 Token）。「本机访问端口」留空则按关联隧道/远端 web 端口推导。",
                      objectName="cardHint")
        hint.setWordWrap(True)
        root.addWidget(hint)
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("保存")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._confirm)
        btns.addWidget(cancel_btn)
        btns.addWidget(save_btn)
        root.addLayout(btns)
        self._name.setFocus()

    @staticmethod
    def _opt_port(le):
        # 可选端口字段: 空 -> (None, ""); 非法 -> (None, 错误文案)
        t = le.text().strip()
        if not t:
            return None, ""
        try:
            v = int(t)
            if not (1 <= v <= 65535):
                raise ValueError
            return v, ""
        except ValueError:
            return None, "端口必须是 1-65535 的整数"

    def _confirm(self):
        # 校验并组装节点 dict; 通过后写 result 并 accept(父页面负责保存)
        name = self._name.text().strip()
        host = self._host.text().strip()
        user = self._user.text().strip()
        port_s = self._port.text().strip() or "22"
        home = self._home.text().strip() or "~/.dsh"
        node_key = self._node_key.text().strip()
        if not name:
            QMessageBox.warning(self, "缺少名称", "请填写节点名称。")
            return
        if bool(host) != bool(user):
            QMessageBox.warning(self, "主机/用户不完整",
                                "直连 SSH 需要同时填写「主机」和「user」；"
                                "若只经隧道访问(跨网)，两者留空并填「节点标识」。")
            return
        if not host and not node_key:
            QMessageBox.warning(self, "缺少连接信息",
                                "请填写「主机 + user」(局域网直连)，"
                                "或填写「节点标识」(经公网信箱/隧道访问)。")
            return
        try:
            port = int(port_s)
            if not (1 <= port <= 65535):
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "端口无效", "SSH 端口必须是 1-65535 的整数。")
            return
        web_port, err = self._opt_port(self._web_port)
        if err:
            QMessageBox.warning(self, "远端 web 端口无效", err)
            return
        access_port, err = self._opt_port(self._access)
        if err:
            QMessageBox.warning(self, "访问端口无效", err)
            return
        if node_key and not re.match(r'^[A-Za-z0-9_\-]+$', node_key):
            QMessageBox.warning(self, "节点标识无效",
                                "节点标识只能用字母/数字/下划线/连字符（公网信箱文件名的要求）。")
            return
        # 同主机同用户同端口重复添加会让人混淆, 直接拦截(编辑自身跳过; 仅直连节点)
        if host:
            for d in self._deployments:
                if self._edit is not None and d is self._edit:
                    continue
                if d.get("host") == host and d.get("user") == user and int(d.get("port") or 22) == port:
                    QMessageBox.warning(self, "主机已存在",
                                        "已存在同主机/同用户/同端口的节点「%s」。" % d.get("name"))
                    return
        result = {"name": name, "dsh_home": home}
        if host:
            result["host"] = host
            result["user"] = user
            result["port"] = port
        if web_port:
            result["web_port"] = web_port
        tid = self._tunnel.currentData() or ""
        if tid:
            result["tunnel_id"] = tid
        if access_port:
            result["access_port"] = access_port
        if node_key:
            result["node_key"] = node_key
        self.result = result
        self.accept()


class _MailboxDialog(QDialog):
    # 公网信箱条目列表(只读展示): 选定后「绑定为节点」或「删除条目」。
    def __init__(self, entries, parent=None):
        super().__init__(parent)
        self.setWindowTitle("公网信箱节点")
        self.setModal(True)
        self.action = None
        self.entry = None
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(8)
        v.addWidget(QLabel("公网信箱里发现的节点（主机名 · 节点码 · 最后更新 · Token）",
                           objectName="cardTitle"))
        self._list = QListWidget()
        import time as _t
        for e in entries or []:
            ts = int(e.get("updated_at") or 0)
            when = _t.strftime("%Y-%m-%d %H:%M", _t.localtime(ts)) if ts else "未知"
            tok = "Token就绪" if e.get("token") else "无Token"
            it = QListWidgetItem("%s · %s · %s · %s" % (e.get("hostname") or "(未知主机)",
                                                        e.get("key") or "?", when, tok))
            it.setData(Qt.UserRole, e)
            self._list.addItem(it)
        if self._list.count():
            self._list.setCurrentRow(0)
        v.addWidget(self._list, 1)
        btns = QHBoxLayout()
        bind = QPushButton("绑定为节点")
        bind.clicked.connect(self._bind)
        dele = QPushButton("删除条目")
        dele.clicked.connect(self._delete)
        close = QPushButton("关闭")
        close.clicked.connect(self.reject)
        btns.addWidget(bind)
        btns.addWidget(dele)
        btns.addStretch(1)
        btns.addWidget(close)
        v.addLayout(btns)

    def _selected(self):
        it = self._list.currentItem()
        return it.data(Qt.UserRole) if it is not None else None

    def _bind(self):
        e = self._selected()
        if e:
            self.entry = e
            self.action = "bind"
            self.accept()

    def _delete(self):
        e = self._selected()
        if e:
            self.entry = e
            self.action = "delete"
            self.accept()


class DeploymentPage(BasePage):
    # 部署管理页: 本机 + config.json deployments 的多部署只读总览。
    # BasePage 范式, 构造签名 (app, parent=None), app 为 MainWindow。
    # 部署联动: 进入本页前 app._current_deploy 若选中远程, 载入后预选该行。

    # 详情区字段: (快照键, 界面名)
    _FIELDS = (
        ("name", "名称"),
        ("host", "主机"),
        ("access_port", "访问端口"),
        ("version", "版本"),
        ("sessions", "会话数"),
        ("size", "会话大小"),
        ("plugins", "插件数"),
        ("profiles", "profile 数"),
        ("presets", "agent 预设数"),
        ("error", "错误信息"),
    )

    def __init__(self, app, parent=None):
        self._deployments = []
        self._rows = []          # [{deployment, snap, dep_index, gen}], 与列表行一一对应
        self._gen = 0            # 列表重建代数, 用于丢弃过期快照回调
        self._refreshing = False
        self._pending = 0        # 刷新总览的未回包行数
        self._pending_op = None  # 正在等待的 service op: "deploy-test" / "deploy-save"
        self._last_op_msg = None
        self._preselect = getattr(app, "_current_deploy", None)
        self._list = None
        self._add_btn = None
        self._del_btn = None
        self._test_btn = None
        self._refresh_btn = None
        self._status_lbl = None
        self._detail_lbls = {}
        super().__init__(app, parent)
        self.app.service.result.connect(self._on_result)
        self.app.service.finished.connect(self._on_finished)
        self._load()

    # ── UI 构建 ──────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 12)
        root.setSpacing(8)

        # 状态文字在标题右侧(原底部状态条位置让给横向滚动条)
        self._status_lbl = QLabel("就绪", objectName="monVal")
        head = QHBoxLayout()
        head.addWidget(QLabel("部署管理（多部署只读总览）", objectName="cardTitle"))
        head.addStretch(1)
        head.addWidget(self._status_lbl)
        root.addLayout(head)
        hint = QLabel("部署信息只存本地 config.json；远程只读操作，写操作后续版本提供。",
                      objectName="cardHint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        # ── 三栏: 部署列表 | 详情 | 操作日志 ──
        mid = three_split(
            card_wrap("部署列表（本机 + config.json deployments）", self._make_list()),
            self._make_detail_card(),
            self._make_oplog_card(),
            widths=(280, 360, 330), mins=(280, 340, 340))

        # ── 操作区 ──
        btns = QHBoxLayout()
        self._add_btn = QPushButton("添加部署")
        self._add_btn.clicked.connect(self._add_deployment)
        self._del_btn = QPushButton("删除部署")
        self._del_btn.clicked.connect(self._delete_deployment)
        self._test_btn = QPushButton("测试连接")
        self._test_btn.clicked.connect(self._test_connection)
        self._refresh_btn = QPushButton("刷新总览")
        self._refresh_btn.clicked.connect(self._refresh_all)
        self._copy_link_btn = QPushButton("复制免密链接")
        self._copy_link_btn.setToolTip("复制选中节点的免密访问链接（含鉴权 Token）")
        self._copy_link_btn.clicked.connect(self._copy_auth_link)
        self._open_link_btn = QPushButton("在浏览器打开")
        self._open_link_btn.setToolTip("用系统默认浏览器打开选中节点的免密访问链接")
        self._open_link_btn.clicked.connect(self._open_auth_link)
        self._edit_btn = QPushButton("编辑节点")
        self._edit_btn.clicked.connect(self._edit_deployment)
        self._discover_btn = QPushButton("从公网信箱发现")
        self._discover_btn.setToolTip("列出公网信箱里已投递 Token 的节点, 可直接绑定为远程节点")
        self._discover_btn.clicked.connect(self._discover_mailbox)
        for b in (self._add_btn, self._edit_btn, self._del_btn, self._test_btn,
                  self._refresh_btn, self._copy_link_btn, self._open_link_btn,
                  self._discover_btn):
            btns.addWidget(b)
        btns.addStretch(1)
        note = QLabel("本机不可删除；状态来自 deployment_snapshot(在线/离线/未测试)",
                      objectName="cardHint")
        btns.addWidget(note)

        mid.setMinimumWidth(1020)
        content = QWidget()
        cv = QVBoxLayout(content)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(8)
        cv.addWidget(mid, 1)

        self._confirm = ConfirmBanner(self)
        cv.addWidget(self._confirm)

        cv.addLayout(btns)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

    # ── 三栏构建(部署|详情|操作日志) ──
    def _make_list(self):
        self._list = ModernList()
        self._list.itemSelectionChanged.connect(self._on_select)
        return self._list

    def _make_detail_card(self):
        detail = QFrame(objectName="card")
        dv = QVBoxLayout(detail)
        dv.setContentsMargins(12, 10, 12, 10)
        dv.setSpacing(4)
        dv.addWidget(QLabel("部署详情（只读）", objectName="rightTitle"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(4)
        for i, (_key, label) in enumerate(self._FIELDS):
            grid.addWidget(QLabel(label, objectName="monNote"), i, 0, Qt.AlignLeft)
            val = QLabel("-", objectName="monVal")
            val.setWordWrap(True)
            grid.addWidget(val, i, 1)
            self._detail_lbls[_key] = val
        grid.setColumnStretch(1, 1)
        dv.addLayout(grid)
        dv.addStretch(1)
        return detail

    def _make_oplog_card(self):
        card = QFrame(objectName="card")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(12, 10, 12, 10)
        cv.setSpacing(4)
        cv.addWidget(QLabel("操作日志", objectName="rightTitle"))
        cv.addWidget(QLabel("测试连接/刷新总览/保存的结果就地显示(带时间戳), 同时进主日志区。",
                            objectName="cardHint"))
        self._op_log = QPlainTextEdit()
        self._op_log.setReadOnly(True)
        self._op_log.setFont(QFont("Consolas", 9))
        self._op_log.setMaximumBlockCount(500)
        cv.addWidget(self._op_log, 1)
        return card

    def _op(self, text, tag=""):
        # 操作日志一行: 时间戳 + 语义色(绿 ok/红 err/灰 普通); 主日志区照常输出
        import time as _t
        color = {"ok": "#7ecb6a", "err": "#e07a7a"}.get(tag, "#9a9ab0")
        stamp = _t.strftime("%H:%M:%S")
        self._op_log.appendHtml(
            '<span style="color:#6a6a80">%s</span>  <span style="color:%s">%s</span>'
            % (stamp, color, text))

    # ── 数据加载与列表渲染(本地小 IO 同步直调) ──
    def _load(self):
        # 读 config.json 的 deployments(本地小 IO 同步直调); "本机"始终作为第一行
        self._set_status("正在读取部署列表...")
        try:
            depls = dsh_data.load_deployments() or []
            err = ""
        except Exception as e:
            depls, err = [], str(e)
        self._deployments = depls
        self._render_rows()
        if err:
            self._set_status("读取失败: " + err)
            self.app.loge("[部署管理] 读取失败: " + err, "err")
        elif self._last_op_msg:
            self._set_status(self._last_op_msg)
            self._last_op_msg = None
        else:
            self._set_status("共 %d 个部署（含本机）" % (len(depls) + 1))

    def _render_rows(self):
        # 重建列表: 第 0 行本机, 其后为 config 里的每个部署
        self._gen += 1
        self._pending = 0   # 列表重建后旧刷新的过期回包不再计数
        if self._refresh_btn is not None:
            self._refresh_btn.setEnabled(True)
        self._rows = []
        entries = [(None, _LOCAL_NAME, "本地", "-", "-")] + [
            (d, d.get("name") or d.get("host") or "-", d.get("host") or "-",
             str(d.get("port") or 22), d.get("user") or "-")
            for d in self._deployments
        ]
        rows = []
        for idx, (dep, name, host, port, user) in enumerate(entries):
            row = {"deployment": dep, "snap": None, "dep_index": idx - 1, "gen": self._gen}
            self._rows.append(row)
            rows.append({
                "title": name,
                "meta": "本地 dsh 实例" if dep is None else "%s · %s" % (host, user),
                "dot": "#9a9ab0",
                "badges": [("未测试", "dim")],
                "data": row,
            })
        self._list.set_rows(rows)
        self._fill_detail(None)
        self._update_action_btns()
        self._preselect_row()

    def _preselect_row(self):
        # 部署联动: 进入本页前 app._current_deploy 已选中的部署, 载入后预选对应行
        dep = self._preselect
        if not self._rows:
            return
        if dep is None:
            self._list.setCurrentRow(0)
            return
        for idx, row in enumerate(self._rows):
            d = row["deployment"]
            if d and (d.get("host") == dep.get("host") and
                      d.get("user") == dep.get("user") and
                      int(d.get("port") or 22) == int(dep.get("port") or 22)):
                self._list.setCurrentRow(idx)
                return

    def _selected_row(self):
        # 当前选中行对应的内部 row dict; 未选中返回 None
        lr = self._list.current_data()
        return lr.get("data") if lr else None

    # ── 选择与详情 ─────────────────────────────
    def _on_select(self):
        row = self._selected_row()
        self._fill_detail(row)
        self._update_action_btns()

    def _update_action_btns(self):
        # 本机行不可删除/测试; 未选中时也禁用
        row = self._selected_row()
        is_local = row is not None and row["deployment"] is None
        if self._del_btn is not None:
            self._del_btn.setEnabled(row is not None and not is_local)
        if self._test_btn is not None:
            has_host = bool(row is not None and (row["deployment"] or {}).get("host"))
            self._test_btn.setEnabled(row is not None and not is_local and has_host)
        if getattr(self, "_edit_btn", None) is not None:
            self._edit_btn.setEnabled(row is not None and not is_local)
        if getattr(self, "_copy_link_btn", None) is not None:
            self._copy_link_btn.setEnabled(row is not None)
        if getattr(self, "_open_link_btn", None) is not None:
            self._open_link_btn.setEnabled(row is not None)

    def _auth_url_for(self, dep):
        # 节点的 (显示名, 访问端口, 免密链接): 本机走 dash_port; 远程走共享的端口推导
        from core.dshctl import get_runtime_token
        cfg = dsh_config.load_config()
        if dep is None:
            tok = get_runtime_token("local")
            port = cfg.get("dash_port") or 3080
            name = _LOCAL_NAME
        else:
            name = dep.get("name") or "remote"
            tok = get_runtime_token(name)
            port = dsh_data.deployment_access_port(dep, cfg)
        url = (("http://127.0.0.1:%s/?token=%s" % (port, tok)) if tok
               else ("http://127.0.0.1:%s" % port))
        return name, port, url

    def _copy_auth_link(self):
        row = self._selected_row()
        if not row:
            return
        name, _port, url = self._auth_url_for(row["deployment"])
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(url)
        self._op("已复制「%s」免密访问链接: %s" % (name, url), "ok")
        self.app.loge("已复制「%s」免密访问链接至剪贴板: %s" % (name, url), "ok")

    def _open_auth_link(self):
        row = self._selected_row()
        if not row:
            return
        name, _port, url = self._auth_url_for(row["deployment"])
        try:
            os.startfile(url)
            self._op("已在浏览器打开「%s」: %s" % (name, url), "ok")
            self.app.loge("已打开「%s」免密访问链接: %s" % (name, url), "ok")
        except Exception as e:
            self._op("打开失败: %s" % e, "err")

    def _fill_detail(self, row):
        # 只读展示快照字段; 未选中或未测过时用占位符
        if row is None:
            for key in self._detail_lbls:
                self._detail_lbls[key].setText("-")
            return
        dep = row["deployment"]
        snap = row["snap"]
        local = dep is None
        cfg = dsh_config.load_config()
        name = _LOCAL_NAME if local else (dep.get("name") or dep.get("host") or "-")
        host = "本地" if local else (dep.get("host") or "-")
        access = (str(cfg.get("dash_port") or 3080) if local
                  else str(dsh_data.deployment_access_port(dep, cfg) or "-"))
        if snap is None:
            vals = {"name": name, "host": host, "access_port": access,
                    "version": "-", "sessions": "-", "size": "-",
                    "plugins": "-", "profiles": "-", "presets": "-",
                    "error": "未测试（点“刷新总览”获取）"}
        else:
            vals = {
                "name": name,
                "host": host,
                "access_port": access,
                "version": snap.get("version") or "-",
                "sessions": str(snap.get("sessions") or 0),
                "size": _human_size(snap.get("session_bytes")),
                "plugins": str(snap.get("plugins") or 0),
                "profiles": str(snap.get("profiles") or 0),
                "presets": str(snap.get("presets") or 0),
                "error": "无" if snap.get("ok") else (snap.get("error") or "未知错误"),
            }
        for key, text in vals.items():
            if key in self._detail_lbls:
                self._detail_lbls[key].setText(text)

    # ── 添加 / 删除(写 config.json 走 service 信号桥) ──
    def _add_deployment(self):
        # 小对话框收集字段 -> service.save_deployments(数据层自动备份)
        dlg = _AddDeployDialog(self._deployments, dsh_config.load_config(), self)
        if dlg.exec() != QDialog.Accepted or not dlg.result:
            return
        self._deployments = list(self._deployments) + [dlg.result]
        self._save_and_reload("已添加节点「%s」" % dlg.result.get("name"))

    def _edit_deployment(self):
        # 编辑选中远程节点(本机不可编辑); 写回 config.json 走 service
        row = self._selected_row()
        if row is None or row["deployment"] is None:
            return
        dep = row["deployment"]
        dlg = _AddDeployDialog(self._deployments, dsh_config.load_config(), self, edit=dep)
        if dlg.exec() != QDialog.Accepted or not dlg.result:
            return
        idx = row["dep_index"]
        if 0 <= idx < len(self._deployments):
            self._deployments = list(self._deployments)
            self._deployments[idx] = dlg.result
        self._save_and_reload("已更新节点「%s」" % dlg.result.get("name"))

    # ── 从公网信箱发现/管理节点 ──
    def _discover_mailbox(self):
        cfg = dsh_config.load_config()
        if not (cfg.get("ssh_server") and cfg.get("ssh_user")):
            self._op("公网信箱不可用: 未配置公网中转服务器（设置页）", "err")
            return
        self._op("正在读取公网信箱...", "warn")
        self.app.service.list_mailbox_nodes(cfg, op="mailbox-list")

    def _show_mailbox(self, entries):
        if not entries:
            self._op("公网信箱为空（远端控制台尚未投递 Token）", "err")
            return
        dlg = _MailboxDialog(entries, self)
        if dlg.exec() != QDialog.Accepted or not dlg.entry:
            return
        e = dlg.entry
        if dlg.action == "bind":
            cfg = dsh_config.load_config()
            prefill = {"name": e.get("hostname") or e.get("key") or "remote",
                       "node_key": e.get("key") or ""}
            add = _AddDeployDialog(self._deployments, cfg, self, prefill=prefill)
            if add.exec() == QDialog.Accepted and add.result:
                self._deployments = list(self._deployments) + [add.result]
                self._save_and_reload("已从信箱绑定节点「%s」" % add.result.get("name"))
        elif dlg.action == "delete":
            cfg = dsh_config.load_config()
            self.app.service.delete_mailbox_node(cfg, e.get("key") or "", op="mailbox-del")

    def _delete_deployment(self):
        # 删除 config.json 里的部署记录(本机不可删); 远程数据不受影响
        row = self._selected_row()
        if row is None or row["deployment"] is None:
            return
        dep = row["deployment"]
        name = dep.get("name") or "-"
        host = dep.get("host") or "-"

        def do_delete():
            idx = row["dep_index"]
            if 0 <= idx < len(self._deployments):
                del self._deployments[idx]
            self._save_and_reload("已删除部署记录")

        self._confirm.ask(
            "删除部署「%s」" % name,
            "将从本地 config.json 中删除部署记录（主机 %s）。此操作不会连接或改动远程机器数据。" % host,
            do_delete,
            level="danger",
            confirm_text="确认删除"
        )

    def _save_and_reload(self, msg):
        # 写回 config.json 走 service(数据层自动 .bak); 结果经 result("deploy-save") 回包
        self._pending_op = "deploy-save"
        self._save_msg = msg
        self._set_btns(False)
        self._set_status("正在保存部署列表...")
        self.app.service.save_deployments(list(self._deployments))

    # ── 测试连接(service 信号桥) ──
    def _test_connection(self):
        # 对选中远程部署 ssh 执行 "echo ok"(core); 本机行不可测(按钮已禁用)
        row = self._selected_row()
        if row is None or row["deployment"] is None:
            return
        dep = row["deployment"]
        host = dep.get("host") or "-"
        self._pending_op = "deploy-test"
        self._set_btns(False)
        self._set_status("正在测试 %s ..." % host)
        self.app.set_status("正在测试部署 %s ..." % host)
        self.app.service.test_deployment(dep)

    # ── 刷新总览(service 单线程串行快照) ──
    def _refresh_all(self):
        # 对每个部署(含本机)快照: core 串行执行, 每完成一个 result("deploy-snap") 回包
        if self._refreshing or self._pending > 0:
            return
        deps = [None] + list(self._deployments)
        self._refreshing = True
        self._pending = len(deps)
        if self._refresh_btn is not None:
            self._refresh_btn.setEnabled(False)
        self._set_btns(False)
        self._set_status("正在刷新 %d 个部署 ..." % self._pending)
        self.app.set_status("正在刷新 %d 个部署 ..." % self._pending)
        self.app.service.refresh_deployments(deps)

    # ── service 信号槽(接收者=本页, 销毁自动断开) ──
    def _on_result(self, op, payload):
        if op == "deploy-snap":
            self._apply_snapshot(payload.get("idx"), payload.get("snap"))
        elif op == "deploy-test":
            self._pending_op = None
            self._set_btns(True)
            self._after_test(payload.get("host", ""), payload.get("msg", ""),
                             payload.get("err", ""))
        elif op == "deploy-save":
            self._pending_op = None
            self._set_btns(True)
            self._after_save(self._save_msg, payload.get("err", ""))
        elif op == "mailbox-list":
            self._show_mailbox(payload.get("data") or [])
        elif op == "mailbox-del":
            d = payload.get("data") or {}
            if payload.get("err") or not d.get("ok"):
                self._op("删除信箱条目失败: " + str(payload.get("err") or d.get("err") or ""), "err")
            else:
                self._op("已删除信箱条目: " + str(d.get("key") or ""), "ok")
            self._discover_mailbox()

    def _on_finished(self, op, ok):
        # 刷新总览整批收尾(每行回包已由 _apply_snapshot 计数); 其余 op 作 busy 兜底
        if op == "deploy-refresh":
            self._refreshing = False
            if self._pending > 0:
                # 理论上 result 已逐行清零; 兜底防止计数错漏导致按钮永禁
                self._pending = 0
                if self._refresh_btn is not None:
                    self._refresh_btn.setEnabled(True)
                self._set_btns(True)
                self._set_status("总览刷新完成")
                self.app.set_status("部署总览刷新完成")
        elif op == self._pending_op:
            self._pending_op = None
            self._set_btns(True)

    def _after_save(self, msg, err):
        if err:
            self._set_status("保存失败: " + err)
            self.app.loge("[部署管理] 写入 config.json 失败: " + err, "err")
            self._op("保存失败: " + err, "err")
            QMessageBox.critical(self, "保存失败", "写入 config.json 失败：\n" + err)
            return
        self.app.loge("[部署管理] " + msg, "ok")
        self._op(msg, "ok")
        self._last_op_msg = msg
        self._load()

    def _after_test(self, host, msg, err):
        if err:
            self._set_status(err)
            self.app.set_status(err)
            self.app.loge("[部署管理] " + err, "err")
            self._op("%s · %s" % (host, err), "err")
            return
        self._set_status(msg)
        self.app.set_status(msg)
        self.app.loge("[部署管理] " + msg, "ok")
        self._op("%s · %s" % (host, msg), "ok")

    def _apply_snapshot(self, idx, snap):
        # 应用单行快照: 更新该行状态徽章/状态点; 若该行正被选中则同步刷新详情
        if not isinstance(snap, dict) or not isinstance(idx, int):
            return
        if not (0 <= idx < len(self._rows)):
            return
        row = self._rows[idx]
        if row.get("gen") != self._gen:
            return   # 列表已重建, 丢弃过期回调
        row["snap"] = snap
        ok = bool(snap.get("ok"))
        status = "在线" if ok else "离线"
        color = "#7ecb6a" if ok else "#e07a7a"
        self._set_row_status(idx, status, color, ok)
        self._op("%s · %s" % (self._row_title(idx), status), "ok" if ok else "err")
        cur = self._selected_row()
        if cur is row:
            self._fill_detail(row)
        self._pending -= 1
        if self._pending <= 0 and self._refreshing:
            self._refreshing = False
            self._pending = 0
            if self._refresh_btn is not None:
                self._refresh_btn.setEnabled(True)
            self._set_status("总览刷新完成")
            self.app.set_status("部署总览刷新完成")

    def _set_row_status(self, idx, status, color, ok):
        # 更新列表行的状态徽章与状态点: 改 Python 侧行数据(权威), 再同步 item 副本重绘
        lr = self._list.row_data(idx)
        if lr is None:
            return
        lr["dot"] = color
        lr["badges"] = [(status, "ok" if ok else "err")]
        self._list.item(idx).setData(Qt.UserRole, lr)
        self._list.viewport().update()

    def _row_title(self, idx):
        lr = self._list.row_data(idx)
        return (lr or {}).get("title") or "?"

    # ── 状态与按钮 ─────────────────────────────
    def _set_btns(self, on):
        for b in (self._add_btn, self._del_btn, self._test_btn, self._refresh_btn):
            b.setEnabled(on)

    def _set_status(self, text):
        if self._status_lbl is not None:
            self._status_lbl.setText(text)
