# -*- coding: utf-8 -*-
# 模型用量统计页(PySide6 迁移版)。
# 只读统计: 解压扫描 ~/.dsh/sessions 下全部 session.jsonl.zstd, 聚合 token 用量(远程部署暂不支持)。
# 价格表为内置估算单价(元/百万 token), 仅内存修改 DEFAULT_PRICES, 不写回任何文件。
# 扫描较慢, 一律后台线程执行 -> Qt Signal 回主线程更新表格, 不直接改 UI(线程安全)。

import threading

import dsh_data
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from pyside.base import BasePage


# 表格固定列: (数据字段, 表头)
MODEL_COLS = (
    ("model", "模型"),
    ("provider", "Provider"),
    ("input", "输入 tokens"),
    ("cache", "缓存命中"),
    ("output", "输出 tokens"),
    ("calls", "调用次数"),
    ("cost", "估算费用"),
)
DAY_COLS = (
    ("date", "日期"),
    ("input", "输入 tokens"),
    ("cache", "缓存命中"),
    ("output", "输出 tokens"),
)


def _num(v):
    # 转数字并千分位格式化; 失败显示 0
    try:
        return "{:,}".format(int(v))
    except (TypeError, ValueError):
        return "0"


def _cost_text(model, inp, out, cache=0):
    # 估算费用: 按 dsh_data.estimate_cost(内置单价, 区分缓存与高峰/空闲); 未定价返回占位
    cost = dsh_data.estimate_cost(model, inp, out, cache)
    if cost is None:
        return "未定价"
    return "%.2f 元" % cost


class UsagePage(BasePage):
    # 模型用量统计: BasePage 范式, app 为 MainWindow。
    _data = Signal(object, str)     # (usage_stats 结果 dict, err)

    def __init__(self, app, parent=None):
        # 部署联动: 当前部署(host 非空)构造 DshRemote; 用量统计对远程明确报不支持
        self._remote = None
        _dep = getattr(app, "_current_deploy", None)
        if _dep and _dep.get("host"):
            self._remote = dsh_data.DshRemote(_dep)
        self._stats = None          # 最近一次 usage_stats() 结果(供价格修改后重算费用)
        self._busy = False
        super().__init__(app, parent)
        self._data.connect(self._apply_data)
        self._refresh()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 12)
        root.setSpacing(8)

        title = QLabel("模型用量统计", objectName="cardTitle")
        root.addWidget(title)
        hint = QLabel("解压扫描全部会话的 session.jsonl.zstd 聚合 token 用量(较慢, 后台执行); "
                      "远程部署统计暂不支持, 会明确提示。", objectName="cardHint")
        root.addWidget(hint)

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
        root.addWidget(info)

        self._model_table = self._make_table(
            [c[0] for c in MODEL_COLS],
            ["w", "w", "e", "e", "e", "e", "w"],
            [150, 130, 100, 100, 100, 80, 100], stretch_col=0)
        root.addWidget(self._wrap_table("按模型", self._model_table), 1)

        self._day_table = self._make_table(
            [c[0] for c in DAY_COLS],
            ["w", "e", "e", "e"],
            [120, 120, 120, 120], stretch_col=0)
        root.addWidget(self._wrap_table("按天", self._day_table))

        note = QLabel("估算费用按内置单价(元/百万 token)计算; 价格修改仅本次运行生效, 不写入文件。",
                      objectName="cardHint")
        root.addWidget(note)

    def _make_table(self, headers, anchors, widths, stretch_col):
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.verticalHeader().setVisible(False)
        t.setSelectionBehavior(QTableWidget.SelectRows)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.setSelectionMode(QTableWidget.SingleSelection)
        hh = t.horizontalHeader()
        for i, (a, wd) in enumerate(zip(anchors, widths)):
            hh.setSectionResizeMode(i, QHeaderView.ResizeToContents if i != stretch_col
                                    else QHeaderView.Stretch)
            t.setColumnWidth(i, wd)
            if a == "e":
                t.horizontalHeaderItem(i).setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            elif a == "center":
                t.horizontalHeaderItem(i).setTextAlignment(Qt.AlignCenter)
        return t

    def _wrap_table(self, caption, table):
        card = QFrame(objectName="card")
        v = QVBoxLayout(card)
        v.setContentsMargins(10, 8, 10, 8)
        cap = QLabel(caption, objectName="rightTitle")
        v.addWidget(cap)
        v.addWidget(table)
        return card

    def _refresh(self):
        # 后台线程解压扫描 session 文件, 完成后经 Signal 回主线程更新
        if self._busy:
            return
        self._busy = True
        self._status_lbl.setText("正在统计…")
        self._set_btns(False)

        def worker():
            res = None
            err = None
            try:
                res = dsh_data.usage_stats(remote=self._remote)
            except Exception as e:
                err = str(e)
            self.safe_emit(self._data, res, err)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_data(self, res, err):
        self._busy = False
        self._set_btns(True)
        self._model_table.setRowCount(0)
        self._day_table.setRowCount(0)
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

    def _fill_models(self, models):
        # 模型表: 每行 model/provider/input/cache/output/calls/估算费用
        for name in sorted(models):
            m = models[name]
            if not isinstance(m, dict):
                m = {}
            inp = int(m.get("input") or 0)
            cache = int(m.get("cache") or 0)
            out = int(m.get("output") or 0)
            provider = m.get("provider") or "（无数据）"
            r = self._model_table.rowCount()
            self._model_table.insertRow(r)
            vals = (name, provider, _num(inp), _num(cache), _num(out),
                    _num(m.get("calls")), _cost_text(name, inp, out, cache))
            for c, v in enumerate(vals):
                self._model_table.setItem(r, c, QTableWidgetItem(v))

    def _fill_days(self, days):
        # 天表: 未知日期("?")排最后
        for date in sorted(days, key=lambda d: (d == "?", str(d))):
            d = days[date]
            if not isinstance(d, dict):
                d = {}
            r = self._day_table.rowCount()
            self._day_table.insertRow(r)
            vals = (date, _num(d.get("input")), _num(d.get("cache")), _num(d.get("output")))
            for c, v in enumerate(vals):
                self._day_table.setItem(r, c, QTableWidgetItem(v))

    def _refresh_costs(self):
        # 价格修改后, 用缓存的统计结果重算费用列(不重新扫描)
        if not self._stats or not self._stats.get("ok"):
            return
        self._model_table.setRowCount(0)
        self._fill_models(self._stats.get("models") or {})

    def _edit_prices(self):
        # 价格表编辑: 内置价格 + 统计中出现但未定价的模型
        models = list(dsh_data.DEFAULT_PRICES.keys())
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
    # 价格编辑对话框: 修改 dsh_data.DEFAULT_PRICES(仅内存, 不写文件)。
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
            p = dsh_data.DEFAULT_PRICES.get(name)
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
            dsh_data.DEFAULT_PRICES[name] = p
        self.accept()
