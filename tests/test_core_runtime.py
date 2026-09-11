# -*- coding: utf-8 -*-
# core/nodeid.py + core/runtime.py 纯逻辑测试(不真连 SSH)。
# 覆盖: 节点码生成/校验/持久化; runtime 文件解析与读写; 公网信箱发布/列举; Token 取用顺序。

import json

import core.nodeid as nodeid
import core.runtime as runtime


class TestNodeId:
    def test_machine_node_id_ascii_short(self):
        nid = nodeid.machine_node_id()
        assert nodeid.valid_node_id(nid) and len(nid) == 10

    def test_valid_node_id(self):
        assert nodeid.valid_node_id("abc123")
        assert not nodeid.valid_node_id("")
        assert not nodeid.valid_node_id("中文")
        assert not nodeid.valid_node_id("ab")
        assert not nodeid.valid_node_id("a" * 33)

    def test_ensure_generates_and_persists(self, tmp_path, monkeypatch):
        cfgf = tmp_path / "config.json"
        cfgf.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(nodeid, "machine_node_id", lambda: "fixed12345")
        assert nodeid.ensure_node_id(str(cfgf)) == "fixed12345"
        assert json.loads(cfgf.read_text(encoding="utf-8"))["node_id"] == "fixed12345"
        # 已有合法值 -> 不再重生成
        monkeypatch.setattr(nodeid, "machine_node_id", lambda: "other99999")
        assert nodeid.ensure_node_id(str(cfgf)) == "fixed12345"


class TestParseRuntime:
    def test_new_json(self):
        rec = runtime.parse_runtime('{"node_id":"n1","hostname":"h","token":"t","updated_at":5}')
        assert rec == {"node_id": "n1", "hostname": "h", "token": "t", "updated_at": 5}

    def test_legacy_raw_token(self):
        assert runtime.parse_runtime("RAWTOKEN") == {
            "node_id": "", "hostname": "", "token": "RAWTOKEN", "updated_at": 0}

    def test_empty_and_bad(self):
        assert runtime.parse_runtime("") is None
        assert runtime.parse_runtime("   ") is None
        assert runtime.parse_runtime("{bad json") is None


class TestRuntimeFile:
    def test_write_read_roundtrip(self, tmp_path):
        p = str(tmp_path / "runtime.json")
        assert runtime.write_runtime("n1", "TOK", hostname="host1", path=p)
        rec = runtime.read_runtime(p)
        assert rec["node_id"] == "n1" and rec["token"] == "TOK" and rec["hostname"] == "host1"

    def test_read_missing(self, tmp_path):
        assert runtime.read_runtime(str(tmp_path / "nope.json")) is None


class TestMailbox:
    def test_publish_builds_remote_cmd(self, monkeypatch):
        calls = []
        monkeypatch.setattr(runtime, "_ssh",
                            lambda host, user, cmd, **k: (calls.append((host, user, cmd)), (0, "", ""))[1])
        assert runtime.publish_mailbox({"ssh_server": "relay", "ssh_user": "u"}, "n1", "TOK") is True
        assert "n1.json" in calls[0][2] and "base64" in calls[0][2]

    def test_list_mailbox_parses_sorted(self, monkeypatch):
        payload = ('@@a.json@@\n{"node_id":"a","hostname":"ha","token":"ta","updated_at":10}\n'
                   '@@b.token@@\nRAWTOK\n')
        monkeypatch.setattr(runtime, "_ssh", lambda host, user, cmd, **k: (0, payload, ""))
        items = runtime.list_mailbox({"ssh_server": "relay", "ssh_user": "u"})
        assert [i["key"] for i in items] == ["a", "b"]
        assert items[0]["hostname"] == "ha" and items[0]["token"] == "ta"
        assert items[1]["token"] == "RAWTOK"

    def test_list_mailbox_no_relay(self):
        assert runtime.list_mailbox({}) == []

    def test_resolve_order_cache_then_mailbox_then_remote(self, monkeypatch):
        import core.dshctl as dshctl
        monkeypatch.setattr(runtime, "pull_mailbox", lambda cfg, key: {"token": "M"})
        monkeypatch.setattr(runtime, "read_remote_runtime", lambda dep: {"token": "R"})
        monkeypatch.setattr(dshctl, "get_runtime_token", lambda name, refresh=False: "C")
        assert runtime.resolve_node_token({"name": "n", "node_key": "k"}, {}) == ("C", "cache")
        monkeypatch.setattr(dshctl, "get_runtime_token", lambda name, refresh=False: None)
        assert runtime.resolve_node_token({"name": "n", "node_key": "k"}, {}) == ("M", "mailbox")
        monkeypatch.setattr(runtime, "pull_mailbox", lambda cfg, key: None)
        assert runtime.resolve_node_token({"name": "n", "node_key": "k"}, {}) == ("R", "remote")
        monkeypatch.setattr(runtime, "read_remote_runtime", lambda dep: None)
        assert runtime.resolve_node_token({"name": "n"}, {}) == (None, "")
