# -*- coding: utf-8 -*-
# tests/test_tunnel_lifecycle.py - 隧道生命周期治理、动态监控端口派生与自检三态测试。

import pytest

from core import config as dsh_config
from core import tunnel_planner as dsh_planner
from core.tunnels import TunnelManager
from core import tunnel_mgr as dsh_tunnels


def test_dynamic_monitor_ports_derivation():
    # 测试单一事实源: local_ports 和 remote_tunnels 始终动态跟随 tunnels 拓扑
    cfg = {
        "dash_port": 3080,
        "local_name": "本机电脑",
        "ssh_name": "中转VPS",
        "local_ports": [[9999, "旧端口", "不应存在"]],  # 模拟历史残留脏数据
        "tunnels": [
            {
                "id": "tun_custom_1",
                "name": "自定义正向隧道",
                "mode": "forward",
                "host": "1.2.3.4",
                "user": "root",
                "forwards": [
                    {"local_port": 7788, "remote_host": "127.0.0.1", "remote_port": 8877, "desc": "服务A"}
                ],
                "enabled": True
            },
            {
                "id": "tun_custom_2",
                "name": "自定义反向隧道",
                "mode": "reverse",
                "host": "1.2.3.4",
                "user": "root",
                "forwards": [
                    {"local_port": 6655, "remote_host": "127.0.0.1", "remote_port": 3080, "desc": "反向B"}
                ],
                "enabled": True
            }
        ]
    }
    d = dsh_config.derived(cfg)

    # 验证本地端口: 包含 3080 和 7788，旧的 9999 已被安全剔除
    loc_ports = [p[0] for p in d["local_ports"]]
    assert 3080 in loc_ports
    assert 7788 in loc_ports
    assert 9999 not in loc_ports

    # 验证远程端口: 包含 6655
    rem_ports = [p[0] for p in d["remote_tunnels"]]
    assert 6655 in rem_ports


def test_apply_plan_cleans_static_ports():
    # 验证 apply_plan 时清除顶层静态 local_ports/remote_tunnels，确保由新方案纯动态派生
    old_cfg = {
        "dash_port": 3080,
        "local_ports": [[8090, "老端口", ""]],
        "remote_tunnels": [[8091, "老反向", ""]],
    }
    new_plan = {
        "name": "方案B",
        "tunnels": [
            {
                "id": "tun_b",
                "name": "B隧道",
                "mode": "forward",
                "host": "2.2.2.2",
                "user": "user",
                "forwards": [{"local_port": 5544, "remote_host": "127.0.0.1", "remote_port": 5544}]
            }
        ]
    }
    applied = dsh_planner.apply_plan(old_cfg, new_plan)
    assert "local_ports" not in applied
    assert "remote_tunnels" not in applied
    assert applied["tunnel_plans_active"] == "方案B"

    # 派生后只包含 3080 和 5544
    d = dsh_config.derived(applied)
    loc_ports = [p[0] for p in d["local_ports"]]
    assert 3080 in loc_ports
    assert 5544 in loc_ports
    assert 8090 not in loc_ports


def test_stop_all_cleans_orphaned_pids(tmp_path, monkeypatch):
    # 验证 stop_all 会自动读取 tunnel-pids.json 中记录的所有活跃进程并全部终止
    killed_pids = []
    monkeypatch.setattr(dsh_tunnels, "_taskkill", lambda pid: killed_pids.append(pid))
    monkeypatch.setattr(dsh_tunnels, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(dsh_tunnels, "_kill_by_cmdline", lambda sig: 0)

    # 模拟在 base_dir 中写入了上一方案遗留的 PID
    fake_pids = {
        "tun_orphan": {
            "pid": 99991,
            "sig": "-L 7788:127.0.0.1:8877",
            "mode": "forward",
            "host": "1.2.3.4",
            "user": "root",
            "forwards": [[7788, "127.0.0.1", 8877]],
            "watch": 7788
        }
    }
    monkeypatch.setattr(dsh_tunnels, "_read_pids", lambda base_dir: dict(fake_pids))
    monkeypatch.setattr(dsh_tunnels, "_write_pids", lambda base_dir, data: True)

    # 当前配置为空拓扑
    mgr = TunnelManager(str(tmp_path), {"tunnels": []})
    stopped = mgr.stop_all()
    assert stopped >= 1
    assert 99991 in killed_pids


def test_self_check_three_states(monkeypatch):
    # 验证 self_check 正确区分三种状态: 🟢 在线(True) / ⚪ 未启动(None) / 🔴 异常(False)
    # 1. tun_online: 端口通 + 进程存活 -> True
    # 2. tun_unstarted: 端口不通 + 进程无 -> None
    # 3. tun_broken: 端口不通 + 进程存活 -> False
    fake_snap = {
        "tun_online": {"pid": 101, "alive": True},
        "tun_broken": {"pid": 102, "alive": True},
    }
    monkeypatch.setattr(dsh_tunnels, "tunnels_snapshot", lambda base_dir: fake_snap)
    monkeypatch.setattr(dsh_tunnels, "tcp_ok", lambda host, port, timeout=0.5: port == 8001)

    plan = {
        "name": "测试方案",
        "tunnels": [
            {
                "id": "tun_online", "name": "在线隧道", "mode": "forward",
                "forwards": [{"local_port": 8001, "remote_host": "127.0.0.1", "remote_port": 8001}]
            },
            {
                "id": "tun_unstarted", "name": "未启动隧道", "mode": "forward",
                "forwards": [{"local_port": 8002, "remote_host": "127.0.0.1", "remote_port": 8002}]
            },
            {
                "id": "tun_broken", "name": "异常隧道", "mode": "forward",
                "forwards": [{"local_port": 8003, "remote_host": "127.0.0.1", "remote_port": 8003}]
            },
        ]
    }

    rows = dsh_planner.self_check({}, base_dir=".", plan=plan)
    res = {n: (s, d) for n, s, d in rows}

    assert res["在线隧道"][0] is True
    assert "在线" in res["在线隧道"][1]

    assert res["未启动隧道"][0] is None
    assert "未启动" in res["未启动隧道"][1]

    assert res["异常隧道"][0] is False
    assert "异常" in res["异常隧道"][1]
