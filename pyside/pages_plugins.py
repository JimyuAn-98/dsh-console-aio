# -*- coding: utf-8 -*-
# 插件管理页(PySide6 迁移版)。
# 已装插件真实来源 = profile/package.json 的 dsh.profile.bundles(cordis.yml 只读参考,
# 用户可写层是 cordis.patch.yml)。停用/启用只写 cordis.patch.yml(内部先 .bak 备份)。
# 安装/卸载不自实现安装逻辑, 走官方命令 dsh plugin --profile <name> add|remove <pkg>,
# 由主窗口 app._stream_cmd 在 DASH_REPO 目录流式执行并打主日志。
# 部署联动: 当前部署(host 非空)构造 DshRemote, 只读操作走远程; 写 patch 仍写本机(与旧版一致)。
# 布局: 顶部选 profile; 中部左表(名称/来源/描述/状态) + 右详情(QPlainTextEdit 只读, 显示 src 区);
# 操作(安装/卸载/禁用/启用)均针对选中条目, 受保护条目拒绝操作。
# 后台线程做 IO/子进程(dsh_data 读取、load_entry_id_map、_stream_cmd) ->
# Qt Signal 回主线程更新控件, worker 用 self.safe_emit 防页面销毁竞态, 不直接改 UI。

import os
import re
import threading

import dsh_data
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView, QMessageBox, QComboBox, QPlainTextEdit)

from pyside.base import BasePage

# 宿主基础设施 id 前缀/名单: 停用会破坏插件链本身, 拒绝切换。
# 沿用 dsh-market 的防护思路(前缀匹配, 宁可多拦)。
_PROTECTED_IDS = re.compile(
    r"^(cordis:|@deepseek-ai/(cordis-plugin-|dsh-host-|dsh-client-|dsh-web|"
    r"dsh-settings|dsh-credentials|dsh-session|dsh-storage|dsh-typert|"
    r"dsh-api-remotes|dsh-tools|dsh-system-prompt|dsh-agent|dsh-llm|dsh-persona|"
    r"dsh-scope|dsh-launch-environment|dsh-shell|dsh-subprocess|dsh-fs|"
    r"dsh-sandbox|dsh-jobs|dsh-skill|dsh-goal|dsh-workflow|dsh-subagent|"
    r"dsh-workspace|dsh-user-approval|dsh-user-questions|dsh-commands|dsh-hook|"
    r"dsh-spill|dsh-guard|dsh-tool-call-timeout-policy|dsh-repeat-tool-reminder))"
)


def _merge_entries(profile, remote=None):
    # 汇总插件列表: 基线 = read_profile_package 的 bundles(已装插件), 版本取 dependencies;
    # cordis.patch.yml 叠加 disabled 标记 / insert 新增; 返回 entry dict 列表。
    pkg = dsh_data.read_profile_package(profile, remote=remote)
    patch_rows = dsh_data.read_cordis_patch(profile, remote=remote) or []
    deps = pkg.get("dependencies") or {}
    out = []
    index = {}
    for bundle in pkg.get("bundles") or []:
        # bundle 行: id/name 就是 bundle 名(patch 里 - id: X 的 X 也是 bundle 名, 直接可覆盖)
        name = str(bundle)
        row = {"id": name, "name": name,
               "version": deps.get(name, ""), "_src": "bundle"}
        out.append(row)
        index.setdefault(name, row)
    for e in patch_rows:
        if not isinstance(e, dict):
            continue
        if isinstance(e.get("insert"), list):
            # insert 行: patch 新增的 loader entry(如 dsh-market 的 id=dsh-market)
            for sub in e["insert"]:
                if isinstance(sub, dict) and (sub.get("id") or sub.get("name")):
                    eid = sub.get("id") or sub.get("name")
                    if eid in index:
                        continue    # bundles 基线已有同名, 不重复列出
                    row = dict(sub)
                    row["_src"] = "patch"
                    row.setdefault("version", deps.get(sub.get("name") or eid, ""))
                    out.append(row)
                    index[eid] = row
            continue
        eid = e.get("id")
        if not eid:
            continue
        if eid in index:
            # patch 覆盖同名 bundle 行(disabled 标记等)
            index[eid].update({k: v for k, v in e.items() if k != "_src"})
            index[eid]["_src"] = "patch"
            if not index[eid].get("version"):
                index[eid]["version"] = deps.get(eid, "")
        else:
            # patch 里的其它行(如禁用不在 bundles 中的插件)也展示
            row = dict(e)
            row["_src"] = "patch"
            row.setdefault("name", eid)
            row.setdefault("version", deps.get(eid, ""))
            out.append(row)
            index[eid] = row
    return out


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


class PluginPage(BasePage):
    # 插件管理: BasePage 范式, app 为 MainWindow。
    _profiles = Signal(object, str)        # (profiles, err) Profile 列表结果
    _refresh_done = Signal(object, str)    # (entries, err) 插件列表结果
    _id_map_loaded = Signal(object)        # (mapping) name->真实 entry id 映射
    _stream_done = Signal(bool)            # (ok) dsh plugin 命令流式执行结果
    _patch_done = Signal(str, str)         # (msg, err) patch 写操作结果

    def __init__(self, app, parent=None):
        self._remote = None
        _dep = getattr(app, "_current_deploy", None)
        if _dep and _dep.get("host"):
            self._remote = dsh_data.DshRemote(_dep)
        self._entries = []      # 与表格行一一对应的 entry dict
        self._id_map = {}       # name(包名)->真实 entry id(来自 dsh --dump-config)
        self._busy = False
        self._last_op_msg = None
        super().__init__(app, parent)
        self._profiles.connect(self._apply_profiles)
        self._refresh_done.connect(self._apply_refresh)
        self._id_map_loaded.connect(self._apply_id_map)
        self._stream_done.connect(self._after_stream)
        self._patch_done.connect(self._after_patch)
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

    # ── Profile / 列表 ────────────────────────────────
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

    def _refresh(self):
        profile = self._profile_cb.currentText().strip()
        if not profile:
            return
        self._set_busy(True)
        self._set_status("正在读取插件列表...")
        dash_repo = getattr(self.app, "DASH_REPO", None)
        remote = self._remote

        def worker():
            err = None
            entries = []
            try:
                entries = _merge_entries(profile, remote=remote)
            except Exception as e:
                err = str(e)
            if not remote:
                # 构建 name->真实 entry id 映射(dump-config 是子进程, 较慢, 后台跑)
                try:
                    m = dsh_data.load_entry_id_map(profile, dash_repo)
                    self.safe_emit(self._id_map_loaded, m)
                except Exception:
                    pass    # 映射失败只影响停用/启用退化为用 bundle 名, 不阻断列表
            self.safe_emit(self._refresh_done, entries, err)

        threading.Thread(target=worker, daemon=True).start()

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

    def _apply_id_map(self, mapping):
        self._id_map = mapping or {}

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

    # ── 安装 / 卸载(官方命令, 针对选中条目) ───────────
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
        if self._is_protected(eid):
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
        if self._is_protected(eid):
            QMessageBox.warning(self, "受保护", "这是 dsh 宿主基础插件，不允许卸载。")
            return
        cmd = dsh_data.plugin_cmd(profile, "remove", pkg)
        if QMessageBox.question(self, "卸载插件",
                                "将执行：\n  " + " ".join(cmd) + "\n\n卸载会移除插件文件与相关行，是否继续？") != QMessageBox.Yes:
            return
        self._run_stream(cmd, "卸载插件 " + pkg)

    def _run_stream(self, cmd, desc):
        # 后台线程流式执行官方命令(经主窗口 _stream_cmd, 在 DASH_REPO 目录), 完成后回主线程刷新。
        self._set_busy(True)
        self._set_status("执行中: " + " ".join(cmd))
        dash_repo = getattr(self.app, "DASH_REPO", None)
        app = self.app

        def worker():
            ok = False
            try:
                app.loge("[插件] " + desc + " 开始: " + " ".join(cmd), "warn")
                # dsh plugin 命令必须在 dsh 仓库目录执行(pnpm dsh ...)
                ok = app._stream_cmd(cmd, cwd=dash_repo)
            except Exception as ex:
                try:
                    app.loge("  [插件] 执行异常: " + str(ex), "err")
                except Exception:
                    pass    # 主窗口可能已销毁, 日志失败不阻断
            self.safe_emit(self._stream_done, ok)

        threading.Thread(target=worker, daemon=True).start()

    def _after_stream(self, ok):
        self._last_op_msg = "已" + ("完成" if ok else "失败") + "(详见主界面日志区)"
        self._refresh()

    # ── 禁用 / 启用(patch 层) ─────────────────────────
    def _disable(self):
        e = self._selected_entry()
        if e is None:
            return
        profile = self._profile_cb.currentText().strip()
        eid = e.get("id")
        name = e.get("name") or eid
        if not profile or not eid:
            return
        if self._is_protected(eid):
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
        # 读 patch -> 增/改 disabled 标记 -> write_cordis_patch(内部先 .bak 备份)。
        # 禁用: 无同名行则追加 id + disabled:true 行; 有则原地置 True。
        # 启用: 移除该行的 disabled 字段; 若只剩 id 则整行删除, 保持 patch 干净。
        # 关键: 必须用真实 entry id(dump-config 映射), 不能用 bundle 名(如 dshmarket->dsh-market)
        eid = self._id_map.get(eid, eid)
        remote = self._remote
        self._set_busy(True)

        def worker():
            err = None
            try:
                patch = dsh_data.read_cordis_patch(profile, remote=remote) or []
                new_rows = []
                touched = False
                for row in patch:
                    if not isinstance(row, dict) or row.get("id") != eid:
                        new_rows.append(row)
                        continue
                    touched = True
                    row2 = dict(row)
                    if disabled:
                        row2["disabled"] = True
                        new_rows.append(row2)
                    else:
                        row2.pop("disabled", None)
                        if len(row2) > 1:
                            new_rows.append(row2)
                        # 只剩 id 的裸行直接删除
                if disabled and not touched:
                    new_rows.append({"id": eid, "disabled": True})
                dsh_data.write_cordis_patch(profile, new_rows)
            except OSError as ex:
                err = "无法写 cordis.patch.yml：" + str(ex)
            except Exception as ex:
                err = "读取/处理 cordis.patch.yml 失败：" + str(ex)
            msg = "已" + ("停用" if disabled else "启用") + " " + eid + " (cordis.patch.yml)"
            self.safe_emit(self._patch_done, msg, err)

        threading.Thread(target=worker, daemon=True).start()

    def _after_patch(self, msg, err):
        if err:
            QMessageBox.critical(self, "操作失败", err)
            self._set_status("操作失败: " + err)
            self.app.loge("[插件] " + err, "err")
            self._refresh()
            return
        self.app.loge("[插件] " + msg, "ok")
        self._last_op_msg = msg + "（已刷新）"
        self._refresh()

    # ── 其它 ──────────────────────────────────────────
    def _is_protected(self, eid):
        # 宿主基础设施行拒绝安装/禁用/卸载
        return bool(eid and _PROTECTED_IDS.match(str(eid)))

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

    # ── 状态 / 按钮 ───────────────────────────────────
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
