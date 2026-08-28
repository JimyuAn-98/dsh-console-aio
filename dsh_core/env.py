# -*- coding: utf-8 -*-
# dsh_core/env.py - 开发环境探测 / SSH 免密测试 / dsh 一键安装流(纯 Python, 零 Qt,
# 严禁 import PySide)。由 pyside/dialogs.py 的内联子进程业务下沉而来(ConfigDialog 的
# SSH 测试 / InstallDialog 的安装流 / EnvDialog 的版本探测与工具命令)。
#
# 通讯约定: install_dsh 遵循 events(kind, payload) 纯数据回调:
#   events("log", text)            逐行输出/说明
#   events("step", (n, text))      安装步骤进度(1..4)
# 其余函数为同步调用(对话框在其自有线程中调用, 线程归 UI 层所有 —— 阶段3 决策:
# 业务全部下沉本模块, 对话框线程保留, 详见 docs/UI_LAYERING.md)。
# 子进程一律 CREATE_NO_WINDOW + text=True errors="replace" + 超时(AGENTS.md 约定)。

import os
import shutil
import subprocess

from dsh_core import config as dsh_config
from dsh_core.dshctl import DshCtl

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW


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


def install_dsh(events=None, url=None, target=None):
    # 一键安装 dsh: 环境预检 -> git clone -> pnpm install -> pnpm build -> 写 config.dash_repo。
    # 契约: {"msg": 成功文案, "err": 中文失败文案, "target": 实际安装目录};
    # 任一步失败立即返回(已执行的步骤不回滚, 与旧版一致)。
    url = (url or "").strip()
    target = (target or "").strip() or os.path.join(os.path.expanduser("~"), "dsh")

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
    # 2) install
    step(2, "步骤 2/3: pnpm install")
    if not ctl.stream_cmd(["pnpm.cmd", "install"], cwd=target, events=bridge):
        return {"msg": "", "err": "pnpm install 失败(详见安装日志)", "target": target}
    # 3) build
    step(3, "步骤 3/3: pnpm run build")
    if not ctl.stream_cmd(["pnpm.cmd", "run", "build"], cwd=target, events=bridge):
        return {"msg": "", "err": "pnpm run build 失败(详见安装日志)", "target": target}
    # 4) 写 config.dash_repo(dsh_core.config: DSH_AIO_CONFIG 感知 + 写前 .bak)
    step(4, "写 config.json(dash_repo)")
    try:
        cfg = dsh_config.load_config()
        cfg["dash_repo"] = target
        if dsh_config.save_config(cfg):
            line("[安装] 已把 dash_repo 写入 config.json, 重启后生效。")
        else:
            line("[安装] 无法写 config.json(权限?), 请在配置向导里手动设置 dash_repo。")
    except Exception as e:
        line("[安装] 写 config 失败: " + str(e))
    return {"msg": "dsh 安装完成 目标目录: " + target, "err": "", "target": target}


__all__ = ["get_version", "tool_versions", "missing_tools", "pnpm_env",
           "run_capture", "test_ssh", "install_dsh"]
