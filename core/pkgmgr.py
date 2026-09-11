# -*- coding: utf-8 -*-
# core/pkgmgr.py - dsh 全局包(pnpm -g)探测 / 环境修正 / 命令拼装(纯 Python, 零 Qt)。
#
# 背景: dsh 官方 npm 包 @deepseek-ai/dsh(bin=dsh)本身只有 web/plugin 子命令, 全局安装/
# 更新/卸载由 pnpm 负责: pnpm add -g @deepseek-ai/dsh[@版本] / pnpm update -g @deepseek-ai/dsh
# / pnpm remove -g @deepseek-ai/dsh。
# 本机坑: pnpm(corepack) 在"全局 bin 目录不在 PATH"时直接报错退出, 故所有 pnpm 调用一律
# 带 pnpm_env() 修正后的环境(全局 bin 目录前置进 PATH + 补 PNPM_HOME)。
#
# 模式判定(控制台据此决定安装/更新/卸载/启动走哪条路):
#   source  = config.dash_repo 指向可用的 dsh 源码目录(含 package.json 且像 dsh 仓库)
#   package = 全局已安装 @deepseek-ai/dsh
#   显式 config.dsh_install_mode(source|package) 优先; 否则源码优先(保持既有行为), 再包。

import json
import os
import subprocess
import time

DSH_PKG = "@deepseek-ai/dsh"
PNPM = "pnpm.cmd"
CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW

_CACHE = {"at": 0.0, "deps": None}   # pnpm list -g 结果缓存(探测一次约 1s)
_CACHE_TTL = 30.0


def _default_bin_dir():
    # 仅用环境变量推导 pnpm 全局可执行目录(不跑子进程, 供 pnpm_env 使用避免递归)。
    home = (os.environ.get("PNPM_HOME") or "").strip()
    if home:
        return home
    base = (os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")).strip()
    return os.path.join(base, "pnpm", "bin")


def pnpm_env(base=None):
    # 复制环境并把全局 bin 目录前置进 PATH; 同时补 PNPM_HOME(解 corepack 报错)。
    env = dict(base if base is not None else os.environ)
    path = ""
    for k in [k for k in env if k.upper() == "PATH"]:
        path = env.pop(k)
        break
    d = _default_bin_dir()
    parts = [p for p in (path or "").split(os.pathsep) if p]
    if d and d not in parts:
        parts.insert(0, d)
    env["PATH"] = os.pathsep.join(parts)
    if not env.get("PNPM_HOME"):
        env["PNPM_HOME"] = d
    return env


def global_bin_dir():
    # pnpm 全局可执行目录: 先 pnpm bin -g(带修正环境), 失败回退环境推导。
    try:
        p = subprocess.run([PNPM, "bin", "-g"], capture_output=True, text=True,
                           errors="replace", timeout=20, env=pnpm_env(),
                           creationflags=CREATE_NO_WINDOW)
        lines = (p.stdout or "").strip().splitlines()
        if lines and lines[-1].strip():
            return lines[-1].strip()
    except Exception:
        pass
    return _default_bin_dir()


def _deps(force=False):
    # 全局顶层依赖 {name: version}; 探测失败返回 None(区别于"未安装"的空 dict)。
    now = time.time()
    if not force and _CACHE["deps"] is not None and now - _CACHE["at"] < _CACHE_TTL:
        return _CACHE["deps"]
    deps = None
    try:
        p = subprocess.run([PNPM, "list", "-g", "--depth", "0", "--json"],
                           capture_output=True, text=True, errors="replace",
                           timeout=30, env=pnpm_env(), creationflags=CREATE_NO_WINDOW)
        data = json.loads(p.stdout or "[]")
        items = data if isinstance(data, list) else [data]
        deps = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            for name, meta in (item.get("dependencies") or {}).items():
                deps[name] = str(meta.get("version") or "") if isinstance(meta, dict) else str(meta or "")
            if item.get("name"):
                deps[item["name"]] = str(item.get("version") or "")
    except Exception:
        deps = None
    _CACHE["at"] = now
    _CACHE["deps"] = deps
    return deps


def package_info(force=False):
    # {"ok", "version", "error"}; error 非空 = 探测失败(不能当作"未安装")。
    deps = _deps(force=force)
    if deps is None:
        return {"ok": False, "version": "", "error": "pnpm 全局包探测失败(检查 pnpm/PATH)"}
    v = deps.get(DSH_PKG) or ""
    return {"ok": bool(v), "version": v, "error": ""}


def source_info(repo):
    # repo 是否为可用的 dsh 源码目录(供模式判定与展示)。
    repo = (repo or "").strip()
    info = {"ok": False, "repo": repo, "version": ""}
    if not repo or not os.path.isabs(repo) or not os.path.isdir(repo):
        return info
    try:
        with open(os.path.join(repo, "package.json"), encoding="utf-8") as f:
            data = json.load(f) or {}
        info["version"] = str(data.get("version") or "")
        name = str(data.get("name") or "")
        info["ok"] = (name == "@deepseek-ai/dsh-root"
                      or os.path.isdir(os.path.join(repo, "apps", "cli"))
                      or os.path.isfile(os.path.join(repo, "pnpm-workspace.yaml")))
    except Exception:
        pass
    return info


def detect_mode(cfg=None, force=False):
    # 返回 {"mode", "explicit", "source":{...}, "package":{...}};
    # mode: source | package | none(两者都没检测到)。
    cfg = cfg or {}
    src = source_info(cfg.get("dash_repo"))
    pkg = package_info(force=force)
    pkg["bin_dir"] = global_bin_dir()
    explicit = str(cfg.get("dsh_install_mode") or "").strip().lower()
    if explicit in ("source", "package"):
        mode = explicit
    elif src["ok"]:
        mode = "source"
    elif pkg["ok"]:
        mode = "package"
    else:
        mode = "none"
    return {"mode": mode, "explicit": explicit, "source": src, "package": pkg}


def mode_label(info):
    # 供 UI 展示的一句话(中文); info = detect_mode() 结果。
    mode = (info or {}).get("mode")
    if mode == "source":
        s = info["source"]
        return "源码模式（%s%s）" % (s["repo"], ("，v" + s["version"]) if s["version"] else "")
    if mode == "package":
        p = info["package"]
        return "全局包模式（%s %s）" % (DSH_PKG, p.get("version") or "?")
    return "未检测到已安装的 dsh"


def install_cmd(version=""):
    v = str(version or "").strip().lstrip("@")
    if v.startswith("v"):
        v = v[1:]   # Release tag(v0.1.5-rc.1) -> npm 版本(0.1.5-rc.1)
    return [PNPM, "add", "-g", DSH_PKG + ("@" + v if v else "")]


def update_cmd():
    return [PNPM, "update", "-g", DSH_PKG]


def remove_cmd():
    return [PNPM, "remove", "-g", DSH_PKG]


def start_cmd():
    # 全局 dsh 启停用 bin 目录下的 shim 绝对路径(避免依赖调用方 PATH)。
    d = global_bin_dir()
    for name in ("dsh.cmd", "dsh.exe", "dsh"):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return [p, "web"]
    return ["dsh", "web"]

