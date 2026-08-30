# -*- coding: utf-8 -*-
# 模型用量统计页(UI 层)。
# 只读统计: 解压扫描 ~/.dsh/sessions 下全部 session.jsonl.zstd, 聚合 token 用量(远程部署暂不支持)。
# 价格表为内置估算单价(元/百万 token), 仅内存修改 DEFAULT_PRICES, 不写回任何文件。
# 统计走 service.read_usage_stats 信号桥(result "usage-read" 回包, 接收者是页面自身,
# 页面销毁 Qt 自动断开); log/status 不在页面 connect(主窗口级已接)。
# P1 多栏展开: 按模型|按天|明细 三栏(ModernList + three_split), 第三栏显示选中行完整字段。

from PySide6.QtCore import Qt

from core import data as core_data
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from ui.base import BasePage
from ui.chart import StackedBarChart, short_model
from ui.widgets import ModernList, card_wrap, three_split

# 明细卡键值对: (数据字段, 界面名)
_MODEL_FIELDS = (("model", "模型"), ("provider", "Provider"), ("input", "输入 tokens"),
                 ("cache", "缓存命中"), ("output", "输出 tokens"), ("calls", "调用次数"),
                 ("cost", "估算费用"))
_DAY_FIELDS = (("date", "日期"), ("input", "输入 tokens"), ("cache", "缓存命中"),
               ("output", "输出 tokens"))


def _num(v):
    # 转数字并千分位格式化; 失败显示 0
    try:
        return "{:,}".format(int(v))
    except (TypeError, ValueError):
        return "0"


def _cost_text(model, inp, out, cache=0):
    # 估算费用: 按 core_data.estimate_cost(内置单价, 区分缓存与高峰/空闲); 未定价返回占位
    cost = core_data.estimate_cost(model, inp, out, cache)
    if cost is None:
        return "未定价"
    return "%.2f 元" % cost


class UsagePage(BasePage):
    # 模型用量统计: BasePage 范式, app 为 MainWindow。

    def __init__(self, app, parent=None):
        # 部署联动: 当前部署(host 非空)构造 DshRemote; 用量统计对远程明确报不支持
        self._remote = None
        _dep = getattr(app, "_current_deploy", None)
        if _dep and _dep.get("host"):
            self._remote = core_data.DshRemote(_dep)
        self._stats = None          # 最近一次 usage_stats() 结果(供价格修改后重算费用)
        self._busy = False
        self._pending = None
        super().__init__(app, parent)
        self.app.service.result.connect(self._on_result)
        self.app.service.finished.connect(self._on_finished)
        self._refresh()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 12)
        root.setSpacing(8)

        # 整页纵向滚动(与设置页同款): 标题/信息条/趋势卡/三栏/说明全部随页面滚动,
        # 视口不够时滚动而不是挤压任何区域
        content = QWidget()
        cv = QVBoxLayout(content)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(8)
        title = QLabel("模型用量统计", objectName="cardTitle")
        cv.addWidget(title)
        hint = QLabel("解压扫描全部会话的 session.jsonl.zstd 聚合 token 用量(较慢, 后台执行); "
                      "远程部署统计暂不支持, 会明确提示。", objectName="cardHint")
        hint.setWordWrap(True)   # 不换行会以整行宽度撑破内容最小宽, 窄窗口出外层横滚
        cv.addWidget(hint)

        info = QFrame(objectName="card")
        il = QHBoxLayout(info)
        il.setContentsMargins(12, 8, 12, 8)
        il.setSpacing(16)
        self._status_lbl = QLabel("就绪", objectName="monName")
        il.addWidget(self._status_lbl)
        self._sessions_lbl = QLabel("会话总数: --", objectName="monName")
        il.addWidget(self._sessions_lbl)
        il.addStretch(1)
        self._btn_edit = QPushButton("编辑价格")
        self._btn_edit.clicked.connect(self._edit_prices)
        il.addWidget(self._btn_edit)
        self._btn_refresh = QPushButton("刷新")
        self._btn_refresh.clicked.connect(self._refresh)
        il.addWidget(self._btn_refresh)
        cv.addWidget(info)

        # 趋势卡(按模型堆叠的每日 token 柱状图; 数据来自最近一次统计, 切窗口不重扫)
        chart_card = QFrame(objectName="card")
        ch = QVBoxLayout(chart_card)
        ch.setContentsMargins(12, 8, 12, 8)
        ch.setSpacing(4)
        chead = QHBoxLayout()
        chead.addWidget(QLabel("每日 token 趋势(输入+输出, 按模型堆叠; 悬停看当日明细)",
                               objectName="rightTitle"))
        chead.addStretch(1)
        self._chart_span = 14
        self._span_btns = {}
        for n in (7, 14, 30):
            b = QPushButton("%d 天" % n)
            b.setCheckable(True)
            b.setChecked(n == self._chart_span)
            b.clicked.connect(lambda _=False, k=n: self._set_span(k))
            self._span_btns[n] = b
            chead.addWidget(b)
        ch.addLayout(chead)
        self._chart = StackedBarChart()
        ch.addWidget(self._chart)
        cv.addWidget(chart_card)

        mid = three_split(
            card_wrap("按模型", self._make_list(is_model=True)),
            card_wrap("按天", self._make_list(is_model=False)),
            self._make_detail_card(),
            mins=(270, 300, 330))

        note = QLabel("估算费用按内置单价(元/百万 token)计算; 价格修改仅本次运行生效, 不写入文件。",
                      objectName="cardHint")
        note.setWordWrap(True)

        # 三栏独立横向滚动容器: widgetResizable 尊重子项最小宽 —— 视口 < 950 时三栏
        # 保持 950 并自己出横向滚动条, 而标题/信息条/趋势卡等仍自适应窗口宽度
        # (不会被三栏最小宽撑破); 视口够宽时三栏照常拉伸铺满
        mid.setMinimumWidth(950)
        mid.setMinimumHeight(430)
        mid_host = QScrollArea()
        mid_host.setWidgetResizable(True)
        mid_host.setFrameShape(QFrame.NoFrame)
        mid_host.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        mid_host.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        mid_host.setWidget(mid)
        cv.addWidget(mid_host, 1)
        cv.addWidget(note)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)   # 横向只发生在三栏容器内
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

    # ── 三栏构建(按模型|按天|明细) ──
    def _make_list(self, is_model):
        lst = ModernList()
        if is_model:
            self._model_list = lst
            lst.itemSelectionChanged.connect(self._on_model_select)
        else:
            self._day_list = lst
            lst.itemSelectionChanged.connect(self._on_day_select)
        return lst

    def _make_detail_card(self):
        card = QFrame(objectName="card")
        v = QVBoxLayout(card)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)
        v.addWidget(QLabel("明细（选择行查看）", objectName="rightTitle"))
        self._d_form = QFormLayout()
        self._d_form.setHorizontalSpacing(14)
        self._d_form.setVerticalSpacing(4)
        v.addLayout(self._d_form)
        v.addStretch(1)
        self._d_note = QLabel("估算费用按内置单价(元/百万 token)计算, 区分缓存命中与高峰/空闲时段。",
                              objectName="monNote")
        self._d_note.setWordWrap(True)
        v.addWidget(self._d_note)
        return card

    def _fill_detail(self, pairs):
        # pairs: [(界面名, 值)] 全量重建明细卡键值行
        while self._d_form.rowCount():
            self._d_form.removeRow(0)
        for label, value in pairs:
            val = QLabel(str(value), objectName="monVal")
            val.setWordWrap(True)
            self._d_form.addRow(QLabel(label, objectName="monNote"), val)

    def _refresh(self):
        # 解压扫描 session 文件(core 业务), 结果经 result("usage-read") 回主线程更新
        if self._busy:
            return
        self._busy = True
        self._pending = "usage-read"
        self._status_lbl.setText("正在统计…")
        self._set_btns(False)
        self.app.service.read_usage_stats(self._remote)

    def _on_result(self, op, payload):
        if op == "usage-read":
            self._pending = None
            self._apply_data(payload.get("data"), payload.get("err", ""))

    def _on_finished(self, op, ok):
        # 兜底: result 槽漏执行导致 busy 悬挂时解除
        if op == self._pending:
            self._pending = None
            self._busy = False
            self._set_btns(True)

    def _apply_data(self, res, err):
        self._busy = False
        self._set_btns(True)
        self._model_list.set_rows([])
        self._day_list.set_rows([])
        self._fill_detail([])
        if err:
            self._sessions_lbl.setText("会话总数: --")
            self._set_status("统计失败: " + err)
            self.app.loge("[模型用量] 统计失败: " + err, "err")
            return
        if not isinstance(res, dict) or not res.get("ok"):
            msg = (res or {}).get("error") or "未知错误"
            self._sessions_lbl.setText("会话总数: --")
            self._set_status("统计失败: " + str(msg))
            self.app.loge("[模型用量] 统计失败: " + str(msg), "err")
            return
        self._stats = res
        self._set_status("统计完成")
        self._sessions_lbl.setText("会话总数: %d" % int(res.get("sessions") or 0))
        self._fill_models(res.get("models") or {})
        self._fill_days(res.get("days") or {})
        self._update_chart()

    # ── 趋势图(天×模型, 数据来自最近一次统计; 切窗口只重排不重扫) ──
    def _set_span(self, n):
        self._chart_span = n
        for k, b in self._span_btns.items():
            b.setChecked(k == n)
        self._update_chart()

    def _update_chart(self):
        res = self._stats or {}
        dm = res.get("days_models") or {}
        dates = sorted(k for k in dm if k and k != "?")[-self._chart_span:]

        def tok(v):
            v = v or {}
            return int(v.get("input") or 0) + int(v.get("output") or 0)

        totals = {}
        for d in dates:
            for m, v in (dm.get(d) or {}).items():
                totals[m] = totals.get(m, 0) + tok(v)
        order = sorted(totals, key=lambda m: -totals[m])
        models = [m for m in order if totals.get(m)]
        top, rest = models[:8], models[8:]
        days = []
        for d in dates:
            stack = {}
            for m in top:
                v = tok((dm.get(d) or {}).get(m))
                if v:
                    stack[m] = v
            other = sum(tok((dm.get(d) or {}).get(m)) for m in rest)
            if other:
                stack["其他"] = other
            days.append((str(d)[5:], stack))
        self._chart.set_series(days, top + (["其他"] if rest else []))

    def _fill_models(self, models):
        # 模型行: 标题=模型名, meta=provider · 调用次数 · 估算费用
        rows = []
        for name in sorted(models):
            m = models[name]
            if not isinstance(m, dict):
                m = {}
            inp = int(m.get("input") or 0)
            cache = int(m.get("cache") or 0)
            out = int(m.get("output") or 0)
            provider = m.get("provider") or "（无数据）"
            rows.append({
                "title": name,
                "meta": "%s · %s 次 · %s" % (provider, _num(m.get("calls")),
                                             _cost_text(name, inp, out, cache)),
                "data": {"model": name, "provider": provider, "input": _num(inp),
                         "cache": _num(cache), "output": _num(out),
                         "calls": _num(m.get("calls")),
                         "cost": _cost_text(name, inp, out, cache)},
            })
        self._model_list.set_rows(rows)

    def _fill_days(self, days):
        # 天行: 标题=日期, meta=输入/缓存/输出; 未知日期("?")排最后
        rows = []
        for date in sorted(days, key=lambda d: (d == "?", str(d))):
            d = days[date]
            if not isinstance(d, dict):
                d = {}
            rows.append({
                "title": str(date),
                "meta": "输入 %s · 缓存 %s · 输出 %s" % (_num(d.get("input")),
                                                        _num(d.get("cache")),
                                                        _num(d.get("output"))),
                "data": {"date": str(date), "input": _num(d.get("input")),
                         "cache": _num(d.get("cache")), "output": _num(d.get("output"))},
            })
        self._day_list.set_rows(rows)

    def _on_model_select(self):
        row = self._model_list.current_data()
        if not row:
            return
        data = row.get("data") or {}
        self._fill_detail([(label, data.get(key) or "-") for key, label in _MODEL_FIELDS])

    def _on_day_select(self):
        row = self._day_list.current_data()
        if not row:
            return
        data = row.get("data") or {}
        self._fill_detail([(label, data.get(key) or "-") for key, label in _DAY_FIELDS])

    def _refresh_costs(self):
        # 价格修改后, 用缓存的统计结果重算费用列(不重新扫描)
        if not self._stats or not self._stats.get("ok"):
            return
        self._fill_models(self._stats.get("models") or {})

    def _edit_prices(self):
        # 价格表编辑: 内置价格 + 统计中出现但未定价的模型
        models = list(core_data.DEFAULT_PRICES.keys())
        if self._stats and isinstance(self._stats.get("models"), dict):
            for m in self._stats["models"]:
                if m not in models:
                    models.append(m)
        if not models:
            QMessageBox.information(self, "编辑价格", "当前没有可编辑的模型。")
            return
        dlg = UsagePriceDialog(self, models)
        dlg.exec()
        self._refresh_costs()

    def _set_btns(self, on):
        for b in (self._btn_refresh, self._btn_edit):
            b.setEnabled(on)

    def _set_status(self, text):
        self._status_lbl.setText(text)


class UsagePriceDialog(QDialog):
    # 价格编辑对话框: 修改 core_data.DEFAULT_PRICES(仅内存, 不写文件)。
    # 结构: {in_cached/in_miss/out: [空闲, 高峰]}, 元/百万 token。

    def __init__(self, parent, models):
        super().__init__(parent)
        self.setWindowTitle("编辑价格表")
        self.resize(760, 360)
        self._rows = []
        self._build(models)

    def _build(self, models):
        wrap = QVBoxLayout(self)
        wrap.setContentsMargins(12, 10, 12, 10)
        wrap.setSpacing(6)
        tip = QLabel("官方单价(元/百万 token), 仅本次运行生效; 高峰=周一至五 9-12/14-18 时")
        wrap.addWidget(tip)

        grid = QGridLayout()
        grid.setSpacing(4)
        for j, t in enumerate(("模型", "输入缓存命中", "输入未命中", "输出")):
            grid.addWidget(QLabel(t), 0, j)
        grid.addWidget(QLabel("← 空闲 | 高峰 →"), 0, 4)
        wrap.addLayout(grid)

        for i, name in enumerate(models):
            p = core_data.DEFAULT_PRICES.get(name)
            p = p if isinstance(p, dict) else {}

            def pair(k, d):
                v = p.get(k)
                if not isinstance(v, (list, tuple)) or len(v) < 2:
                    v = d
                return str(v[0]), str(v[1])

            ic1, ic2 = pair("in_cached", [0.05, 0.10])
            im1, im2 = pair("in_miss", [1.5, 3.0])
            o1, o2 = pair("out", [4.5, 9.0])
            row = i + 1
            name_edit = QLineEdit(name)
            e_ic1, e_ic2 = QLineEdit(ic1), QLineEdit(ic2)
            e_im1, e_im2 = QLineEdit(im1), QLineEdit(im2)
            e_o1, e_o2 = QLineEdit(o1), QLineEdit(o2)
            grid.addWidget(name_edit, row, 0)
            for col, edits in ((1, (e_ic1, e_ic2)), (2, (e_im1, e_im2)), (3, (e_o1, e_o2))):
                box = QWidget()
                hl = QHBoxLayout(box)
                hl.setContentsMargins(0, 0, 0, 0)
                hl.setSpacing(2)
                for ed in edits:
                    hl.addWidget(ed)
                grid.addWidget(box, row, col)
            grid.addWidget(QLabel("← 空闲 | 高峰 →"), row, 4)
            self._rows.append((name_edit, e_ic1, e_ic2, e_im1, e_im2, e_o1, e_o2,
                               (ic1, ic2, im1, im2, o1, o2)))

        note = QLabel("每列两个输入框: 左=空闲时段价, 右=高峰时段价。留空沿用原值。")
        wrap.addWidget(note)
        btns = QHBoxLayout()
        save = QPushButton("保存")
        save.clicked.connect(self._save)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        btns.addWidget(save)
        btns.addWidget(cancel)
        btns.addStretch(1)
        wrap.addLayout(btns)

    def _save(self):
        # 校验全部行: 单价必须为数字; 留空回退到行默认值(当前价或内置价)
        updates = {}
        for row in self._rows:
            name = row[0].text().strip()
            if not name:
                continue
            defaults = row[7]
            try:
                def to_float(ed, d):
                    s = ed.text().strip()
                    return float(s) if s else float(d)
                nv = [to_float(row[1], defaults[0]), to_float(row[2], defaults[1]),
                      to_float(row[3], defaults[2]), to_float(row[4], defaults[3]),
                      to_float(row[5], defaults[4]), to_float(row[6], defaults[5])]
            except ValueError:
                QMessageBox.critical(self, "输入错误", "单价必须是数字(如 2.0)。")
                return
            updates[name] = {"in_cached": [nv[0], nv[1]], "in_miss": [nv[2], nv[3]],
                             "out": [nv[4], nv[5]]}
        for name, p in updates.items():
            core_data.DEFAULT_PRICES[name] = p
        self.accept()
