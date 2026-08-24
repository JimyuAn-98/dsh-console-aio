# -*- coding: utf-8 -*-
# mgmt_theme.py — 主题 / 外观配置管理窗口
# 只读展示 + 开关 settings.yaml 里的 UI 配置项, 每次切换前确认, 写后提示重启 dsh web 生效。

import tkinter as tk
from tkinter import ttk, messagebox

import dsh_data

# 风格常量与主程序 dsh-tunnel-console.py 顶部保持一致(文件含连字符无法常规 import)
F_BOLD = ("Segoe UI", 10, "bold")
F_SMALL = ("Segoe UI", 9)


def _get_path(data, path):
    # 按 key 路径取嵌套值; 路径中间不是 dict 时返回 None
    cur = data
    for k in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _set_path(data, path, value):
    # 按 key 路径写嵌套值(中间缺层自动补 dict), 就地修改并返回 data
    cur = data
    for k in path[:-1]:
        nxt = cur.get(k)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[k] = nxt
        cur = nxt
    cur[path[-1]] = value
    return data


class ThemeDialog(tk.Toplevel):
    # 开关项: (settings.yaml 键路径, 界面名, 说明)
    ITEMS = [
        (("skin-background", "enabled"), "皮肤背景", "web 界面使用皮肤背景"),
        (("dsh-better-sidebar", "openByDefault"), "侧边栏默认展开", "打开 dsh web 时侧边栏默认展开"),
        (("dsh-better-sidebar", "tabsEnabled", "git"), "侧边栏 Git 标签", "侧边栏启用 Git 标签页"),
        (("pet", "enabled"), "桌宠", "是否启用桌面宠物"),
    ]

    def __init__(self, master):
        # master 兼容 Dashboard 实例(推荐)或 Tk 根窗口
        if hasattr(master, "root"):
            tk_master = master.root
            self._master = master
        else:
            tk_master = master
            self._master = None
        super().__init__(tk_master)
        self.title("主题 / 外观")
        self.geometry("560x420")
        self.minsize(520, 380)
        self.configure(padx=15, pady=12)
        self._settings = self._load_settings()
        self._build()
        self.transient(tk_master)
        self.grab_set()

    def _load_settings(self):
        # 读取 settings.yaml; 缺失/损坏时按空 dict 处理
        try:
            s = dsh_data.read_settings()
        except Exception:
            s = {}
        return s if isinstance(s, dict) else {}

    def _build(self):
        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True)
        ttk.Label(wrap, text="UI 配置开关（settings.yaml）",
                  font=F_BOLD).pack(anchor="w", pady=(0, 6))
        table = ttk.Frame(wrap)
        table.pack(fill="x")
        ttk.Label(table, text="配置项", font=F_BOLD).grid(row=0, column=0, sticky="w", padx=2, pady=2)
        ttk.Label(table, text="当前值", font=F_BOLD).grid(row=0, column=1, sticky="w", padx=2)
        ttk.Label(table, text="操作", font=F_BOLD).grid(row=0, column=2, sticky="w", padx=2)
        self._rows = {}
        for i, (path, label, desc) in enumerate(self.ITEMS):
            r = i + 1
            cell = ttk.Frame(table)
            cell.grid(row=r, column=0, sticky="w", padx=2, pady=4)
            ttk.Label(cell, text=label, font=F_BOLD).pack(anchor="w")
            ttk.Label(cell, text=desc, font=F_SMALL, foreground="#888").pack(anchor="w")
            val_lbl = ttk.Label(table, text="", width=10)
            val_lbl.grid(row=r, column=1, sticky="w", padx=2)
            ttk.Button(table, text="切换",
                       command=lambda p=path: self._toggle(p)).grid(row=r, column=2, sticky="w", padx=2)
            self._rows[path] = val_lbl
        foot = ttk.Frame(wrap)
        foot.pack(fill="x", pady=(14, 0))
        ttk.Label(foot, text="修改写入 settings.yaml（自动备份 .bak），重启 dsh web 生效。",
                  font=F_SMALL, foreground="#888").pack(side="left")
        ttk.Button(foot, text="重新读取", command=self._reload).pack(side="right", padx=(6, 0))
        ttk.Button(foot, text="关闭", command=self.destroy).pack(side="right")
        self._refresh()

    def _refresh(self):
        # 刷新所有开关的当前值显示
        for path, lbl in self._rows.items():
            v = _get_path(self._settings, path)
            if v is None:
                txt = "未设置"
            else:
                txt = "开启" if v else "关闭"
            lbl.configure(text=txt, foreground=("#3c3" if txt == "开启" else "#999"))

    def _toggle(self, path):
        # 切换前 askyesno 确认; 写失败给中文错误提示
        item = next((x for x in self.ITEMS if x[0] == path), None)
        if item is None:
            return
        _path, label, desc = item
        old = bool(_get_path(self._settings, path))
        new = not old
        old_txt = "开启" if old else "关闭"
        new_txt = "开启" if new else "关闭"
        desc_txt = ("将把「%s」由 %s 改为 %s。\n\n%s\n\n"
                    "写入 settings.yaml（自动备份 .bak），重启 dsh web 生效。\n是否继续？"
                    % (label, old_txt, new_txt, desc))
        if not messagebox.askyesno("确认切换", desc_txt, parent=self):
            return
        try:
            _set_path(self._settings, path, new)
            dsh_data.write_settings(self._settings)
        except Exception as e:
            messagebox.showerror("保存失败", "写入 settings.yaml 失败：%s" % e, parent=self)
            return
        self._refresh()
        m = self._master
        if m is not None and hasattr(m, "log"):
            m.log("[主题] %s 已切换为 %s" % (label, new_txt), "ok")
        messagebox.showinfo("已保存", "「%s」已改为 %s。\n重启 dsh web 生效。" % (label, new_txt),
                            parent=self)

    def _reload(self):
        # 重新读取 settings.yaml 并刷新开关显示
        self._settings = self._load_settings()
        self._refresh()
