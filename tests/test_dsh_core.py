# -*- coding: utf-8 -*-
# test_dsh_core.py - dsh_core 业务层纯单元测试(默认 pytest 层, 零真实资源)。
#
# 安全边界: 不构造 MainWindow, 不起探测/隧道线程, 不连任何端口与 SSH。
# 端口相关输入一律 0/空列表(配合 derived 的 allow_empty_ports 分支), 与真实 3080 无交集。
# 覆盖: config.derived 兜底规则(与主程序对齐的默认分支 + allow_empty_ports 隔离分支),
#       TunnelManager.build 用假配置纯组装隧道参数, DshService events->Signal 转发契约。

import json
import os
import time

import pytest

from dsh_core.config import derived, load_config, load_derived

# 假配置: 服务器全占位符, 端口全空 —— 与 tests/fake_env.py 同一脱钩原则。
EMPTY_PORTS_CFG = {
    "ssh_server": "YOUR_PUBLIC_IP",
    "ssh_user": "YOUR_USER",
    "lab_server": "YOUR_LAB_IP",
    "lab_user": "YOUR_LAB_USER",
    "dash_repo": "",
    "dash_port": 0,
    "lab_port": 0,
    "reverse_port": 0,
    "forward_ports": [],
}


class TestDerivedDefault:
    # 默认分支: 空/0 端口兜底为真实默认端口 —— 契约是与 dsh-console-aio.py 顶层派生
    # 保持同一套值; 任何一侧改动必须同步另一侧(真实 GUI 行为不能变)。
    def test_empty_config_falls_back_to_real_ports(self):
        d = derived({})
        assert d["dash_port"] == 3080
        assert d["lab_port"] == 3090
        assert d["reverse_port"] == 8091
        assert d["forward_ports"] == [8090, 8022, 8091]
        assert d["dash_cmd"] == ["pnpm.cmd", "dsh", "web"]

    def test_zero_ports_fall_back_by_default(self):
        # 历史事故根因: 假配置端口 0 被兜底回真实端口(曾干掉运行中的 3080)。
        # 默认行为保持不变(主链路与主程序一致), 隔离需求由 allow_empty_ports 承担。
        d = derived(dict(EMPTY_PORTS_CFG))
        assert d["dash_port"] == 3080
        assert d["lab_port"] == 3090
        assert d["reverse_port"] == 8091
        assert d["forward_ports"] == [8090, 8022, 8091]

    def test_explicit_ports_pass_through(self):
        d = derived({"dash_port": 1234, "lab_port": 22, "reverse_port": 5555,
                     "forward_ports": [1, 2, 3]})
        assert d["dash_port"] == 1234
        assert d["lab_port"] == 22
        assert d["reverse_port"] == 5555
        assert d["forward_ports"] == [1, 2, 3]

    def test_string_fields_fall_back_to_empty(self):
        d = derived({})
        assert d["dash_repo"] == ""
        assert d["ssh_server"] == ""
        assert d["ssh_user"] == ""
        assert d["lab_server"] == ""
        assert d["lab_user"] == ""


class TestDerivedAllowEmpty:
    # 隔离分支: 端口不兜底(空/0 原样保留), 供测试用假配置与真实端口彻底隔离。
    def test_empty_ports_stay_empty(self):
        d = derived(dict(EMPTY_PORTS_CFG), allow_empty_ports=True)
        assert d["dash_port"] == 0
        assert d["lab_port"] == 0
        assert d["reverse_port"] == 0
        assert d["forward_ports"] == []

    def test_missing_ports_become_zero(self):
        d = derived({}, allow_empty_ports=True)
        assert d["dash_port"] == 0
        assert d["lab_port"] == 0
        assert d["reverse_port"] == 0
        assert d["forward_ports"] == []

    def test_explicit_ports_pass_through(self):
        d = derived({"dash_port": 1234, "forward_ports": [7]}, allow_empty_ports=True)
        assert d["dash_port"] == 1234
        assert d["forward_ports"] == [7]

    def test_non_port_fields_follow_default_rules(self):
        # 隔离分支只放开端口类配置, 其余字段与默认分支同规则。
        d = derived(dict(EMPTY_PORTS_CFG), allow_empty_ports=True)
        assert d["ssh_server"] == "YOUR_PUBLIC_IP"
        assert d["dash_cmd"] == ["pnpm.cmd", "dsh", "web"]
        assert d["tcp_timeout"] == 0.8
        assert d["local_ports"] == []
        assert d["remote_tunnels"] == []


class TestLoadConfig:
    def test_missing_file_returns_empty_dict(self, tmp_path):
        assert load_config(str(tmp_path / "nope.json")) == {}

    def test_load_derived_passthrough(self, tmp_path):
        p = tmp_path / "config.json"
        p.write_text(json.dumps(dict(EMPTY_PORTS_CFG), ensure_ascii=False),
                     encoding="utf-8")
        assert load_config(str(p))["dash_port"] == 0
        d = load_derived(str(p), allow_empty_ports=True)
        assert d["dash_port"] == 0
        assert d["forward_ports"] == []
        d2 = load_derived(str(p))
        assert d2["dash_port"] == 3080
        assert d2["forward_ports"] == [8090, 8022, 8091]


class TestTunnelManagerBuild:
    # build() 是纯组装: 只构造 tunnel_mgr.Tunnel(构造函数零副作用), 不 start 不探测。
    def _mgr(self, tmp_path, allow_empty=False):
        from dsh_core.tunnels import TunnelManager
        d = derived(dict(EMPTY_PORTS_CFG), allow_empty_ports=allow_empty)
        return TunnelManager(str(tmp_path), d)

    def test_forward_tunnel_from_fake_config(self, tmp_path):
        m = self._mgr(tmp_path)
        t = m.build("dsh-tunnel")
        assert t.mode == "forward"
        assert t.host == "YOUR_PUBLIC_IP"
        assert t.user == "YOUR_USER"
        assert t.forwards == [(8090, "127.0.0.1", 8090),
                              (8022, "127.0.0.1", 8022),
                              (8091, "127.0.0.1", 8091)]
        assert t.watch_port == 8090

    def test_empty_forward_ports_yield_no_forwards(self, tmp_path):
        m = self._mgr(tmp_path, allow_empty=True)
        t = m.build("dsh-tunnel")
        assert t.forwards == []
        assert t.watch_port is None

    def test_lab_tunnel_from_fake_config(self, tmp_path):
        m = self._mgr(tmp_path)
        t = m.build("connect-lab-dsh")
        assert (t.host, t.user, t.mode) == ("YOUR_LAB_IP", "YOUR_LAB_USER", "forward")
        assert t.forwards == [(3090, "127.0.0.1", 3090)]
        assert t.watch_port == 3090

    def test_reverse_tunnel_maps_public_to_local_dash(self, tmp_path):
        m = self._mgr(tmp_path)
        t = m.build("dsh-tunnel-reverse")
        assert t.mode == "reverse"
        assert t.forwards == [(8091, "127.0.0.1", 3080)]
        assert t.watch_port is None

    def test_unknown_key_raises_on_build_and_stop(self, tmp_path):
        m = self._mgr(tmp_path)
        with pytest.raises(ValueError):
            m.build("no-such-tunnel")
        # stop 分支同样先经 build 校验: 在读 PID 文件/杀进程之前就失败。
        with pytest.raises(ValueError):
            m.stop("no-such-tunnel")


class TestServiceSignalBridge:
    # DshService 的 events 回调 -> Qt Signal 转发契约(信号-槽是后端->UI 唯一通道)。
    # 直接调回调本身, 不经 start_*/monitor_once(那些会起线程碰真实子进程)。
    def test_events_forward_to_signals(self, tmp_path):
        pytest.importorskip("PySide6")
        from app.services import DshService
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps(dict(EMPTY_PORTS_CFG), ensure_ascii=False),
                       encoding="utf-8")
        svc = DshService(base_dir=str(tmp_path), config_path=str(cfg))
        got = []
        svc.log.connect(lambda text, tag: got.append(("log", text, tag)))
        svc.status.connect(lambda text: got.append(("status", text)))
        svc.card.connect(lambda key, on: got.append(("card", key, on)))
        ev = svc._events()
        ev("log", ("hello", "err"))
        ev("status", "running")
        ev("card", ("dsh-tunnel", True))
        assert ("log", "hello", "err") in got
        assert ("status", "running") in got
        assert ("card", "dsh-tunnel", True) in got

    def test_ctor_is_side_effect_free(self, tmp_path):
        # 构造 service(读配置/建 manager)不起线程、不探测: UI 测试可安全持有它。
        pytest.importorskip("PySide6")
        from app.services import DshService
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps(dict(EMPTY_PORTS_CFG), ensure_ascii=False),
                       encoding="utf-8")
        svc = DshService(base_dir=str(tmp_path), config_path=str(cfg))
        assert svc.tunnels._py_persist == {}
        assert svc.ctl.d["forward_ports"] == [8090, 8022, 8091]

    def test_service_read_op_wraps_result(self, tmp_path, monkeypatch, qapp):
        # 阶段4 纯读统一通道: _run_core_op 把 core 任意返回值包装为 {"data","err"},
        # 工作线程 emit 需 processEvents 驱动事件循环投递。core 函数被拦截(不碰真实 ~/.dsh)。
        pytest.importorskip("PySide6")
        import dsh_core.data as core_data
        from app.services import DshService
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps(dict(EMPTY_PORTS_CFG), ensure_ascii=False),
                       encoding="utf-8")
        svc = DshService(base_dir=str(tmp_path), config_path=str(cfg))
        monkeypatch.setattr(core_data, "read_taskboard",
                            lambda remote=None: {"ledger": {"tasks": []}})
        got = []
        svc.result.connect(lambda op, payload: got.append((op, payload)))
        svc.read_taskboard()
        deadline = time.time() + 5
        while not got and time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.05)
        assert got and got[0][0] == "taskboard-read"
        assert got[0][1]["data"] == {"ledger": {"tasks": []}}
        assert got[0][1]["err"] == ""

    def test_service_read_op_error_payload(self, tmp_path, monkeypatch, qapp):
        # core 函数抛异常时: {"data": None, "err": 中文/原始信息}, 不向外抛、不卡 UI。
        pytest.importorskip("PySide6")
        import dsh_core.data as core_data
        from app.services import DshService
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps(dict(EMPTY_PORTS_CFG), ensure_ascii=False),
                       encoding="utf-8")
        svc = DshService(base_dir=str(tmp_path), config_path=str(cfg))

        def boom(remote=None):
            raise OSError("disk gone")

        monkeypatch.setattr(core_data, "read_taskboard", boom)
        got = []
        svc.result.connect(lambda op, payload: got.append((op, payload)))
        svc.read_taskboard()
        deadline = time.time() + 5
        while not got and time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.05)
        assert got and got[0][1]["data"] is None
        assert "disk gone" in got[0][1]["err"]


class TestDshDataShim:
    # 阶段4: 仓库根 dsh_data.py 是 dsh_core.data 的兼容 shim —— 同一对象,
    # 原地修改(DEFAULT_PRICES)跨命名空间共享。
    def test_shim_binds_same_module_objects(self):
        import dsh_data
        import dsh_core.data as core_data
        assert dsh_data.DshRemote is core_data.DshRemote
        assert dsh_data.DEFAULT_PRICES is core_data.DEFAULT_PRICES
        assert dsh_data.load_deployments is core_data.load_deployments

    def test_shim_exports_private_helpers(self):
        # tests/ 与历史调用方引用过私有 YAML/SSH 助手, shim 必须显式带上
        import dsh_data
        for name in ("_dump_yaml", "_dump_scalar", "_parse_yaml_block",
                     "_ssh_base", "_ssh_run", "_config_path"):
            assert hasattr(dsh_data, name), name


class TestDshCtlUpdate:
    # update_dsh 步骤编排契约: 全程 monkeypatch 掉真实子进程(stop/start/stream_cmd),
    # 只验证步骤顺序、命令 cwd 与失败中止, 绝不真跑 git/pnpm。
    def _ctl(self, tmp_path):
        from dsh_core.dshctl import DshCtl
        return DshCtl(derived({"dash_repo": str(tmp_path / "repo")}))

    def test_steps_in_order_all_in_repo_then_restart(self, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        repo.mkdir()
        ctl = self._ctl(tmp_path)
        calls = []
        monkeypatch.setattr(ctl, "stop_dsh", lambda ev=None: calls.append("stop") or True)
        monkeypatch.setattr(ctl, "start_dsh", lambda ev=None: calls.append("start") or True)
        monkeypatch.setattr(ctl, "stream_cmd",
                            lambda cmd, cwd=None, env=None, events=None,
                            timeout_override=None: calls.append((tuple(cmd), cwd)) or True)
        monkeypatch.setattr(time, "sleep", lambda s: None)
        assert ctl.update_dsh() is True
        assert calls[0] == "stop"
        cmds = [c for c in calls if isinstance(c, tuple)]
        # 命令序列: fetch -> pull -> clean -> install -> build(全部在 dsh 仓库内执行)。
        # clean 不可省: dsh 的 lib/ 产物被 gitignore, git pull 不清; 上游改导出后
        # 过期产物会让 build 报 MISSING_EXPORT(2026-08-28 实测事故)。
        assert [c[0] for c in cmds] == [
            ("git", "fetch", "origin", "--prune"),
            ("git", "pull", "--ff-only"),
            ("pnpm.cmd", "run", "clean"),
            ("pnpm.cmd", "install"),
            ("pnpm.cmd", "run", "build"),
        ]
        assert all(c[1] == str(repo) for c in cmds)
        assert calls[-1] == "start"

    def test_failure_aborts_before_restart(self, tmp_path, monkeypatch):
        (tmp_path / "repo").mkdir()
        ctl = self._ctl(tmp_path)
        calls = []
        monkeypatch.setattr(ctl, "stop_dsh", lambda ev=None: calls.append("stop") or True)
        monkeypatch.setattr(ctl, "start_dsh", lambda ev=None: calls.append("start") or True)

        def fake_stream(cmd, cwd=None, env=None, events=None, timeout_override=None):
            calls.append(cmd[0])
            return cmd[:1] != ["pnpm.cmd"]  # 第一个 pnpm 步骤(install)失败

        monkeypatch.setattr(ctl, "stream_cmd", fake_stream)
        monkeypatch.setattr(time, "sleep", lambda s: None)
        assert ctl.update_dsh() is False
        assert "start" not in calls          # 失败后不得重启
        assert calls.count("pnpm.cmd") == 1  # install 失败后不再跑 build

    def test_missing_repo_aborts_without_commands(self, tmp_path, monkeypatch):
        ctl = self._ctl(tmp_path)  # dash_repo 指向不存在的目录
        monkeypatch.setattr(ctl, "stop_dsh", lambda ev=None: True)
        monkeypatch.setattr(ctl, "stream_cmd",
                            lambda *a, **k: pytest.fail("仓库不存在时不应执行任何命令"))
        assert ctl.update_dsh() is False

    def test_service_update_dsh_emits_finished(self, tmp_path, monkeypatch, qapp):
        # service.update_dsh 后台线程跑 ctl 并以 finished(op, ok) 收场(信号-槽契约)。
        # 工作线程 emit 是队列投递, 需以 processEvents 驱动事件循环才能到达槽。
        pytest.importorskip("PySide6")
        from app.services import DshService
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps(dict(EMPTY_PORTS_CFG), ensure_ascii=False),
                       encoding="utf-8")
        svc = DshService(base_dir=str(tmp_path), config_path=str(cfg))
        (tmp_path / "repo").mkdir()
        monkeypatch.setattr(svc.ctl, "update_dsh", lambda ev=None: True)
        monkeypatch.setattr(time, "sleep", lambda s: None)
        got = []
        svc.finished.connect(lambda op, ok: got.append((op, ok)))
        svc.update_dsh()
        deadline = time.time() + 5
        while not got and time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.05)
        assert got == [("update-dsh", True)]
