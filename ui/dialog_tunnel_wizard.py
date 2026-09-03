# -*- coding: utf-8 -*-
# ui/dialog_tunnel_wizard.py - 隧道创建助手与场景向导对话框。
# 包含场景模板(在家中继/内网反向/局域网直连/从部署生成)与高级自定义，带端口冲突检测。

import uuid
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QTabWidget, QWidget, QFormLayout, QLineEdit, QComboBox, QCheckBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QRadioButton,
    QButtonGroup)

from core import config as dsh_config
from core import tunnel_mgr as dsh_tunnels
from core import data as dsh_data


class TunnelWizardDialog(QDialog):
    # 隧道创建向导与编辑对话框: 既用于新建(带场景向导), 也用于编辑已有隧道。
    def __init__(self, cfg=None, editing_item=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑隧道" if editing_item else "添加隧道 / 场景向导")
        self.setModal(True)
        self.resize(640, 540)
        self.cfg = cfg or dsh_config.load_config()
        self.editing_item = editing_item
        self.result_item = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        title_txt = "编辑 SSH 隧道" if self.editing_item else "添加 SSH 隧道"
        title = QLabel(title_txt, objectName="cardTitle")
        root.addWidget(title)

        self._tabs = QTabWidget(objectName="card")
        if not self.editing_item:
            self._tabs.addTab(self._build_wizard_tab(), "🌟 场景向导 (小白推荐)")
        self._tabs.addTab(self._build_custom_tab(), "🛠️ 自定义配置" if not self.editing_item else "隧道参数配置")
        root.addWidget(self._tabs, 1)

        bar = QHBoxLayout()
        self._hint_lbl = QLabel("", objectName="cardHint")
        bar.addWidget(self._hint_lbl, 1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        save = QPushButton("保存隧道", objectName="primary")
        save.setDefault(True)
        save.clicked.connect(self._on_save)
        bar.addWidget(cancel)
        bar.addWidget(save)
        root.addLayout(bar)

        if self.editing_item:
            self._fill_from_item(self.editing_item)

    # ── Tab 1: 场景向导 ──
    def _build_wizard_tab(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(10)

        v.addWidget(QLabel("选择你的使用场景，助手将自动填充推荐的拓扑规则与端口：", objectName="cardHint"))

        self._scene_group = QButtonGroup(self)
        self._r_fwd = QRadioButton("① 【在家/外部访问】通过公网中转服务器访问办公室/学校内网的 dsh")
        self._r_rev = QRadioButton("② 【内网穿透】把本机/办公室的 dsh 服务反向暴露到公网 VPS")
        self._r_lan = QRadioButton("③ 【局域网直连】在同一局域网 / VPN / Tailscale 内直连远程机器")
        self._r_dep = QRadioButton("④ 【从已有部署生成】从「部署管理」中已有远程机器一键创建")

        self._r_fwd.setChecked(True)
        for idx, r in enumerate((self._r_fwd, self._r_rev, self._r_lan, self._r_dep)):
            r.setStyleSheet("font-weight: bold; padding: 4px 0;")
            self._scene_group.addButton(r, idx)
            v.addWidget(r)
            r.toggled.connect(self._on_scene_changed)

        self._scene_card = QFrame(objectName="card")
        self._sf = QFormLayout(self._scene_card)
        self._sf.setContentsMargins(12, 10, 12, 10)
        self._sf.setSpacing(6)

        self._w_name = QLineEdit()
        self._w_server = QLineEdit()
        self._w_server.setPlaceholderText("服务器 IP 或域名")
        self._w_user = QLineEdit()
        self._w_user.setPlaceholderText("SSH 用户名")
        self._w_port = QLineEdit("22")
        self._w_dep_combo = QComboBox()
        self._lbl_port1 = QLabel("本机访问端口 (电脑本地):")
        self._lbl_port2 = QLabel("远端服务端口 (目标机器):")
        self._w_local_port = QLineEdit()
        self._w_remote_port = QLineEdit()
        self._w_flow_lbl = QLabel("", objectName="monName")
        self._w_flow_lbl.setWordWrap(True)
        self._w_flow_lbl.setTextFormat(Qt.RichText)

        self._sf.addRow("隧道名称:", self._w_name)
        self._sf.addRow("目标主机/VPS:", self._w_server)
        self._sf.addRow("SSH 用户名:", self._w_user)
        self._sf.addRow("SSH 端口:", self._w_port)
        self._sf.addRow("已有部署:", self._w_dep_combo)
        self._sf.addRow(self._lbl_port1, self._w_local_port)
        self._sf.addRow(self._lbl_port2, self._w_remote_port)
        self._sf.addRow("拓扑说明:", self._w_flow_lbl)

        self._w_dep_combo.currentIndexChanged.connect(self._on_dep_combo_changed)

        v.addWidget(self._scene_card)
        v.addStretch(1)

        self._init_wizard_fields()
        return page

    def _init_wizard_fields(self):
        depls = dsh_data.load_deployments()
        self._w_dep_combo.clear()
        for d in depls:
            self._w_dep_combo.addItem(d.get("name") or d.get("host"), d)
        self._on_scene_changed()

    def _on_scene_changed(self):
        cfg = self.cfg
        ssh_srv = cfg.get("ssh_server") or ""
        ssh_usr = cfg.get("ssh_user") or ""
        local_n = cfg.get("local_name") or "本机"
        ssh_n = cfg.get("ssh_name") or "公网中转"
        dash_p = cfg.get("dash_port") or 3080

        if self._r_fwd.isChecked():
            self._w_name.setText("%s正向隧道 (中继)" % ssh_n)
            self._w_server.setText(ssh_srv)
            self._w_server.setPlaceholderText("公网 VPS 服务器 IP 或域名")
            self._w_user.setText(ssh_usr)
            self._w_port.setText("22")
            self._lbl_port1.setText("本机访问端口 (电脑本地):")
            self._w_local_port.setText("8090")
            self._w_local_port.setPlaceholderText("例如 8090")
            self._lbl_port2.setText("远端服务端口 (目标机器):")
            self._w_remote_port.setText("8090")
            self._w_remote_port.setPlaceholderText("例如 8090")
            self._sf.setRowVisible(self._w_dep_combo, False)
            self._sf.setRowVisible(self._w_server, True)
            self._sf.setRowVisible(self._w_user, True)
            self._w_flow_lbl.setText("<span style='color:#7ecb6a;'>在家访问: </span>浏览器打开 http://127.0.0.1:8090 -> 经公网 VPS 转发 -> 远程办公室 dsh GUI")
        elif self._r_rev.isChecked():
            self._w_name.setText("%s反向暴露隧道" % local_n)
            self._w_server.setText(ssh_srv)
            self._w_server.setPlaceholderText("公网 VPS 服务器 IP 或域名")
            self._w_user.setText(ssh_usr)
            self._w_port.setText("22")
            self._lbl_port1.setText("公网暴露端口 (VPS服务器):")
            self._w_local_port.setText("8091")
            self._w_local_port.setPlaceholderText("例如 8091")
            self._lbl_port2.setText("本机服务端口 (本地 dsh):")
            self._w_remote_port.setText(str(dash_p))
            self._w_remote_port.setPlaceholderText("例如 3080")
            self._sf.setRowVisible(self._w_dep_combo, False)
            self._sf.setRowVisible(self._w_server, True)
            self._sf.setRowVisible(self._w_user, True)
            self._w_flow_lbl.setText("<span style='color:#7ecb6a;'>内网穿透: </span>本机 dsh (:%d) -> 反向暴露到公网 VPS :8091 (自动同步免密鉴权 Token)" % dash_p)
        elif self._r_lan.isChecked():
            self._w_name.setText("局域网直连隧道")
            self._w_server.setText(cfg.get("lab_server") or "")
            self._w_server.setPlaceholderText("局域网目标主机 IP 或域名")
            self._w_user.setText(cfg.get("lab_user") or "")
            self._w_port.setText("22")
            self._lbl_port1.setText("本机访问端口 (电脑本地):")
            self._w_local_port.setText("3090")
            self._w_local_port.setPlaceholderText("例如 3090")
            self._lbl_port2.setText("远端服务端口 (目标机器):")
            self._w_remote_port.setText("3080")
            self._w_remote_port.setPlaceholderText("例如 3080")
            self._sf.setRowVisible(self._w_dep_combo, False)
            self._sf.setRowVisible(self._w_server, True)
            self._sf.setRowVisible(self._w_user, True)
            self._w_flow_lbl.setText("<span style='color:#7ecb6a;'>局域网直连: </span>本机 http://127.0.0.1:3090 -> 局域网 SSH 直连目标电脑 :3080")
        elif self._r_dep.isChecked():
            self._sf.setRowVisible(self._w_dep_combo, True)
            self._sf.setRowVisible(self._w_server, False)
            self._sf.setRowVisible(self._w_user, False)
            self._lbl_port1.setText("本机访问端口 (电脑本地):")
            self._lbl_port2.setText("远端服务端口 (目标机器):")
            self._on_dep_combo_changed()

    def _on_dep_combo_changed(self):
        if not self._r_dep.isChecked():
            return
        d = self._w_dep_combo.currentData() or {}
        name = d.get("name") or "远程部署"
        self._w_name.setText("%s专属隧道" % name)
        self._w_server.setText(d.get("host") or "")
        self._w_user.setText(d.get("user") or "")
        self._w_port.setText(str(d.get("port") or 22))
        self._w_local_port.setText("8090")
        self._w_remote_port.setText("3080")
        self._w_flow_lbl.setText("<span style='color:#7ecb6a;'>部署直连: </span>打通到远程部署「%s」的端口转发" % name)

    # ── Tab 2: 自定义配置 ──
    def _build_custom_tab(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)

        form = QFormLayout()
        self._c_name = QLineEdit()
        self._c_mode = QComboBox()
        self._c_mode.addItems(["正向端口转发 (-L, 把远端服务拉到本地访问)", "反向暴露端口 (-R, 把本地服务暴露到公网 VPS)"])
        self._c_mode.currentIndexChanged.connect(self._on_custom_mode_changed)
        self._c_host = QLineEdit()
        self._c_user = QLineEdit()
        self._c_ssh_port = QLineEdit("22")
        self._c_auto_restart = QCheckBox("断线自动重连 (常驻守护)")
        self._c_auto_restart.setChecked(True)
        self._c_enabled = QCheckBox("启用此隧道")
        self._c_enabled.setChecked(True)

        form.addRow("隧道名称:", self._c_name)
        form.addRow("隧道模式:", self._c_mode)
        form.addRow("目标服务器 IP/域名:", self._c_host)
        form.addRow("SSH 用户名:", self._c_user)
        form.addRow("SSH 连接端口:", self._c_ssh_port)
        v.addLayout(form)

        v.addWidget(QLabel("端口映射列表 (可配置多对端口转发)：", objectName="rightTitle"))
        self._fwd_tbl = QTableWidget(0, 4)
        self._update_table_headers()
        self._fwd_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._fwd_tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._fwd_tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._fwd_tbl.verticalHeader().setVisible(False)
        self._fwd_tbl.setMaximumHeight(130)
        v.addWidget(self._fwd_tbl)

        tbl_bar = QHBoxLayout()
        add_btn = QPushButton("添加端口映射")
        add_btn.clicked.connect(self._add_fwd_row)
        del_btn = QPushButton("删除选中行")
        del_btn.clicked.connect(self._del_fwd_row)
        tbl_bar.addWidget(add_btn)
        tbl_bar.addWidget(del_btn)
        tbl_bar.addStretch(1)
        v.addLayout(tbl_bar)

        opt_box = QHBoxLayout()
        opt_box.addWidget(self._c_auto_restart)
        opt_box.addWidget(self._c_enabled)
        opt_box.addStretch(1)
        v.addLayout(opt_box)

        if not self.editing_item:
            self._add_fwd_row(8090, "127.0.0.1", 8090, "dsh Web GUI")
        return page

    def _on_custom_mode_changed(self):
        self._update_table_headers()

    def _update_table_headers(self):
        if self._c_mode.currentIndex() == 1:
            self._fwd_tbl.setHorizontalHeaderLabels(["公网暴露端口", "本地回源主机", "本地服务端口", "说明/备注"])
        else:
            self._fwd_tbl.setHorizontalHeaderLabels(["本机访问端口", "远端目标主机", "远端服务端口", "说明/备注"])

    def _add_fwd_row(self, lp=8090, host="127.0.0.1", rp=8090, desc=""):
        r = self._fwd_tbl.rowCount()
        self._fwd_tbl.insertRow(r)
        self._fwd_tbl.setItem(r, 0, QTableWidgetItem(str(lp or "")))
        self._fwd_tbl.setItem(r, 1, QTableWidgetItem(str(host or "127.0.0.1")))
        self._fwd_tbl.setItem(r, 2, QTableWidgetItem(str(rp or "")))
        self._fwd_tbl.setItem(r, 3, QTableWidgetItem(str(desc or "")))

    def _del_fwd_row(self):
        for idx in sorted({i.row() for i in self._fwd_tbl.selectedIndexes()}, reverse=True):
            self._fwd_tbl.removeRow(idx)

    def _fill_from_item(self, item):
        self._c_name.setText(item.get("name") or "")
        is_rev = item.get("mode") == "reverse"
        self._c_mode.setCurrentIndex(1 if is_rev else 0)
        self._c_host.setText(item.get("host") or "")
        self._c_user.setText(item.get("user") or "")
        self._c_ssh_port.setText(str(item.get("ssh_port") or 22))
        self._c_auto_restart.setChecked(bool(item.get("auto_restart", True)))
        self._c_enabled.setChecked(bool(item.get("enabled", True)))
        self._fwd_tbl.setRowCount(0)
        for fw in item.get("forwards") or []:
            if isinstance(fw, dict):
                self._add_fwd_row(fw.get("local_port"), fw.get("remote_host"), fw.get("remote_port"), fw.get("desc"))
            elif isinstance(fw, (list, tuple)) and len(fw) >= 3:
                self._add_fwd_row(fw[0], fw[1], fw[2], fw[3] if len(fw) >= 4 else "")

    def _collect_data(self):
        if not self.editing_item and self._tabs.currentIndex() == 0:
            name = self._w_name.text().strip() or "未命名隧道"
            host = self._w_server.text().strip()
            user = self._w_user.text().strip()
            mode = "reverse" if self._r_rev.isChecked() else "forward"
            try:
                ssh_port = int(self._w_port.text().strip() or 22)
            except ValueError:
                ssh_port = 22
            try:
                lp = int(self._w_local_port.text().strip() or 0)
                rp = int(self._w_remote_port.text().strip() or 0)
            except ValueError:
                return None, "本地或远端端口必须是有效整数"
            if not (1 <= lp <= 65535 and 1 <= rp <= 65535):
                return None, "端口必须在 1~65535 范围内"
            forwards = [{"local_port": lp, "remote_host": "127.0.0.1", "remote_port": rp, "desc": name}]
            auto_restart = True
            enabled = True
        else:
            name = self._c_name.text().strip() or "未命名隧道"
            mode = "reverse" if self._c_mode.currentIndex() == 1 else "forward"
            host = self._c_host.text().strip()
            user = self._c_user.text().strip()
            try:
                ssh_port = int(self._c_ssh_port.text().strip() or 22)
            except ValueError:
                ssh_port = 22
            forwards = []
            for r in range(self._fwd_tbl.rowCount()):
                try:
                    lp = int((self._fwd_tbl.item(r, 0) or QTableWidgetItem("")).text().strip())
                    rh = (self._fwd_tbl.item(r, 1) or QTableWidgetItem("")).text().strip() or "127.0.0.1"
                    rp = int((self._fwd_tbl.item(r, 2) or QTableWidgetItem("")).text().strip())
                    desc = (self._fwd_tbl.item(r, 3) or QTableWidgetItem("")).text().strip()
                    if not (1 <= lp <= 65535 and 1 <= rp <= 65535):
                        return None, "第 %d 行端口超出 1~65535 范围" % (r + 1)
                    forwards.append({"local_port": lp, "remote_host": rh, "remote_port": rp, "desc": desc})
                except ValueError:
                    return None, "第 %d 行端口必须为整数" % (r + 1)
            auto_restart = self._c_auto_restart.isChecked()
            enabled = self._c_enabled.isChecked()

        if not host:
            return None, "请填写目标服务器 IP 或域名"
        if not user:
            return None, "请填写 SSH 用户名"
        if not forwards:
            return None, "至少需要配置一条端口映射规则"

        tid = self.editing_item.get("id") if self.editing_item else ("tun_" + uuid.uuid4().hex[:8])
        item = {
            "id": tid,
            "name": name,
            "mode": mode,
            "host": host,
            "user": user,
            "ssh_port": ssh_port,
            "forwards": forwards,
            "auto_restart": auto_restart,
            "enabled": enabled,
            "desc": forwards[0].get("desc", "") if forwards else "",
        }
        return item, ""

    def _on_save(self):
        item, err = self._collect_data()
        if err or not item:
            QMessageBox.warning(self, "校验未通过", err or "配置不完整")
            return
        if item.get("mode") == "forward":
            # 编辑已有隧道时放行自身原已监听端口，避免自占误报
            orig_ports = set()
            if self.editing_item:
                for fw in (self.editing_item.get("forwards") or []):
                    p = fw.get("local_port") if isinstance(fw, dict) else (fw[0] if fw else None)
                    if p:
                        orig_ports.add(p)

            for fw in item.get("forwards") or []:
                lp = fw.get("local_port")
                if lp and (lp not in orig_ports) and not dsh_tunnels.port_free(lp):
                    ret = QMessageBox.question(
                        self, "端口可能已被占用",
                        "检测到本地端口 %d 当前已被占用。若其他程序正在使用该端口，隧道可能无法正常启动。是否仍然保存？" % lp,
                        QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
                    )
                    if ret != QMessageBox.Yes:
                        return
        self.result_item = item
        self.accept()
