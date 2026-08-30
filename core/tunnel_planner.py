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
PLAN_FIELDS = ("forward_ports", "reverse_port", "lab_port", "local_ports")


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
    out["tunnel_plans"] = [p for p in load_plans(cfg) if p.get("name") != name]
    return out


def snapshot_plan(cfg, name):
    # 从当前配置抓一份拓扑快照
    d = derived(cfg or {})
    return {"name": str(name),
            "forward_ports": list(d["forward_ports"]),
            "reverse_port": d["reverse_port"],
            "lab_port": d["lab_port"],
            "local_ports": list(d["local_ports"])}


def apply_plan(cfg, plan):
    # 方案字段写回 config 副本(未知字段忽略); 调用方 save + 热重载
    out = dict(cfg or {})
    for f in PLAN_FIELDS:
        if f in (plan or {}):
            out[f] = plan[f]
    out["tunnel_plans_active"] = (plan or {}).get("name") or ""
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
    # 校验方案: 返回 [{"level": "error"/"warn", "msg": str}]。error=启动会失败/配置
    # 冲突, warn=建议检查。占用探测为本机 bind 一次(毫秒级, 只读)。
    issues = []
    d = derived(cfg or {})
    fwd = _ports_of((plan or {}).get("forward_ports"))
    rev = (plan or {}).get("reverse_port")
    lab = (plan or {}).get("lab_port")
    loc = _ports_of((plan or {}).get("local_ports"))
    dash = d["dash_port"]

    def bad_port(p):
        return p is None or not (1 <= p <= 65535)

    # 1) 端口合法性与重复
    seen = {}
    for p in fwd:
        if bad_port(p):
            issues.append({"level": "error", "msg": "中继转发端口含非法值: %r" % (p,)})
            continue
        seen[p] = seen.get(p, 0) + 1
    for p, n in sorted(seen.items()):
        if n > 1:
            issues.append({"level": "error", "msg": "中继转发端口 %d 重复了 %d 次" % (p, n)})
    if not fwd:
        issues.append({"level": "warn", "msg": "中继转发端口列表为空(dsh-tunnel 无事可做)"})

    # 2) 本机撞车: 转发端口是 ssh -L 的本机绑定端, 不能撞本机服务(dsh web)与实验室映射
    for p in fwd:
        if p == dash:
            issues.append({"level": "error",
                           "msg": "转发端口 %d 与本机 dsh web 端口冲突(本机无法绑定)" % p})
        if p == lab and lab:
            issues.append({"level": "error",
                           "msg": "转发端口 %d 与实验室映射端口冲突(本机无法绑定)" % p})
        if 0 < p < 1024:
            issues.append({"level": "warn", "msg": "转发端口 %d 是特权端口(<1024), Windows 一般可用但目标主机可能受限" % p})

    # 3) 中继侧撞车: 反向端口与转发端口同在公网中转主机上监听, 重复即冲突
    if not bad_port(rev) and rev in fwd:
        issues.append({"level": "error",
                       "msg": "反向端口 %d 与中继转发端口重复(中转主机上冲突)" % rev})
    if not bad_port(lab) and lab == dash:
        issues.append({"level": "error", "msg": "实验室端口 %d 与 dsh web 端口相同" % lab})

    # 4) 监测端口: 重复警告
    lseen = {}
    for p in loc:
        if not bad_port(p):
            lseen[p] = lseen.get(p, 0) + 1
    for p, n in sorted(lseen.items()):
        if n > 1:
            issues.append({"level": "warn", "msg": "监测端口 %d 重复了 %d 次" % (p, n)})

    # 5) 本机占用实测(仅转发/实验室映射的本机绑定端口; 已被占则隧道启动会失败)
    for p in fwd + ([lab] if lab else []):
        if not bad_port(p) and not dsh_tunnels.port_free(p):
            issues.append({"level": "warn",
                           "msg": "本机端口 %d 当前已被占用(若对应隧道未运行, 启动会失败)" % p})
    return issues


# ── 启动自检(本机只读探测; 反向隧道本机不监听, 只查进程) ──
def self_check(cfg, base_dir):
    # 返回 [(名称, 状态, 详情)]: 状态 True=通 / False=不通 / None=未配置
    d = derived(cfg or {})
    snap = dsh_tunnels.tunnels_snapshot(base_dir)
    out = []

    def one(name, key, port):
        rec = snap.get(key) or {}
        alive = rec.get("alive")
        if port is None:
            if rec:
                return (name, bool(alive), "进程 %s" % ("存活" if alive else "已退出"))
            return (name, None, "未配置")
        online = dsh_tunnels.tcp_ok("127.0.0.1", port)
        detail = "端口 %d %s" % (port, "在线" if online else "不通")
        if rec:
            detail += " | 进程 %s" % ("存活" if alive else "已退出")
        return (name, online, detail)

    out.append(one("dsh-tunnel(中继转发)", "dsh-tunnel",
                   d["forward_ports"][0] if d["forward_ports"] else None))
    out.append(one("connect-lab-dsh(实验室)", "connect-lab-dsh",
                   d["lab_port"] if d["lab_server"] else None))
    out.append(one("dsh-tunnel-reverse(反向)", "dsh-tunnel-reverse", None))
    return out
