# -*- coding: utf-8 -*-
# 会话与工作区管理页(UI 层): 只做展示/确认框/busy 管理, 写业务在 core/sessions.py(纯 Python)。
# 归档/恢复与删除分组经 app.services 信号桥后台执行: set_sessions_archived(ids) /
# delete_session_group(workdir) -> result(op, payload) + finished(op, ok) 回页面槽;
# 接收者是页面自身, 页面销毁 Qt 自动断开。log/status 不在页面 connect —— 主窗口级已 connect
# 一次(勿叠加)。写盘路径校验与 rmtree 全部在 core(防线), 页面确认框只是交互前置。
# 刷新读取保留页面内后台线程 + safe_emit(纯读过渡态; 阶段4 收敛 dsh_data 后统一走 service)。
# 远程只读红线(本页关键约束): self._remote 非 None(远程部署)时归档/恢复/删除分组一律拒绝 ——
# 读取走远程、写入却落本机 workspace.json/本机 sessions 目录是语义错误, 必须封死。
# P1 多栏展开: 分组|会话|会话详情 三栏(ModernList + three_split), 第三栏显示选中会话完整信息。

import json
import time

from core import cache as core_cache
from core import data as dsh_data
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton, QMessageBox, QTextEdit,
    QScrollArea, QWidget)

from ui.base import BasePage
from ui.widgets import ModernList, RefreshIndicator, ConfirmBanner, card_wrap, three_split


def _human_size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f%s" % (n, unit)
        n /= 1024.0
    return "0B"


def _fmt_time(ts):
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts)))
    except Exception:
        # 时间展示失败只影响该单元格, 显示占位符即可
        return "-"


_REMOTE_READONLY_MSG = "远程部署下暂不支持写操作（远程只读），请切换回本机部署"


class SessionPage(BasePage):
    # 会话与工作区管理: BasePage 范式, app 为 MainWindow; 全部操作经 service 信号桥。

    def __init__(self, app, parent=None):
        self._remote = None
        _dep = getattr(app, "_current_deploy", None)
        if _dep and _dep.get("host"):
            self._remote = dsh_data.DshRemote(_dep)
        self._group_map = {}
        self._archived = set()
        self._sel_group = None
        self._sel_session = None    # 选中会话名(详情栏展示用)
        self._last_op_msg = None
        self._busy = False
        self._pending = None   # 正在等待的 service op: "sessions-read" / "sessions-archive" / "sessions-delete"
        super().__init__(app, parent)
        self.app.service.result.connect(self._on_result)
        self.app.service.finished.connect(self._on_finished)
        self._refresh()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 12)
        root.setSpacing(8)

        # 状态文字在标题右侧, 新增 RefreshIndicator 状态指示灯
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_row.addWidget(QLabel("会话与工作区管理", objectName="cardTitle"))
        self._spinner = RefreshIndicator()
        self._spinner.setToolTip("刷新状态: 绿=无变化 / 黄=数据有变化 / 红=获取错误")
        title_row.addWidget(self._spinner)
        title_row.addStretch(1)
        self._status_lbl = QLabel("就绪", objectName="monVal")
        title_row.addWidget(self._status_lbl)
        root.addLayout(title_row)
        hint = QLabel("会话数据存放在 ~/.dsh/sessions；归档只写 workspace.json，不移动数据；"
                      "进页自动取缓存+按需刷新。", objectName="cardHint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        wsf = QFrame(objectName="card")
        wl = QHBoxLayout(wsf)
        wl.setContentsMargins(12, 8, 12, 8)
        self._ws_lbl = QLabel("工作区数量: 0 个    已归档会话: 0 个", objectName="monName")
        wl.addWidget(self._ws_lbl)
        wl.addStretch(1)
        root.addWidget(wsf)

        mid = three_split(
            card_wrap("会话分组", self._make_list(is_group=True)),
            card_wrap("会话", self._make_list(is_group=False)),
            self._make_detail_card())
        root.addWidget(mid, 1)

        self._confirm = ConfirmBanner(self)
        root.addWidget(self._confirm)

        btns = QHBoxLayout()
        self._btn_refresh = QPushButton("刷新")
        self._btn_refresh.clicked.connect(self._refresh)
        self._btn_archive = QPushButton("归档/恢复")
        self._btn_archive.clicked.connect(self._toggle_archive)
        self._btn_delete = QPushButton("删除分组")
        self._btn_delete.clicked.connect(self._delete_group)
        for b in (self._btn_refresh, self._btn_archive, self._btn_delete):
            btns.addWidget(b)
        btns.addStretch(1)
        root.addLayout(btns)

        # 三栏横向可扩展: 视口不足时出横向滚动条, 底部位置让给滚动条
        mid.setMinimumWidth(1020)
        content = QWidget()
        cv = QVBoxLayout(content)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(8)
        cv.addWidget(mid, 1)
        cv.addLayout(btns)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

    # ── 三栏构建(分组|会话|详情) ──
    def _make_list(self, is_group):
        lst = ModernList()
        if is_group:
            self._group_list = lst
            lst.itemSelectionChanged.connect(self._on_group_select)
        else:
            self._session_list = lst
            lst.itemSelectionChanged.connect(self._on_session_select)
        return lst

    _DETAIL_FIELDS = (("name", "名称"), ("bytes", "大小"), ("mtime", "修改时间"),
                      ("state", "状态"), ("group", "所在分组"))

    def _make_detail_card(self):
        card = QFrame(objectName="card")
        v = QVBoxLayout(card)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)
        v.addWidget(QLabel("会话详情（选择会话查看）", objectName="rightTitle"))
        self._d_fields = {}
        for key, label in self._DETAIL_FIELDS:
            row = QHBoxLayout()
            row.addWidget(QLabel(label, objectName="monNote"))
            val = QLabel("-", objectName="monVal")
            val.setWordWrap(True)
            row.addWidget(val, 1)
            v.addLayout(row)
            self._d_fields[key] = val
        v.addWidget(QLabel("原始数据", objectName="rightTitle"))
        self._d_json = QTextEdit()
        self._d_json.setReadOnly(True)
        self._d_json.setFont(QFont("Consolas", 9))
        v.addWidget(self._d_json, 1)
        return card

    # ---- service 信号槽(接收者=本页, 销毁自动断开) ----
    def _on_result(self, op, payload):
        # result(op, payload) 按 op 分派; 其他页面的 op 直接忽略。
        if op == "sessions-read":
            self._busy = False
            self._set_btns(True)
            self._spinner.set_loading(False)
            err = payload.get("err") or ""
            data = payload.get("data")
            if err or not isinstance(data, dict):
                self._apply_data({}, [], str(err or "读取失败"))
                self._spinner.set_status("err")
                self._spinner.setToolTip("数据获取错误: " + str(err))
                return
            changed = core_cache.data_changed("sessions", data)
            core_cache.write_cache("sessions", data)
            self._apply_data(data.get("ws") or {}, data.get("groups") or [], "")
            if changed:
                self._spinner.set_status("warn")
                self._spinner.setToolTip("数据有变化(已刷新)")
            else:
                self._spinner.set_status("ok")
                self._spinner.setToolTip("无变化(缓存已是最新)")
        elif op == "sessions-archive":
            self._after_op(payload)
        elif op == "sessions-delete":
            self._after_op(payload)

    def _on_finished(self, op, ok):
        if op == self._pending:
            self._pending = None
            self._set_btns(True)

    # ---- 刷新(先读缓存, mtime 变化或强制时后台拉取) ----
    def _refresh(self, force=False):
        if self._busy:
            return
        src_mtime = dsh_data.sessions_source_mtime(self._remote)
        cache_data, _ = core_cache.read_cache("sessions")
        if not force and cache_data is not None and not core_cache.needs_refresh("sessions", src_mtime):
            # 缓存已是最新: 直接呈现, 标记"无变化"(绿)
            ws = cache_data.get("ws") or {}
            groups = cache_data.get("groups") or []
            self._apply_data(ws, groups, "")
            self._spinner.set_status("ok")
            self._spinner.setToolTip("无变化(缓存已是最新)")
            return

        self._busy = True
        self._pending = "sessions-read"
        self._set_status("正在读取会话数据...")
        self._set_btns(False)
        self._spinner.set_loading(True)
        self.app.service.read_sessions(self._remote)

    def _apply_data(self, ws, groups, err):
        self._set_btns(True)
        ws_ids = ws.get("workspaceIds") or []
        arch_ids = ws.get("archivedSessionIds") or []
        self._archived = set(str(x) for x in (arch_ids if isinstance(arch_ids, list) else []))
        self._ws_lbl.setText("工作区数量: %d 个    已归档会话: %d 个"
                             % (len(ws_ids), len(self._archived)))
        self._fill_groups(groups)
        if self._sel_group in self._group_map:
            self._select_group(self._sel_group)
        if err:
            self._set_status("读取失败: " + err)
        elif self._last_op_msg:
            self._set_status(self._last_op_msg)
            self._last_op_msg = None
        else:
            total = sum(g.get("count") or 0 for g in groups)
            self._set_status("已就绪: %d 个分组, %d 个会话" % (len(groups), total))

    def _fill_groups(self, groups):
        self._group_map = {}
        rows = []
        for g in groups:
            self._group_map[g["workdir"]] = g
            rows.append({
                "title": g["workdir"],
                "meta": "%d 个会话 · %s" % (g.get("count") or 0, _human_size(g.get("bytes"))),
                "data": g,
            })
        self._group_list.set_rows(rows)

    def _on_group_select(self):
        row = self._group_list.current_data()
        if not row:
            return
        g = row.get("data") or {}
        self._sel_group = g.get("workdir")
        self._show_group_details(self._sel_group)

    def _select_group(self, workdir):
        for r in range(self._group_list.count()):
            row = self._group_list.item(r).data(Qt.UserRole) or {}
            if (row.get("data") or {}).get("workdir") == workdir:
                self._group_list.setCurrentRow(r)
                return

    def _show_group_details(self, workdir):
        g = self._group_map.get(workdir)
        self._session_list.set_rows([])
        self._fill_session_detail(None)
        if not g:
            return
        rows = []
        for s in (g.get("sessions") or []):
            name = s.get("name") or "?"
            archived = name in self._archived
            rows.append({
                "title": name,
                "meta": "%s · %s" % (_human_size(s.get("bytes")), _fmt_time(s.get("mtime"))),
                "badges": [("已归档", "dim")] if archived else [("活跃", "ok")],
                "data": s,
            })
        self._session_list.set_rows(rows)
        if self._sel_session:
            self._select_session(self._sel_session)

    def _select_session(self, name):
        for r in range(self._session_list.count()):
            row = self._session_list.item(r).data(Qt.UserRole) or {}
            if (row.get("data") or {}).get("name") == name:
                self._session_list.setCurrentRow(r)
                return

    def _on_session_select(self):
        row = self._session_list.current_data()
        s = (row or {}).get("data")
        self._sel_session = (s or {}).get("name")
        self._fill_session_detail(s)

    def _fill_session_detail(self, s):
        vals = {k: "-" for k, _ in self._DETAIL_FIELDS}
        if s:
            archived = (s.get("name") or "") in self._archived
            vals = {
                "name": s.get("name") or "-",
                "bytes": _human_size(s.get("bytes")),
                "mtime": _fmt_time(s.get("mtime")),
                "state": "已归档" if archived else "活跃",
                "group": self._sel_group or "-",
            }
        for key, text in vals.items():
            self._d_fields[key].setText(text)
        self._d_json.setPlainText(
            json.dumps(s, ensure_ascii=False, indent=2) if s else "（未选择会话）")

    # ---- 归档/恢复(危险操作, 先确认; 远程只读红线) ----
    def _toggle_archive(self):
        if self._remote is not None:
            self._set_status(_REMOTE_READONLY_MSG)
            return
        row = self._session_list.current_data()
        if not row:
            self._set_status("请先选择要归档/恢复的会话")
            return
        name = (row.get("data") or {}).get("name") or ""
        was_archived = name in self._archived
        act = "恢复" if was_archived else "归档"
        msg = ("确定恢复会话「%s」为正常活跃状态？" % name) if was_archived \
            else ("确定归档会话「%s」？(写入 workspace.json，会话数据仍保留)" % name)

        def do_toggle():
            new_arch = set(self._archived)
            if was_archived:
                new_arch.discard(name)
            else:
                new_arch.add(name)
            self._pending = "sessions-archive"
            self._set_status("正在写入归档状态...")
            self._set_btns(False)
            self.app.service.set_sessions_archived(sorted(new_arch))

        self._confirm.ask(
            act + "会话",
            msg,
            do_toggle,
            level="warn",
            confirm_text="确认" + act
        )

    # ---- 删除分组(危险操作; 校验与 rmtree 在 core) ----
    def _delete_group(self):
        if self._remote is not None:
            self._set_status(_REMOTE_READONLY_MSG)
            return
        row = self._group_list.current_data()
        if not row:
            self._set_status("请先选择要删除的会话分组")
            return
        workdir = (row.get("data") or {}).get("workdir") or ""
        g = self._group_map.get(workdir)
        n = g.get("count") if g else 0

        def do_delete():
            self._pending = "sessions-delete"
            self._set_status("正在删除分组...")
            self._set_btns(False)
            self.app.service.delete_session_group(workdir)

        self._confirm.ask(
            "删除会话分组",
            "确定删除会话分组「%s」及其包含的 %d 个会话？此操作将彻底删除磁盘数据且不可恢复！" % (workdir, n),
            do_delete,
            level="danger",
            confirm_text="确认删除分组"
        )

    def _after_op(self, payload):
        # 写操作结果统一收尾: payload 至少含 "err"(成功为空字符串), "msg" 为成功文案。
        msg = payload.get("msg", "")
        err = payload.get("err", "")
        self._pending = None
        if err:
            self._set_btns(True)
            self._set_status("操作失败: " + err)
            return
        self.app.loge("[会话管理] " + msg, "ok")
        self._last_op_msg = msg + "（已刷新）"
        self._refresh(force=True)

    def _set_btns(self, on):
        for b in (self._btn_refresh, self._btn_archive, self._btn_delete):
            b.setEnabled(on)

    def _set_status(self, text):
        self._status_lbl.setText(text)
