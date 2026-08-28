# -*- coding: utf-8 -*-
# test_core_deployments.py - core/deployments.py 纯单元测试(零 Qt, 零真实 ssh)。
#
# 安全边界: DshRemote 与 deployment_snapshot/save_deployments 全部 monkeypatch,
# 绝不发起真实 ssh 连接、绝不写真实 config.json。

from core import data as dsh_data
from core import deployments as dep_mod


class _FakeRemote:
    # 假 DshRemote: exec 可控成败, 不发起任何网络/子进程
    def __init__(self, dep=None, fail=False):
        self.dep = dep
        self.fail = fail

    def exec(self, cmd):
        if self.fail:
            raise OSError("ssh unreachable")
        return cmd


class TestSnapshotOne:
    def test_local_none_snapshot(self, monkeypatch):
        monkeypatch.setattr(dsh_data, "DshRemote", _FakeRemote)
        monkeypatch.setattr(dsh_data, "deployment_snapshot",
                            lambda r: {"ok": True, "version": "0.5.0"})
        snap = dep_mod.snapshot_one(None)
        assert snap["ok"] is True and snap["version"] == "0.5.0"

    def test_non_dict_becomes_error(self, monkeypatch):
        monkeypatch.setattr(dsh_data, "DshRemote", _FakeRemote)
        monkeypatch.setattr(dsh_data, "deployment_snapshot", lambda r: ["bad"])
        snap = dep_mod.snapshot_one({"host": "h"})
        assert snap["ok"] is False and "格式错误" in snap["error"]

    def test_exception_becomes_error_snap(self, monkeypatch):
        monkeypatch.setattr(dsh_data, "DshRemote", _FakeRemote)

        def boom(r):
            raise RuntimeError("ssh failed")

        monkeypatch.setattr(dsh_data, "deployment_snapshot", boom)
        snap = dep_mod.snapshot_one({"host": "h"})
        assert snap["ok"] is False and "ssh failed" in snap["error"]


class TestSnapshotAll:
    def test_serial_results_in_order(self, monkeypatch):
        snaps = [{"ok": True}, {"ok": False, "error": "x"}, {"ok": True}]
        monkeypatch.setattr(dep_mod, "snapshot_one", lambda dep: snaps[dep])
        got = []
        # events("result", (op, payload)): kind 恒为 "result", op 名在 payload[0]
        r = dep_mod.snapshot_all(lambda k, p: got.append((k, p)), [0, 1, 2])
        assert r["err"] == "" and r["count"] == 3
        assert all(k == "result" for k, p in got)
        assert all(p[0] == "deploy-snap" for k, p in got)
        assert [p[1]["idx"] for k, p in got] == [0, 1, 2]
        assert [p[1]["snap"] for k, p in got] == snaps


class TestTestConn:
    def test_ok(self, monkeypatch):
        monkeypatch.setattr(dsh_data, "DshRemote", _FakeRemote)
        r = dep_mod.test_conn(None, {"host": "1.2.3.4"})
        assert r["err"] == "" and "连接正常" in r["msg"] and r["host"] == "1.2.3.4"

    def test_unreachable_chinese_err(self, monkeypatch):
        monkeypatch.setattr(dsh_data, "DshRemote",
                            lambda dep=None: _FakeRemote(dep, fail=True))
        r = dep_mod.test_conn(None, {"host": "1.2.3.4"})
        assert r["msg"] == "" and "连接失败" in r["err"] and "不可达" in r["err"]

    def test_local_dep_refused(self, monkeypatch):
        r = dep_mod.test_conn(None, None)
        assert r["msg"] == "" and "远程部署" in r["err"]
        r = dep_mod.test_conn(None, {"user": "u"})
        assert "远程部署" in r["err"]


class TestSave:
    def test_success(self, monkeypatch):
        saved = {}
        monkeypatch.setattr(dsh_data, "save_deployments",
                            lambda depls: saved.update(depls=depls))
        r = dep_mod.save(None, [{"name": "a"}])
        assert r["err"] == "" and saved["depls"] == [{"name": "a"}]

    def test_failure_chinese_err(self, monkeypatch):
        def boom(depls):
            raise OSError("config locked")

        monkeypatch.setattr(dsh_data, "save_deployments", boom)
        r = dep_mod.save(None, [])
        assert r["msg"] == "" and "写入 config.json 失败" in r["err"]
