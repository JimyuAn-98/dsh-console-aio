# -*- coding: utf-8 -*-
# 设置页(P1 弹窗收敛 A1): 配置向导(ConfigDialog)与监控设置(MonitorSettingsDialog)合并为
# 页面内标签页 —— 顶栏"配置"与右栏"⚙ 监控设置"改为导航到这里, 不再弹模态。
# 保存: 以磁盘 config.json 为基准合并两页字段 -> core save_config(自动 .bak) ->
# app.reload_config() 热重载(端口/命名/监控点即时生效; 隧道 SSH 参数下次启动隧道生效)。
# 场景模板/SSH 测试/端口表编辑沿用原对话框交互(线程 + 内联结果, 无弹窗)。
# self._config_path 默认 None(走 DSH_AIO_CONFIG/默认路径), 测试可注入 tmp 路径。

import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QFormLayout, QLineEdit,
    QPushButton, QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QScrollArea, QWidget)

from core import config as dsh_config
from core import env as core_env
from ui.base import BasePage


class SettingsPage(BasePage):
    # 设置: BasePage 范式, app 为 MainWindow。页面随导航重建, 字段每次从磁盘回填。
    _ssh_done = Signal(str, object)   # (结果文案, True/False/None)

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
    LABELS = {
        "ssh_server": "服务器 IP/域名", "ssh_user": "用户名", "ssh_port": "SSH 端口",
        "dash_repo": "仓库路径", "dash_port": "端口", "dash_cmd": "启动命令",
        "forward_ports": "在家正向端口", "lab_server": "实验室 IP",
        "lab_user": "实验室用户", "lab_port": "实验室映射端口",
        "reverse_port": "反向端口", "poll_seconds": "本机轮询(秒)",
        "remote_poll_seconds": "远端轮询(秒)",
    }
    TEMPLATES = {
        "在家→中继隧道": {"ssh_server": "YOUR_PUBLIC_IP", "ssh_user": "YOUR_USER",
                      "forward_ports": "8090,8022,8091", "reverse_port": "8091"},
        "实验室→直连实验室dsh": {"lab_server": "YOUR_LAB_IP", "lab_user": "YOUR_USER",
                          "lab_port": "3090"},
        "本机→中继反向": {"reverse_port": "8091"},
    }

    def __init__(self, app, parent=None):
        self._vars = {}
        self._config_path = None   # None = DSH_AIO_CONFIG/默认路径; 测试注入 tmp 路径
        super().__init__(app, parent)
        self._ssh_done.connect(self._on_ssh_done)
        tab = getattr(app, "_pending_settings_tab", None)
        if tab:
            self._tabs.setCurrentIndex(1 if tab == "monitor" else 0)
            app._pending_settings_tab = None

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 12)
        root.setSpacing(8)

        # 状态文字在标题右侧(原底部状态条位置取消); 显示配置文件实际路径(打包运行可定位)
        self._status_lbl = QLabel("就绪", objectName="monVal")
        head = QHBoxLayout()
        head.addWidget(QLabel("设置", objectName="cardTitle"))
        head.addStretch(1)
        head.addWidget(self._status_lbl)
        root.addLayout(head)
        self._config_file_lbl = QLabel(
            "配置在页面内完成, 不弹窗; 保存后端口/命名/监控点即时热重载。配置文件: %s"
            % (self._config_path or dsh_config.default_config_path()),
            objectName="cardHint")
        self._config_file_lbl.setWordWrap(True)
        root.addWidget(self._config_file_lbl)

        bar = QHBoxLayout()
        save = QPushButton("保存设置", objectName="primary")
        save.clicked.connect(self._on_save)
        bar.addWidget(save)
        self._save_lbl = QLabel("", objectName="cardHint")
        bar.addWidget(self._save_lbl)
        bar.addStretch(1)

        # 内容纵向可滚动(配置项多, 视口不足时出纵向滚动条)
        self._tabs = QTabWidget(objectName="card")
        self._tabs.addTab(self._build_tunnel_tab(), "隧道与部署")
        self._tabs.addTab(self._build_monitor_tab(), "监控与命名")
        content = QWidget()
        cv = QVBoxLayout(content)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(8)
        cv.addWidget(self._tabs, 1)
        cv.addLayout(bar)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

    # ── Tab 1: 隧道与部署(原 ConfigDialog) ──
    def _build_tunnel_tab(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)

        v.addWidget(QLabel("场景模板 (一键填充, 把占位符改成真实 IP/用户名)", objectName="rightTitle"))
        tpl_row = QHBoxLayout()
        cfg = dsh_config.load_config(self._config_path)
        for name in list(self.TEMPLATES) + ["自定义"]:
            btn = QPushButton(name)
            btn.clicked.connect(lambda _=False, n=name: self._apply(n))
            tpl_row.addWidget(btn)
        tpl_row.addStretch(1)
        v.addLayout(tpl_row)

        form = QFormLayout()
        self._form = form
        self._sec(form, "① 公网中转服务器")
        self._field(cfg, "ssh_server", None)
        self._field(cfg, "ssh_user", None)
        self._field(cfg, "ssh_port", "22")
        self._test_btn = QPushButton("测试 SSH 连接")
        self._test_btn.clicked.connect(self._test_ssh)
        self._test_lbl = QLabel("")
        self._test_lbl.setWordWrap(True)
        form.addRow(self._test_btn, self._test_lbl)
        self._sec(form, "② 本机 dsh")
        self._field(cfg, "dash_repo", None)
        self._field(cfg, "dash_port", None)
        self._field(cfg, "dash_cmd", None)
        self._sec(form, "③ 隧道参数")
        self._field(cfg, "forward_ports", None)
        self._field(cfg, "lab_server", None)
        self._field(cfg, "lab_user", None)
        self._field(cfg, "lab_port", None)
        self._field(cfg, "reverse_port", None)
        self._sec(form, "④ 轮询与超时")
        self._field(cfg, "poll_seconds", None)
        self._field(cfg, "remote_poll_seconds", None)
        v.addLayout(form)
        v.addStretch(1)
        return page

    def _sec(self, form, title):
        lbl = QLabel(title)
        lbl.setStyleSheet("font-weight: bold; color: #7d92ff;")
        form.addRow(lbl)

    def _field(self, cfg, key, placeholder):
        # 一个配置字段: 表单行, 帮助文本做悬停 tooltip
        label = QLabel(self.LABELS[key] + ":")
        default = cfg.get(key)
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
        # 场景模板一键填充; 自定义/未知模板不动作
        tpl = self.TEMPLATES.get(name)
        if not tpl:
            return
        for k, val in tpl.items():
            if k in self._vars:
                self._vars[k].setText(val)

    def _test_ssh(self):
        # SSH 测试: 后台线程调 core(免密/超时细节在 core.env), 信号回主线程内联更新
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
        self._test_lbl.setText(msg)
        color = "#888888" if ok is None else ("#7ecb6a" if ok else "#e07a7a")
        self._test_lbl.setStyleSheet("color: %s;" % color)

    def _on_ssh_done(self, msg, ok):
        self._test_btn.setEnabled(True)
        self._set_test(msg, ok)

    def _collect_basic(self):
        # 隧道与部署字段收集(与原 ConfigDialog._on_save 一致); 非法整数抛 ValueError
        cfg = {}
        cfg["ssh_server"] = self._vars["ssh_server"].text().strip() or "YOUR_PUBLIC_IP"
        cfg["ssh_user"] = self._vars["ssh_user"].text().strip() or "tunnel"
        cfg["dash_repo"] = self._vars["dash_repo"].text().strip()
        cfg["dash_port"] = int(self._vars["dash_port"].text().strip())
        cfg["dash_cmd"] = self._vars["dash_cmd"].text().strip().split()
        # forward_ports 支持 "8090,8022,8091" 或 "[8090, 8022, 8091]" 两种写法
        fp_raw = self._vars["forward_ports"].text().strip().strip("[]").replace(" ", "")
        cfg["forward_ports"] = [int(x) for x in fp_raw.split(",") if x]
        cfg["poll_seconds"] = int(self._vars["poll_seconds"].text().strip())
        cfg["remote_poll_seconds"] = int(self._vars["remote_poll_seconds"].text().strip())
        cfg["lab_server"] = self._vars["lab_server"].text().strip()
        cfg["lab_user"] = self._vars["lab_user"].text().strip()
        lp = self._vars["lab_port"].text().strip()
        cfg["lab_port"] = int(lp) if lp else 3090
        rp = self._vars["reverse_port"].text().strip()
        cfg["reverse_port"] = int(rp) if rp else 8091
        return cfg

    # ── Tab 2: 监控与命名(原 MonitorSettingsDialog) ──
    def _build_monitor_tab(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)

        v.addWidget(QLabel("机器命名(右栏/卡片/部署下拉跟随)", objectName="rightTitle"))
        form = QFormLayout()
        self._in_local = QLineEdit("本机")
        self._in_lab = QLineEdit("实验室")
        self._in_ssh = QLineEdit("公网中转")
        form.addRow("本机名称", self._in_local)
        form.addRow("实验室名称", self._in_lab)
        form.addRow("公网中转名称", self._in_ssh)
        v.addLayout(form)

        v.addWidget(QLabel("监测端口(增删改后保存, 右栏监控点/卡片/探测即时跟随)", objectName="rightTitle"))
        self._tabs2 = QTabWidget()
        self._local_tbl = self._make_table()
        self._remote_tbl = self._make_table()
        self._tabs2.addTab(self._local_tbl, "本机端口")
        self._tabs2.addTab(self._remote_tbl, "公网隧道")
        v.addWidget(self._tabs2, 1)

        btns = QHBoxLayout()
        add = QPushButton("添加一行")
        add.clicked.connect(lambda: self._current_tbl().insertRow(self._current_tbl().rowCount()))
        dele = QPushButton("删除选中")
        dele.clicked.connect(self._del_row)
        btns.addWidget(add)
        btns.addWidget(dele)
        btns.addStretch(1)
        v.addLayout(btns)

        # 字段回填
        cfg = dsh_config.load_config(self._config_path)
        self._in_local.setText(cfg.get("local_name") or "本机")
        self._in_lab.setText(cfg.get("lab_name") or "实验室")
        self._in_ssh.setText(cfg.get("ssh_name") or "公网中转")
        self._fill(self._local_tbl, cfg.get("local_ports", []))
        self._fill(self._remote_tbl, cfg.get("remote_tunnels", []))
        return page

    def _make_table(self):
        t = QTableWidget(0, 3)
        t.setHorizontalHeaderLabels(["端口", "名称", "备注"])
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        t.verticalHeader().setVisible(False)
        t.setAlternatingRowColors(True)
        t.setMaximumHeight(220)
        return t

    def _current_tbl(self):
        return self._local_tbl if self._tabs2.currentIndex() == 0 else self._remote_tbl

    def _fill(self, tbl, rows):
        for port, name, note in rows:
            r = tbl.rowCount()
            tbl.insertRow(r)
            tbl.setItem(r, 0, QTableWidgetItem(str(port)))
            tbl.setItem(r, 1, QTableWidgetItem(name))
            tbl.setItem(r, 2, QTableWidgetItem(note))

    def _collect_tbl(self, tbl):
        rows = []
        for r in range(tbl.rowCount()):
            try:
                port = int((tbl.item(r, 0) or QTableWidgetItem("")).text().strip())
            except ValueError:
                port = 0
            name = (tbl.item(r, 1) or QTableWidgetItem("")).text().strip()
            note = (tbl.item(r, 2) or QTableWidgetItem("")).text().strip()
            if port > 0:
                rows.append([port, name, note])
        return rows

    def _del_row(self):
        tbl = self._current_tbl()
        for idx in sorted({i.row() for i in tbl.selectedIndexes()}, reverse=True):
            tbl.removeRow(idx)

    # ── 保存(两页合一, 磁盘为基准合并; core 自动 .bak) ──
    def _on_save(self):
        try:
            fields = self._collect_basic()
            ports = self._collect_tbl(self._local_tbl)
            tunnels = self._collect_tbl(self._remote_tbl)
        except ValueError:
            self._set_save("保存未执行: 端口/轮询间隔/端口列表必须是整数", err=True)
            return
        cfg = dsh_config.load_config(self._config_path)
        cfg.update(fields)
        cfg["local_ports"] = ports
        cfg["remote_tunnels"] = tunnels
        cfg["local_name"] = self._in_local.text().strip() or "本机"
        cfg["lab_name"] = self._in_lab.text().strip() or "实验室"
        cfg["ssh_name"] = self._in_ssh.text().strip() or "公网中转"
        if not dsh_config.save_config(cfg, self._config_path):
            self._set_save("保存失败: config.json 写入失败(可能被占用), 请重试", err=True)
            return
        self._set_save("已保存并热重载(端口/命名即时生效; 隧道 SSH 参数下次启动隧道生效)")
        self.app.reload_config()

    def _set_save(self, text, err=False):
        self._save_lbl.setText(text)
        self._save_lbl.setStyleSheet("color: %s;" % ("#e07a7a" if err else "#7ecb6a"))
        self._set_status(text)
        if not err:
            self.app.loge("[设置] " + text, "ok")

    def _set_status(self, text):
        self._status_lbl.setText(text)
