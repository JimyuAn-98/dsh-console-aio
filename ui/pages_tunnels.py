# -*- coding: utf-8 -*-
# ui/pages_tunnels.py - 隧道管理页: 隧道卡片启停 + 隧道方案规划器(校验/切换/自检)。
# 卡片在线状态经 service.card 信号回本页; 拓扑方案应用/删除经 ConfirmBanner 内联确认。

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QComboBox, QInputDialog)

from core import config as dsh_config
from core import tunnel_planner as dsh_planner
from ui.base import BasePage
from ui.widgets import ConfirmBanner

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BTN_TEXT = {
    "start": "启动",
    "restart": "重启",
    "persist": "常驻",
    "stop": "停止",
    "run": "运行更新"
}


def build_items(cfg):
    # 隧道卡片清单(名字可配置, P0): local/lab/ssh 三处命名来自 config。
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
    # 热重载: 原地重建卡片清单(TunnelsPage 重建时读取)
    ITEMS.clear()
    ITEMS.extend(build_items(cfg))


def card_states_from_monitor(local, remote, cfg):
    # 把监控探测结果翻译为隧道卡片状态(纯函数, 可单测): 返回 {key: bool}。
    # 本机 dsh / 本机隧道卡片看本机端口探测; 反向隧道看公网侧 reverse_port 是否在监听
    # (remote 探测); 探测无数据(如 remote 为 None)的 key 不下结论, 保持上次状态。
    states = {}
    for item in ITEMS:
        key, port = item["key"], item.get("port")
        if key in ("dsh-web", "dsh-tunnel", "connect-lab-dsh"):
            states[key] = bool(local and local.get(port, (False, -1))[0])
        elif key == "dsh-tunnel-reverse" and remote is not None:
            rp = (cfg or {}).get("reverse_port") or 8091
            states[key] = bool(remote.get(rp, False))
    return states


class TunnelsPage(BasePage):
    # 隧道与 dsh 服务操控页: 卡片启停 + 方案管理
    def _build(self):
        # 卡片在线状态经 service.card 信号回本页(接收者=本页, 页面销毁时 Qt 自动断开)。
        self.app.service.card.connect(self._apply_card)
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(6)
        title = QLabel("隧道 / dsh 服务操控", objectName="cardTitle")
        self._status_lbl = QLabel("就绪", objectName="monVal")
        head = QHBoxLayout()
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self._status_lbl)
        v.addLayout(head)

        # 隧道方案(规划器): 拓扑字段的命名快照, 应用=写回标准字段并热重载;
        # 字段编辑仍走设置页端口表(唯一编辑器), 这里负责 校验/切换/自检
        plan_card = QFrame(objectName="card")
        pv = QVBoxLayout(plan_card)
        pv.setContentsMargins(16, 12, 16, 12)
        pv.setSpacing(6)
        prow = QHBoxLayout()
        prow.addWidget(QLabel("隧道方案", objectName="rightTitle"))
        self._plan_combo = QComboBox()
        self._plan_combo.setMinimumWidth(170)
        self._plan_combo.currentIndexChanged.connect(self._plan_selected)
        prow.addWidget(self._plan_combo)
        for text, fn in (("应用", self._plan_apply), ("存当前为方案", self._plan_save),
                         ("重命名", self._plan_rename), ("删除", self._plan_del),
                         ("校验", self._plan_validate), ("启动自检", self._plan_selfcheck)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            prow.addWidget(b)
        prow.addStretch(1)
        pv.addLayout(prow)
        self._plan_out = QLabel("选择方案后「应用」切换拓扑(自动 .bak + 热重载); "
                                "改端口/加映射请到 设置 页的端口表。", objectName="cardHint")
        self._plan_out.setWordWrap(True)
        pv.addWidget(self._plan_out)

        self._confirm = ConfirmBanner(self)
        pv.addWidget(self._confirm)

        v.addWidget(plan_card)

        self._cards = {}
        grid = QVBoxLayout()
        grid.setSpacing(10)
        row = QHBoxLayout()
        row.setSpacing(10)
        for i, item in enumerate(ITEMS):
            # dsh 域两卡(本机 dsh 操控/运行更新)已迁「DSH 管理」页, 隧道页回归纯隧道;
            # ITEMS 保留这两项(探测/状态单一来源, 概览页 dsh-web 卡与监控仍依赖)
            if item.get("type") == "dsh" or item.get("key") == "update-dsh":
                continue
            card = self._make_card(item)
            row.addWidget(card, 1)
            if (i + 1) % 2 == 0:
                grid.addLayout(row)
                row = QHBoxLayout()
                row.setSpacing(10)
        if row.count():
            row.addStretch(1)
            grid.addLayout(row)
        v.addLayout(grid)
        v.addStretch(1)

        # 应用已知状态快照(监控/启停事件持续更新; 页面重建后不丢状态)
        for key, on in self.app._card_state.items():
            self._set_card(key, on)
        self._plan_refresh()

    # ── 隧道方案(规划器): 拓扑字段的命名快照, 应用=写回标准字段+热重载 ──
    def _plan_refresh(self, select=None):
        cfg = dsh_config.load_config()
        plans = dsh_planner.load_plans(cfg)
        self._plan_combo.blockSignals(True)
        self._plan_combo.clear()
        for p in plans:
            self._plan_combo.addItem(p.get("name"), p)
        cur = select or cfg.get("tunnel_plans_active") or ""
        idx = next((i for i in range(self._plan_combo.count())
                    if self._plan_combo.itemText(i) == cur), 0)
        if self._plan_combo.count():
            self._plan_combo.setCurrentIndex(idx)
        self._plan_combo.blockSignals(False)

    def _selected_plan(self):
        return self._plan_combo.currentData()

    @staticmethod
    def _plan_summary(p):
        return "中继转发: %s | 反向端口: %s | 实验室端口: %s" % (
            ", ".join(str(x) for x in (p.get("forward_ports") or [])) or "无",
            p.get("reverse_port") or "无", p.get("lab_port") or "无")

    def _plan_selected(self, _idx):
        p = self._selected_plan()
        if p:
            self._plan_out.setText(self._plan_summary(p) + " —— 点「应用」生效")

    def _set_plan_out(self, text, err=False):
        self._plan_out.setText(text)
        self._plan_out.setStyleSheet("color: %s;" % ("#e07a7a" if err else "#7ecb6a"))

    def _plan_apply(self):
        p = self._selected_plan()
        if not p:
            self._set_plan_out("先在方案列表中选择一个方案", err=True)
            return

        def do_apply():
            cfg = dsh_planner.apply_plan(dsh_config.load_config(), p)
            if not dsh_config.save_config(cfg):
                self._set_plan_out("应用失败: config.json 写入失败(可能被占用)", err=True)
                return
            self.app.reload_config()
            self._plan_refresh(select=p["name"])
            self._set_plan_out("已应用方案「%s」(新端口在下次启动隧道时生效)" % p["name"])

        self._confirm.ask(
            "应用方案「%s」" % p["name"],
            "将把方案端口拓扑写入 config.json(自动 .bak)并热重载。正在运行的隧道不受影响，新配置下次生效。",
            do_apply,
            level="warn",
            confirm_text="应用方案"
        )

    def _plan_save(self):
        cfg = dsh_config.load_config()
        default = "方案 %d" % (len(dsh_planner.load_plans(cfg)) + 1)
        name, ok = QInputDialog.getText(self, "存当前为方案", "方案名:", text=default)
        if not ok or not name.strip():
            return
        name = name.strip()
        cfg = dsh_planner.upsert_plan(cfg, dsh_planner.snapshot_plan(cfg, name))
        if not dsh_config.save_config(cfg):
            self._set_plan_out("保存失败: config.json 写入失败(可能被占用)", err=True)
            return
        self._plan_refresh(select=name)
        self._set_plan_out("已保存方案: " + name + " —— " + self._plan_summary(
            dsh_planner.find_plan(cfg, name) or {}))

    def _plan_rename(self):
        p = self._selected_plan()
        if not p:
            self._set_plan_out("先选择要重命名的方案", err=True)
            return
        name, ok = QInputDialog.getText(self, "重命名方案", "新方案名:", text=p["name"])
        if not ok or not name.strip() or name.strip() == p["name"]:
            return
        name = name.strip()
        cfg = dsh_planner.delete_plan(dsh_config.load_config(), p["name"])
        cfg = dsh_planner.upsert_plan(cfg, dict(p, name=name))
        if cfg.get("tunnel_plans_active") == p["name"]:
            cfg["tunnel_plans_active"] = name
        if not dsh_config.save_config(cfg):
            self._set_plan_out("重命名失败: 写入失败(可能被占用)", err=True)
            return
        self._plan_refresh(select=name)
        self._set_plan_out("已重命名为: " + name)

    def _plan_del(self):
        p = self._selected_plan()
        if not p:
            self._set_plan_out("先选择要删除的方案", err=True)
            return

        def do_del():
            cfg = dsh_planner.delete_plan(dsh_config.load_config(), p["name"])
            if not dsh_config.save_config(cfg):
                self._set_plan_out("删除失败: 写入失败(可能被占用)", err=True)
                return
            self._plan_refresh()
            self._set_plan_out("已删除方案: " + p["name"])

        self._confirm.ask(
            "删除方案「%s」" % p["name"],
            "将删除该方案配置（不影响当前已应用的配置与正在运行的隧道）。",
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
            self._set_plan_out("校验通过: 「%s」未发现问题" % p["name"])
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
        rows = dsh_planner.self_check(dsh_config.load_config(), BASE_DIR)
        text = " | ".join("%s: %s(%s)" % (n, "未配置" if s is None else ("通" if s else "不通"), d)
                          for n, s, d in rows)
        ok = all(s is not False for _, s, _ in rows)
        self._set_plan_out("自检 — " + text, err=not ok)
        self.app.loge("[隧道] 启动自检: " + ("全部通过" if ok else "存在不通项"), "ok" if ok else "warn")

    def _make_card(self, item):
        card = QFrame(objectName="card")
        lv = QVBoxLayout(card)
        lv.setContentsMargins(16, 14, 16, 14)
        lv.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel(item.get("title") or item["key"], objectName="cardTitle")
        head.addWidget(title)
        head.addStretch(1)
        # 状态圆点只对可探测的卡片显示(update-dsh 是纯动作卡, 无在线状态)
        dot = None
        if item.get("port", -1) >= 0:
            dot = QLabel("○", objectName="monDot")
            dot.setStyleSheet("color:#999; font-size:15px;")
            head.addWidget(dot)
        lv.addLayout(head)

        desc = QLabel(item["desc"], objectName="cardHint")
        desc.setWordWrap(True)
        lv.addWidget(desc)

        btns = QHBoxLayout()
        for act in item["actions"]:
            b = QPushButton(BTN_TEXT[act])
            b.clicked.connect(lambda _=False, it=item, a=act: self._on_action(it, a))
            btns.addWidget(b)
        btns.addStretch(1)
        lv.addLayout(btns)

        self._cards[item["key"]] = (dot, item)
        return card

    def _set_card(self, key, on, label=None):
        entry = self._cards.get(key)
        if entry is None or entry[0] is None:
            return
        d, item = entry
        d.setText("●" if on else "○")
        d.setStyleSheet("color:#7ecb6a; font-size:15px;" if on else "color:#999; font-size:15px;")

    # ---- 动作分派: 页面只分派与提示, 业务经 service 信号桥在后台线程执行 ----
    def _on_action(self, item, mode):
        # 仅 python 隧道(dsh 操控/更新已迁「DSH 管理」页); persist 停止标志由 service
        # 持有(窗口生命周期), 不再随页面重建丢失导致"停止后又被重连"。
        key = item["key"]
        self.app.loge("[%s] 模式: %s (Python)" % (key, mode), "warn")
        self.app.set_status("正在执行 %s -> %s (Python) ..." % (mode, key))
        self.app.service.start_tunnel(key, mode)

    def _apply_card(self, key, on):
        # service.card 信号槽(主线程): 更新卡片圆点。
        self._set_card(key, on)

