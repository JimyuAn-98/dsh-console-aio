# -*- coding: utf-8 -*-
# 模型用量统计页(UI 层)。
# 只读统计: 解压扫描 ~/.dsh/sessions 下全部 session.jsonl.zstd, 聚合 token 用量(远程部署暂不支持)。
# 价格表持久化到软件路径 model_prices.json(load/save 走 core.data.effective_prices/save_prices),
# 修改后下次启动自动带入; 计费模式 billing: token 按量 / token-plan 按月订阅(不走按量估算)。
# 数据缓存进页机制: 进页先读缓存 直接呈现(绿), 数据源时间戳(最新 session 文件 mtime)变了才
# 后台重扫(标题右侧转圈), 结束后对比缓存: 有变化刷新 + 黄 / 无变化绿 / 错误红。
# 统计走 service.read_usage_stats 信号桥(result "usage-read" 回包, 接收者是页面自身,
# 页面销毁 Qt 自动断开); log/status 不在页面 connect(主窗口级已接)。
# P1 多栏展开: 按模型|按天|明细 三栏(ModernList + three_split), 第三栏显示选中行完整字段。

from PySide6.QtCore import Qt

from core import cache as core_cache
from core import data as core_data
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ui.base import BasePage
from ui.chart import StackedBarChart, short_model
from ui.widgets import ModernList, RefreshIndicator, card_wrap, three_split

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
        self._update_plan_lbl()   # 订阅费合计(独立于用量扫描, 依当前生效价格)
        self._refresh()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 12)
        root.setSpacing(8)

        # 标题/提示/信息条固定在滚动区外(常驻顶部); 趋势卡/三栏/说明进滚动区
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title = QLabel("模型用量统计", objectName="cardTitle")
        title_row.addWidget(title)
        self._spinner = RefreshIndicator()
        self._spinner.setToolTip("刷新状态: 绿=无变化 / 黄=数据有变化 / 红=获取错误")
        title_row.addWidget(self._spinner)
        title_row.addStretch(1)
        root.addLayout(title_row)
        hint = QLabel("解压扫描全部会话的 session.jsonl.zstd 聚合 token 用量(较慢, 后台执行); "
                      "进页自动取缓存+按需刷新; 远程部署统计暂不支持, 会明确提示。", objectName="cardHint")
        hint.setWordWrap(True)   # 不换行会以整行宽度撑破内容最小宽, 窄窗口出外层横滚
        root.addWidget(hint)

        info = QFrame(objectName="card")
        il = QHBoxLayout(info)
        il.setContentsMargins(12, 8, 12, 8)
        il.setSpacing(16)
        self._status_lbl = QLabel("就绪", objectName="monName")
        il.addWidget(self._status_lbl)
        self._sessions_lbl = QLabel("会话总数: --", objectName="monName")
        il.addWidget(self._sessions_lbl)
        self._plan_lbl = QLabel("订阅费: 月 ¥0 · 年 ¥0", objectName="monName")
        self._plan_lbl.setToolTip("所有订阅(token-plan)模型的月/年费合计; 编辑价格后更新")
        il.addWidget(self._plan_lbl)
        il.addStretch(1)
        self._btn_edit = QPushButton("编辑价格")
        self._btn_edit.clicked.connect(self._edit_prices)
        il.addWidget(self._btn_edit)
        self._btn_refresh = QPushButton("刷新")
        self._btn_refresh.clicked.connect(self._refresh)
        il.addWidget(self._btn_refresh)
        root.addWidget(info)

        # 滚动区内容: 趋势卡 → 三栏(固定高) → 说明; 用户滚动整页, 三栏不参与纵向滚动
        content = QWidget()
        cv = QVBoxLayout(content)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(8)

        # 趋势卡(按模型堆叠的每日 token 柱状图; 数据来自最近一次统计, 切窗口不重扫)
        chart_card = QFrame(objectName="card")
        ch = QVBoxLayout(chart_card)
        ch.setContentsMargins(12, 8, 12, 8)
        ch.setSpacing(4)
        chead = QHBoxLayout()
        chead.addWidget(QLabel("每日 token 趋势(输入+输出, 按模型堆叠; 悬停看当日明细)",
                               objectName="rightTitle"))
        chead.addStretch(1)
        self._btn_collapse = QPushButton("收起图表")
        self._btn_collapse.setToolTip("收起后趋势卡只占一行标题, 高度让给下方三栏")
        self._btn_collapse.clicked.connect(self._toggle_chart)
        chead.addWidget(self._btn_collapse)
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

        note = QLabel("估算费用按单价(元/百万 token)计算, 保存后持久化到软件路径, 下次自动带入; "
                      "订阅token-plan 模型按月付费不走按量估算。",
                      objectName="cardHint")
        note.setWordWrap(True)

        # 三栏固定高度 500px: 纵向不滚(整页滚动兜底), 列表行多时由 ModernList 自滚;
        # 窄窗口时只有三栏横向滚, 标题/信息条/趋势卡等仍自适应窗口宽度
        mid.setMinimumWidth(950)
        mid_host = QScrollArea()
        mid_host.setWidgetResizable(True)
        mid_host.setFrameShape(QFrame.NoFrame)
        mid_host.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        mid_host.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        mid_host.setFixedHeight(500)
        mid_host.setWidget(mid)
        cv.addWidget(mid_host)
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

    def _refresh(self, force=False):
        # 进页/手动刷新: 先看缓存 + 数据源时间戳, 决定是否真去重扫。
        #   - 缓存存在且源时间戳未变(非强制) -> 用缓存直接呈现(绿, 不转圈)。
        #   - 无缓存 / 源时间戳已变 / 强制  -> 后台拉取(转圈), 结束后对比缓存决定绿/黄/红。
        if self._busy:
            return
        src_mtime = core_data.usage_source_mtime()
        cache_data, _ = core_cache.read_cache("usage")
        if not force and cache_data is not None and not core_cache.needs_refresh("usage", src_mtime):
            # 缓存已是最新: 直接用缓存呈现, 标记"无变化"(绿)。
            self._apply_data(cache_data, "")
            self._status_lbl.setText("数据无变化")
            self._spinner.set_status("ok")
            self._spinner.setToolTip("无变化(缓存已是最新)")
            return
        self._busy = True
        self._pending = "usage-read"
        self._status_lbl.setText("正在统计…")
        self._set_btns(False)
        self._spinner.set_loading(True)
        self.app.service.read_usage_stats(self._remote)

    def _apply_result(self, data, err):
        # 后台拉取收尾: 错误->红; 否则写缓存, 对比旧缓存: 变则刷新+黄, 不变则绿。
        self._busy = False
        self._set_btns(True)
        self._spinner.set_loading(False)
        if err or not isinstance(data, dict) or not data.get("ok"):
            msg = err or (data or {}).get("error") or "未知错误"
            self._apply_data(None, str(msg))
            self._spinner.set_status("err")
            self._spinner.setToolTip("数据获取错误")
            return
        self._stats = data
        changed = core_cache.data_changed("usage", data)
        core_cache.write_cache("usage", data)
        self._apply_data(data, "")
        if changed:
            self._status_lbl.setText("数据有变化(已刷新)")
            self._spinner.set_status("warn")
            self._spinner.setToolTip("数据有变化(已刷新)")
        else:
            self._status_lbl.setText("数据无变化")
            self._spinner.set_status("ok")
            self._spinner.setToolTip("无变化(数据与上次一致)")

    def _on_result(self, op, payload):
        if op == "usage-read":
            self._pending = None
            self._apply_result(payload.get("data"), payload.get("err", ""))

    def _on_finished(self, op, ok):
        # 兜底: result 槽漏执行导致 busy 悬挂时解除(同步收起转圈)
        if op == self._pending:
            self._pending = None
            self._busy = False
            self._set_btns(True)
            self._spinner.set_loading(False)

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

    def _toggle_chart(self):
        # 收起/展开趋势图: 收起后趋势卡只剩标题行, 高度全让给下方三栏
        vis = not self._chart.isVisible()
        self._chart.setVisible(vis)
        self._btn_collapse.setText("展开图表" if not vis else "收起图表")

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

    def _update_plan_lbl(self):
        # 刷新订阅费合计(所有 token-plan 模型的月/年费), 供信息条展示
        m, y = core_data.subscription_cost()
        self._plan_lbl.setText("订阅费: 月 ¥%.2f · 年 ¥%.2f" % (m, y))

    def _edit_prices(self):
        # 价格表编辑: 基于生效价格(内置 + 已持久化覆盖) + 统计中出现但未定价的模型
        eff = core_data.effective_prices()
        models = list(eff.keys())
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
        self._update_plan_lbl()   # 价格可能改过订阅费, 同步刷新合计

    def _set_btns(self, on):
        for b in (self._btn_refresh, self._btn_edit):
            b.setEnabled(on)

    def _set_status(self, text):
        self._status_lbl.setText(text)


class UsagePriceDialog(QDialog):
    # 价格编辑对话框: 结果写回软件路径 model_prices.json 持久化(下次启动自动带入)。
    # 每行: 模型名(可编辑) + 计费模式(按量/订阅token-plan 下拉) + 三组 空闲/高峰 双档价。
    # 基于 effective_prices()(内置 + 已持久化覆盖), 保存时整体写回(含仅统计出现的新模型)。
    # 表格加宽 + 模型列 Stretch, 避免模型名被压缩看不到。
    HEAD = ["模型", "计费模式", "输入缓存命中(闲/峰)", "输入未命中(闲/峰)", "输出(闲/峰)"]

    def __init__(self, parent, models):
        super().__init__(parent)
        self.setWindowTitle("编辑价格表")
        self.resize(980, 440)
        self.setMinimumSize(860, 360)
        self._rows = []          # 每行: [name_item, billing_cb, ic_edits, im_edits, o_edits]
        self._build(models)

    def _build(self, models):
        wrap = QVBoxLayout(self)
        wrap.setContentsMargins(12, 10, 12, 10)
        wrap.setSpacing(6)
        tip = QLabel("单价(元/百万 token), 保存后持久化到软件路径, 下次启动自动带入; "
                     "计费模式: 按量=按 token 用量估算 / 订阅token-plan=按月付费, 不走按量估算。"
                     "每条两个输入框: 左=空闲时段价, 右=高峰时段价; 高峰=周一至五 9-12/14-18 时, "
                     "留空沿用当前值。")
        tip.setWordWrap(True)
        wrap.addWidget(tip)

        eff = core_data.effective_prices()
        table = QTableWidget(len(models), len(self.HEAD))
        table.setHorizontalHeaderLabels(self.HEAD)
        table.verticalHeader().setVisible(False)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        hh = table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)   # 模型列拉满, 名字不被压缩
        for c in (1, 2, 3, 4):
            hh.setSectionResizeMode(c, QHeaderView.Fixed)
        table.setColumnWidth(1, 130)
        for c in (2, 3, 4):
            table.setColumnWidth(c, 186)
        # 行高: 单元格里放的是 QLineEdit/QComboBox(默认高约 26px), 默认行高会把它们裁掉、
        # 数字看不清; 显式给足行高(含内边距)。defaultSectionSize 管初始, setRowHeight 在
        # 下方放完 setCellWidget 后再统一覆盖(见_populate_rows 之后), 防被控件重排回矮行。
        self._row_h = 44
        table.verticalHeader().setDefaultSectionSize(self._row_h)

        # 行多时纵向滚动(整体不给页面纵向挤压); 横向必要时走横滚
        page = QScrollArea()
        page.setWidgetResizable(True)
        page.setWidget(table)
        page.setFrameShape(QFrame.NoFrame)
        page.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        wrap.addWidget(page, 1)

        for i, name in enumerate(models):
            p = eff.get(name) or {}
            billing = p.get("billing") or core_data.BILLING_TOKEN

            def pair(k, d):
                v = p.get(k)
                if not isinstance(v, (list, tuple)) or len(v) < 2:
                    v = d
                return str(v[0]), str(v[1])

            ic = pair("in_cached", [0.05, 0.10])
            im = pair("in_miss", [1.5, 3.0])
            o = pair("out", [4.5, 9.0])
            monthly = p.get("monthly")
            yearly = p.get("yearly")
            monthly = "" if monthly is None else ("%.2f" % float(monthly))
            yearly = "" if yearly is None else ("%.2f" % float(yearly))

            name_item = QTableWidgetItem(name)
            name_item.setFlags(name_item.flags() | Qt.ItemIsEditable)
            table.setItem(i, 0, name_item)

            cb = QComboBox()
            cb.addItem("按量(token)", core_data.BILLING_TOKEN)
            cb.addItem("订阅token-plan", core_data.BILLING_PLAN)
            cb.setCurrentIndex(1 if billing == core_data.BILLING_PLAN else 0)
            table.setCellWidget(i, 1, cb)

            # 跨 2-4 列的单格容纳 两套输入: token 三组单价 / 订阅月费年费, 按计费模式切换可见性。
            # (每行只这一个跨列 cellWidget, 避免 setSpan 与逐列 setCellWidget 冲突)
            roww = QWidget()
            rv = QHBoxLayout(roww)
            rv.setContentsMargins(6, 0, 6, 0)
            rv.setSpacing(8)
            table.setSpan(i, 2, 1, 3)

            tokenw = QWidget()
            tl = QHBoxLayout(tokenw)
            tl.setContentsMargins(0, 0, 0, 0)
            tl.setSpacing(8)
            icb, e_ic1, e_ic2 = self._token_box(ic, "缓存命中")
            imb, e_im1, e_im2 = self._token_box(im, "未命中")
            ob, e_o1, e_o2 = self._token_box(o, "输出")
            for b in (icb, imb, ob):
                tl.addWidget(b)
            tl.addStretch(1)

            planw = QWidget()
            pl = QHBoxLayout(planw)
            pl.setContentsMargins(0, 0, 0, 0)
            pl.setSpacing(8)
            e_month = QLineEdit(monthly)
            e_year = QLineEdit(yearly)
            e_month.setToolTip("月费(元/月)")
            e_year.setToolTip("年费(元/年)")
            e_month.setMinimumWidth(120)
            e_year.setMinimumWidth(120)
            pl.addWidget(QLabel("月费 ¥"))
            pl.addWidget(e_month)
            pl.addWidget(QLabel("年费 ¥"))
            pl.addWidget(e_year)
            pl.addStretch(1)

            rv.addWidget(tokenw)
            rv.addWidget(planw)
            table.setCellWidget(i, 2, roww)

            # 计费模式切换: 按量显示三组 token 单价; 订阅显示月费/年费
            def apply_billing(_=None, tw=tokenw, pw=planw, b=cb):
                plan = b.currentData() == core_data.BILLING_PLAN
                tw.setVisible(not plan)
                pw.setVisible(plan)
            cb.currentIndexChanged.connect(apply_billing)
            apply_billing()   # 应用初始计费模式

            self._rows.append([name_item, cb, tokenw, planw,
                               e_ic1, e_ic2, e_im1, e_im2, e_o1, e_o2,
                               e_month, e_year])

        # 放完所有 setCellWidget 后再统一抬高行高, 覆盖控件重排可能压回的行高, 保证数字完整可见。
        for r in range(len(models)):
            table.setRowHeight(r, self._row_h)

        note = QLabel("按量模型填 缓存命中/未命中/输出 的 空闲·高峰 双档价; 订阅token-plan 模型只填 "
                      "月费/年费(不走按量估算)。留空沿用当前值。", objectName="cardHint")
        note.setWordWrap(True)
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

    @staticmethod
    def _token_box(pair_v, label):
        # 单组双档价(按量): 一个横向容器内放 空闲/高峰 两个输入框, 前置小标题区分组。
        box = QWidget()
        hl = QHBoxLayout(box)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)
        cap = QLabel(label, objectName="monNote")
        cap.setToolTip("每个价格两输入框: 左=空闲, 右=高峰(元/百万 token)")
        e1 = QLineEdit(pair_v[0])
        e2 = QLineEdit(pair_v[1])
        e1.setToolTip("空闲时段价")
        e2.setToolTip("高峰时段价")
        e1.setMinimumWidth(64)
        e2.setMinimumWidth(64)
        hl.addWidget(cap)
        hl.addWidget(e1)
        hl.addWidget(e2)
        return (box, e1, e2)

    def _save(self):
        # 校验全部行并按计费模式分支写回: token 存三组双档价; token-plan 存月费/年费。
        # 留空沿用当前生效价(或内置默认); 非法数字整批拒绝。整体写回持久化。
        eff = core_data.effective_prices()
        updates = {}

        def to_float(ed, d):
            s = ed.text().strip()
            return float(s) if s else float(d)

        for row in self._rows:
            name_item, cb = row[0], row[1]
            name = name_item.text().strip()
            if not name:
                continue
            base = eff.get(name) or {}
            plan = cb.currentData() == core_data.BILLING_PLAN
            try:
                if plan:
                    updates[name] = {
                        "monthly": to_float(row[10], base.get("monthly") or 0.0),
                        "yearly": to_float(row[11], base.get("yearly") or 0.0),
                        "billing": core_data.BILLING_PLAN,
                    }
                else:
                    updates[name] = {
                        "in_cached": [to_float(row[4], (base.get("in_cached") or [0.05, 0.10])[0]),
                                      to_float(row[5], (base.get("in_cached") or [0.05, 0.10])[1])],
                        "in_miss": [to_float(row[6], (base.get("in_miss") or [1.5, 3.0])[0]),
                                    to_float(row[7], (base.get("in_miss") or [1.5, 3.0])[1])],
                        "out": [to_float(row[8], (base.get("out") or [4.5, 9.0])[0]),
                                to_float(row[9], (base.get("out") or [4.5, 9.0])[1])],
                        "billing": core_data.BILLING_TOKEN,
                    }
            except ValueError:
                if plan:
                    QMessageBox.critical(self, "输入错误", "月费/年费必须是数字(如 99.0)。")
                else:
                    QMessageBox.critical(self, "输入错误", "单价必须是数字(如 2.0)。")
                return
        if core_data.save_prices(updates):
            QMessageBox.information(self, "保存", "价格已保存到软件路径, 下次启动自动带入。")
            self.accept()
        else:
            QMessageBox.critical(self, "保存失败", "无法写入价格文件(软件路径只读?)。")
