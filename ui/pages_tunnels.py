# -*- coding: utf-8 -*-
# ui/pages_tunnels.py - 动态 SSH 隧道管理页: 声明式隧道卡片 CRUD + 方案规划器 + 批量启停。
# 支持任意拓扑与数量，支持场景向导新建/编辑，状态经 service 信号联动。

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QComboBox, QInputDialog, QMessageBox, QScrollArea, QWidget)

from core import config as dsh_config
from core import tunnel_planner as dsh_planner
from ui.base import BasePage
from ui.widgets import ConfirmBanner
from ui.dialog_tunnel_wizard import TunnelWizardDialog

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BTN_TEXT = {
    "start": "启动",
    "restart": "重启",
    "persist": "常驻",
    "stop": "停止",
    "edit": "编辑",
    "delete": "删除"
}


def build_items(cfg):
    # 兼容层: 供历史测试/外部调用(包含 5 张经典卡片定义)
    local = (cfg or {}).get("local_name") or "本机"
    lab = (cfg or {}).get("lab_name") or "实验室"
    ssh = (cfg or {}).get("ssh_name") or "公网中转"
    port = (cfg or {}).get("dash_port") or 3080
    return [
        {"type": "dsh", "key": "dsh-web", "title": local + " dsh", "port": port,
         "actions": ["start", "restart", "stop"],
         "desc": "启动/重启/停止%s dsh GUI\n(后台 pnpm dsh web,\n访问 http://127.0.0.1:%d)" % (local, port)},
        {"type": "py", "key": "dsh-tunnel", "port": 8090, "backend": "python",
         "actions": ["start", "persist", "stop"],
         "desc": "在家 -> 打通三个转发口\n8090->%sGUI / 8022->SSH / 8091->本机GUI" % lab},
        {"type": "py", "key": "connect-lab-dsh", "port": 3090, "backend": "python",
         "actions": ["start", "persist", "stop"],
         "desc": "%s局域网 -> 直连%s dsh GUI (本机 3090)" % (lab, lab)},
        {"type": "py", "key": "dsh-tunnel-reverse", "port": 0, "backend": "python",
         "actions": ["start", "persist", "stop"],
         "desc": "%s dsh -> %s反向隧道\n%s:8091 -> 本机 3080" % (local, ssh, ssh)},
        {"type": "py", "key": "update-dsh", "port": -1, "backend": "python",
         "actions": ["run"],
         "desc": "运行一次完整更新:\ngit 拉取->依赖->构建->重启"},
    ]


ITEMS = build_items(dsh_config.load_config())


def _apply_items(cfg):
    # 热重载: 原地更新 ITEMS 供外部单测/兼容调用
    ITEMS.clear()
    ITEMS.extend(build_items(cfg))


def card_states_from_monitor(local, remote, cfg):
    # 纯函数: 把监控探测结果翻译为隧道卡片状态 {key: bool}
    states = {}
    dp = (cfg or {}).get("dash_port") or 3080
    states["dsh-web"] = bool(local and local.get(dp, (False, -1))[0])
    states["dsh-tunnel"] = bool(local and local.get(8090, (False, -1))[0])
    lab_p = (cfg or {}).get("lab_port") or 3090
    states["connect-lab-dsh"] = bool(local and local.get(lab_p, (False, -1))[0])
    if remote is not None:
        rp = (cfg or {}).get("reverse_port") or 8091
        states["dsh-tunnel-reverse"] = bool(remote.get(rp, False))

    tunnels = dsh_config.normalize_tunnels(cfg)
    for tun in tunnels:
        tid = tun.get("id")
        mode = tun.get("mode") or "forward"
        forwards = tun.get("forwards") or []
        if mode == "forward":
            wp = tun.get("watch_port") or (forwards[0].get("local_port") if forwards else None)
            if wp and local:
                states[tid] = bool(local.get(wp, (False, -1))[0])
        elif mode == "reverse" and remote is not None:
            rp = forwards[0].get("local_port") if forwards else None
            if rp:
                states[tid] = bool(remote.get(rp, False))
    return states


class TunnelsPage(BasePage):
    # 动态 SSH 隧道管理页面
    def _build(self):
        self.app.service.card.connect(self._apply_card)
        self.app.service.finished.connect(self._on_service_finished)
        self._cards = {}
        self._pending_apply_plan = None

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # 1. 顶栏: 标题 + 全局启停 + 新增隧道
        head = QHBoxLayout()
        title = QLabel("SSH 隧道管理", objectName="cardTitle")
        self._status_lbl = QLabel("就绪", objectName="monVal")
        head.addWidget(title)
        head.addStretch(1)

        btn_add = QPushButton("添加隧道 (向导)", objectName="primary")
        btn_add.clicked.connect(self._on_add_tunnel)
        btn_start_all = QPushButton("全部启动")
        btn_start_all.clicked.connect(self._on_start_all)
        btn_stop_all = QPushButton("全部停止")
        btn_stop_all.clicked.connect(self._on_stop_all)

        head.addWidget(btn_add)
        head.addWidget(btn_start_all)
        head.addWidget(btn_stop_all)
        head.addWidget(self._status_lbl)
        root.addLayout(head)

        # 2. 方案规划器卡片
        plan_card = QFrame(objectName="card")
        pv = QVBoxLayout(plan_card)
        pv.setContentsMargins(14, 10, 14, 10)
        pv.setSpacing(6)
        prow = QHBoxLayout()
        prow.addWidget(QLabel("拓扑方案:", objectName="rightTitle"))
        self._plan_combo = QComboBox()
        self._plan_combo.setMinimumWidth(160)
        self._plan_combo.currentIndexChanged.connect(self._plan_selected)
        prow.addWidget(self._plan_combo)

        for text, fn in (("应用", self._plan_apply),
                         ("新建", self._plan_new),
                         ("保存", self._plan_save),
                         ("重命名", self._plan_rename),
                         ("删除", self._plan_del),
                         ("拓扑校验", self._plan_validate),
                         ("启动自检", self._plan_selfcheck)):
            b = QPushButton(text)
            if text == "应用":
                self._btn_apply = b
            b.clicked.connect(fn)
            prow.addWidget(b)
        prow.addStretch(1)
        pv.addLayout(prow)

        self._plan_out = QLabel("选择方案后点「应用」切换整套拓扑组合 (自动备份并热重载)。", objectName="cardHint")
        self._plan_out.setWordWrap(True)
        pv.addWidget(self._plan_out)

        self._confirm = ConfirmBanner(self)
        pv.addWidget(self._confirm)
        root.addWidget(plan_card)

        # 3. 动态隧道卡片滚动容器
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll_content = QWidget()
        self._cards_layout = QVBoxLayout(scroll_content)
        self._cards_layout.setContentsMargins(0, 4, 0, 4)
        self._cards_layout.setSpacing(10)
        scroll.setWidget(scroll_content)
        root.addWidget(scroll, 1)

        self._plan_refresh()
        self._render_cards()

    def _current_cards_tunnels(self):
        p = self._selected_plan()
        if p and p.get("tunnels"):
            return list(p["tunnels"])
        return [item for _, item in self._cards.values()]

    def _render_cards(self, tunnels=None):
        # 递归彻底清理已有卡片与嵌套布局
        def _clear_layout(lay):
            while lay.count():
                item = lay.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
                elif item.layout():
                    _clear_layout(item.layout())
        _clear_layout(self._cards_layout)

        self._cards.clear()
        cfg = dsh_config.load_config()
        p = self._selected_plan()
        active_name = cfg.get("tunnel_plans_active") or ""
        is_active = bool(p and p.get("name") == active_name) if p else True

        if tunnels is None:
            if p is not None:
                if "tunnels" in p and p.get("tunnels"):
                    tunnels = p.get("tunnels") or []
                else:
                    tunnels = dsh_config.normalize_tunnels(p)
            else:
                tunnels = dsh_config.normalize_tunnels(cfg)

        if not is_active and p:
            hint = QLabel("⚠️ 当前方案「%s」为未生效预览。点上方「应用」使该方案生效。" % p.get("name"), objectName="cardHint")
            hint.setStyleSheet("background: rgba(229,192,123,0.15); border: 1px solid #e5c07b; border-radius: 4px; padding: 6px 12px; color: #e5c07b;")
            self._cards_layout.addWidget(hint)

        if not tunnels:
            empty = QLabel("暂无配置的 SSH 隧道。点击上方「添加隧道 (向导)」按钮通过向导快速创建。", objectName="cardHint")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet("padding: 40px; color: #888;")
            self._cards_layout.addWidget(empty)
            return

        row = QHBoxLayout()
        row.setSpacing(10)
        for i, tun in enumerate(tunnels):
            card = self._make_tunnel_card(tun, is_active=is_active)
            row.addWidget(card, 1)
            if (i + 1) % 2 == 0:
                self._cards_layout.addLayout(row)
                row = QHBoxLayout()
                row.setSpacing(10)
        if row.count():
            row.addStretch(1)
            self._cards_layout.addLayout(row)
        self._cards_layout.addStretch(1)

        # 恢复状态圆点
        for key, on in self.app._card_state.items():
            self._set_card(key, on)

    def _make_tunnel_card(self, item, is_active=True):
        card = QFrame(objectName="card")
        lv = QVBoxLayout(card)
        lv.setContentsMargins(14, 12, 14, 12)
        lv.setSpacing(6)

        # 标题栏: 名称 + 模式徽章 + 状态圆点
        head = QHBoxLayout()
        tname = item.get("name") or item.get("id")
        title = QLabel(tname, objectName="cardTitle")
        head.addWidget(title)

        mode = item.get("mode") or "forward"
        badge_txt = "[正向 -L]" if mode == "forward" else "[反向 -R]"
        badge = QLabel(badge_txt)
        badge.setStyleSheet("color: #58a6ff; font-weight: bold; font-size: 11px;")
        head.addWidget(badge)
        if not is_active:
            prev_badge = QLabel("(未生效)")
            prev_badge.setStyleSheet("color: #e5c07b; font-size: 11px;")
            head.addWidget(prev_badge)
        head.addStretch(1)

        dot = QLabel("○", objectName="monDot")
        dot.setStyleSheet("color:#999; font-size:16px;")
        head.addWidget(dot)
        lv.addLayout(head)

        # 主机信息
        target = "%s@%s:%d" % (item.get("user") or "user", item.get("host") or "host", item.get("ssh_port") or 22)
        host_lbl = QLabel("目标: " + target, objectName="cardHint")
        lv.addWidget(host_lbl)

        # 端口映射明细
        fwd_lines = []
        is_reverse = (item.get("mode") == "reverse")
        for fw in item.get("forwards") or []:
            lp = fw.get("local_port") if isinstance(fw, dict) else fw[0]
            rh = (fw.get("remote_host") if isinstance(fw, dict) else fw[1]) or "127.0.0.1"
            rp = fw.get("remote_port") if isinstance(fw, dict) else fw[2]
            desc = fw.get("desc") if isinstance(fw, dict) else (fw[3] if len(fw) >= 4 else "")
            if is_reverse:
                line = "• 公网暴露 :%d  ➔  回源本机 %s:%d" % (lp, rh, rp)
            else:
                line = "• 本机访问 :%d  ➔  远端目标 %s:%d" % (lp, rh, rp)
            if desc:
                line += "  (%s)" % desc
            fwd_lines.append(line)

        fwd_desc = QLabel("\n".join(fwd_lines) if fwd_lines else "• 无端口映射规则", objectName="monName")
        fwd_desc.setStyleSheet("color: #bbb; line-height: 1.4;")
        lv.addWidget(fwd_desc)

        # 操作按钮
        btns = QHBoxLayout()
        tid = item.get("id")

        b_start = QPushButton("启动")
        b_start.clicked.connect(lambda _=False, it=item: self._on_tunnel_action(it, "start"))
        b_persist = QPushButton("常驻")
        b_persist.clicked.connect(lambda _=False, it=item: self._on_tunnel_action(it, "persist"))
        b_stop = QPushButton("停止")
        b_stop.clicked.connect(lambda _=False, it=item: self._on_tunnel_action(it, "stop"))
        b_edit = QPushButton("编辑")
        b_edit.clicked.connect(lambda _=False, it=item: self._on_edit_tunnel(it))
        b_del = QPushButton("删除")
        b_del.clicked.connect(lambda _=False, it=item: self._on_delete_tunnel(it))

        btns.addWidget(b_start)
        btns.addWidget(b_persist)
        btns.addWidget(b_stop)
        btns.addWidget(b_edit)
        btns.addWidget(b_del)
        btns.addStretch(1)
        lv.addLayout(btns)

        self._cards[tid] = (dot, item)
        return card

    def _set_card(self, key, on):
        entry = self._cards.get(key)
        if entry is None or entry[0] is None:
            return
        d, _ = entry
        d.setText("●" if on else "○")
        d.setStyleSheet("color:#7ecb6a; font-size:16px;" if on else "color:#999; font-size:16px;")

    def _apply_card(self, key, on):
        self._set_card(key, on)

    def _on_tunnel_action(self, item, mode):
        tid = item.get("id")
        tname = item.get("name") or tid
        cfg = dsh_config.load_config()
        active_plan = cfg.get("tunnel_plans_active") or ""
        p = self._selected_plan()
        # 若方案未生效，启动前确认是否立即应用并启动
        if p and p.get("name") != active_plan and mode in ("start", "persist"):
            ret = QMessageBox.question(
                self, "方案未生效",
                "方案「%s」当前尚未应用生效。\n是否立即应用该方案并执行【%s】？" % (p["name"], BTN_TEXT.get(mode, mode)),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
            )
            if ret == QMessageBox.Yes:
                self._plan_apply()
            else:
                return

        self.app.loge("[%s] 模式: %s" % (tname, mode), "warn")
        self.app.set_status("正在执行 %s -> %s ..." % (mode, tname))
        self.app.service.start_tunnel(tid, mode)

    def _on_action(self, item, mode):
        return self._on_tunnel_action(item, mode)

    def _on_start_all(self):
        self.app.loge("[全部启动] 正在启动所有启用的 SSH 隧道...", "warn")
        self.app.service.start_all_tunnels()

    def _on_stop_all(self):
        self.app.loge("[全部停止] 正在停止所有 SSH 隧道...", "warn")
        self.app.service.stop_all_tunnels()

    # ── 隧道 CRUD ──
    def _on_add_tunnel(self):
        cfg = dsh_config.load_config()
        dlg = TunnelWizardDialog(cfg=cfg, parent=self)
        if dlg.exec_() == TunnelWizardDialog.Accepted and dlg.result_item:
            p = self._selected_plan()
            plan_name = p.get("name") if p else None
            tunnels = list(p.get("tunnels") or []) if p else list(dsh_config.normalize_tunnels(cfg))
            tunnels.append(dlg.result_item)
            if p:
                p["tunnels"] = tunnels
                cfg = dsh_planner.upsert_plan(cfg, p)
            if not p or cfg.get("tunnel_plans_active") == plan_name:
                cfg["tunnels"] = tunnels
            if dsh_config.save_config(cfg):
                self._plan_refresh(select=plan_name)
                self.app.reload_config()
                self._render_cards()
                self.app.loge("成功添加隧道: %s" % dlg.result_item.get("name"), "ok")
            else:
                QMessageBox.warning(self, "保存失败", "写入 config.json 失败")

    def _on_edit_tunnel(self, item):
        cfg = dsh_config.load_config()
        dlg = TunnelWizardDialog(cfg=cfg, editing_item=item, parent=self)
        if dlg.exec_() == TunnelWizardDialog.Accepted and dlg.result_item:
            p = self._selected_plan()
            plan_name = p.get("name") if p else None
            tunnels = list(p.get("tunnels") or []) if p else list(dsh_config.normalize_tunnels(cfg))
            new_list = []
            for t in tunnels:
                if t.get("id") == item.get("id"):
                    new_list.append(dlg.result_item)
                else:
                    new_list.append(t)
            if p:
                p["tunnels"] = new_list
                cfg = dsh_planner.upsert_plan(cfg, p)
            if not p or cfg.get("tunnel_plans_active") == plan_name:
                cfg["tunnels"] = new_list
            if dsh_config.save_config(cfg):
                self._plan_refresh(select=plan_name)
                self.app.reload_config()
                self._render_cards()
                self.app.loge("已更新隧道: %s" % dlg.result_item.get("name"), "ok")
            else:
                QMessageBox.warning(self, "保存失败", "写入 config.json 失败")

    def _on_delete_tunnel(self, item):
        tid = item.get("id")
        tname = item.get("name") or tid
        ret = QMessageBox.question(
            self, "确认删除",
            "确定要删除隧道「%s」吗？若该隧道正在运行，将自动终止该进程。" % tname,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if ret == QMessageBox.Yes:
            self.app.service.stop_tunnel(tid)
            p = self._selected_plan()
            plan_name = p.get("name") if p else None
            cfg = dsh_config.load_config()
            tunnels = list(p.get("tunnels") or []) if p else list(dsh_config.normalize_tunnels(cfg))
            new_list = [t for t in tunnels if t.get("id") != tid]
            if p:
                p["tunnels"] = new_list
                cfg = dsh_planner.upsert_plan(cfg, p)
            if not p or cfg.get("tunnel_plans_active") == plan_name:
                cfg["tunnels"] = new_list
            dsh_config.save_config(cfg)
            self._plan_refresh(select=plan_name)
            self.app.reload_config()
            self._render_cards()
            self.app.loge("已删除隧道: %s" % tname, "ok")

    # ── 隧道方案管理 ──
    def _plan_refresh(self, select=None):
        cfg = dsh_config.load_config()
        plans = dsh_planner.load_plans(cfg)
        self._plan_combo.blockSignals(True)
        self._plan_combo.clear()
        for p in plans:
            self._plan_combo.addItem(p.get("name"), p)
        cur = select or cfg.get("tunnel_plans_active") or (plans[0].get("name") if plans else "")
        idx = next((i for i in range(self._plan_combo.count())
                    if self._plan_combo.itemText(i) == cur), 0)
        if self._plan_combo.count():
            self._plan_combo.setCurrentIndex(idx)
        self._plan_combo.blockSignals(False)

    def _selected_plan(self):
        name = self._plan_combo.currentText().strip()
        if not name:
            return None
        cfg = dsh_config.load_config()
        p = dsh_planner.find_plan(cfg, name)
        if p is not None:
            return p
        return self._plan_combo.currentData()

    @staticmethod
    def _plan_summary(p):
        tuns = p.get("tunnels") or []
        if tuns:
            return "包含 %d 条隧道: %s" % (len(tuns), ", ".join(t.get("name") or t.get("id") for t in tuns))
        return "中继: %s | 反向: %s | 实验室: %s" % (
            ", ".join(str(x) for x in (p.get("forward_ports") or [])) or "无",
            p.get("reverse_port") or "无", p.get("lab_port") or "无")

    def _plan_selected(self, _idx):
        p = self._selected_plan()
        if p:
            cfg = dsh_config.load_config()
            active_name = cfg.get("tunnel_plans_active") or ""
            is_active = (p.get("name") == active_name)
            summary = self._plan_summary(p)
            if is_active:
                self._set_plan_out("当前生效方案: 「%s」 (%s)" % (p["name"], summary), err=False)
            else:
                self._set_plan_out("方案「%s」: %s (未生效预览，点「应用」切换生效)" % (p["name"], summary), err=False)
            self._render_cards()

    def _set_plan_out(self, text, err=False):
        self._plan_out.setText(text)
        self._plan_out.setStyleSheet("color: %s;" % ("#e07a7a" if err else "#7ecb6a"))

    def _plan_apply(self):
        p = self._selected_plan()
        if not p:
            self._set_plan_out("先在方案列表中选择一个方案", err=True)
            return

        # 1. 记录待应用方案并禁用按钮，先异步停止上一方案所有隧道
        self._pending_apply_plan = p
        if hasattr(self, "_btn_apply"):
            self._btn_apply.setEnabled(False)
        self._set_plan_out("正在切换方案「%s」，等待旧方案隧道停止..." % p["name"], err=False)
        self.app.loge("[隧道方案] 切换生效方案「%s」，正在安全停止上一方案运行中的隧道..." % p["name"], "warn")
        self.app.service.stop_all_tunnels(op="plan-apply-stop-all")

    def _on_service_finished(self, op, ok):
        if op == "plan-apply-stop-all":
            self._finish_plan_apply()

    def _finish_plan_apply(self):
        p = getattr(self, "_pending_apply_plan", None)
        if hasattr(self, "_btn_apply"):
            self._btn_apply.setEnabled(True)
        if not p:
            return
        self._pending_apply_plan = None

        # 2. 旧隧道完全停机后，应用新方案并写入配置
        cfg = dsh_planner.apply_plan(dsh_config.load_config(), p)
        if not dsh_config.save_config(cfg):
            self._set_plan_out("应用失败: config.json 写入失败", err=True)
            return

        # 3. 刷新界面、重载配置并即时触发监控探测
        self._plan_refresh(select=p["name"])
        self.app.reload_config()
        self._render_cards()
        self.app.service.monitor_once()
        self._set_plan_out("已应用生效方案「%s」(旧隧道已停止，新拓扑已生效并重载监控)" % p["name"], err=False)
        self.app.loge("[隧道方案] 已应用生效方案: " + p["name"], "ok")

    def _plan_new(self):
        cfg = dsh_config.load_config()
        default = "方案 %d" % (len(dsh_planner.load_plans(cfg)) + 1)
        name, ok = QInputDialog.getText(self, "新建拓扑方案", "输入新方案名称:", text=default)
        if not ok or not name.strip():
            return
        name = name.strip()
        if dsh_planner.find_plan(cfg, name):
            QMessageBox.warning(self, "名称冲突", "方案名称「%s」已存在，请使用其他名称。" % name)
            return
        p = self._selected_plan()
        tunnels = list(p.get("tunnels") or []) if p else list(dsh_config.normalize_tunnels(cfg))
        plan_data = {
            "name": name,
            "tunnels": tunnels,
            "forward_ports": [],
            "reverse_port": 0,
            "lab_port": 0,
        }
        cfg = dsh_planner.upsert_plan(cfg, plan_data)
        if not dsh_config.save_config(cfg):
            self._set_plan_out("新建失败: config.json 写入失败", err=True)
            return
        self._plan_refresh(select=name)
        self._render_cards()
        self._set_plan_out("已新建方案「%s」(保存了当前隧道拓扑)" % name)
        self.app.loge("[隧道方案] 已新建: " + name, "ok")

    def _plan_save(self):
        p = self._selected_plan()
        if not p:
            self._plan_new()
            return
        name = p.get("name")
        cfg = dsh_config.load_config()
        tunnels = list(p.get("tunnels") or [])
        plan_data = dict(p)
        plan_data["tunnels"] = tunnels
        cfg = dsh_planner.upsert_plan(cfg, plan_data)
        if cfg.get("tunnel_plans_active") == name:
            cfg["tunnels"] = tunnels
        if not dsh_config.save_config(cfg):
            self._set_plan_out("保存失败: config.json 写入失败", err=True)
            return
        self._plan_refresh(select=name)
        self.app.reload_config()
        self._render_cards()
        self._set_plan_out("已将当前隧道拓扑保存覆盖至方案「%s」" % name)
        self.app.loge("[隧道方案] 已覆盖保存: " + name, "ok")

    def _plan_rename(self):
        p = self._selected_plan()
        if not p:
            self._set_plan_out("先选择要重命名的方案", err=True)
            return
        name, ok = QInputDialog.getText(self, "重命名方案", "新方案名:", text=p["name"])
        if not ok or not name.strip() or name.strip() == p["name"]:
            return
        name = name.strip()
        cfg = dsh_config.load_config()
        if dsh_planner.find_plan(cfg, name):
            QMessageBox.warning(self, "名称冲突", "方案名称「%s」已存在，请使用其他名称。" % name)
            return
        cfg = dsh_planner.delete_plan(cfg, p["name"])
        cfg = dsh_planner.upsert_plan(cfg, dict(p, name=name))
        if cfg.get("tunnel_plans_active") == p["name"]:
            cfg["tunnel_plans_active"] = name
        if not dsh_config.save_config(cfg):
            self._set_plan_out("重命名失败: 写入失败", err=True)
            return
        self._plan_refresh(select=name)
        self.app.reload_config()
        self._set_plan_out("已重命名为: " + name)

    def _plan_del(self):
        p = self._selected_plan()
        if not p:
            self._set_plan_out("先选择要删除的方案", err=True)
            return

        def do_del():
            cfg = dsh_planner.delete_plan(dsh_config.load_config(), p["name"])
            if not dsh_config.save_config(cfg):
                self._set_plan_out("删除失败: 写入失败", err=True)
                return
            self._plan_refresh()
            self.app.reload_config()
            self._render_cards()
            self._set_plan_out("已删除方案: " + p["name"])

        self._confirm.ask(
            "删除方案「%s」" % p["name"],
            "将删除该拓扑方案快照（不影响当前已生效的隧道规则）。",
            do_del,
            level="danger",
            confirm_text="确认删除"
        )

    def _plan_validate(self):
        p = self._selected_plan()
        if not p:
            self._set_plan_out("先选择要校验的方案", err=True)
            return
        issues = dsh_planner.validate_plan(p, dsh_config.load_config())
        if not issues:
            self._set_plan_out("校验通过: 「%s」未发现配置冲突" % p["name"])
            self.app.loge("[隧道] 方案校验通过: " + p["name"], "ok")
            return
        errs = [i for i in issues if i["level"] == "error"]
        text = "校验「%s」: %d 错误 / %d 警告 — %s" % (
            p["name"], len(errs), len(issues) - len(errs),
            " ; ".join(i["msg"] for i in issues))
        self._set_plan_out(text, err=bool(errs))
        self.app.loge("[隧道] 方案校验: %d 错误 / %d 警告" % (len(errs), len(issues) - len(errs)),
                      "err" if errs else "warn")

    def _plan_selfcheck(self):
        p = self._selected_plan()
        cfg = dsh_config.load_config()
        target_name = p.get("name") if p else "当前配置"
        self.app.loge("[隧道] 正在对方案「%s」执行连通性与进程自检..." % target_name, "warn")
        rows = dsh_planner.self_check(cfg, BASE_DIR, plan=p)

        for n, s, d in rows:
            tag = "ok" if s is True else ("warn" if s is None else "err")
            state_str = "在线" if s is True else ("未启动" if s is None else "异常")
            self.app.loge("  • %s: %s (%s)" % (n, state_str, d), tag)

        err_cnt = sum(1 for _, s, _ in rows if s is False)
        ok_cnt = sum(1 for _, s, _ in rows if s is True)
        unstart_cnt = sum(1 for _, s, _ in rows if s is None)

        summary = "自检「%s」: %d 在线 / %d 未启动 / %d 异常" % (target_name, ok_cnt, unstart_cnt, err_cnt)
        self._set_plan_out(summary, err=(err_cnt > 0))
        self.app.loge("[隧道] 自检完成: " + summary, "ok" if err_cnt == 0 else "warn")
