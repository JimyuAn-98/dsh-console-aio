# -*- coding: utf-8 -*-
# test_diagnostics.py - 诊断报告/配置导出导入 纯单元测试(core 层零 Qt, 全部探测打桩)。

import json


def test_mask_host_and_user():
    from core.diagnostics import mask_host, mask_user
    assert mask_host("1.2.3.4") == "1.2.x.x"
    assert mask_host("100.100.100.100") == "100.100.x.x"
    assert mask_host("example.com") == "example.***"
    assert mask_host("") == "(未配置)"
    assert mask_user("alice") == "a***"
    assert mask_user("") == "(未配置)"


def test_collect_masks_sensitive_and_probes(monkeypatch):
    # 全部探测打桩(不依赖真实端口/工具/进程); 脱敏断言: 原始 IP/用户名不得出现
    from core import diagnostics as dsh_diag
    from core import tunnel_mgr as dsh_tunnels
    from core import env as dsh_env
    monkeypatch.setattr(dsh_tunnels, "tcp_ok", lambda host, port: port == 3080)
    monkeypatch.setattr(dsh_env, "get_version", lambda cmd: "v1.2.3")
    monkeypatch.setattr(dsh_diag.shutil, "which", lambda name: "C:/bin/" + name)
    monkeypatch.setattr(dsh_tunnels, "tunnels_snapshot",
                        lambda base_dir: {"dsh-tunnel": {"pid": 123, "alive": True}})
    cfg = {"dash_port": 3080, "forward_ports": [8090], "lab_port": 0,
           "ssh_server": "1.2.3.4", "ssh_user": "alice",
           "lab_server": "", "lab_user": "",
           "dash_repo": "D:/Apps/deepseek-harness",
           "local_ports": [3080], "remote_tunnels": [1, 2],
           "deployments": [{"name": "lab"}]}
    r = dsh_diag.collect(None, cfg, "0.7.0", base_dir=".")
    assert r["dsh_web"]["online"] is True
    assert r["relay"]["host"] == "1.2.x.x" and r["relay"]["user"] == "a***"
    assert r["dash_repo_tail"] == "deepseek-harness"
    assert r["tunnels"]["dsh-tunnel"]["alive"] is True
    text = dsh_diag.render(r)
    assert "1.2.x.x" in text and "a***" in text
    assert "1.2.3.4" not in text and "alice" not in text
    assert "远程 SSH 未主动探测" in text


def test_export_import_roundtrip():
    from core.config import export_envelope, parse_import
    env = export_envelope({"ssh_server": "1.2.3.4", "dash_port": 3080},
                          now="2026-08-30T12:00:00")
    assert env["_type"] == "dsh-console-config" and env["_version"] == 1
    cfg, err = parse_import(json.loads(json.dumps(env)))
    assert err == "" and cfg["dash_port"] == 3080


def test_parse_import_rejects_bad_data():
    from core.config import parse_import
    assert parse_import("not a dict")[0] is None
    assert parse_import({"config": {}})[1]           # 缺 _type
    assert parse_import({"_type": "other", "config": {}})[1]   # 类型不符
    assert parse_import({"_type": "dsh-console-config"})[1]    # 缺 config
    cfg, err = parse_import({"_type": "dsh-console-config", "config": {"a": 1}})
    assert err == "" and cfg == {"a": 1}
