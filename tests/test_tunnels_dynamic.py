# -*- coding: utf-8 -*-
# tests/test_tunnels_dynamic.py - 通用动态隧道架构与向导助手测试。

import os
import json
import pytest

from core import config as dsh_config
from core.tunnels import TunnelManager
from core import tunnel_planner as dsh_planner


def test_normalize_tunnels_empty_cfg():
    cfg = {
        "ssh_server": "1.2.3.4",
        "ssh_user": "root",
        "local_name": "我的电脑",
        "forward_ports": [8090, 8022, 8091],
        "lab_port": 3090,
        "reverse_port": 8091,
    }
    tunnels = dsh_config.normalize_tunnels(cfg)
    assert len(tunnels) == 3
    ids = [t["id"] for t in tunnels]
    assert "dsh-tunnel" in ids
    assert "connect-lab-dsh" in ids
    assert "dsh-tunnel-reverse" in ids

    # 检查正向中继端口
    tun_relay = next(t for t in tunnels if t["id"] == "dsh-tunnel")
    assert tun_relay["mode"] == "forward"
    assert tun_relay["host"] == "1.2.3.4"
    assert len(tun_relay["forwards"]) == 3
    assert tun_relay["forwards"][0]["local_port"] == 8090


def test_normalize_tunnels_custom_list():
    raw_tunnels = [
        {
            "id": "tun_custom_1",
            "name": "GPU集群隧道",
            "mode": "forward",
            "host": "gpu.cluster.com",
            "user": "ubuntu",
            "ssh_port": 2222,
            "forwards": [
                {"local_port": 6006, "remote_host": "127.0.0.1", "remote_port": 6006, "desc": "TensorBoard"}
            ],
            "auto_restart": True,
            "enabled": True
        }
    ]
    cfg = {"tunnels": raw_tunnels}
    tunnels = dsh_config.normalize_tunnels(cfg)
    assert len(tunnels) == 1
    t = tunnels[0]
    assert t["id"] == "tun_custom_1"
    assert t["name"] == "GPU集群隧道"
    assert t["ssh_port"] == 2222
    assert t["forwards"][0]["local_port"] == 6006


def test_normalize_tunnels_explicit_empty_list():
    # 显式配置 tunnels 为 [] 时，不得回退合成 3 条默认隧道(允许清空隧道)
    cfg = {
        "ssh_server": "1.2.3.4",
        "tunnels": [],
        "forward_ports": [8090, 8022, 8091],
    }
    tunnels = dsh_config.normalize_tunnels(cfg)
    assert tunnels == []


def test_derived_dynamic_ports():
    cfg = {
        "dash_port": 3080,
        "tunnels": [
            {
                "id": "t1",
                "name": "隧道1",
                "mode": "forward",
                "host": "1.1.1.1",
                "user": "u",
                "forwards": [{"local_port": 9001, "remote_host": "127.0.0.1", "remote_port": 9001, "desc": "服务1"}]
            },
            {
                "id": "t2",
                "name": "隧道2",
                "mode": "reverse",
                "host": "1.1.1.1",
                "user": "u",
                "forwards": [{"local_port": 9002, "remote_host": "127.0.0.1", "remote_port": 3080, "desc": "服务2"}]
            }
        ]
    }
    d = dsh_config.derived(cfg)
    assert len(d["tunnels"]) == 2
    local_ports_list = [p[0] for p in d["local_ports"]]
    assert 3080 in local_ports_list
    assert 9001 in local_ports_list
    remote_ports_list = [p[0] for p in d["remote_tunnels"]]
    assert 9002 in remote_ports_list


def test_save_and_load_tunnels(tmp_path):
    p = str(tmp_path / "config.json")
    cfg = {"ssh_server": "1.2.3.4"}
    dsh_config.save_config(cfg, path=p)

    new_tunnels = [
        {
            "id": "t_test",
            "name": "测试隧道",
            "mode": "forward",
            "host": "10.0.0.1",
            "user": "test",
            "ssh_port": 22,
            "forwards": [{"local_port": 7000, "remote_host": "127.0.0.1", "remote_port": 7000}],
            "auto_restart": False,
            "enabled": True
        }
    ]
    ok = dsh_config.save_tunnels(new_tunnels, path=p)
    assert ok is True

    loaded = dsh_config.load_tunnels(path=p)
    assert len(loaded) == 1
    assert loaded[0]["id"] == "t_test"
    assert loaded[0]["name"] == "测试隧道"


def test_tunnel_manager_operations(tmp_path, monkeypatch):
    base_dir = str(tmp_path)
    cfg = {
        "tunnels": [
            {
                "id": "t1",
                "name": "隧道1",
                "mode": "forward",
                "host": "10.0.0.1",
                "user": "test",
                "forwards": [{"local_port": 7000, "remote_host": "127.0.0.1", "remote_port": 7000}],
                "enabled": True
            }
        ]
    }
    d = dsh_config.derived(cfg)
    mgr = TunnelManager(base_dir, d)
    assert len(mgr.list_tunnels()) == 1
    assert mgr.find_tunnel("t1") is not None

    # Mock Tunnel start / stop
    from core.tunnel_mgr import Tunnel
    started = []
    stopped = []

    def mock_start(self):
        started.append(self.key)
        return True

    def mock_stop(self):
        stopped.append(self.key)
        return 1

    monkeypatch.setattr(Tunnel, "start", mock_start)
    monkeypatch.setattr(Tunnel, "stop", mock_stop)

    ev_log = []
    events = lambda k, p: ev_log.append((k, p))

    mgr.start("t1", mode="start", events=events)
    assert "t1" in started

    mgr.stop("t1", events=events)
    assert "t1" in stopped

    mgr.start_all(events=events, persist_default=False)
    assert started.count("t1") == 2

    mgr.stop_all(events=events)
    assert stopped.count("t1") == 2


def test_tunnel_planner_dynamic_snapshot_and_validate():
    cfg = {
        "dash_port": 3080,
        "tunnels": [
            {
                "id": "t1",
                "name": "隧道1",
                "mode": "forward",
                "host": "1.1.1.1",
                "user": "root",
                "forwards": [{"local_port": 8090, "remote_host": "127.0.0.1", "remote_port": 8090}]
            },
            {
                "id": "t2",
                "name": "冲突隧道",
                "mode": "forward",
                "host": "2.2.2.2",
                "user": "root",
                "forwards": [{"local_port": 3080, "remote_host": "127.0.0.1", "remote_port": 3080}]
            }
        ]
    }
    snap = dsh_planner.snapshot_plan(cfg, "场景A")
    assert snap["name"] == "场景A"
    assert len(snap["tunnels"]) == 2

    # 校验方案: t2 绑定 3080 应该报错冲突
    issues = dsh_planner.validate_plan(snap, cfg)
    errs = [i for i in issues if i["level"] == "error"]
    assert any("冲突" in i["msg"] for i in errs)
