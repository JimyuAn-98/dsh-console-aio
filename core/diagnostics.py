# -*- coding: utf-8 -*-
# core/diagnostics.py - 一键诊断报告(纯 Python 零 Qt): 工具链版本 + 本机 dsh/端口探测
# + 隧道常驻进程存活 + 配置概览。报告文本用于外发求助/issue —— 隐私红线:
# 服务器地址/用户名一律打码, 仓库路径只取末级目录; config 本不含密钥明文(dsh 的
# apiKeyEnv 只引用环境变量名), 打码后可安全外发。
# 远程 SSH 主动探测刻意不做(诊断不发起任何远程连接, 报告只标注"远程未探测")。
# 探测均为本机只读操作(tcp 连接毫秒级 + tasklist), 由调用方(UI 页面自有线程)执行,
# 契约与 service._run_result_op 一致: collect(events, ...) -> dict。

import os
import platform
import shutil
import sys
import time

from core import env as dsh_env
from core import tunnel_mgr as dsh_tunnels
from core.config import derived

_TOOLS = ("git", "node", "npm", "pnpm")


# ── 脱敏(纯函数, 单测覆盖) ──
def mask_host(host):
    # IPv4 保前两段(可判断公网/内网), 其余 x.x; 域名保首标签; 空值显式标注
    if not host:
        return "(未配置)"
    parts = str(host).split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        return ".".join(parts[:2] + ["x", "x"])
    return parts[0] + ".***"


def mask_user(user):
    if not user:
        return "(未配置)"
    return str(user)[0] + "***"


def _tool_versions():
    # 逐个探测工具链版本; 缺失为 None。shutil.which 在 Windows 上按 PATHEXT 找到
    # npm.cmd/pnpm.cmd, 规避 subprocess 找不到 .cmd shim 的问题。
    out = {}
    for name in _TOOLS:
        exe = shutil.which(name)
        out[name] = dsh_env.get_version([exe, "--version"]) if exe else None
    return out


def _os_line():
    if sys.platform == "win32":
        try:
            return "Windows build %d" % sys.getwindowsversion().build
        except Exception:
            return "Windows (版本未知)"   # getwindowsversion 仅 win32, 失败不致命
    return platform.platform()


def collect(events=None, cfg=None, app_version="", base_dir="."):
    # 汇集诊断数据(只读本地, 不发起 SSH/远程连接); 返回报告 dict, render 负责转文本。
    d = derived(cfg or {})

    def probe(port):
        return {"port": port, "online": dsh_tunnels.tcp_ok("127.0.0.1", port)}

    probe_pts = [p[0] for p in (d.get("local_ports") or []) if p and p[0] != d.get("dash_port")]
    ports = [probe(p) for p in probe_pts if p]
    deployments = [x for x in (cfg or {}).get("deployments") or [] if isinstance(x, dict)]
    lab_srv = d.get("lab_server") or (deployments[0].get("host") if deployments else "")
    lab_usr = d.get("lab_user") or (deployments[0].get("user") if deployments else "")
    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "app_version": app_version,
        "mode": "打包" if getattr(sys, "frozen", False) else "源码",
        "python": platform.python_version(),
        "os": _os_line(),
        "tools": _tool_versions(),
        "local_name": d["local_name"],
        "relay": {"name": d["ssh_name"], "host": mask_host(d.get("ssh_server", "")),
                  "user": mask_user(d.get("ssh_user", "")), "configured": bool(d.get("ssh_server"))},
        "lab": {"name": d["lab_name"], "host": mask_host(lab_srv),
                "user": mask_user(lab_usr), "configured": bool(lab_srv)},
        "dsh_web": probe(d["dash_port"]),
        "ports": ports,
        "tunnels_configured": len(d.get("tunnels") or []),
        "tunnels": dsh_tunnels.tunnels_snapshot(base_dir),
        "deployments": len(deployments),
        "dash_repo_tail": os.path.basename((d["dash_repo"] or "").replace("\\", "/").rstrip("/")) or "(未配置)",
        "local_ports_count": len(d.get("local_ports") or []),
    }


def render(report):
    # 报告 dict -> 可外发文本(分节, 纯 ASCII 符号 + 中文)
    r = report or {}
    lines = ["====== dsh-console-aio 诊断报告 ======",
             "生成时间: %s" % r.get("generated_at", ""),
             "应用: v%s (%s 模式) | Python %s | %s"
             % (r.get("app_version", "?"), r.get("mode", "?"),
                r.get("python", "?"), r.get("os", "?"))]

    tools = r.get("tools") or {}
    missing = [k for k, v in tools.items() if not v]
    lines.append("[工具链] " + " | ".join(
        "%s %s" % (k, tools.get(k) or "未安装") for k in _TOOLS)
        + (" | 缺失: %s" % ", ".join(missing) if missing else ""))

    web = r.get("dsh_web") or {}
    lines.append("[本机 dsh] web :%s %s"
                 % (web.get("port", "?"), "在线" if web.get("online") else "离线/未启动"))

    ports = r.get("ports") or []
    if ports:
        lines.append("[端口探测] " + " | ".join(
            ":%s %s" % (p.get("port"), "在线" if p.get("online") else "离线")
            for p in ports))

    tun = r.get("tunnels") or {}
    if tun:
        lines.append("[隧道进程] " + " | ".join(
            "%s(pid %s, %s)" % (k, v.get("pid"), "存活" if v.get("alive") else "已退出")
            for k, v in sorted(tun.items())))
    else:
        lines.append("[隧道进程] 无常驻记录(tunnel-pids.json 不存在或为空)")
    lines.append("[隧道配置] 已配置 %s 条 | 本机监测端口 %s 个 | 部署清单 %s 份"
                 % (r.get("tunnels_configured", 0), r.get("local_ports_count", 0),
                    r.get("deployments", 0)))

    relay, lab = r.get("relay") or {}, r.get("lab") or {}

    def _machine(info):
        if not info.get("configured"):
            return "未配置"
        return "%s(用户 %s)" % (info.get("host"), info.get("user"))
    lines.append("[机器] 本机=%s | %s=%s | %s=%s"
                 % (r.get("local_name", "?"),
                    relay.get("name", "中转"), _machine(relay),
                    lab.get("name", "实验室"), _machine(lab)))
    lines.append("[仓库] 末级目录: %s" % r.get("dash_repo_tail", "(未配置)"))
    lines.append("[说明] 远程 SSH 未主动探测(诊断不发起远程连接); "
                 "地址/用户名已打码, 本报告可安全外发。")
    return "\n".join(lines)
