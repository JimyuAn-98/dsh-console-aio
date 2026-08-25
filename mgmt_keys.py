# -*- coding: utf-8 -*-
# mgmt_keys.py — SSH 密钥管理页面(KeysPage)。
# 安全红线: 私钥内容绝不读取/展示/复制/写入; 只显示文件名/时间/指纹(ssh-keygen -lf)。
# 公钥(.pub)为公开信息, 可展示与复制。
import os
import io
import time
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox

F_BOLD = ("Segoe UI", 10, "bold")
F_SMALL = ("Segoe UI", 9)

# 私钥文件名模式(不读内容, 只列存在性)
_PRIV_PREFIXES = ("id_rsa", "id_ed25519", "id_ecdsa", "id_dsa", "id_ecdsa_sk", "id_ed25519_sk")


def ssh_dir():
    return os.path.join(os.path.expanduser("~"), ".ssh")


def _key_fingerprint(path):
    # 指纹: ssh-keygen -lf 输出(公钥指纹, 不泄露私钥); 失败返回 None
    try:
        r = subprocess.run(["ssh-keygen", "-lf", path], capture_output=True, text=True,
                           errors="replace", timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        if r.returncode == 0:
            parts = r.stdout.split()
            if len(parts) >= 2:
                return parts[1]   # 如 SHA256:xxxx
    except Exception:
        pass
    return None


def list_keys():
    # 返回 [{name, is_priv, fp, mtime}]; 私钥不读内容, 指纹经 ssh-keygen -lf
    out = []
    d = ssh_dir()
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        fp = os.path.join(d, fn)
        if not os.path.isfile(fp):
            continue
        is_pub = fn.endswith(".pub")
        is_priv = (not is_pub) and fn.startswith(_PRIV_PREFIXES)
        if not (is_pub or is_priv):
            continue
        name = fn[:-4] if is_pub else fn
        out.append({
            "name": name,
            "is_pub": is_pub,
            "fp": _key_fingerprint(fp),
            "mtime": os.path.getmtime(fp),
        })
    return out


def read_pubkey(name):
    # 读公钥内容(.pub, 公开信息); 私钥绝不读
    p = os.path.join(ssh_dir(), name + ".pub")
    if not os.path.isfile(p):
        return None
    with io.open(p, encoding="utf-8", errors="replace") as fh:
        return fh.read().strip()


class KeysPage(ttk.Frame):
    # 页面: SSH 密钥管理(只读展示 + 生成 + 公钥查看/复制)

    def __init__(self, parent, app):
        super().__init__(parent, padding=(15, 12))
        self._app = app
        self._master = app
        self._keys = []
        self._build()
        self._refresh()

    def _build(self):
        ttk.Label(self, text="SSH 密钥管理", font=F_BOLD).pack(anchor="w", pady=(0, 6))
        ttk.Label(self, text="安全说明: 私钥内容绝不展示/复制; 只显示指纹(公钥指纹)。公钥(.pub)为公开信息。",
                  font=F_SMALL, foreground="#a33").pack(anchor="w", pady=(0, 6))
        # 密钥列表
        cols = ("name", "kind", "fp", "mtime")
        self._tree = ttk.Treeview(self, columns=cols, show="headings", height=8)
        for col, title, width in (("name", "名称", 180), ("kind", "类型", 60),
                                  ("fp", "指纹", 340), ("mtime", "修改时间", 130)):
            self._tree.heading(col, text=title)
            self._tree.column(col, width=width, anchor="w")
        self._tree.pack(fill="both", expand=True)
        self._tree.bind("<<TreeviewSelect>>", self._on_select)
        # 操作按钮
        btns = ttk.Frame(self)
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="刷新", command=self._refresh).pack(side="left", padx=2)
        ttk.Button(btns, text="生成新密钥", command=self._gen_key).pack(side="left", padx=2)
        self._view_btn = ttk.Button(btns, text="查看公钥", command=self._view_pub,
                                    state="disabled")
        self._view_btn.pack(side="left", padx=2)
        self._copy_btn = ttk.Button(btns, text="复制公钥", command=self._copy_pub,
                                    state="disabled")
        self._copy_btn.pack(side="left", padx=2)
        ttk.Button(btns, text="打开 .ssh 目录", command=self._open_dir).pack(side="left", padx=2)
        # 公钥展示区
        ttk.Label(self, text="公钥内容(公开):", font=F_BOLD).pack(anchor="w", pady=(8, 2))
        self._pub_text = tk.Text(self, height=4, wrap="word", font=("Consolas", 9))
        self._pub_text.pack(fill="x")
        self._status = ttk.Label(self, text="", font=F_SMALL, foreground="#888")
        self._status.pack(anchor="w", pady=(4, 0))

    def _selected(self):
        sel = self._tree.selection()
        if not sel:
            return None
        idx = int(sel[0].split("r")[1])
        return self._keys[idx] if 0 <= idx < len(self._keys) else None

    def _refresh(self):
        self._tree.delete(*self._tree.get_children())
        self._keys = []
        for k in list_keys():
            self._keys.append(k)
            iid = "r%d" % (len(self._keys) - 1)
            kind = "私钥" if not k["is_pub"] else "公钥"
            mt = time.strftime("%Y-%m-%d %H:%M", time.localtime(k["mtime"])) if k["mtime"] else "?"
            self._tree.insert("", "end", iid=iid,
                              values=(k["name"], kind, k["fp"] or "—", mt))
        self._on_select()
        self._set_status("共 %d 个密钥" % len(self._keys))

    def _on_select(self, _evt=None):
        k = self._selected()
        if k is None or k["is_pub"] is False:
            self._view_btn.configure(state="normal" if k and not k["is_pub"] else "disabled")
            self._copy_btn.configure(state="disabled")
            self._pub_text.configure(state="normal")
            self._pub_text.delete("1.0", "end")
            self._pub_text.configure(state="disabled")
            return
        pub = read_pubkey(k["name"])
        self._view_btn.configure(state="normal")
        self._copy_btn.configure(state="normal" if pub else "disabled")
        self._pub_text.configure(state="normal")
        self._pub_text.delete("1.0", "end")
        self._pub_text.insert("1.0", pub or "(无 .pub 文件)")
        self._pub_text.configure(state="disabled")

    def _set_status(self, text, color="#888"):
        self._status.configure(text=text, foreground=color)

    def _gen_key(self):
        name = tk.simpledialog.askstring("生成新密钥", "密钥名称(如 id_ed25519_my):", parent=self)
        if not name:
            return
        if not name.startswith("id_"):
            messagebox.showwarning("命名建议", "建议以 id_ 开头(如 id_ed25519_my)", parent=self)
        path = os.path.join(ssh_dir(), name)
        ok = messagebox.askyesno(
            "生成新密钥",
            "将执行: ssh-keygen -t ed25519 -f %s -N \"\"\n\n"
            "注意: -N \"\" 表示无口令保护。如需口令保护, 请在终端手动生成。\n是否继续？" % path,
            parent=self)
        if not ok:
            return
        def worker():
            try:
                os.makedirs(ssh_dir(), exist_ok=True)
                r = subprocess.run(["ssh-keygen", "-t", "ed25519", "-f", path, "-N", "",
                                    "-C", "dsh-console-aio"], capture_output=True, text=True,
                                   errors="replace", timeout=30,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
                msg = "已生成: %s (ed25519)" % name if r.returncode == 0 else ("生成失败: " + (r.stderr or "").strip())
                self.after(0, lambda: (self._refresh(), self._set_status(msg, "#3c3" if r.returncode == 0 else "#c33")))
            except Exception as e:
                self.after(0, lambda: self._set_status("生成异常: " + str(e), "#c33"))
        threading.Thread(target=worker, daemon=True).start()

    def _view_pub(self):
        k = self._selected()
        if k is None:
            return
        pub = read_pubkey(k["name"]) or "(无 .pub 文件)"
        messagebox.showinfo("公钥 " + k["name"], pub, parent=self)

    def _copy_pub(self):
        k = self._selected()
        if k is None:
            return
        pub = read_pubkey(k["name"])
        if not pub:
            messagebox.showwarning("无公钥", "未找到 %s.pub", parent=self)
            return
        self.clipboard_clear()
        self.clipboard_append(pub)
        self._set_status("公钥已复制到剪贴板", "#3c3")

    def _open_dir(self):
        try:
            os.makedirs(ssh_dir(), exist_ok=True)
            os.startfile(ssh_dir())
        except Exception as e:
            messagebox.showerror("无法打开", str(e), parent=self)


class KeysDialog(tk.Toplevel):
    # 兼容包装(Toplevel 内嵌 KeysPage)
    def __init__(self, master):
        if hasattr(master, "root"):
            tk_master = master.root
            app = master
        else:
            tk_master = master
            app = None
        super().__init__(tk_master)
        self.title("SSH 密钥管理")
        self.geometry("760x560")
        self.configure(padx=10, pady=10)
        self._page = KeysPage(self, app)
        self._page.pack(fill="both", expand=True)
        self.transient(tk_master)
        self.grab_set()
