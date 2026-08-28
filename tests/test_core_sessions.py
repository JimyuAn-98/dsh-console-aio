# -*- coding: utf-8 -*-
# test_core_sessions.py - core/sessions.py 纯单元测试(零 Qt, 零子进程)。
#
# 安全边界: DSH_HOME 指向 tmp_path 造假 ~/.dsh, 绝不触碰真实会话数据;
# delete_group 的越界拒绝路径必须证明"什么都没删"。

import json
import os

import pytest

import core.sessions as sess


def _fake_home(tmp_path, monkeypatch):
    # 造假 ~/.dsh: workspace.json(含未知顶层 key 以验证信封保留) + 一个会话分组
    home = tmp_path / "dshhome"
    (home / "storages").mkdir(parents=True)
    (home / "sessions" / "C--work-proj").mkdir(parents=True)
    (home / "sessions" / "C--work-proj" / "session-1").mkdir()
    ws = {"global": {"workspaceIds": ["w1"], "archivedSessionIds": []},
          "futureTopKey": "keep-me"}
    (home / "storages" / "workspace.json").write_text(
        json.dumps(ws, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("DSH_HOME", str(home))
    return home


class TestSetArchived:
    def test_success_replaces_and_baks(self, tmp_path, monkeypatch):
        home = _fake_home(tmp_path, monkeypatch)
        p = home / "storages" / "workspace.json"
        r = sess.set_archived(None, ["s-b", "s-a"])
        assert r["err"] == "" and "已更新归档状态(2 个)" in r["msg"]
        raw = json.loads(p.read_text(encoding="utf-8"))
        assert raw["global"]["archivedSessionIds"] == ["s-a", "s-b"]
        assert raw["global"]["workspaceIds"] == ["w1"]   # 其他字段不动
        assert raw["futureTopKey"] == "keep-me"          # 未知顶层 key 保留
        assert os.path.isfile(str(p) + ".bak")           # 写前备份已生成

    def test_idempotent_full_replace(self, tmp_path, monkeypatch):
        # session_ids 是归档后的完整列表(整体替换): 二次调用以最后一次为准
        home = _fake_home(tmp_path, monkeypatch)
        p = home / "storages" / "workspace.json"
        sess.set_archived(None, ["s1", "s2"])
        sess.set_archived(None, ["s2"])
        raw = json.loads(p.read_text(encoding="utf-8"))
        assert raw["global"]["archivedSessionIds"] == ["s2"]

    def test_rejects_non_list(self, tmp_path, monkeypatch):
        home = _fake_home(tmp_path, monkeypatch)
        p = home / "storages" / "workspace.json"
        before = p.read_text(encoding="utf-8")
        r = sess.set_archived(None, "s1")
        assert "不合法" in r["err"] and r["msg"] == ""
        assert p.read_text(encoding="utf-8") == before   # 拒绝时零副作用

    def test_rejects_non_string_items(self, tmp_path, monkeypatch):
        home = _fake_home(tmp_path, monkeypatch)
        p = home / "storages" / "workspace.json"
        before = p.read_text(encoding="utf-8")
        r = sess.set_archived(None, ["ok", 3])
        assert "不合法" in r["err"]
        assert p.read_text(encoding="utf-8") == before


class TestDeleteGroup:
    def test_success_removes_group_dir(self, tmp_path, monkeypatch):
        home = _fake_home(tmp_path, monkeypatch)
        target = home / "sessions" / "C--work-proj"
        assert target.is_dir()
        r = sess.delete_group(None, "C--work-proj")
        assert r["err"] == "" and "已删除分组" in r["msg"]
        assert not target.exists()
        assert (home / "sessions").is_dir()               # base 自身必须还在

    def test_refuses_traversal(self, tmp_path, monkeypatch):
        home = _fake_home(tmp_path, monkeypatch)
        escape = home / "storages"                        # sessions 外的真实目录
        assert escape.is_dir()
        r = sess.delete_group(None, os.path.join("..", "storages"))
        assert r["msg"] == "" and "越界" in r["err"]
        assert escape.is_dir()                             # 越界目标分毫未动
        assert (home / "sessions" / "C--work-proj").is_dir()

    def test_refuses_base_itself(self, tmp_path, monkeypatch):
        home = _fake_home(tmp_path, monkeypatch)
        r = sess.delete_group(None, ".")
        assert r["msg"] == "" and "越界" in r["err"]
        assert (home / "sessions" / "C--work-proj").is_dir()

    def test_refuses_missing_dir(self, tmp_path, monkeypatch):
        home = _fake_home(tmp_path, monkeypatch)
        r = sess.delete_group(None, "no-such-group")
        assert r["msg"] == "" and "不存在" in r["err"]

    def test_refuses_empty_name(self, tmp_path, monkeypatch):
        _fake_home(tmp_path, monkeypatch)
        r = sess.delete_group(None, "   ")
        assert r["msg"] == "" and "不合法" in r["err"]

    def test_events_log_carries_outcome(self, tmp_path, monkeypatch):
        _fake_home(tmp_path, monkeypatch)
        got = []
        r = sess.delete_group(lambda kind, p: got.append((kind, p)), "no-such-group")
        assert r["err"]
        assert any(kind == "log" and "err" in p[1] for kind, p in got)
