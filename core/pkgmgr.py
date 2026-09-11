# -*- coding: utf-8 -*-
# core/pkgmgr.py - dsh 全局包(npm -g)探测 / 环境修正 / 命令拼装(纯 Python, 零 Qt)。
#
# 背景: dsh 官方 npm 包 @deepseek-ai/dsh(bin=dsh, 只有 web/plugin 子命令)。
# 包模式(全局安装)走 **npm** 而不是 pnpm: dsh 运行时的 cordis-plugin-loader 用动态 import
# 加载插件包, Node 只从 loader 自己的目录逐级向上找 node_modules; pnpm 的隔离式布局
# (全局虚拟仓库 store/v11/links/...) 不把插件放在 loader 的祖先链上, 启动时 100+ 条
# ERR_MODULE_NOT_FOUND 直接退出(实机 BUG-016)。npm/npx 是扁平提升布局, 能解析。
# 官方 README 只文档化 npx(npm 布局), 但 npx 每次启动都要解析 registry 且可能重新下载;
# 故控制台采用 npm 全局安装: 安装/更新/卸载有明确状态, 模块布局与 npx 同源。
#
# 模式判定(控制台据此决定安装/更新/卸载/启动走哪条路):
#   source  = config.dash_repo 指向可用的 dsh 源码目录(含 package.json 且像 dsh 仓库)
#   package = npm 全局已安装 @deepseek-ai/dsh
#   显式 config.dsh_install_mode(source|package) 优先; 否则源码优先(保持既有行为), 再包。

import json
import os
import subprocess
import time

DSH_PKG = "@deepseek-ai/dsh"
NPM = "npm.cmd"
PNPM = "pnpm.cmd"   # 仅用于环境检查卡的 pnpm 工具命令(见 pnpm_env), 与 dsh 包模式无关
CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW

_PKG_CACHE = {"at": 0.0, "deps": None}      # npm ls -g 结果缓存(约 1s)
_PKG_TTL = 30.0
_PREFIX_CACHE = {"at": 0.0, "prefix": ""}  # npm prefix -g 结果缓存
_PREFIX_TTL = 60.0


def _with_path_prepended(d, base=None):
    # 复制环境, 把目录 d 前置进 PATH(Windows 的 PATH 键名大小写不固定, 先统一移除)。
    env = dict(base if base is not None else os.environ)
    path = ""
    for k in [k for k in env if k.upper() == "PATH"]:
        path = env.pop(k)
        break
    parts = [p for p in (path or "").split(os.pathsep) if p]
    if d and d not in parts:
        parts.insert(0, d)
    env["PATH"] = os.pathsep.join(parts)
    return env


def npm_global_prefix():
    # npm 全局前缀; Windows 上全局 shim 直接放在该目录(prefix/dsh.cmd)。
    now = time.time()
    if _PREFIX_CACHE["prefix"] and now - _PREFIX_CACHE["at"] < _PREFIX_TTL:
        return _PREFIX_CACHE["prefix"]
    prefix = ""
    try:
        p = subprocess.run([NPM, "prefix", "-g"], capture_output=True, text=True,
                           errors="replace", timeout=20, creationflags=CREATE_NO_WINDOW)
        lines = (p.stdout or "").strip().splitlines()
        if lines and lines[-1].strip():
            prefix = lines[-1].strip()
    except Exception:
        prefix = ""
    if not prefix:
        prefix = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "npm")
    _PREFIX_CACHE["at"] = now
    _PREFIX_CACHE["prefix"] = prefix
    return prefix


def global_bin_dir():
    # 包模式可执行目录: Windows 上就是 npm 全局前缀; 其它平台是 prefix/bin。
    prefix = npm_global_prefix()
    return prefix if os.name == "nt" else os.path.join(prefix, "bin")


def npm_env(base=None):
    # npm 全局命令 / dsh shim 启动用: 把 npm 全局前缀前置进 PATH。
    return _with_path_prepended(global_bin_dir(), base)


def pnpm_home():
    # pnpm 的"家"目录(PNPM_HOME): 全局包与 shim 的根, 注意不是 bin 目录本身。
    home = (os.environ.get("PNPM_HOME") or "").strip()
    if home:
        return home
    base = (os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")).strip()
    return os.path.join(base, "pnpm")


def _pnpm_default_bin_dir():
    # pnpm 全局可执行目录 = pnpm home 下的 bin; 只推导不跑子进程(供 pnpm_env 避免递归)。
    return os.path.join(pnpm_home(), "bin")


def pnpm_env(base=None):
    # 复制环境并把 pnpm 全局 bin 目录前置进 PATH。
    # 红线: 绝不能把 PNPM_HOME 设成 bin 目录本身 —— pnpm 会在 PNPM_HOME 之后**再拼一层 bin**,
    # 得到 pnpm/bin/bin, 因不在 PATH 而直接报错退出(BUG-013, 实机复现)。
    return _with_path_prepended(_pnpm_default_bin_dir(), base)


def _deps(force=False):
    # npm 全局顶层依赖 {name: version}; 探测失败返回 None(区别于"未安装"的空 dict)。
    now = time.time()
    if not force and _PKG_CACHE["deps"] is not None and now - _PKG_CACHE["at"] < _PKG_TTL:
        return _PKG_CACHE["deps"]
    deps = None
    try:
        p = subprocess.run([NPM, "ls", "-g", "--depth", "0", "--json"],
                           capture_output=True, text=True, errors="replace",
                           timeout=30, env=npm_env(), creationflags=CREATE_NO_WINDOW)
        data = json.loads(p.stdout or "{}")
        deps = {}
        block = data.get("dependencies") if isinstance(data, dict) else None
        for name, meta in (block or {}).items():
            deps[name] = str(meta.get("version") or "") if isinstance(meta, dict) else str(meta or "")
    except Exception:
        deps = None
    _PKG_CACHE["at"] = now
    _PKG_CACHE["deps"] = deps
    return deps


def package_info(force=False):
    # {"ok", "version", "error"}; error 非空 = 探测失败(不能当作"未安装")。
    deps = _deps(force=force)
    if deps is None:
        return {"ok": False, "version": "", "error": "npm 全局包探测失败(检查 npm/PATH)"}
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
        return "源码模式（%s%s）" % (s["repo"], (", v" + s["version"]) if s["version"] else "")
    if mode == "package":
        p = info["package"]
        return "全局包模式（npm -g %s@%s）" % (DSH_PKG, p.get("version") or "?")
    return "未检测到已安装的 dsh"


def npm_version(tag):
    # dsh Release tag -> npm 版本: dsh-v0.1.5-rc.2 / v0.1.5-rc.2 / @0.1.5-rc.2 -> 0.1.5-rc.2。
    # 源码模式仍用原始 tag(git checkout 需要 dsh-v0.1.5-rc.2), 只有包模式做这层映射。
    v = str(tag or "").strip()
    if v.startswith("@"):
        v = v[1:]
    for prefix in ("dsh-v", "dsh-", "v"):
        if v.startswith(prefix):
            v = v[len(prefix):]
            break
    return v


def install_cmd(version=""):
    v = npm_version(version)
    return [NPM, "install", "-g", DSH_PKG + ("@" + v if v else "")]


def update_cmd():
    # npm 没有 pnpm update -g 的对等语义; 明确按 latest 重装最可靠。
    return [NPM, "install", "-g", DSH_PKG + "@latest"]


def remove_cmd():
    return [NPM, "uninstall", "-g", DSH_PKG]


def start_cmd():
    # 全局 dsh 启停用 npm 全局前缀下的 shim 绝对路径(避免依赖调用方 PATH)。
    d = global_bin_dir()
    for name in ("dsh.cmd", "dsh.exe", "dsh"):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return [p, "web"]
    return ["dsh", "web"]
