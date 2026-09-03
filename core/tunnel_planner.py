# -*- coding: utf-8 -*-
# core/tunnel_planner.py - 隧道规划器纯函数层(零 Qt): 方案/校验/应用/启动自检。
#
# 模型(2026-08-30 T1+T2 拍板): 「方案」= config.json "tunnel_plans" 里的一份命名拓扑
# 快照(forward_ports/reverse_port/lab_port/local_ports)。**应用方案 = 把字段写回
# config 顶层并热重载** —— 引擎(TunnelManager)/卡片/监控继续读标准字段, 单一代码
# 事实源, 不另立第二套拓扑结构; 多套拓扑 = 多份快照一键切换。
#
# 拓扑字段的具体编辑仍走设置页端口表(唯一编辑器, 规划器不重复造表); 本模块负责
# 快照/校验/应用/自检。全部本机只读操作(port_free bind 探测/tcp_ok), 不发起 SSH。

from core import tunnel_mgr as dsh_tunnels
from core.config import derived

# 方案快照覆盖的字段(应用时写回 config 顶层)
PLAN_FIELDS = ("tunnels",)


# ── 方案存取(纯函数, cfg 进出) ──
def load_plans(cfg):
    p = (cfg or {}).get("tunnel_plans")
    if not isinstance(p, list):
        return []
    return [x for x in p if isinstance(x, dict) and str(x.get("name") or "").strip()]


def find_plan(cfg, name):
    for p in load_plans(cfg):
        if p.get("name") == name:
            return p
    return None


def upsert_plan(cfg, plan):
    # 按 name 替换或追加, 返回新 cfg 副本(调用方负责 save)
    out = dict(cfg or {})
    plans = [p for p in load_plans(cfg) if p.get("name") != plan.get("name")]
    plans.append(dict(plan or {}))
    out["tunnel_plans"] = plans
    return out


def delete_plan(cfg, name):
    out = dict(cfg or {})
    plans = [p for p in load_plans(cfg) if p.get("name") != name]
    out["tunnel_plans"] = plans
    if out.get("tunnel_plans_active") == name:
        out["tunnel_plans_active"] = plans[0]["name"] if plans else ""
    return out


def snapshot_plan(cfg, name):
    # 从当前配置抓一份拓扑快照(含全量 dynamic tunnels)
    d = derived(cfg or {})
    return {
        "name": str(name),
        "tunnels": list(d.get("tunnels") or []),
    }


def apply_plan(cfg, plan):
    # 方案字段写回 config 副本(未知字段忽略); 调用方 save + 热重载
    out = dict(cfg or {})
    if "tunnels" in (plan or {}):
        out["tunnels"] = list(plan["tunnels"])
    else:
        from core.config import normalize_tunnels
        out["tunnels"] = normalize_tunnels(plan)
    out["tunnel_plans_active"] = (plan or {}).get("name") or ""
    # 清理老旧历史隧道字段，确保由新拓扑纯动态派生
    for legacy_key in ("local_ports", "remote_tunnels", "forward_ports", "reverse_port", "lab_port", "lab_server", "lab_user"):
        out.pop(legacy_key, None)
    return out


# ── 校验(纯函数 + 本机 bind 探测) ──
def _ports_of(v):
    # 宽松取整数端口: 非法项原样带出由 range 检查报错
    out = []
    for p in (v or []):
        try:
            out.append(int(p))
        except (TypeError, ValueError):
            out.append(None)
    return out


def validate_plan(plan, cfg):
    # 校验方案: 返回 [{"level": "error"/"warn", "msg": str}]。
    issues = []
    d = derived(cfg or {})
    dash = d.get("dash_port") or 3080

    def bad_port(p):
        return p is None or not (1 <= p <= 65535)

    # 1. 动态 tunnels 校验
    tunnels = (plan or {}).get("tunnels")
    if isinstance(tunnels, list):
        if not tunnels:
            issues.append({"level": "warn", "msg": "方案中隧道列表为空"})
        local_seen = {}
        remote_rev_seen = {}
        for tun in tunnels:
            tname = tun.get("name") or tun.get("id") or "未命名隧道"
            mode = tun.get("mode") or "forward"
            host = tun.get("host") or ""
            user = tun.get("user") or ""
            if tun.get("enabled", True) and (not host or not user):
                issues.append({"level": "warn", "msg": "「%s」已启用但未配置目标主机或用户名" % tname})

            forwards = tun.get("forwards") or []
            if not forwards:
                issues.append({"level": "warn", "msg": "「%s」未配置任何端口映射规则" % tname})

            for fw in forwards:
                lp = fw.get("local_port") if isinstance(fw, dict) else (fw[0] if len(fw) >= 1 else None)
                rp = fw.get("remote_port") if isinstance(fw, dict) else (fw[2] if len(fw) >= 3 else None)
                if mode == "forward":
                    if bad_port(lp):
                        issues.append({"level": "error", "msg": "「%s」本机访问端口非法: %r" % (tname, lp)})
                    if bad_port(rp):
                        issues.append({"level": "error", "msg": "「%s」远端服务端口非法: %r" % (tname, rp)})
                    if not bad_port(lp):
                        if lp == dash:
                            issues.append({"level": "error", "msg": "「%s」本机访问端口 %d 与本机 dsh web 端口冲突" % (tname, lp)})
                        local_seen[lp] = local_seen.get(lp, []) + [tname]
                else:  # mode == "reverse"
                    exposed_port = lp
                    local_svc_port = rp
                    if bad_port(exposed_port):
                        issues.append({"level": "error", "msg": "「%s」公网暴露端口非法: %r" % (tname, exposed_port)})
                    if bad_port(local_svc_port):
                        issues.append({"level": "error", "msg": "「%s」本机服务端口非法: %r" % (tname, local_svc_port)})
                    if not bad_port(exposed_port):
                        key = (host, exposed_port)
                        remote_rev_seen[key] = remote_rev_seen.get(key, []) + [tname]

        for lp, names in local_seen.items():
            if len(names) > 1:
                issues.append({"level": "error", "msg": "本机访问端口 %d 在多条正向隧道中重复绑定: %s" % (lp, ", ".join(names))})
            elif not dsh_tunnels.port_free(lp):
                issues.append({"level": "warn", "msg": "本机访问端口 %d 当前已被系统其他程序占用" % lp})

        for (host, exp_port), names in remote_rev_seen.items():
            if len(names) > 1:
                issues.append({"level": "error", "msg": "公网暴露端口 %d 在服务器 %s 上被多条反向隧道重复暴露: %s" % (exp_port, host or "VPS", ", ".join(names))})

    # 2. 标量字段完整校验(仅在方案未配置动态 tunnels 时回退兼容旧版方案与旧单测)
    if not isinstance(tunnels, list):
        fwd = _ports_of((plan or {}).get("forward_ports"))
        rev = (plan or {}).get("reverse_port")
        lab = (plan or {}).get("lab_port")
        loc = _ports_of((plan or {}).get("local_ports"))

        if fwd:
            seen = {}
            for p in fwd:
                if bad_port(p):
                    issues.append({"level": "error", "msg": "中继转发端口含非法值: %r" % (p,)})
                    continue
                seen[p] = seen.get(p, 0) + 1
            for p, n in sorted(seen.items()):
                if n > 1:
                    issues.append({"level": "error", "msg": "中继转发端口 %d 重复了 %d 次" % (p, n)})

            for p in fwd:
                if p == dash:
                    issues.append({"level": "error",
                                   "msg": "转发端口 %d 与本机 dsh web 端口冲突(本机无法绑定)" % p})
                if p == lab and lab:
                    issues.append({"level": "error",
                                   "msg": "转发端口 %d 与实验室映射端口冲突(本机无法绑定)" % p})
                if 0 < p < 1024:
                    issues.append({"level": "warn", "msg": "转发端口 %d 是特权端口(<1024), Windows 一般可用但目标主机可能受限" % p})

            if not bad_port(rev) and rev in fwd:
                issues.append({"level": "error",
                               "msg": "反向端口 %d 与中继转发端口重复(中转主机上冲突)" % rev})
            if not bad_port(lab) and lab == dash:
                issues.append({"level": "error", "msg": "实验室端口 %d 与 dsh web 端口相同" % lab})

            for p in fwd + ([lab] if lab else []):
                if not bad_port(p) and not dsh_tunnels.port_free(p):
                    issues.append({"level": "warn",
                                   "msg": "本机端口 %d 当前已被占用(若对应隧道未运行, 启动会失败)" % p})

    return issues


# ── 启动自检(本机只读探测; 反向隧道本机不监听, 只查进程) ──
def self_check(cfg, base_dir, plan=None):
    # 启动自检: 探测当前生效配置或指定方案的连通性与进程状态
    # 返回 [(名称, 状态, 详情)]: 状态 True=在线 / False=异常 / None=未启动
    target = plan if plan is not None else (cfg or {})
    d = derived(target or {})
    snap = dsh_tunnels.tunnels_snapshot(base_dir)
    out = []

    tunnels = d.get("tunnels") or []
    if not tunnels:
        return [("无隧道配置", None, "方案中未配置任何 SSH 隧道")]

    for tun in tunnels:
        tid = tun.get("id") or "unknown"
        tname = tun.get("name") or tid
        mode = tun.get("mode") or "forward"
        rec = snap.get(tid) or {}
        alive = bool(rec.get("alive"))
        watch = tun.get("watch_port")
        if not watch and mode == "forward" and tun.get("forwards"):
            first_fw = tun["forwards"][0]
            watch = first_fw.get("local_port") if isinstance(first_fw, dict) else first_fw[0]

        if mode == "reverse":
            if alive:
                out.append((tname, True, "运行中 | 进程存活 (PID %s)" % rec.get("pid", "?")))
            elif rec:
                out.append((tname, False, "异常 | 进程已退出 (记录 PID %s)" % rec.get("pid", "?")))
            else:
                out.append((tname, None, "未启动"))
        else:
            if not watch:
                if alive:
                    out.append((tname, True, "运行中 | 进程存活"))
                else:
                    out.append((tname, None, "未启动"))
                continue

            online = dsh_tunnels.tcp_ok("127.0.0.1", watch, timeout=0.5)
            if online and alive:
                out.append((tname, True, "在线 | 端口 :%d 连通 · 进程存活" % watch))
            elif online and not alive:
                out.append((tname, False, "警告 | 端口 :%d 在线但无记录进程(可能被外部程序占用)" % watch))
            elif not online and alive:
                out.append((tname, False, "异常 | 进程存活但端口 :%d 未监听" % watch))
            else:
                out.append((tname, None, "未启动 | 端口 :%d 空闲" % watch))

    return out
