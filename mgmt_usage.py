# -*- coding: utf-8 -*-
# mgmt_usage.py — 模型用量统计窗口: 解压 ~/.dsh/sessions 聚合 token 用量并按模型/天展示。
# 解压扫描较慢, 一律后台线程执行, 结果经 after(0,...) 回主线程更新(窗口关闭后忽略 TclError)。
# 价格表为内置估算单价(元/百万 token), 仅内存修改, 不写回任何文件。

import threading
import tkinter as tk
from tkinter import ttk, messagebox

import dsh_data

# 与 dsh-tunnel-console.py 顶部一致的风格常量(独立文件, 不复用主程序避免循环导入)
F_BOLD = ("Segoe UI", 10, "bold")
F_SMALL = ("Segoe UI", 9)

# 表格固定列: (数据字段, 表头)
MODEL_COLS = (
    ("model", "模型"),
    ("provider", "Provider"),
    ("input", "输入 tokens"),
    ("output", "输出 tokens"),
    ("calls", "调用次数"),
    ("cost", "估算费用"),
)
DAY_COLS = (
    ("date", "日期"),
    ("input", "输入 tokens"),
    ("output", "输出 tokens"),
)


def _num(v):
    # 转数字并千分位格式化; 失败显示 0
    try:
        return "{:,}".format(int(v))
    except (TypeError, ValueError):
        return "0"


class UsageDialog(tk.Toplevel):
    # 只读"模型用量统计"窗口 + 价格表(内存)编辑

    def __init__(self, master):
        # master 可以是 Dashboard(推荐) 或 Tk 根窗口
        if hasattr(master, "root"):
            tk_master = master.root
            self._master = master
        else:
            tk_master = master
            self._master = None
        super().__init__(tk_master)
        self.title("模型用量统计")
        self.configure(padx=12, pady=10)
        self.geometry("760x560")
        self.minsize(720, 500)
        self._stats = None      # 最近一次 usage_stats() 结果(供价格修改后重算费用)
        self._busy = False
        self._build()
        self.transient(tk_master)
        self.grab_set()
        self._refresh()

    def _build(self):
        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True)

        ttk.Label(wrap, text="模型用量统计", font=F_BOLD).pack(anchor="w", pady=(0, 6))

        top = ttk.Frame(wrap)
        top.pack(fill="x", pady=(0, 6))
        self._status = ttk.Label(top, text="", font=F_SMALL, foreground="#888")
        self._status.pack(side="left")
        self._sessions_lbl = ttk.Label(top, text="会话总数: --", font=F_SMALL, foreground="#444")
        self._sessions_lbl.pack(side="left", padx=(16, 0))
        self._refresh_btn = ttk.Button(top, text="刷新", command=self._refresh)
        self._refresh_btn.pack(side="right", padx=(0, 4))
        ttk.Button(top, text="编辑价格", command=self._edit_prices).pack(side="right", padx=(0, 4))

        # 按模型表格
        mbox = ttk.LabelFrame(wrap, text="按模型", padding=6)
        mbox.pack(fill="both", expand=True, pady=(0, 6))
        cols = [c[0] for c in MODEL_COLS]
        self._mtree = ttk.Treeview(mbox, columns=cols, show="headings", height=8)
        widths = {"model": 150, "provider": 130, "input": 100, "output": 100, "calls": 80, "cost": 100}
        for key, title in MODEL_COLS:
            self._mtree.heading(key, text=title)
            self._mtree.column(key, width=widths[key], anchor="e" if key not in ("model", "provider", "cost") else "w")
        msb = ttk.Scrollbar(mbox, orient="vertical", command=self._mtree.yview)
        self._mtree.configure(yscrollcommand=msb.set)
        self._mtree.pack(side="left", fill="both", expand=True)
        msb.pack(side="right", fill="y")

        # 按天表格
        dbox = ttk.LabelFrame(wrap, text="按天", padding=6)
        dbox.pack(fill="x")
        dcols = [c[0] for c in DAY_COLS]
        self._dtree = ttk.Treeview(dbox, columns=dcols, show="headings", height=5)
        for key, title in DAY_COLS:
            self._dtree.heading(key, text=title)
            self._dtree.column(key, width=150, anchor="w" if key == "date" else "e")
        dsb = ttk.Scrollbar(dbox, orient="vertical", command=self._dtree.yview)
        self._dtree.configure(yscrollcommand=dsb.set)
        self._dtree.pack(side="left", fill="both", expand=True)
        dsb.pack(side="right", fill="y")

        ttk.Label(wrap, text="估算费用按内置单价(元/百万 token)计算; 价格修改仅本次运行生效, 不写入文件。",
                  font=F_SMALL, foreground="#888").pack(anchor="w", pady=(8, 0))
        btns = ttk.Frame(wrap)
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="关闭", command=self.destroy).pack(side="left")

    def _refresh(self):
        # 后台线程扫描解压 session 文件, 完成后回主线程更新
        if self._busy:
            return
        self._busy = True
        self._status.configure(text="正在统计…", foreground="#888")
        self._refresh_btn.configure(state="disabled")

        def worker():
            try:
                res = dsh_data.usage_stats()
            except Exception as e:
                res = {"ok": False, "error": str(e)}
            try:
                self.after(0, lambda: self._apply(res))
            except tk.TclError:
                pass   # 窗口已关闭, 忽略
        threading.Thread(target=worker, daemon=True).start()

    def _apply(self, res):
        try:
            self._busy = False
            self._apply_inner(res)
        except tk.TclError:
            pass   # 窗口已关闭, 忽略

    def _apply_inner(self, res):
        self._busy = False
        self._refresh_btn.configure(state="normal")
        self._stats = res
        for item in self._mtree.get_children():
            self._mtree.delete(item)
        for item in self._dtree.get_children():
            self._dtree.delete(item)
        if not isinstance(res, dict) or not res.get("ok"):
            msg = (res or {}).get("error") or "未知错误"
            self._status.configure(text="统计失败: " + str(msg), foreground="#c33")
            self._sessions_lbl.configure(text="会话总数: --")
            return
        self._status.configure(text="统计完成", foreground="#3c3")
        self._sessions_lbl.configure(text="会话总数: %d" % int(res.get("sessions") or 0))
        self._fill_models(res.get("models") or {})
        self._fill_days(res.get("days") or {})

    def _fill_models(self, models):
        # 模型表: 每行 model/provider/input/output/calls/估算费用
        for name in sorted(models):
            m = models[name]
            if not isinstance(m, dict):
                m = {}
            inp = int(m.get("input") or 0)
            out = int(m.get("output") or 0)
            provider = m.get("provider") or "（无数据）"
            self._mtree.insert("", "end", values=(
                name, provider, _num(inp), _num(out), _num(m.get("calls")),
                self._cost_text(name, inp, out),
            ))

    def _fill_days(self, days):
        # 天表: 未知日期("?")排最后
        for date in sorted(days, key=lambda d: (d == "?", str(d))):
            d = days[date]
            if not isinstance(d, dict):
                d = {}
            self._dtree.insert("", "end", values=(
                date, _num(d.get("input")), _num(d.get("output")),
            ))

    def _price_for(self, model):
        # 返回 (输入单价, 输出单价) 或 None(未定价)
        p = dsh_data.DEFAULT_PRICES.get(model)
        if not isinstance(p, dict):
            return None
        pi = p.get("input")
        po = p.get("output")
        if pi is None or po is None:
            return None
        try:
            return (float(pi), float(po))
        except (TypeError, ValueError):
            return None

    def _cost_text(self, model, inp, out):
        p = self._price_for(model)
        if p is None:
            return "未定价"
        cost = inp / 1e6 * p[0] + out / 1e6 * p[1]
        return "%.2f 元" % cost

    def _refresh_costs(self):
        # 价格修改后, 用缓存的统计结果重算费用列(不重新扫描)
        if not self._stats or not self._stats.get("ok"):
            return
        for item in self._mtree.get_children():
            self._mtree.delete(item)
        self._fill_models(self._stats.get("models") or {})

    def _edit_prices(self):
        # 价格表编辑: 内置价格 + 统计中出现但未定价的模型
        models = list(dsh_data.DEFAULT_PRICES.keys())
        if self._stats and isinstance(self._stats.get("models"), dict):
            for m in self._stats["models"]:
                if m not in models:
                    models.append(m)
        if not models:
            messagebox.showinfo("编辑价格", "当前没有可编辑的模型。", parent=self)
            return
        PriceDialog(self, models)
        self._refresh_costs()


class PriceDialog(tk.Toplevel):
    # 简单价格编辑对话框: 修改 dsh_data.DEFAULT_PRICES(仅内存, 不写文件)

    def __init__(self, master, models):
        self._master = master
        super().__init__(master)
        self.title("编辑价格表")
        self.configure(padx=12, pady=10)
        self.geometry("480x320")
        self._rows = []
        self._build(models)
        self.transient(master)
        self.grab_set()

    def _build(self, models):
        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True)
        ttk.Label(wrap, text="估算单价(元/百万 token), 仅本次运行生效",
                  font=F_BOLD).pack(anchor="w", pady=(0, 6))
        head = ttk.Frame(wrap)
        head.pack(fill="x", pady=(0, 2))
        for j, t in enumerate(("模型", "输入单价", "输出单价")):
            ttk.Label(head, text=t, font=F_BOLD, width=16, anchor="w").grid(row=0, column=j, padx=2)
        table = ttk.Frame(wrap)
        table.pack(fill="both", expand=True)
        for i, name in enumerate(models):
            p = dsh_data.DEFAULT_PRICES.get(name)
            iv = tk.StringVar(value=str(p.get("input")) if isinstance(p, dict) and p.get("input") is not None else "")
            ov = tk.StringVar(value=str(p.get("output")) if isinstance(p, dict) and p.get("output") is not None else "")
            name_v = tk.StringVar(value=name)
            ttk.Entry(table, textvariable=name_v, width=16).grid(row=i, column=0, padx=2, pady=2, sticky="ew")
            ttk.Entry(table, textvariable=iv, width=16).grid(row=i, column=1, padx=2, pady=2, sticky="ew")
            ttk.Entry(table, textvariable=ov, width=16).grid(row=i, column=2, padx=2, pady=2, sticky="ew")
            self._rows.append((name_v, iv, ov))
        ttk.Label(wrap, text="价格留空表示沿用原值; 模型名留空则跳过该行。",
                  font=F_SMALL, foreground="#888").pack(anchor="w", pady=(8, 0))
        btns = ttk.Frame(wrap)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="保存", command=self._save).pack(side="left", padx=4)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="left", padx=4)

    def _save(self):
        # 逐行解析; 任一价格非法则整体不保存
        updates = {}
        for name_v, iv, ov in self._rows:
            name = name_v.get().strip()
            if not name:
                continue
            old = dsh_data.DEFAULT_PRICES.get(name)
            old = old if isinstance(old, dict) else {}
            try:
                inp = float(iv.get().strip()) if iv.get().strip() else float(old.get("input") or 0)
                out = float(ov.get().strip()) if ov.get().strip() else float(old.get("output") or 0)
            except ValueError:
                messagebox.showerror("输入错误", "单价必须是数字(如 2.0)。", parent=self)
                return
            updates[name] = {"input": inp, "output": out}
        for name, p in updates.items():
            dsh_data.DEFAULT_PRICES[name] = p
        self.destroy()
