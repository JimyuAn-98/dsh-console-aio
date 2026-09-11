# -*- coding: utf-8 -*-
# core/env.py - 开发环境探测 / SSH 免密测试 / dsh 一键安装流(纯 Python, 零 Qt,
# 严禁 import PySide)。由旧 ui/dialogs.py 的内联子进程业务下沉而来(ConfigDialog 的
# SSH 测试 / InstallDialog 的安装流 / EnvDialog 的版本探测与工具命令)—— 弹窗收敛后
# 环境检查与安装向导改为 DSH 管理页(ui/pages_dsh.py)页面内分步, 业务仍在本模块。
#
# 通讯约定: install_dsh 遵循 events(kind, payload) 纯数据回调:
#   events("log", text)            逐行输出/说明
#   events("step", (n, text))      安装步骤进度(1..4)
# 其余函数为同步调用(对话框在其自有线程中调用, 线程归 UI 层所有 —— 阶段3 决策:
# 业务全部下沉本模块, 对话框线程保留, 详见 docs/ARCHITECTURE.md)。
# 子进程一律 CREATE_NO_WINDOW + text=True errors="replace" + 超时(AGENTS.md 约定)。

import os
import shutil
import subprocess
import sys

from core import config as dsh_config
from core.dshctl import DshCtl

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW


def _rmtree_force(path, log=None):
    # Windows 递归删除加固 + 全程日志: 只读文件/目录(.git/objects) + 长路径(>260) + 短暂占用句柄。
    # 流程: 清只读位 -> 带兜底回调的 rmtree(长路径前缀) -> 重试 -> cmd rmdir 兜底;
    # 仍未删净则抛 OSError(带路径)。log: 可选单参回调(逐行中文输出, 交调用方透传到控制台/操作日志)。
    import stat as _stat
    import time as _t

    def _log(msg):
        if log:
            log(msg)

    if not os.path.exists(path):
        _log("[删除] 路径不存在, 跳过: " + path)
        return
    _log("[删除] 开始: " + path)

    failed = []

    def _clear(node):
        try:
            os.chmod(node, _stat.S_IWRITE)
        except OSError:
            pass

    def _walk_clear(root):
        # onerror 吞掉个别不可遍历子目录, 由末尾存在性检查统一报错
        for base, dirs, files in os.walk(root, topdown=False, onerror=lambda _e: None):
            for name in files:
                _clear(os.path.join(base, name))
            for name in dirs:
                _clear(os.path.join(base, name))

    def _onerror(func, node, exc):
        _clear(node)
        try:
            func(node)
        except OSError as e:
            if len(failed) < 8:
                failed.append(node)
                _log("[删除] 无法删除: %s (%s)" % (node, e))

    def _attempt(target):
        try:
            _walk_clear(target)
        except OSError as e:
            _log("[删除] 遍历清理告警: %s" % e)
        kwargs = ({"onexc": _onerror} if sys.version_info >= (3, 12)
                  else {"onerror": _onerror})
        try:
            shutil.rmtree(target, **kwargs)
        except OSError as e:
            _log("[删除] rmtree 告警: %s" % e)

    sep = os.sep
    target = path
    if os.name == "nt":
        ap = os.path.abspath(path)
        if not ap.startswith(sep + sep + "?" + sep):
            if ap.startswith(sep + sep):
                ap = sep + sep + "?" + sep + "UNC" + sep + ap[2:]
            else:
                ap = sep + sep + "?" + sep + ap
        target = ap

    for attempt in range(1, 4):
        if not os.path.exists(path):
            break
        _attempt(target)
        if os.path.exists(path) and attempt < 3:
            _log("[删除] 第 %d 次未清空, 0.4s 后重试..." % attempt)
            _t.sleep(0.4)

    if os.path.exists(path) and os.name == "nt":
        _log("[删除] 尝试 cmd rmdir /s /q 兜底...")
        try:
            subprocess.run(["cmd", "/c", 'rmdir /s /q "%s"' % path],
                           capture_output=True, text=True, errors="replace",
                           timeout=180, creationflags=CREATE_NO_WINDOW)
        except Exception as e:
            _log("[删除] cmd rmdir 异常: %s" % e)

    if os.path.exists(path):
        _log("[删除] 失败: 仍有残留(前几项已列出) " + path)
        raise OSError("部分文件无法删除(可能被占用或权限不足): " + path)
    _log("[删除] 完成: " + path)


def get_version(cmd, timeout=8):
    # 版本命令输出首行; 命令缺失/超时/失败返回 None(展示为"未安装")。
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                           timeout=timeout, creationflags=CREATE_NO_WINDOW)
        if r.stdout or r.stderr:
            return (r.stdout or r.stderr or "").strip().splitlines()[0]
    except Exception:
        # 命令不存在/超时等一律降级为 None, 由 UI 显示占位
        pass
    return None


def tool_versions(tools):
    # tools: [(key, name, cmd), ...] -> {key: 版本行或 None}; 逐个执行, 缺失不中断。
    return {key: get_version(cmd) for key, _name, cmd in tools}


def missing_tools(tools=("git", "node", "npm", "pnpm")):
    # 返回 PATH 中缺失的工具名列表(安装流预检用)。
    return [t for t in tools if not shutil.which(t)]


def pnpm_env():
    # pnpm 要求全局 bin 目录在 PATH 中, 自动注入避免报错; 返回新的 env dict。
    env = dict(os.environ)
    pnpm_bin = os.path.join(os.environ.get("LOCALAPPDATA", ""), "pnpm", "bin")
    if pnpm_bin and pnpm_bin not in env.get("PATH", ""):
        env["PATH"] = env.get("PATH", "") + os.pathsep + pnpm_bin
    return env


def run_capture(cmd, timeout=600):
    # 捕获式执行(无主界面时的兜底路径): 返回 (ok, 尾部输出)。
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                           timeout=timeout, creationflags=CREATE_NO_WINDOW)
        tail = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()[-600:]
        return r.returncode == 0, tail
    except Exception as e:
        return False, str(e)


def test_ssh(host, user, port="22"):
    # SSH 免密连通测试(ssh BatchMode + echo ok)。契约: {"ok": bool, "detail": str, "err": ""};
    # detail 为失败原因片段(给 UI 拼 ❌ 文案), 成功为空; err 仅在探测本身异常时非空。
    host = str(host or "").strip()
    user = str(user or "").strip()
    port = str(port or "").strip() or "22"
    if not host or not user:
        return {"ok": False, "detail": "请先填服务器 IP 和用户名", "err": ""}
    try:
        ssh = shutil.which("ssh")
        if not ssh:
            raise FileNotFoundError("ssh 不在 PATH 中")
        r = subprocess.run(
            [ssh, "-o", "BatchMode=yes", "-o", "ConnectTimeout=6",
             "-o", "StrictHostKeyChecking=accept-new",
             "-p", port, user + "@" + host, "echo ok"],
            capture_output=True, text=True, errors="replace", timeout=18,
            creationflags=CREATE_NO_WINDOW)
        if r.returncode == 0:
            return {"ok": True, "detail": "", "err": ""}
        detail = (r.stderr or r.stdout or "").strip().replace("\n", " ")[:180]
        return {"ok": False, "detail": detail, "err": ""}
    except Exception as e:
        return {"ok": False, "detail": str(e)[:140], "err": ""}


def _bridge(events):
    # dshctl.stream_cmd 的 events("log", (text, tag)) -> 本模块 events("log", text)
    def cb(kind, payload):
        if kind == "log":
            events("log", payload[0])
    return cb


def install_dsh(events=None, url=None, target=None, version=""):
    # 一键安装 dsh: 环境预检 -> git clone -> (指定版本时 checkout) -> pnpm install -> pnpm build
    # -> 写 config.dash_repo(指定版本时同时写 dsh_version_pin)。
    # 契约: {"msg", "err", "target", "version"}; 任一步失败立即返回(已执行的步骤不回滚)。
    # version 留空=跟随默认分支。
    url = (url or "").strip()
    target = (target or "").strip() or os.path.join(os.path.expanduser("~"), "dsh")
    version = (version or "").strip()

    def step(n, text):
        if events:
            events("step", (n, text))

    def line(text):
        if events:
            events("log", text)

    if not url:
        return {"msg": "", "err": "请填写 dsh 的 git 仓库地址", "target": target}
    # 0) 环境预检
    need = missing_tools()
    if need:
        line("[安装] 缺少依赖: " + ", ".join(need))
        line("  请先安装 Node.js(含 npm) 和 git; 然后 npm install -g pnpm")
        return {"msg": "", "err": "缺少依赖: " + ", ".join(need), "target": target}
    # 流式执行经 dshctl.stream_cmd(超时/kill/找不到命令统一处理, 超时取用户 config)
    ctl = DshCtl(dsh_config.load_derived())
    bridge = _bridge(events)
    # 1) clone(完整克隆, 便于后续 update 的 git pull)
    if os.path.isdir(target) and os.listdir(target):
        line("[安装] 目录已存在且有内容, 跳过 clone: " + target)
    else:
        step(1, "步骤 1/3: git clone ...")
        if not ctl.stream_cmd(["git", "clone", url, target], events=bridge):
            return {"msg": "", "err": "git clone 失败(详见安装日志)", "target": target}
    # 1.5) 指定版本: 拉 tags 并切换到目标 tag(留空则跟随默认分支)
    if version:
        line("[安装] 切换到指定版本: " + version)
        if not ctl.stream_cmd(["git", "fetch", "--tags", "--prune"], cwd=target, events=bridge):
            return {"msg": "", "err": "获取 tags 失败(详见安装日志)", "target": target}
        if not ctl.stream_cmd(["git", "checkout", version], cwd=target, events=bridge):
            return {"msg": "", "err": "切换到版本 %s 失败(详见安装日志)" % version,
                    "target": target}
    # 2) install
    step(2, "步骤 2/3: pnpm install")
    if not ctl.stream_cmd(["pnpm.cmd", "install"], cwd=target, events=bridge):
        return {"msg": "", "err": "pnpm install 失败(详见安装日志)", "target": target}
    # 3) build
    step(3, "步骤 3/3: pnpm run build")
    if not ctl.stream_cmd(["pnpm.cmd", "run", "build"], cwd=target, events=bridge):
        return {"msg": "", "err": "pnpm run build 失败(详见安装日志)", "target": target}
    # 4) 写 config.dash_repo(core.config: DSH_AIO_CONFIG 感知 + 写前 .bak)
    step(4, "写 config.json(dash_repo)")
    try:
        cfg = dsh_config.load_config()
        cfg["dash_repo"] = target
        if version:
            cfg["dsh_version_pin"] = version
        else:
            cfg.pop("dsh_version_pin", None)
        if dsh_config.save_config(cfg):
            line("[安装] 已把 dash_repo 写入 config.json, 重启后生效。")
        else:
            line("[安装] 无法写 config.json(权限?), 请在配置向导里手动设置 dash_repo。")
    except Exception as e:
        line("[安装] 写 config 失败: " + str(e))
    msg = "dsh 安装完成 目标目录: " + target
    if version:
        msg += "(版本 " + version + ")"
    return {"msg": msg, "err": "", "target": target, "version": version}


def uninstall_dsh(events=None, keep_data=True):
    # 卸载本机 dsh(与 install_dsh 对应的纯业务, 零 Qt): 停 web -> 删源码目录(dash_repo)
    # -> 清 config.dash_repo; keep_data=False 时再删 ~/.dsh 数据目录。
    # 契约: {"msg", "err", "removed_repo": bool, "removed_data": bool, "data_dir": 数据目录}
    # 危险操作: 本函数只执行, 由 UI 层先弹强确认框(逐条列出将删的具体路径)。
    # 删除守卫: 仅当路径非空、绝对、且确实存在时才删, 绝不手拼/通配, 防误删用户关键目录。
    def step(n, text):
        if events:
            events("step", (n, text))

    def line(text):
        if events:
            events("log", text)

    cfg = dsh_config.load_config()
    repo = (cfg.get("dash_repo") or "").strip()
    ctl = DshCtl(dsh_config.load_derived())

    removed_repo = False
    removed_data = False
    data_dir = ""

    # 0) 停 web(先停再用, 避免删到被占用/运行中的目录)
    step(1, "步骤 1/3: 停止本机 dsh web")
    ctl.stop_dsh(events=_bridge(events))

    # 1) 删源码目录
    if repo and os.path.isabs(repo) and os.path.isdir(repo):
        step(2, "步骤 2/3: 删除源码目录 " + repo)
        line("[卸载] 删除源码目录: " + repo)
        try:
            _rmtree_force(repo, log=line)
            removed_repo = True
        except Exception as e:
            line("[卸载] 删除源码目录失败: " + str(e))
            return {"msg": "", "err": "删除源码目录失败: %s" % e,
                    "removed_repo": False, "removed_data": False, "data_dir": ""}
    else:
        line("[卸载] 未检测到 dsh 源码目录(跳过): " + (repo or "config 未设置 dash_repo"))

    # 2) 清 config.dash_repo
    step(3, "步骤 3/3: 清空 config.json 的 dash_repo")
    try:
        cfg2 = dsh_config.load_config()
        if cfg2.get("dash_repo"):
            cfg2["dash_repo"] = ""
            if dsh_config.save_config(cfg2):
                line("[卸载] 已清空 config.json 的 dash_repo(写前已 .bak)。")
    except Exception as e:
        line("[卸载] 清 config.dash_repo 失败(请手动在配置向导里清): " + str(e))

    # 3) 数据目录(仅"彻底卸载"删)
    if not keep_data:
        from core import data as dsh_data
        data_dir = dsh_data.dsh_home()
        if os.path.isabs(data_dir) and os.path.isdir(data_dir) \
                and os.path.abspath(data_dir) != os.path.abspath(os.path.expanduser("~")):
            step(4, "删除数据目录 ~/.dsh")
            line("[卸载] 删除数据目录: " + data_dir)
            try:
                _rmtree_force(data_dir, log=line)
                removed_data = True
            except Exception as e:
                line("[卸载] 删除数据目录失败: " + str(e))
                return {"msg": "", "err": "删除数据目录失败: %s" % e, "removed_repo": removed_repo,
                        "removed_data": False, "data_dir": data_dir}
        else:
            line("[卸载] 未检测到数据目录(跳过): " + data_dir)

    parts = []
    if removed_repo:
        parts.append("源码目录已删除")
    if not keep_data and removed_data:
        parts.append("数据目录(~/.dsh)已删除")
    if not parts:
        parts = ["未检测到已安装的 dsh(无可删)"]
    return {"msg": "dsh 卸载完成: " + "; ".join(parts), "err": "", "removed_repo": removed_repo,
            "removed_data": removed_data, "data_dir": data_dir}


__all__ = ["get_version", "tool_versions", "missing_tools", "pnpm_env",
           "run_capture", "test_ssh", "install_dsh", "uninstall_dsh"]
