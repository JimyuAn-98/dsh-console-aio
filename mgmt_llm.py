# -*- coding: utf-8 -*-
# mgmt_llm.py — LLM / 模型配置管理(页面化): LlmPage 嵌入主界面, LlmDialog 兼容包装
# 数据: ~/.dsh/settings.yaml 的 agent-default-model(读写) 与 llm-pi-ai.providers(只读)。
# 密钥安全: apiKeyEnv 只引用环境变量名, 本窗口不读取/不写入/不展示密钥明文。
# 风格: 与主程序 dsh-console-aio.py 的 EnvDialog 一致(ttk + transient + grab_set)。

import os
import tkinter as tk
from tkinter import ttk, messagebox

import dsh_data

# 风格常量与主程序 dsh-console-aio.py 顶部保持一致。
# 主程序文件名含连字符无法常规 import, 此处直接定义同值常量, 避免循环依赖。
F_BOLD = ("Segoe UI", 10, "bold")
F_SMALL = ("Segoe UI", 9)

# 内置官方 provider 不在 settings.yaml 里, 模型 id 与数据层单价表保持一致
BUILTIN_PROVIDER = "deepseek-official"
BUILTIN_MODELS = list(dsh_data.DEFAULT_PRICES.keys())
REASONING_LEVELS = ["min", "medium", "max"]


class LlmPage(ttk.Frame):
    # 查看/切换 agent-default-model, 只读展示自定义 providers。
    # parent=容器 Frame, app=Dashboard 实例(可为 None); 页面高度随容器自适应, 不设窗口尺寸。
    def __init__(self, parent, app):
        super().__init__(parent, padding=(15, 12))
        self._app = app
        self._settings = self._load_settings()
        self._build()

    def _load_settings(self):
        # 读取 settings.yaml; 文件缺失或损坏时按空 dict 处理, 不让页面白屏
        try:
            s = dsh_data.read_settings()
        except Exception:
            s = {}
        return s if isinstance(s, dict) else {}

    def _providers_map(self):
        # 自定义 providers 必须是 dict{名称: 配置}, 否则按空处理
        llm = self._settings.get("llm-pi-ai")
        p = llm.get("providers") if isinstance(llm, dict) else None
        return p if isinstance(p, dict) else {}

    def _build(self):
        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True)

        ttk.Label(wrap, text="默认模型（agent-default-model）",
                  font=F_BOLD).pack(anchor="w", pady=(0, 4))
        form = ttk.LabelFrame(wrap, text="切换默认模型", padding=8)
        form.pack(fill="x", pady=(0, 6))

        self._provider_var = tk.StringVar()
        self._model_var = tk.StringVar()
        self._effort_var = tk.StringVar()
        self._provider_cb = ttk.Combobox(form, textvariable=self._provider_var,
                                         state="readonly", width=32)
        self._model_cb = ttk.Combobox(form, textvariable=self._model_var,
                                      state="readonly", width=32)
        self._effort_cb = ttk.Combobox(form, textvariable=self._effort_var,
                                       state="readonly", width=14)

        ttk.Label(form, text="provider:").grid(row=0, column=0, sticky="w", pady=2)
        self._provider_cb.grid(row=0, column=1, sticky="ew", padx=6, pady=2)
        ttk.Label(form, text="model:").grid(row=1, column=0, sticky="w", pady=2)
        self._model_cb.grid(row=1, column=1, sticky="ew", padx=6, pady=2)
        ttk.Label(form, text="reasoningEffort:").grid(row=2, column=0, sticky="w", pady=2)
        self._effort_cb.grid(row=2, column=1, sticky="w", padx=6, pady=2)
        form.columnconfigure(1, weight=1)

        btns = ttk.Frame(form)
        btns.grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Button(btns, text="保存默认模型", command=self._on_save).pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="重新读取", command=self._reload).pack(side="left")

        ttk.Label(wrap, text="密钥安全：密钥只保存在系统环境变量中（apiKeyEnv 只引用环境变量名）。\n"
                             "控制台不读取、不写入、不展示密钥明文。",
                  font=F_SMALL, foreground="#888", justify="left").pack(anchor="w", pady=(0, 6))

        prov = ttk.LabelFrame(wrap, text="自定义 Providers（只读）", padding=8)
        prov.pack(fill="both", expand=True)
        cols = ("name", "api", "models", "keyenv")
        self._tree = ttk.Treeview(prov, columns=cols, show="headings", height=7)
        self._tree.heading("name", text="name")
        self._tree.heading("api", text="api")
        self._tree.heading("models", text="models 数量")
        self._tree.heading("keyenv", text="apiKeyEnv（环境变量）")
        self._tree.column("name", width=110, anchor="w")
        self._tree.column("api", width=150, anchor="w")
        self._tree.column("models", width=80, anchor="center")
        self._tree.column("keyenv", width=230, anchor="w")
        sb = ttk.Scrollbar(prov, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # 页面无"关闭"按钮: 页面随容器销毁, 关闭是外层 Toplevel 的事
        foot = ttk.Frame(wrap)
        foot.pack(fill="x", pady=(10, 0))
        ttk.Label(foot, text="修改写入 settings.yaml（自动备份 .bak），重启 dsh web 生效。",
                  font=F_SMALL, foreground="#888").pack(side="left")

        self._provider_cb.bind("<<ComboboxSelected>>", self._on_provider_changed)
        self._load_current()
        self._fill_providers()

    def _provider_options(self):
        # 下拉顺序: 内置官方 provider 在前, 其余为 settings 里的自定义 provider 名
        names = [k for k in self._providers_map() if k != BUILTIN_PROVIDER]
        return [BUILTIN_PROVIDER] + names

    def _models_for(self, provider):
        # 返回该 provider 的模型 id 列表; 内置 provider 合并内置模型与同名自定义项
        ids = []
        if provider == BUILTIN_PROVIDER:
            ids = list(BUILTIN_MODELS)
        p = self._providers_map().get(provider)
        if isinstance(p, dict):
            mlist = p.get("models")
            if isinstance(mlist, list):
                for m in mlist:
                    mid = m.get("id") if isinstance(m, dict) else m
                    mid = str(mid) if mid else ""
                    if mid and mid not in ids:
                        ids.append(mid)
        return ids

    def _load_current(self):
        # 把 settings 当前值填进三个下拉框, 未知取值保留显示而非静默改值
        adm = self._settings.get("agent-default-model")
        cur = adm if isinstance(adm, dict) else {}
        cur_provider = str(cur.get("provider") or BUILTIN_PROVIDER)
        cur_model = str(cur.get("model") or "")
        cur_effort = str(cur.get("reasoningEffort") or "medium")

        opts = self._provider_options()
        self._provider_cb.configure(values=opts)
        self._provider_var.set(cur_provider if cur_provider in opts else (opts[0] if opts else ""))

        self._apply_models(cur_model)

        efforts = list(REASONING_LEVELS)
        if cur_effort not in efforts:
            efforts.insert(0, cur_effort)
        self._effort_cb.configure(values=efforts)
        self._effort_var.set(cur_effort)

    def _apply_models(self, keep_model):
        # 刷新 model 下拉选项, 尽量保留当前选中
        provider = self._provider_var.get()
        models = self._models_for(provider)
        self._model_cb.configure(values=models)
        if keep_model in models:
            self._model_var.set(keep_model)
        elif models:
            self._model_var.set(models[0])

    def _on_provider_changed(self, _event=None):
        self._apply_models(self._model_var.get())

    def _fill_providers(self):
        # 刷新只读 providers 表格; apiKeyEnv 只显示环境变量名与是否已设置
        for i in self._tree.get_children():
            self._tree.delete(i)
        for name, p in self._providers_map().items():
            if not isinstance(p, dict):
                continue
            api = str(p.get("api") or "")
            mlist = p.get("models")
            n = len(mlist) if isinstance(mlist, list) else 0
            env = str(p.get("apiKeyEnv") or "")
            if env:
                env_txt = env + ("（已设置）" if os.environ.get(env) else "（未设置）")
            else:
                env_txt = ""
            self._tree.insert("", "end", values=(name, api, n, env_txt))

    def _on_save(self):
        provider = self._provider_var.get()
        model = self._model_var.get()
        effort = self._effort_var.get()
        if not provider or not model:
            messagebox.showwarning("请选择", "请先选择 provider 与 model。", parent=self)
            return
        if model not in self._models_for(provider):
            messagebox.showwarning("模型无效", "所选模型不在该 provider 的模型列表中。", parent=self)
            return
        desc = ("将默认模型改为：\n"
                "  provider: %s\n  model: %s\n  reasoningEffort: %s\n\n"
                "写入 settings.yaml（自动备份 .bak），重启 dsh web 生效。\n是否继续？"
                % (provider, model, effort))
        if not messagebox.askyesno("确认修改默认模型", desc, parent=self):
            return
        try:
            self._settings["agent-default-model"] = {
                "provider": provider, "model": model, "reasoningEffort": effort}
            dsh_data.write_settings(self._settings)
        except Exception as e:
            messagebox.showerror("保存失败", "写入 settings.yaml 失败：%s" % e, parent=self)
            return
        m = self._app
        if m is not None and hasattr(m, "log"):
            m.log("[LLM] 默认模型已改为 %s / %s" % (provider, model), "ok")
        messagebox.showinfo("已保存",
                            "默认模型已写入 settings.yaml（已自动备份 .bak）。\n重启 dsh web 生效。",
                            parent=self)

    def _reload(self):
        # 重新读取 settings.yaml(可能被外部修改)并刷新界面
        self._settings = self._load_settings()
        self._load_current()
        self._fill_providers()


class LlmDialog(tk.Toplevel):
    # 兼容包装: 内容由 LlmPage 提供, 保留原 Toplevel 的窗口行为(标题/尺寸/transient/grab_set)
    def __init__(self, master):
        # master 兼容 Dashboard 实例(推荐)或 Tk 根窗口
        if hasattr(master, "root"):
            tk_master = master.root
            app = master
        else:
            tk_master = master
            app = None
        super().__init__(tk_master)
        self._master = app
        self.title("LLM / 模型配置")
        self.geometry("720x540")
        self.minsize(640, 480)
        self._page = LlmPage(self, app)
        self._page.pack(fill="both", expand=True)
        self.transient(tk_master)
        self.grab_set()
