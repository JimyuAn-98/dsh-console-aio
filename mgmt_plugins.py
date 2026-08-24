# -*- coding: utf-8 -*-
# mgmt_plugins.py — dsh 插件管理窗口(独立 Toplevel), 供 dsh-tunnel-console.py 集成。
# 设计要点:
#   - 已装插件真实来源 = profile/package.json 的 dsh.profile.bundles 数组
#     (cordis.yml 是空组合架构, 只读参考; 用户可写层是 cordis.patch.yml)。
#   - 停用/启用只写 cordis.patch.yml(dsh_data.write_cordis_patch 内部先 .bak 备份再写回)。
#   - 安装/卸载不自实现安装逻辑, 走官方命令 dsh plugin --profile <name> add|remove <pkg>,
#     由主界面 Dashboard._stream_cmd 流式输出到主日志区。
#   - 参考 dsh-market(https://github.com/dsh-market/dsh-market) 的 patch 层语义:
#     patch 行 `- id: X` + `disabled: true` 停用对应 loader entry。

import os
import re
import threading
import tkinter as tk
from tkinter import ttk, messagebox

import dsh_data

# 与主程序一致的风格常量(独立模块自带, 避免强依赖导入 dsh-tunnel-console.py)
F_BOLD = ("Segoe UI", 10, "bold")
F_SMALL = ("Segoe UI", 9)

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


class PluginDialog(tk.Toplevel):
    # master 可以是 Dashboard 实例(推荐) 或 Tk 根窗口; 与 EnvDialog 同样的兼容方式。
    def __init__(self, master):
        if hasattr(master, "root"):
            tk_master = master.root
            self._master = master
        else:
            tk_master = master
            self._master = None
        super().__init__(tk_master)
        self.title("插件管理")
        self.geometry("700x520")
        self.minsize(660, 480)
        self.configure(padx=12, pady=10)
        self._profiles = []
        self._entries = []      # [(tree_iid, entry_dict)], 与 Treeview 行一一对应
        self._tree = None
        self._status_lbl = None
        self._disable_btn = None
        self._enable_btn = None
        self._remove_btn = None
        self._profile_var = tk.StringVar()
        self._pkg_var = tk.StringVar(value="dshmarket")
        self._build()
        self.transient(tk_master)
        self.grab_set()
        self._load_profiles()

    # ── UI ────────────────────────────────────────────
    def _build(self):
        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True)

        # 顶部: Profile 选择 + 刷新 + 打开 patch
        top = ttk.Frame(wrap)
        top.pack(fill="x", pady=(0, 6))
        ttk.Label(top, text="Profile:").pack(side="left")
        self._profile_cb = ttk.Combobox(top, textvariable=self._profile_var,
                                        state="readonly", width=22)
        self._profile_cb.pack(side="left", padx=(4, 8))
        self._profile_cb.bind("<<ComboboxSelected>>", lambda _e: self._refresh())
        ttk.Button(top, text="刷新", command=self._refresh).pack(side="left", padx=2)
        ttk.Button(top, text="打开 patch 文件", command=self._open_patch).pack(side="left", padx=2)
        ttk.Label(top, text="已装插件来自 package.json bundles · 改动写入 cordis.patch.yml",
                  font=F_SMALL, foreground="#888").pack(side="right")

        # 插件列表
        list_frame = ttk.Frame(wrap)
        list_frame.pack(fill="both", expand=True)
        cols = ("status", "name", "version", "source")
        self._tree = ttk.Treeview(list_frame, columns=cols, show="headings", height=12)
        for col, title, width in (("status", "状态", 80),
                                  ("name", "名称(包名)", 300),
                                  ("version", "版本", 110),
                                  ("source", "来源", 120)):
            self._tree.heading(col, text=title)
            self._tree.column(col, width=width, anchor="w")
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        # 安装行: npm 包名 + 官方 dsh plugin add
        inst = ttk.Frame(wrap)
        inst.pack(fill="x", pady=(8, 2))
        ttk.Label(inst, text="安装插件( npm 包名 ):").pack(side="left")
        ttk.Entry(inst, textvariable=self._pkg_var, width=28).pack(side="left", padx=4)
        ttk.Button(inst, text="安装", command=self._install).pack(side="left", padx=2)
        ttk.Label(inst, text="经 dsh plugin add 安装, 输出到主日志区",
                  font=F_SMALL, foreground="#888").pack(side="left", padx=6)

        # 操作行
        btns = ttk.Frame(wrap)
        btns.pack(fill="x", pady=(6, 0))
        self._disable_btn = ttk.Button(btns, text="停用", command=self._disable, state="disabled")
        self._disable_btn.pack(side="left", padx=2)
        self._enable_btn = ttk.Button(btns, text="启用", command=self._enable, state="disabled")
        self._enable_btn.pack(side="left", padx=2)
        self._remove_btn = ttk.Button(btns, text="卸载", command=self._remove, state="disabled")
        self._remove_btn.pack(side="left", padx=2)
        ttk.Label(btns, text="停用/启用写入 cordis.patch.yml(写前自动备份, HMR 约 1 秒生效)",
                  font=F_SMALL, foreground="#888").pack(side="left", padx=10)
        ttk.Button(btns, text="关闭", command=self.destroy).pack(side="right")

        # 底部状态
        self._status_lbl = ttk.Label(wrap, text="", font=F_SMALL, foreground="#888")
        self._status_lbl.pack(fill="x", pady=(8, 0))

    # ── Profile / 列表 ────────────────────────────────
    def _load_profiles(self):
        # 只列有 cordis.yml 或 cordis.patch.yml 的 profile
        self._profiles = [p for p in dsh_data.list_profiles()
                          if p.get("cordis") or p.get("patch")]
        names = [p["name"] for p in self._profiles]
        self._profile_cb.configure(values=names)
        if names:
            cur = self._profile_var.get()
            if cur not in names:
                self._profile_var.set(names[0])
            self._refresh()
        else:
            self._tree.delete(*self._tree.get_children())
            self._set_status("未找到可用 profile(~/.dsh/profiles 下没有 cordis.yml / cordis.patch.yml)",
                             "#c33")

    def _merge_entries(self, profile):
        # 汇总插件列表: 基线 = read_profile_package(profile)['bundles'](已装插件),
        # 版本取 dependencies; cordis.patch.yml 叠加 disabled 标记 / insert 新增。
        pkg = dsh_data.read_profile_package(profile)
        deps = pkg.get("dependencies") or {}
        out = []
        index = {}
        for bundle in pkg.get("bundles") or []:
            name = str(bundle)
            row = {"id": name, "name": name,
                   "version": deps.get(name, ""), "_src": "package.json"}
            out.append(row)
            index.setdefault(name, row)
        for e in dsh_data.read_cordis_patch(profile) or []:
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
                    in
