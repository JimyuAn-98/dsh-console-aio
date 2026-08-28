# -*- coding: utf-8 -*-
# 插件管理页(UI 层): 只做展示/预检/确认框/busy 管理, 业务在 dsh_core/plugins.py(纯 Python)。
# 已装插件真实来源 = profile/package.json 的 dsh.profile.bundles(cordis.yml 只读参考,
# 用户可写层是 cordis.patch.yml)。停用/启用写入 cordis.patch.yml(内部先 .bak 备份);
# 安装/卸载走官方命令 dsh plugin --profile <name> add|remove <pkg>, 经 service.run_cmd
# 在 dsh 仓库目录流式执行(逐行输出经 service.log 回主日志) —— 页面不再依赖 app._stream_cmd。
# 列表加载走 service.load_plugins(entries + name->真实 entry id 映射一并回包)。
# 远程只读红线: 远程部署(self._remote 非 None)下安装/卸载/停用/启用一律拒绝 ——
# 旧版远程读列表却写本机 patch / 在本机跑安装命令, 语义错误, 已封死。
# 列表读取(Profile 下拉)暂留页面直连线程(纯读过渡态, 阶段4 收敛); 其余全走 service 信号:
# 接收者是页面自身, 页面销毁 Qt 自动断开; log/status 不在页面 connect(主窗口级已接)。

import os
import threading

import dsh_data
from dsh_core import plugins as core_plugins
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView, QMessageBox, QComboBox, QPlainTextEdit)

from pyside.base import BasePage


def _entry_src_text(e):
    # 渲染条目 src 区: 来源 + 原始键值(patch 行含 disabled/description 等, bundle 行含版本)。
    origin = "cordis.patch.yml" if e.get("_src") == "patch" else "package.json (dsh.profile.bundles)"
    lines = ["# 来源: " + origin]
    for k in sorted(e.keys()):
        if k in ("_src", "_src_text"):
            continue
        v = e[k]
        if v is None:
            v = ""
        lines.append(str(k) + ": " + str(v))
    return "\n".join(lines)


_REMOTE_READONLY_MSG = "远程部署下暂不支持写操作（远程只读），请切换回本机部署"


class PluginPage(BasePage):
    # 插件管理: BasePage 范式, app 为 MainWindow。
    _profiles = Signal(object, str)        # (profiles, err) Profile 列表结果(纯读线程)

    def __init__(self, app, parent=None):
        self._remote = None
        _dep = getattr(app, "_current_deploy", None)
        if _dep and _dep.get("host"):
            self._remote = dsh_data.DshRemote(_dep)
        self._entries = []      # 与表格行一一对应的 entry dict
        self._id_map = {}       # name(包名)->真实 entry id(来自 dsh --dump-config, service 回包)
        self._busy = False
        self._pending = None    # 正在等待的 service op
        self._last_op_msg = None
        super().__init__(app, parent)
        self._profiles.connect(self._apply_profiles)
        self.app.service.result.connect(self._on_result)
        self.app.service.finished.connect(self._on_finished)
        self._load_profiles()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 12)
        root.setSpacing(8)

        title = QLabel("插件管理", objectName="cardTitle")
        root.addWidget(title)
        hint = QLabel("停用/启用写入 cordis.patch.yml；安装/卸载经官方 dsh plugin 命令执行。",
                      objectName="cardHint")
        root.addWidget(hint)

        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(QLabel("Profile:"))
        self._profile_cb = QComboBox()
        self._profile_cb.setMinimumWidth(200)
        top.addWidget(self._profile_cb)
        self._btn_refresh = QPushButton("刷新")
        self._btn_refresh.clicked.connect(self._refresh)
        top.addWidget(self._btn_refresh)
        self._btn_open_patch = QPushButton("打开 patch 文件")
        self._btn_open_patch.clicked.connect(self._open_patch)
        top.addWidget(self._btn_open_patch)
        top.addStretch(1)
        top.addWidget(QLabel("已装插件来自 package.json bundles · 改动写入 cordis.patch.yml",
                             objectName="cardHint"))
        root.addLayout(top)

        mid = QHBoxLayout()
        mid.setSpacing(10)
        self._table = self._make_table(
            ["名称", "来源", "描述", "状态"], ["w", "w", "w", "center"],
            [200, 110, 240, 70], stretch_col=2)
        self._table.itemSelectionChanged.connect(self._on_select)
        mid.addWidget(self._wrap_table("插件条目", self._table), 3)

        detail_card = QFrame(objectName="card")
        dv = QVBoxLayout(detail_card)
        dv.setContentsMargins(10, 8, 10, 8)
        dv.setSpacing(4)
        dv.addWidget(QLabel("条目详情（src 区）", objectName="rightTitle"))
        self._detail_text = QPlainTextEdit()
        self._detail_text.setReadOnly(True)
        self._detail_text.setFont(QFont("Consolas", 9))
        dv.addWidget(self._detail_text)
        mid.addWidget(detail_card, 2)
        root.addLayout(mid, 1)

        btns = QHBoxLayout()
        btns.setSpacing(6)
        self._btn_install = QPushButton("安装")
        self._btn_install.clicked.connect(self._install)
        self._disable_btn = QPushButton("禁用")
        self._disable_btn.clicked.connect(self._disable)
        self._enable_btn = QPushButton("启用")
        self._enable_btn.clicked.connect(self._enable)
        self._remove_btn = QPushButton("卸载")
        self._remove_btn.clicked.connect(self._remove)
        btns.addWidget(self._btn_install)
        btns.addWidget(self._disable_btn)
        btns.addWidget(self._enable_btn)
        btns.addWidget(self._remove_btn)
        btns.addWidget(QLabel("操作针对选中条目；停用/启用写入 cordis.patch.yml(写前自动备份, HMR 约 1 秒生效)",
                              objectName="cardHint"))
        btns.addStretch(1)
        root.addLayout(btns)

        self._status_lbl = QLabel("就绪", objectName="statusBar")
        root.addWidget(self._status_lbl)

        self._profile_cb.activated.connect(lambda _i: self._refresh())
        self._refresh_btns()

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

    def _dash_repo(self):
        # dsh plugin/dump-config 命令必须在 dsh 仓库目录执行; 取 service 的 config 派生值
        return self.app.service.ctl.d.get("dash_repo") or ""

    # ── Profile 列表(纯读过渡态: 页面线程 + safe_emit) ──
    def _load_profiles(self):
        # 只列有 cordis.yml 或 cordis.patch.yml 的 profile; 读取是 IO, 放后台线程。
        self._set_busy(True)
        self._set_status("正在读取 Profile 列表...")
        remote = self._remote

        def worker():
            err = None
            profiles = None
            try:
                profiles = dsh_data.list_profiles(remote=remote)
            except Exception as e:
                err = str(e)
            self.safe_emit(self._profiles, profiles or [], err)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_profiles(self, profiles, err):
        if err:
            self._set_busy(False)
            self._table.setRowCount(0)
            self._entries = []
            self._set_status("Profile 列表读取失败: " + err)
            self.app.loge("[插件] Profile 列表读取失败: " + err, "err")
            return
        usable = [p for p in profiles if p.get("cordis") or p.get("patch")]
        names = [p["name"] for p in usable]
        self._profile_cb.clear()
        self._profile_cb.addItems(names)
        if names:
            self._profile_cb.setCurrentIndex(0)
            self._refresh()
        else:
            self._set_busy(False)
            self._table.setRowCount(0)
            self._entries = []
            self._set_status("未找到可用 profile(~/.dsh/profiles 下没有 cordis.yml / cordis.patch.yml)")

    # ── 列表加载(service: entries + id 映射一并回包) ──
    def _refresh(self):
        profile = self._profile_cb.currentText().strip()
        if not profile:
            return
        self._set_busy(True)
        self._pending = "plugins-load"
        self._set_status("正在读取插件列表...")
        self.app.service.load_plugins(profile, self._remote)

    def _apply_refresh(self, entries, err):
        self._set_busy(False)
        self._entries = entries
        self._table.setRowCount(len(entries))
        for r, e in enumerate(entries):
            src = "cordis.patch.yml" if e.get("_src") == "patch" else "bundle"
            self._table.setItem(r, 0, QTableWidgetItem(e.get("name") or e.get("id") or "?"))
            self._table.setItem(r, 1, QTableWidgetItem(src))
            self._table.setItem(r, 2, QTableWidgetItem(e.get("description") or "—"))
            self._table.setItem(r, 3, QTableWidgetItem("已停用" if e.get("disabled") else "已启用"))
            if e.get("disabled"):
                for c in range(4):
                    self._table.item(r, c).setForeground(Qt.gray)
        self._table.clearSelection()
        self._on_select()
        if err:
            self._set_status("读取失败: " + err)
            self.app.loge("[插件] 读取失败: " + err, "err")
        elif self._last_op_msg:
            self._set_status(self._last_op_msg)
            self._last_op_msg = None
        else:
            self._set_status("共 %d 个插件" % len(entries))

    # ── service 信号槽(接收者=本页, 销毁自动断开) ──
    def _on_result(self, op, payload):
        if op == "plugins-load":
            self._pending = None
            self._id_map = payload.get("id_map") or {}
            self._apply_refresh(payload.get("entries") or [], payload.get("err", ""))
        elif op == "plugins-toggle":
            self._pending = None
            self._after_toggle(payload)

    def _on_finished(self, op, ok):
        if op == "plugins-cmd":
            # run_cmd 只有 finished(无 result): 流式输出已在主日志区, 完成后刷新列表
            self._pending = None
            self._after_stream(ok)
        elif op == self._pending:
            # 兜底: result 槽漏执行导致 busy 悬挂时解除
            self._pending = None
            self._set_busy(False)

    # ── 安装 / 卸载(官方命令, 经 service.run_cmd 流式执行) ──
    def _install(self):
        e = self._selected_entry()
        if e is None:
            self._set_status("请先在列表中选择要安装的插件")
            return
        profile = self._profile_cb.currentText().strip()
        eid = e.get("id")
        pkg = e.get("name") or eid
        if not profile or not pkg:
            return
        if self._remote is not None:
            QMessageBox.warning(self, "远程只读", _REMOTE_READONLY_MSG)
            return
        if core_plugins.protected(eid):
            QMessageBox.warning(self, "受保护", "这是 dsh 宿主基础插件，不允许安装。")
            return
        cmd = dsh_data.plugin_cmd(profile, "add", pkg)
        if QMessageBox.question(self, "安装插件",
                                "将执行：\n  " + " ".join(cmd) + "\n\n是否继续？") != QMessageBox.Yes:
            return
        self._run_stream(cmd, "安装插件 " + pkg)

    def _remove(self):
        e = self._selected_entry()
        if e is None:
            return
        profile = self._profile_cb.currentText().strip()
        eid = e.get("id")
        pkg = e.get("name") or eid
        if not profile or not pkg:
            return
        if self._remote is not None:
            QMessageBox.warning(self, "远程只读", _REMOTE_READONLY_MSG)
            return
        if core_plugins.protected(eid):
            QMessageBox.warning(self, "受保护", "这是 dsh 宿主基础插件，不允许卸载。")
            return
        cmd = dsh_data.plugin_cmd(profile, "remove", pkg)
        if QMessageBox.question(self, "卸载插件",
                                "将执行：\n  " + " ".join(cmd) + "\n\n卸载会移除插件文件与相关行，是否继续？") != QMessageBox.Yes:
            return
        self._run_stream(cmd, "卸载插件 " + pkg)

    def _run_stream(self, cmd, desc):
        # 官方命令经 service.run_cmd 在 dsh 仓库目录流式执行(逐行打主日志), 完成后回 finished。
        self._set_busy(True)
        self._pending = "plugins-cmd"
        self._set_status("执行中: " + " ".join(cmd))
        self.app.loge("[插件] " + desc + " 开始: " + " ".join(cmd), "warn")
        self.app.service.run_cmd(cmd, cwd=self._dash_repo(), op="plugins-cmd")

    def _after_stream(self, ok):
        self._last_op_msg = "已" + ("完成" if ok else "失败") + "(详见主界面日志区)"
        self._refresh()

    # ── 禁用 / 启用(patch 层, service 信号桥) ──
    def _disable(self):
        e = self._selected_entry()
        if e is None:
            return
        profile = self._profile_cb.currentText().strip()
        eid = e.get("id")
        name = e.get("name") or eid
        if not profile or not eid:
            return
        if self._remote is not None:
            QMessageBox.warning(self, "远程只读", _REMOTE_READONLY_MSG)
            return
        if core_plugins.protected(eid):
            QMessageBox.warning(self, "受保护", "这是 dsh 宿主基础插件，禁用会破坏插件链本身，已拒绝。")
            return
        if e.get("disabled"):
            QMessageBox.information(self, "已停用", "「%s」已处于停用状态。" % name)
            return
        if QMessageBox.question(
                self, "禁用插件",
                "将把「%s」标记为已停用：\n" % name +
                "写入 %s/cordis.patch.yml(写前自动备份，HMR 约 1 秒生效)。\n\n是否继续？" % profile) != QMessageBox.Yes:
            return
        self._set_disabled(profile, eid, True)

    def _enable(self):
        e = self._selected_entry()
        if e is None:
            return
        profile = self._profile_cb.currentText().strip()
        eid = e.get("id")
        name = e.get("name") or eid
        if not profile or not eid:
            return
        if self._remote is not None:
            QMessageBox.warning(self, "远程只读", _REMOTE_READONLY_MSG)
            return
        if not e.get("disabled"):
            QMessageBox.information(self, "未停用", "「%s」当前未停用，无需启用。" % name)
            return
        if QMessageBox.question(
                self, "启用插件",
                "将移除「%s」的 disabled 标记：\n" % name +
                "写入 %s/cordis.patch.yml(写前自动备份，HMR 约 1 秒生效)。\n\n是否继续？" % profile) != QMessageBox.Yes:
            return
        self._set_disabled(profile, eid, False)

    def _set_disabled(self, profile, eid, disabled):
        # 必须用真实 entry id(dump-config 映射), 不能用 bundle 名(如 dshmarket->dsh-market);
        # 宿主基础设施防线在 core 再做一次(不信任 UI 预检)。
        eid = self._id_map.get(eid, eid)
        self._set_busy(True)
        self._pending = "plugins-toggle"
        self._set_status("正在写入 cordis.patch.yml ...")
        self.app.service.toggle_plugin(profile, eid, disabled)

    def _after_toggle(self, payload):
        msg = payload.get("msg", "")
        err = payload.get("err", "")
        if err:
            self._set_busy(False)
            QMessageBox.critical(self, "操作失败", err)
            self._set_status("操作失败: " + err)
            self.app.loge("[插件] " + err, "err")
            self._refresh()
            return
        self.app.loge("[插件] " + msg, "ok")
        self._last_op_msg = msg + "（已刷新）"
        self._refresh()

    # ── 其它 ──
    def _selected_entry(self):
        # 当前表格选中行对应的 entry dict; 未选中返回 None
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        idx = rows[0].row()
        return self._entries[idx] if 0 <= idx < len(self._entries) else None

    def _on_select(self):
        # 选中条目时右侧显示 src 区, 并控制操作按钮
        e = self._selected_entry()
        self._detail_text.setPlainText(_entry_src_text(e) if e else "")
        self._refresh_btns()

    def _open_patch(self):
        profile = self._profile_cb.currentText().strip()
        if not profile:
            return
        if self._remote:
            QMessageBox.information(self, "远程部署",
                                    "当前为远程部署，patch 文件在远端，不支持本地打开。")
            return
        p = os.path.join(dsh_data.profiles_dir(), profile, "cordis.patch.yml")
        if not os.path.isfile(p):
            QMessageBox.information(self, "文件不存在",
                                    "该 profile 还没有 cordis.patch.yml。\n可以先执行一次禁用/启用操作生成。")
            return
        try:
            os.startfile(p)
        except Exception as ex:
            QMessageBox.critical(self, "无法打开", str(ex))

    # ── 状态 / 按钮 ──
    def _refresh_btns(self):
        sel = self._selected_entry() is not None
        self._btn_refresh.setEnabled(not self._busy)
        self._btn_open_patch.setEnabled(not self._busy)
        self._btn_install.setEnabled(not self._busy and sel)
        self._disable_btn.setEnabled(not self._busy and sel)
        self._enable_btn.setEnabled(not self._busy and sel)
        self._remove_btn.setEnabled(not self._busy and sel)

    def _set_busy(self, busy):
        self._busy = busy
        self._refresh_btns()

    def _set_status(self, text):
        self._status_lbl.setText(text)
