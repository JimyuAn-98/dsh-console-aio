# -*- coding: utf-8 -*-
# test_tunnel_planner.py - 隧道规划器纯函数单测(占用探测打桩, 不绑真实端口)。

import pytest

from core import tunnel_mgr as dsh_tunnels
from core import tunnel_planner as dsh_planner

_CFG = {"dash_port": 3080, "lab_port": 3090, "reverse_port": 8091,
        "forward_ports": [8090, 8022, 8091], "local_ports": [3080],
        "ssh_server": "1.2.3.4", "lab_server": "10.1.12.204"}


def test_snapshot_and_apply_roundtrip():
    plan = dsh_planner.snapshot_plan(_CFG, "在家")
    assert plan["forward_ports"] == [8090, 8022, 8091]
    cfg2 = dsh_planner.apply_plan({"dash_port": 3080}, plan)
    assert cfg2["forward_ports"] == [8090, 8022, 8091]
    assert cfg2["reverse_port"] == 8091
    assert cfg2["tunnel_plans_active"] == "在家"
    assert cfg2["dash_port"] == 3080          # 非方案字段不被动


def test_upsert_delete_find():
    cfg = {}
    cfg = dsh_planner.upsert_plan(cfg, {"name": "a", "forward_ports": [1]})
    cfg = dsh_planner.upsert_plan(cfg, {"name": "b", "forward_ports": [2]})
    cfg = dsh_planner.upsert_plan(cfg, {"name": "a", "forward_ports": [3]})   # 同名替换
    names = [p["name"] for p in dsh_planner.load_plans(cfg)]
    assert names == ["b", "a"]
    assert dsh_planner.find_plan(cfg, "a")["forward_ports"] == [3]
    cfg = dsh_planner.delete_plan(cfg, "a")
    assert dsh_planner.find_plan(cfg, "a") is None
    assert dsh_planner.load_plans({"tunnel_plans": "垃圾"}) == []   # 脏结构不致命


def test_validate_conflicts(monkeypatch):
    monkeypatch.setattr(dsh_tunnels, "port_free", lambda p: True)
    plan = {"name": "x", "forward_ports": [8090, 8090, 3080, 443],
            "reverse_port": 8090, "lab_port": 3090, "local_ports": []}
    issues = dsh_planner.validate_plan(plan, _CFG)
    msgs = " ; ".join(i["msg"] for i in issues)
    levels = {i["msg"]: i["level"] for i in issues}
    assert any("重复" in m for m in levels if "8090" in m)
    assert any(i["level"] == "error" and "dsh web" in i["msg"] for i in issues)   # 3080 撞 web
    assert any(i["level"] == "error" and "中转主机上冲突" in i["msg"] for i in issues)  # 反向撞转发
    assert any(i["level"] == "warn" and "特权端口" in i["msg"] for i in issues)   # 443


def test_validate_occupied_warn(monkeypatch):
    monkeypatch.setattr(dsh_tunnels, "port_free", lambda p: p != 8090)
    plan = {"name": "x", "forward_ports": [8090], "reverse_port": 8091,
            "lab_port": 3090, "local_ports": []}
    issues = dsh_planner.validate_plan(plan, _CFG)
    assert any(i["level"] == "warn" and "已被占用" in i["msg"] for i in issues)
    clean = {"name": "y", "forward_ports": [8092], "reverse_port": 8091,
             "lab_port": 3090, "local_ports": []}
    assert dsh_planner.validate_plan(clean, _CFG) == []


def test_self_check_states(monkeypatch):
    monkeypatch.setattr(dsh_tunnels, "tcp_ok", lambda host, port: port == 8090)
    monkeypatch.setattr(dsh_tunnels, "tunnels_snapshot",
                        lambda base_dir: {"dsh-tunnel": {"pid": 1, "alive": True}})
    rows = dsh_planner.self_check(_CFG, base_dir=".")
    by_name = {n: (s, d) for n, s, d in rows}
    assert by_name["dsh-tunnel(中继转发)"][0] is True
    assert "进程 存活" in by_name["dsh-tunnel(中继转发)"][1]
    assert by_name["connect-lab-dsh(实验室)"][0] is False    # 已配置但 3090 探测不通
    assert by_name["dsh-tunnel-reverse(反向)"][0] is None    # 无 pid 记录 -> 未配置
