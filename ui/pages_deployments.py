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

from core import data as dsh_data
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView, QMessageBox, QDialog, QLineEdit, QFormLayout,
    QGridLayout)

from core import deployments as core_deployments
from ui.base import BasePage


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
    # 添加部署的小对话框(独立 QDialog, 非 BasePage): 名称/主机/user/端口(默认22)/dsh_home(默认~/.dsh)。
    # 只收集字段并返回 result dict; 写 config.json 由页面负责(save_deployments 自动备份)。
    def __init__(self, deployments, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加部署")
        self.setModal(True)
        self._deployments = deployments or []
        self.result = None
        self._name = QLineEdit()
        self._host = QLineEdit()
        self._user = QLineEdit()
        self._port = QLineEdit("22")
        self._home = QLineEdit("~/.dsh")
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)
        title = QLabel("添加远程部署", objectName="cardTitle")
        root.addWidget(title)
        hint = QLabel("部署信息只写本地 config.json（自动备份 .bak），不会连接远程。",
                      objectName="cardHint")
        root.addWidget(hint)
        form = QFormLayout()
        form.addRow("名称", self._name)
        form.addRow("主机", self._host)
        form.addRow("user", self._user)
        form.addRow("端口", self._port)
        form.addRow("dsh_home", self._home)
        root.addLayout(form)
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

    def _confirm(self):
        # 校验并组装部署 dict; 通过后写 result 并 accept(父页面负责保存)
        name = self._name.text().strip()
        host = self._host.text().strip()
        user = self._user.text().strip()
        port_s = self._port.text().strip() or "22"
        home = self._home.text().strip() or "~/.dsh"
        if not name:
            QMessageBox.warning(self, "缺少名称", "请填写部署名称。")
            return
        if not host:
            QMessageBox.warning(self, "缺少主机", "请填写主机地址(IP 或域名)。")
            return
        if not user:
            QMessageBox.warning(self, "缺少用户", "请填写 SSH 用户名。")
            return
        try:
            port = int(port_s)
            if not (1 <= port <= 65535):
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "端口无效", "端口必须是 1-65535 的整数。")
            return
        # 同主机同用户同端口重复添加会让人混淆, 直接拦截
        for d in self._deployments:
            if d.get("host") == host and d.get("user") == user and int(d.get("port") or 22) == port:
                QMessageBox.warning(self, "主机已存在",
                                    "已存在同主机/同用户/同端口的部署「%s」。" % d.get("name"))
                return
        self.result = {"name": name, "host": host, "user": user,
                       "port": port, "dsh_home": home}
        self.accept()


class DeploymentPage(BasePage):
    # 部署管理页: 本机 + config.json deployments 的多部署只读总览。
    # BasePage 范式, 构造签名 (app, parent=None), app 为 MainWindow。
    # 部署联动: 进入本页前 app._current_deploy 若选中远程, 载入后预选该行。

    # 详情区字段: (快照键, 界面名)
    _FIELDS = (
        ("name", "名称"),
        ("host", "主机"),
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
        self._rows = []          # [{deployment, snap, dep_index, gen}], 与表格行一一对应
        self._gen = 0            # 列表重建代数, 用于丢弃过期快照回调
        self._refreshing = False
        self._pending = 0        # 刷新总览的未回包行数
        self._pending_op = None  # 正在等待的 service op: "deploy-test" / "deploy-save"
        self._last_op_msg = None
        self._preselect = getattr(app, "_current_deploy", None)
        self._table = None
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

        title = QLabel("部署管理（多部署只读总览）", objectName="cardTitle")
        root.addWidget(title)
        hint = QLabel("部署信息只存本地 config.json；远程只读操作，写操作后续版本提供。",
                      objectName="cardHint")
        root.addWidget(hint)

        # ── 上半区: 部署列表 ──
        self._table = self._make_table(
            ["名称", "主机", "端口", "用户", "状态"], ["w", "w", "center", "w", "center"],
            [160, 200, 60, 100, 70], stretch_col=1)
        self._table.itemSelectionChanged.connect(self._on_select)
        root.addWidget(self._wrap_table("部署列表（本机 + config.json deployments）",
                                        self._table), 1)

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
        for b in (self._add_btn, self._del_btn, self._test_btn, self._refresh_btn):
            btns.addWidget(b)
        btns.addStretch(1)
        note = QLabel("本机不可删除；状态来自 deployment_snapshot(在线/离线/未测试)",
                      objectName="cardHint")
        btns.addWidget(note)
        root.addLayout(btns)

        # ── 下半区: 选中部署详情(只读) ──
        detail = QFrame(objectName="card")
        dv = QVBoxLayout(detail)
        dv.setContentsMargins(10, 8, 10, 8)
        dv.setSpacing(2)
        dv.addWidget(QLabel("部署详情（只读）", objectName="rightTitle"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(2)
        for i, (_key, label) in enumerate(self._FIELDS):
            grid.addWidget(QLabel(label, objectName="monName"), i, 0, Qt.AlignLeft)
            val = QLabel("-", objectName="monVal")
            val.setWordWrap(True)
            grid.addWidget(val, i, 1)
            self._detail_lbls[_key] = val
        grid.setColumnStretch(1, 1)
        dv.addLayout(grid)
        root.addWidget(detail)

        # ── 页面内状态行 ──
        self._status_lbl = QLabel("就绪", objectName="statusBar")
        root.addWidget(self._status_lbl)

    def _make_table(self, headers, anchors, widths, stretch_col):
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.verticalHeader().setVisible(False)
        t.setSelectionBehavior(QTableWidget.SelectRows)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        hh = t.horizontalHeader()
        for i, (a, wd) in enumerate(zip(anchors, widths)):
            hh.setSectionResizeMode(i, QHeaderView.ResizeToContents if i != stretch_col
                                    else QHeaderView.Stretch)
            t.setColumnWidth(i, wd)
            if a == "e":
                t.horizontalHeaderItem(i).setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            elif a == "center":
                t.horizontalHeaderItem(i).setTextAlignment(Qt.AlignCenter)
        t.setSelectionMode(QTableWidget.SingleSelection)
        return t

    def _wrap_table(self, caption, table):
        card = QFrame(objectName="card")
        v = QVBoxLayout(card)
        v.setContentsMargins(10, 8, 10, 8)
        cap = QLabel(caption, objectName="rightTitle")
        v.addWidget(cap)
        v.addWidget(table)
        return card

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
        # 重建表格: 第 0 行本机, 其后为 config 里的每个部署
        if self._table is None:
            return
        self._table.setRowCount(0)
        self._gen += 1
        self._pending = 0   # 列表重建后旧刷新的过期回包不再计数
        if self._refresh_btn is not None:
            self._refresh_btn.setEnabled(True)
        self._rows = []
        rows = [(None, _LOCAL_NAME, "本地", "-", "-")] + [
            (d, d.get("name") or d.get("host") or "-", d.get("host") or "-",
             str(d.get("port") or 22), d.get("user") or "-")
            for d in self._deployments
        ]
        self._table.setRowCount(len(rows))
        for idx, (dep, name, host, port, user) in enumerate(rows):
            self._rows.append({"deployment": dep, "snap": None,
                               "dep_index": idx - 1, "gen": self._gen})
            items = (QTableWidgetItem(name), QTableWidgetItem(host),
                     QTableWidgetItem(port), QTableWidgetItem(user),
                     QTableWidgetItem("未测试"))
            for c, it in enumerate(items):
                if c == 4:
                    it.setForeground(QColor("#888888"))
                    it.setTextAlignment(Qt.AlignCenter)
                self._table.setItem(idx, c, it)
        self._table.clearSelection()
        self._fill_detail(None)
        self._update_action_btns()
        self._preselect_row()

    def _preselect_row(self):
        # 部署联动: 进入本页前 app._current_deploy 已选中的部署, 载入后预选对应行
        dep = self._preselect
        if not self._rows:
            return
        if dep is None:
            self._table.selectRow(0)
            return
        for idx, row in enumerate(self._rows):
            d = row["deployment"]
            if d and (d.get("host") == dep.get("host") and
                      d.get("user") == dep.get("user") and
                      int(d.get("port") or 22) == int(dep.get("port") or 22)):
                self._table.selectRow(idx)
                return

    def _selected_row(self):
        # 当前选中行对应的 row dict; 未选中返回 None
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        idx = rows[0].row()
        if 0 <= idx < len(self._rows):
            return self._rows[idx]
        return None

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
            self._test_btn.setEnabled(row is not None and not is_local)

    def _fill_detail(self, row):
        # 只读展示快照字段; 未选中或未测过时用占位符
        if row is None:
            for key in self._detail_lbls:
                self._detail_lbls[key].setText("-")
            return
        dep = row["deployment"]
        snap = row["snap"]
        local = dep is None
        name = _LOCAL_NAME if local else (dep.get("name") or dep.get("host") or "-")
        host = "本地" if local else (dep.get("host") or "-")
        if snap is None:
            vals = {"name": name, "host": host,
                    "version": "-", "sessions": "-", "size": "-",
                    "plugins": "-", "profiles": "-", "presets": "-",
                    "error": "未测试（点“刷新总览”获取）"}
        else:
            vals = {
                "name": name,
                "host": host,
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
        dlg = _AddDeployDialog(self._deployments, self)
        if dlg.exec() != QDialog.Accepted or not dlg.result:
            return
        self._deployments = list(self._deployments) + [dlg.result]
        self._save_and_reload("已添加部署「%s」" % dlg.result.get("name"))

    def _delete_deployment(self):
        # 删除 config.json 里的部署记录(本机不可删); 远程数据不受影响
        row = self._selected_row()
        if row is None or row["deployment"] is None:
            return
        dep = row["deployment"]
        name = dep.get("name") or "-"
        host = dep.get("host") or "-"
        msg = ("将删除部署「%s」（主机 %s）的本地记录。\n"
               "仅删除本地 config.json 中的记录，不会改动远程任何数据。\n\n"
               "是否继续？" % (name, host))
        if QMessageBox.question(self, "删除部署", msg) != QMessageBox.Yes:
            return
        idx = row["dep_index"]
        if 0 <= idx < len(self._deployments):
            del self._deployments[idx]
        self._save_and_reload("已删除部署记录")

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
            QMessageBox.critical(self, "保存失败", "写入 config.json 失败：\n" + err)
            return
        self.app.loge("[部署管理] " + msg, "ok")
        self._last_op_msg = msg
        self._load()

    def _after_test(self, host, msg, err):
        if err:
            self._set_status(err)
            self.app.set_status(err)
            self.app.loge("[部署管理] " + err, "err")
            return
        self._set_status(msg)
        self.app.set_status(msg)
        self.app.loge("[部署管理] " + msg, "ok")

    def _apply_snapshot(self, idx, snap):
        # 应用单行快照: 更新状态列; 若该行正被选中则同步刷新详情
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
        it = self._table.item(idx, 4)
        if it is not None:
            it.setText(status)
            it.setForeground(QColor(color))
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

    # ── 状态与按钮 ─────────────────────────────
    def _set_btns(self, on):
        for b in (self._add_btn, self._del_btn, self._test_btn, self._refresh_btn):
            b.setEnabled(on)

    def _set_status(self, text):
        if self._status_lbl is not None:
            self._status_lbl.setText(text)
