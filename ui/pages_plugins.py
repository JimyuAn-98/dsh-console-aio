# -*- coding: utf-8 -*-
# 插件管理页(UI 层): 只做展示/预检/确认框/busy 管理, 业务在 core/plugins.py(纯 Python)。
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

from core import cache as core_cache
from core import data as dsh_data
from core import plugins as core_plugins
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPlainTextEdit, QScrollArea,
    QPushButton, QMessageBox, QComboBox, QTextEdit, QWidget)

from ui.base import BasePage
from ui.widgets import ModernList, RefreshIndicator, ConfirmBanner, card_wrap, three_split


def _entry_src_text(e):
    # 渲染条目 src 区: 来源 + 原始键值(patch 行含 disabled/description 等, bundle 行含版本)。
    # cordis 是我们附加的生效状态字段, 不属于文件内容, 不展示。
    origin = "cordis.patch.yml" if e.get("_src") == "patch" else "package.json (dsh.profile.bundles)"
    lines = ["# 来源: " + origin]
    for k in sorted(e.keys()):
        if k in ("_src", "_src_text", "cordis"):
            continue
        v = e[k]
        if v is None:
            v = ""
        lines.append(str(k) + ": " + str(v))
    return "\n".join(lines)


def _chips_html(chips):
    # 详情卡徽章 chips 行(QLabel 富文本; Qt 富文本不支持圆角, 用底色块近似);
    # 底色取 theme token bg_active(accent 同族深底)
    from ui.theme import TOKENS
    return " ".join(
        '<span style="background-color:%s; color:%s;">&nbsp;%s&nbsp;</span>'
        % (TOKENS["bg_active"], color, text)
        for text, color in chips)


_REMOTE_READONLY_MSG = "远程部署下暂不支持写操作（远程只读），请切换回本机部署"


class PluginPage(BasePage):
    # 插件管理: BasePage 范式, app 为 MainWindow。

    def __init__(self, app, parent=None):
        self._remote = None
        _dep = getattr(app, "_current_deploy", None)
        if _dep and _dep.get("host"):
            self._remote = dsh_data.DshRemote(_dep)
        self._entries = []          # 当前列表条目(list 行 data 指向)
        self._id_map = {}           # name(包名)->真实 entry id(来自 dsh --dump-config, service 回包)
        self._cordis_states = {}    # entry id -> {name, disabled, yaml(合成原文)}
        self._busy = False
        self._pending = None    # 正在等待的 service op
        self._last_op_msg = None
        super().__init__(app, parent)
        self.app.service.result.connect(self._on_result)
        self.app.service.finished.connect(self._on_finished)
        self._load_profiles()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 12)
        root.setSpacing(8)

        # 状态文字在标题右侧, 增加 RefreshIndicator
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_row.addWidget(QLabel("插件管理", objectName="cardTitle"))
        self._spinner = RefreshIndicator()
        self._spinner.setToolTip("刷新状态: 绿=无变化 / 黄=数据有变化 / 红=获取错误")
        title_row.addWidget(self._spinner)
        title_row.addStretch(1)
        self._status_lbl = QLabel("就绪", objectName="monVal")
        title_row.addWidget(self._status_lbl)
        root.addLayout(title_row)
        hint = QLabel("停用/启用写入 cordis.patch.yml；安装/卸载经官方 dsh plugin 命令执行；"
                      "进页自动取缓存+按需刷新。", objectName="cardHint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(QLabel("Profile:"))
        self._profile_cb = QComboBox()
        self._profile_cb.setMinimumWidth(200)
        self._profile_cb.currentIndexChanged.connect(lambda: self._refresh(force=False))
        top.addWidget(self._profile_cb)
        self._btn_refresh = QPushButton("刷新")
        self._btn_refresh.clicked.connect(lambda: self._refresh(force=True))
        top.addWidget(self._btn_refresh)
        top.addStretch(1)
        root.addLayout(top)
        top.addWidget(self._btn_refresh)
        self._btn_open_patch = QPushButton("打开 patch 文件")
        self._btn_open_patch.clicked.connect(self._open_patch)
        top.addWidget(self._btn_open_patch)
        top.addStretch(1)
        _top_hint = QLabel("已装插件来自 package.json bundles · 改动写入 cordis.patch.yml · cordis 列=dump-config 生效状态",
                           objectName="cardHint")
        _top_hint.setWordWrap(True)
        top.addWidget(_top_hint)
        root.addLayout(top)

        mid = three_split(
            card_wrap("插件", self._make_list()),
            self._make_detail_card(),
            self._make_config_card())

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

        # 三栏横向可扩展: 视口不足时出横向滚动条(未来加栏不挤压), 底部位置让给滚动条
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

        self._profile_cb.activated.connect(lambda _i: self._refresh())
        self._refresh_btns()

    # ── 三栏构建(列表|详情|配置) ──
    def _make_list(self):
        self._list = ModernList()
        self._list.itemSelectionChanged.connect(self._on_select)
        return self._list

    def _make_detail_card(self):
        card = QFrame(objectName="card")
        dv = QVBoxLayout(card)
        dv.setContentsMargins(12, 10, 12, 10)
        dv.setSpacing(6)
        self._d_name = QLabel("-", objectName="cardTitle")
        self._d_name.setWordWrap(True)   # 长插件名不撑大栏最小宽度
        self._d_badges = QLabel("")
        self._d_badges.setTextFormat(Qt.RichText)
        self._d_badges.setWordWrap(True)   # 徽章行换行, 否则整行宽成为栏最小宽度挤压其他栏
        self._d_badges.setTextInteractionFlags(Qt.TextSelectableByMouse)
        dv.addWidget(self._d_name)
        dv.addWidget(self._d_badges)
        dv.addWidget(QLabel("描述", objectName="rightTitle"))
        self._d_desc = QLabel("-", objectName="monName")
        self._d_desc.setWordWrap(True)
        dv.addWidget(self._d_desc)
        dv.addWidget(QLabel("来源", objectName="rightTitle"))
        self._d_src = QLabel("-", objectName="monName")
        self._d_src.setWordWrap(True)
        dv.addWidget(self._d_src)
        dv.addWidget(QLabel("patch 原始键值", objectName="rightTitle"))
        self._detail_text = QPlainTextEdit()
        self._detail_text.setReadOnly(True)
        self._detail_text.setFont(QFont("Consolas", 9))
        dv.addWidget(self._detail_text, 1)
        return card

    def _make_config_card(self):
        card = QFrame(objectName="card")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(12, 10, 12, 10)
        cv.setSpacing(6)
        cv.addWidget(QLabel("配置（cordis 合成 · 只读）", objectName="rightTitle"))
        cv.addWidget(QLabel("来自 dsh --dump-config 的合成 entry 原文（含 bundle 层叠加后的最终配置）。",
                            objectName="cardHint"))
        self._config_text = QTextEdit()
        self._config_text.setReadOnly(True)
        self._config_text.setFont(QFont("Consolas", 9))
        cv.addWidget(self._config_text, 1)
        return card

    def _dash_repo(self):
        # dsh plugin/dump-config 命令必须在 dsh 仓库目录执行; 取 service 的 config 派生值
        return self.app.service.ctl.d.get("dash_repo") or ""

    # ── Profile 列表(经 service 信号桥) ──
    def _load_profiles(self):
        self._set_busy(True)
        self._set_status("正在读取 Profile 列表...")
        self.app.service.list_profiles(self._remote, op="plugins-profiles-list")

    def _apply_profiles(self, profiles, err):
        if err:
            self._set_busy(False)
            self._list.set_rows([])
            self._entries = []
            self._set_status("Profile 列表读取失败: " + err)
            self.app.loge("[插件] Profile 列表读取失败: " + err, "err")
            return
        usable = [p for p in profiles if p.get("cordis") or p.get("patch")]
        names = [p["name"] for p in usable]
        self._profile_cb.blockSignals(True)
        self._profile_cb.clear()
        self._profile_cb.addItems(names)
        self._profile_cb.blockSignals(False)
        if names:
            self._profile_cb.setCurrentIndex(0)
            self._refresh(force=False)
        else:
            self._set_busy(False)
            self._list.set_rows([])
            self._entries = []
            self._set_status("未找到可用 profile(~/.dsh/profiles 下没有 cordis.yml / cordis.patch.yml)")

    # ── 列表加载(先读缓存, mtime 变化或强制时后台拉取) ──
    def _refresh(self, force=False):
        profile = self._profile_cb.currentText().strip()
        if not profile:
            return
        if self._busy and not force:
            return
        src_mtime = dsh_data.plugins_source_mtime(profile, self._remote)
        cache_key = "plugins_" + profile
        cache_data, _ = core_cache.read_cache(cache_key)
        if not force and cache_data is not None and not core_cache.needs_refresh(cache_key, src_mtime):
            # 缓存已是最新: 直接呈现, 标记"无变化"(绿)
            self._id_map = cache_data.get("id_map") or {}
            self._cordis_states = cache_data.get("cordis_states") or {}
            self._apply_refresh(cache_data.get("entries") or [], "")
            self._spinner.set_status("ok")
            self._spinner.setToolTip("无变化(缓存已是最新)")
            return

        self._set_busy(True)
        self._pending = "plugins-load"
        self._set_status("正在读取插件列表...")
        self._spinner.set_loading(True)
        self.app.service.load_plugins(profile, self._remote)

    def _apply_refresh(self, entries, err):
        self._set_busy(False)
        self._entries = entries
        rows = []
        for e in entries:
            eid = e.get("id")
            name = e.get("name") or eid or "?"
            src = "cordis.patch.yml" if e.get("_src") == "patch" else "bundle"
            meta = [e.get("description") or "—", src]
            if e.get("version"):
                meta.append("v" + str(e.get("version")))
            if core_plugins.protected(eid):
                badge = ("受保护", "warn")
            elif e.get("disabled"):
                badge = ("已停用", "dim")
            else:
                badge = ("启用", "ok")
            badges = [badge]
            # 配置态与 cordis 生效态一致时不加徽章, 只提示分歧(例外才可见)
            cordis = e.get("cordis")
            if cordis == "disabled" and not e.get("disabled"):
                badges.append(("cordis 停用", "err"))
            elif cordis == "enabled" and e.get("disabled"):
                badges.append(("cordis 启用", "accent"))
            rows.append({"title": name, "meta": " · ".join(meta),
                         "badges": badges, "data": e})
        self._list.set_rows(rows)
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
        if op == "plugins-profiles-list":
            self._pending = None
            self._apply_profiles(payload.get("data") or [], payload.get("err", ""))
        elif op == "plugins-load":
            self._pending = None
            self._spinner.set_loading(False)
            profile = self._profile_cb.currentText().strip()
            cache_key = "plugins_" + profile
            err = payload.get("err") or ""
            if err:
                self._apply_refresh([], err)
                self._spinner.set_status("err")
                self._spinner.setToolTip("数据获取错误: " + str(err))
                return
            self._id_map = payload.get("id_map") or {}
            self._cordis_states = payload.get("cordis_states") or {}
            changed = core_cache.data_changed(cache_key, payload)
            core_cache.write_cache(cache_key, payload)
            self._apply_refresh(payload.get("entries") or [], "")
            if changed:
                self._spinner.set_status("warn")
                self._spinner.setToolTip("数据有变化(已刷新)")
            else:
                self._spinner.set_status("ok")
                self._spinner.setToolTip("无变化(缓存已是最新)")
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

        def do_install():
            self._run_stream(cmd, "安装插件 " + pkg)

        self._confirm.ask(
            "安装插件「%s」" % pkg,
            "将执行命令：\n<code>%s</code>" % " ".join(cmd),
            do_install,
            level="warn",
            confirm_text="确认安装"
        )

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

        def do_remove():
            self._run_stream(cmd, "卸载插件 " + pkg)

        self._confirm.ask(
            "卸载插件「%s」" % pkg,
            "将执行命令：\n<code>%s</code>\n卸载会从 Profile 移除插件文件与相关依赖行。" % " ".join(cmd),
            do_remove,
            level="danger",
            confirm_text="确认卸载"
        )

    def _run_stream(self, cmd, desc):
        # 官方命令经 service.run_cmd 在 dsh 仓库目录流式执行(逐行打主日志), 完成后回 finished。
        self._set_busy(True)
        self._pending = "plugins-cmd"
        self._set_status("执行中: " + " ".join(cmd))
        self.app.loge("[插件] " + desc + " 开始: " + " ".join(cmd), "warn")
        self.app.service.run_cmd(cmd, cwd=self._dash_repo(), op="plugins-cmd")

    def _after_stream(self, ok):
        self._last_op_msg = "已" + ("完成" if ok else "失败") + "(详见主界面日志区)"
        self._refresh(force=True)

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

        def do_disable():
            self._set_disabled(profile, eid, True)

        self._confirm.ask(
            "停用插件「%s」" % name,
            "将把「%s」标记为 disabled 并写入 %s/cordis.patch.yml(自动备份，HMR 约 1 秒生效)。" % (name, profile),
            do_disable,
            level="warn",
            confirm_text="确认停用"
        )

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

        def do_enable():
            self._set_disabled(profile, eid, False)

        self._confirm.ask(
            "启用插件「%s」" % name,
            "将移除「%s」的 disabled 标记并写入 %s/cordis.patch.yml(自动备份，HMR 约 1 秒生效)。" % (name, profile),
            do_enable,
            level="warn",
            confirm_text="确认启用"
        )

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
            self._refresh(force=True)
            return
        self.app.loge("[插件] " + msg, "ok")
        self._last_op_msg = msg + "（已刷新）"
        self._refresh(force=True)

    # ── 其它 ──
    def _selected_entry(self):
        # 当前选中行对应的 entry dict; 未选中返回 None
        row = self._list.current_data()
        return row.get("data") if row else None

    def _on_select(self):
        # 选中条目: 详情卡(徽章 chips + 描述/来源/patch 键值) + 配置栏(合成 entry 原文)
        e = self._selected_entry()
        if e is None:
            self._d_name.setText("-")
            self._d_badges.setText("")
            self._d_desc.setText("-")
            self._d_src.setText("-")
            self._detail_text.setPlainText("")
            self._config_text.setPlainText("（未选择条目）")
            self._refresh_btns()
            return
        eid = e.get("id")
        src = "cordis.patch.yml" if e.get("_src") == "patch" else "package.json (dsh.profile.bundles)"
        if core_plugins.protected(eid):
            state_chip = ("受保护", "#e5c07b")
        elif e.get("disabled"):
            state_chip = ("已停用", "#9a9ab0")
        else:
            state_chip = ("启用", "#7ecb6a")
        if e.get("cordis") == "disabled":
            cordis_chip = ("cordis 停用", "#e07a7a")
        elif e.get("cordis") == "enabled":
            cordis_chip = ("cordis 启用", "#7ecb6a")
        else:
            cordis_chip = ("cordis 未知", "#9a9ab0")
        self._d_name.setText(e.get("name") or eid or "?")
        chips = [(src, "#9a9ab0")]
        if e.get("version"):
            chips.append(("v" + str(e.get("version")), "#9a9ab0"))
        chips.append(state_chip)
        chips.append(cordis_chip)
        self._d_badges.setText(_chips_html(chips))
        self._d_desc.setText(e.get("description") or "—")
        self._d_src.setText(src)
        self._detail_text.setPlainText(_entry_src_text(e))
        rid = self._id_map.get(eid, eid)
        st = self._cordis_states.get(rid) or {}
        yaml = st.get("yaml")
        if yaml:
            self._config_text.setPlainText(yaml)
        else:
            self._config_text.setPlainText(
                "# 该条目不在 cordis 合成层\n"
                "# （纯依赖库/客户端包, 或 dump-config 不可用、远程部署）\n"
                "# 映射 id: " + str(rid))
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
