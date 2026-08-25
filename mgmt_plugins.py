# -*- coding: utf-8 -*-
# mgmt_plugins.py — dsh 插件管理页面(PluginPage, ttk.Frame) + 独立窗口兼容包装(PluginDialog)。
# 供 dsh-console-aio.py 集成: 左导航中栏内嵌 PluginPage; 旧入口仍可打开 PluginDialog 独立窗口。
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

# 与主程序一致的风格常量(独立模块自带, 避免强依赖导入 dsh-console-aio.py)
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


class PluginPage(ttk.Frame):
    # 插件管理页面: parent=容器 Frame, app=Dashboard 实例(裸 Tk 打开时为 None)。
    # 页面只负责内容与布局, 不做窗口级行为(标题/尺寸/transient/grab_set 属包装窗口)。
    def __init__(self, parent, app):
        super().__init__(parent)
        self._app = app
        self._master = app   # 兼容旧逻辑: _log/_run_stream 读取 self._master
        # 部署联动: 当前部署(host 非空)构造 DshRemote, 读操作走远程; None=本机
        remote = None
        _dep = getattr(app, "_current_deploy", None)
        if _dep and _dep.get("host"):
            remote = dsh_data.DshRemote(_dep)
        self._remote = remote
        self._profiles = []
        self._entries = []      # [(tree_iid, entry_dict)], 与 Treeview 行一一对应
        self._id_map = {}      # name(包名)->真实 entry id(来自 dsh --dump-config)
        self._tree = None
        self._status_lbl = None
        self._disable_btn = None
        self._enable_btn = None
        self._remove_btn = None
        self._profile_var = tk.StringVar()
        self._pkg_var = tk.StringVar(value="dshmarket")
        self._build()
        self._load_profiles()

    # ── UI ────────────────────────────────────────────
    def _build(self):
        # 页面自身即容器; pack 填充, 高度自适应(不写死)

        # 顶部: Profile 选择 + 刷新 + 打开 patch
        top = ttk.Frame(self)
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
        list_frame = ttk.Frame(self)
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
        inst = ttk.Frame(self)
        inst.pack(fill="x", pady=(8, 2))
        ttk.Label(inst, text="安装插件( npm 包名 ):").pack(side="left")
        ttk.Entry(inst, textvariable=self._pkg_var, width=28).pack(side="left", padx=4)
        ttk.Button(inst, text="安装", command=self._install).pack(side="left", padx=2)
        ttk.Label(inst, text="经 dsh plugin add 安装, 输出到主日志区",
                  font=F_SMALL, foreground="#888").pack(side="left", padx=6)

        # 操作行
        btns = ttk.Frame(self)
        btns.pack(fill="x", pady=(6, 0))
        self._disable_btn = ttk.Button(btns, text="停用", command=self._disable, state="disabled")
        self._disable_btn.pack(side="left", padx=2)
        self._enable_btn = ttk.Button(btns, text="启用", command=self._enable, state="disabled")
        self._enable_btn.pack(side="left", padx=2)
        self._remove_btn = ttk.Button(btns, text="卸载", command=self._remove, state="disabled")
        self._remove_btn.pack(side="left", padx=2)
        ttk.Label(btns, text="停用/启用写入 cordis.patch.yml(写前自动备份, HMR 约 1 秒生效)",
                  font=F_SMALL, foreground="#888").pack(side="left", padx=10)

        # 底部状态
        self._status_lbl = ttk.Label(self, text="", font=F_SMALL, foreground="#888")
        self._status_lbl.pack(fill="x", pady=(8, 0))

    # ── Profile / 列表 ────────────────────────────────
    def _load_profiles(self):
        # 只列有 cordis.yml 或 cordis.patch.yml 的 profile
        try:
            profiles = dsh_data.list_profiles(remote=self._remote)
        except Exception as e:
            self._tree.delete(*self._tree.get_children())
            self._set_status("Profile 列表读取失败: %s" % e, "#c33")
            return
        self._profiles = [p for p in profiles if p.get("cordis") or p.get("patch")]
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
        # 汇总插件列表: 基线 = read_profile_package(profile) 的 bundles 字段(已装插件),
        # 版本取 dependencies; cordis.patch.yml 叠加 disabled 标记 / insert 新增。
        try:
            pkg = dsh_data.read_profile_package(profile, remote=self._remote)
            patch_rows = dsh_data.read_cordis_patch(profile, remote=self._remote) or []
        except Exception as e:
            self._set_status("插件数据读取失败: %s" % e, "#c33")
            return []
        deps = pkg.get("dependencies") or {}
        out = []
        index = {}
        for bundle in pkg.get("bundles") or []:
            # bundle 行: id/name 就是 bundle 名(patch 里 - id: X 的 X 也是 bundle 名, 直接可覆盖)
            name = str(bundle)
            row = {"id": name, "name": name,
                   "version": deps.get(name, ""), "_src": "bundle"}
            out.append(row)
            index.setdefault(name, row)
        for e in patch_rows:
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
                    index[eid]["version"] = deps.get(eid, "")
            else:
                # patch 里的其它行(如禁用不在 bundles 中的插件)也展示
                row = dict(e)
                row["_src"] = "patch"
                row.setdefault("name", eid)
                row.setdefault("version", deps.get(eid, ""))
                out.append(row)
                index[eid] = row
        return out

    def _refresh(self):
        profile = self._profile_var.get().strip()
        if not profile:
            return
        self._tree.delete(*self._tree.get_children())
        # 构建 name->真实 entry id 映射(dump-config 较慢, 后台线程; 停用/启用用真实 id)
        self._id_map = {}
        dash_repo = getattr(self._app, "DASH_REPO", None) if self._app else None
        if not self._remote:
            def _load_map():
                try:
                    m = dsh_data.load_entry_id_map(profile, dash_repo)
                except Exception:
                    m = {}
                try:
                    self.after(0, lambda: setattr(self, "_id_map", m))
                except tk.TclError:
                    pass
            threading.Thread(target=_load_map, daemon=True).start()
        self._entries = []
        self._tree.tag_configure("disabled", foreground="#c33")
        for i, e in enumerate(self._merge_entries(profile)):
            iid = "row%d" % i
            self._entries.append((iid, e))
            status = "已停用" if e.get("disabled") else "已启用"
            src = "cordis.patch.yml" if e.get("_src") == "patch" else "bundle"
            self._tree.insert(
                "", "end", iid=iid,
                values=(status, e.get("name") or e.get("id") or "?",
                        e.get("version") or "", src),
                tags=("disabled",) if e.get("disabled") else ())
        self._set_status("共 %d 个插件" % len(self._entries))
        self._on_select()

    def _selected_entry(self):
        # 当前 Treeview 选中行对应的 entry dict; 未选中返回 None
        sel = self._tree.selection()
        if not sel:
            return None
        iid = sel[0]
        for row_iid, e in self._entries:
            if row_iid == iid:
                return e
        return None

    def _on_select(self, _event=None):
        # 根据是否选中行控制 停用/启用/卸载 按钮
        st = "normal" if self._selected_entry() is not None else "disabled"
        for btn in (self._disable_btn, self._enable_btn, self._remove_btn):
            btn.configure(state=st)

    def _set_status(self, text, color="#888"):
        if self._status_lbl is not None:
            try:
                self._status_lbl.configure(text=text, foreground=color)
            except tk.TclError:
                pass    # 窗口已关闭, 忽略

    def _log(self, msg, tag=""):
        # 打到主界面日志区; 主窗口缺失或已销毁时静默
        m = self._master
        if m is not None and hasattr(m, "log"):
            try:
                m.log(msg, tag)
            except Exception:
                pass    # 主窗口已销毁等异常, 日志属附加信息, 不阻断操作

    # ── 安装 / 卸载(官方命令) ─────────────────────────
    def _install(self):
        profile = self._profile_var.get().strip()
        pkg = self._pkg_var.get().strip()
        if not profile:
            self._set_status("请先选择 Profile", "#c33")
            return
        if not pkg:
            messagebox.showwarning("缺少包名", "请填写要安装的 npm 包名。", parent=self)
            return
        cmd = dsh_data.plugin_cmd(profile, "add", pkg)
        ok = messagebox.askyesno(
            "安装插件",
            "将执行：\n  " + " ".join(cmd) + "\n\n是否继续？",
            parent=self)
        if not ok:
            return
        self._run_stream(cmd, "安装插件 " + pkg)

    def _remove(self):
        e = self._selected_entry()
        if e is None:
            return
        profile = self._profile_var.get().strip()
        eid = e.get("id")
        pkg = e.get("name") or eid
        if not profile or not pkg:
            return
        if self._is_protected(eid):
            messagebox.showwarning("受保护", "这是 dsh 宿主基础插件，不允许卸载。", parent=self)
            return
        cmd = dsh_data.plugin_cmd(profile, "remove", pkg)
        ok = messagebox.askyesno(
            "卸载插件",
            "将执行：\n  " + " ".join(cmd) + "\n\n卸载会移除插件文件与相关行，是否继续？",
            parent=self)
        if not ok:
            return
        self._run_stream(cmd, "卸载插件 " + pkg)

    def _run_stream(self, cmd, desc):
        # 后台线程流式执行官方命令(经主界面 _stream_cmd), 完成后回主线程刷新列表。
        self._set_status("执行中: " + " ".join(cmd), "#c90")
        def worker():
            m = self._master
            if not (m is not None and hasattr(m, "_stream_cmd") and hasattr(m, "log")):
                # 无主界面时无法流式输出, 明确提示需从主界面打开
                def hint():
                    try:
                        messagebox.showinfo(
                            "无法执行",
                            "请从主界面(dsh 控制台)打开插件管理，命令才会流式输出到主日志区。\n\n" +
                            " ".join(cmd), parent=self)
                    except tk.TclError:
                        pass    # 窗口已关闭, 忽略
                try:
                    self.after(0, hint)
                except tk.TclError:
                    pass    # 窗口已关闭, 忽略
                return
            try:
                m.log("[插件] " + desc + " 开始: " + " ".join(cmd), "warn")
                # dsh plugin 命令必须在 dsh 仓库目录执行(pnpm dsh ...)
                cwd = getattr(m, "DASH_REPO", None)
                ok = m._stream_cmd(cmd, cwd=cwd)
            except Exception as ex:
                ok = False
                try:
                    m.log("  [插件] 执行异常: " + str(ex), "err")
                except Exception:
                    pass    # 主窗口可能已销毁, 日志失败不阻断
            def done():
                try:
                    self._refresh()
                    self._set_status(
                        "已" + ("完成" if ok else "失败") + "(详见主界面日志区)",
                        "#3c3" if ok else "#c33")
                except tk.TclError:
                    pass    # 窗口已关闭, 忽略
            try:
                self.after(0, done)
            except tk.TclError:
                pass    # 窗口已关闭, 忽略
        threading.Thread(target=worker, daemon=True).start()

    # ── 停用 / 启用(patch 层) ─────────────────────────
    def _disable(self):
        e = self._selected_entry()
        if e is None:
            return
        profile = self._profile_var.get().strip()
        eid = e.get("id")
        name = e.get("name") or eid
        if not profile or not eid:
            return
        if self._is_protected(eid):
            messagebox.showwarning("受保护", "这是 dsh 宿主基础插件，停用会破坏插件链本身，已拒绝。",
                                   parent=self)
            return
        if e.get("disabled"):
            messagebox.showinfo("已停用", "「%s」已处于停用状态。" % name, parent=self)
            return
        ok = messagebox.askyesno(
            "停用插件",
            "将把「%s」标记为已停用：\n写入 %s/cordis.patch.yml(写前自动备份，HMR 约 1 秒生效)。\n\n是否继续？"
            % (name, profile),
            parent=self)
        if not ok:
            return
        self._set_disabled(profile, eid, True)

    def _enable(self):
        e = self._selected_entry()
        if e is None:
            return
        profile = self._profile_var.get().strip()
        eid = e.get("id")
        name = e.get("name") or eid
        if not profile or not eid:
            return
        if not e.get("disabled"):
            messagebox.showinfo("未停用", "「%s」当前未停用，无需启用。" % name, parent=self)
            return
        ok = messagebox.askyesno(
            "启用插件",
            "将移除「%s」的 disabled 标记：\n写入 %s/cordis.patch.yml(写前自动备份，HMR 约 1 秒生效)。\n\n是否继续？"
            % (name, profile),
            parent=self)
        if not ok:
            return
        self._set_disabled(profile, eid, False)

    def _set_disabled(self, profile, eid, disabled):
        # 读 patch → 增/改 disabled 标记 → dsh_data.write_cordis_patch(内部先 .bak 备份)。
        # 停用: 无同名行则追加 `- id: X` + `disabled: true`; 有则原地置 True。
        # 启用: 移除该行的 disabled 字段; 若只剩 id 则整行删除, 保持 patch 干净。
        # 关键: 必须用真实 entry id(dump-config 映射), 不能用 bundle 名(如 dshmarket->dsh-market)
        eid = self._id_map.get(eid, eid)
        try:
            patch = dsh_data.read_cordis_patch(profile, remote=self._remote) or []
        except Exception as e:
            messagebox.showerror("读取失败", "读取 cordis.patch.yml 失败：%s" % e, parent=self)
            return
        new_rows = []
        touched = False
        for row in patch:
            if not isinstance(row, dict) or row.get("id") != eid:
                new_rows.append(row)
                continue
            touched = True
            row2 = dict(row)
            if disabled:
                row2["disabled"] = True
                new_rows.append(row2)
            else:
                row2.pop("disabled", None)
                if len(row2) > 1:
                    new_rows.append(row2)
                # 只剩 id 的裸行直接删除
        if disabled and not touched:
            new_rows.append({"id": eid, "disabled": True})
        try:
            dsh_data.write_cordis_patch(profile, new_rows)
        except OSError as ex:
            messagebox.showerror("写入失败", "无法写 cordis.patch.yml：%s" % ex, parent=self)
            return
        self._log("[插件] 已%s %s (cordis.patch.yml)" % ("停用" if disabled else "启用", eid), "ok")
        self._set_status("已" + ("停用" if disabled else "启用") + " " + eid, "#3c3")
        self._refresh()

    # ── 其它 ──────────────────────────────────────────
    def _is_protected(self, eid):
        # 宿主基础设施行拒绝停用/卸载
        return bool(eid and _PROTECTED_IDS.match(str(eid)))

    def _open_patch(self):
        profile = self._profile_var.get().strip()
        if not profile:
            return
        p = os.path.join(dsh_data.profiles_dir(), profile, "cordis.patch.yml")
        if not os.path.isfile(p):
            messagebox.showinfo("文件不存在",
                                "该 profile 还没有 cordis.patch.yml。\n可以先执行一次停用/启用操作生成。",
                                parent=self)
            return
        try:
            os.startfile(p)
        except Exception as ex:
            messagebox.showerror("无法打开", str(ex), parent=self)


class PluginDialog(tk.Toplevel):
    # 兼容包装: 独立窗口内嵌 PluginPage(保留原窗口行为: 标题/尺寸/transient/grab_set)。
    def __init__(self, master):
        # master 可以是 Dashboard 实例(推荐) 或 Tk 根窗口; 与 EnvDialog 同样的兼容方式。
        if hasattr(master, "root"):
            tk_master = master.root
            app = master
        else:
            tk_master = master
            app = None
        super().__init__(tk_master)
        self.title("插件管理")
        self.geometry("700x520")
        self.minsize(660, 480)
        self.configure(padx=12, pady=10)
        self._page = PluginPage(self, app)
        self._page.pack(fill="both", expand=True)
        self.transient(tk_master)
        self.grab_set()
