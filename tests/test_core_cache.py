# -*- coding: utf-8 -*-
# core/cache.py 数据缓存层单元测试(纯 stdlib, 零 Qt)。
# 覆盖: 路径定位、读写、多 kind 合并、needs_refresh 时间戳比对、data_changed 签名比较。
# 隔离: monkeypatch 把 cache_file_path 指到 tmp_path, 绝不写真实缓存文件。

import io
import json
import os
import time

import pytest


def _iso(tmp_path, monkeypatch):
    import core.cache as c
    monkeypatch.setattr(c, "cache_file_path",
                        lambda: os.path.join(str(tmp_path), "dsh_aio_cache.json"))
    return c


class TestCachePath:
    def test_default_is_json_in_base(self, tmp_path, monkeypatch):
        c = _iso(tmp_path, monkeypatch)
        assert c.cache_file_path().endswith("dsh_aio_cache.json")


class TestCacheReadWrite:
    def test_empty_missing_kind(self, tmp_path, monkeypatch):
        c = _iso(tmp_path, monkeypatch)
        assert c.read_cache("usage") == (None, None)

    def test_roundtrip(self, tmp_path, monkeypatch):
        c = _iso(tmp_path, monkeypatch)
        assert c.write_cache("usage", {"ok": True, "n": 3})
        data, fetched = c.read_cache("usage")
        assert data == {"ok": True, "n": 3}
        assert fetched is not None and fetched > 0

    def test_multi_kind_merge_and_preserve(self, tmp_path, monkeypatch):
        c = _iso(tmp_path, monkeypatch)
        c.write_cache("usage", {"a": 1})
        c.write_cache("sessions", {"b": 2})
        assert c.read_cache("usage")[0] == {"a": 1}
        assert c.read_cache("sessions")[0] == {"b": 2}
        # 再次写 usage, sessions 不受影响
        c.write_cache("usage", {"a": 3})
        assert c.read_cache("sessions")[0] == {"b": 2}

    def test_explicit_fetched_at(self, tmp_path, monkeypatch):
        c = _iso(tmp_path, monkeypatch)
        c.write_cache("usage", {"x": 1}, fetched_at=100)
        _, fetched = c.read_cache("usage")
        assert fetched == 100

    def test_corrupt_file_returns_empty(self, tmp_path, monkeypatch):
        c = _iso(tmp_path, monkeypatch)
        with io.open(os.path.join(str(tmp_path), "dsh_aio_cache.json"), "w",
                     encoding="utf-8") as fh:
            fh.write("{not valid json")
        assert c.read_cache("usage") == (None, None)


class TestNeedsRefresh:
    def test_no_cache_always_refresh(self, tmp_path, monkeypatch):
        c = _iso(tmp_path, monkeypatch)
        assert c.needs_refresh("usage", 100) is True
        assert c.needs_refresh("usage", 0) is True

    def test_src_unchanged_no_refresh(self, tmp_path, monkeypatch):
        c = _iso(tmp_path, monkeypatch)
        c.write_cache("usage", {"x": 1}, fetched_at=1000)
        assert c.needs_refresh("usage", 500) is False    # 源更早 -> 缓存最新
        assert c.needs_refresh("usage", 1000) is False   # 源==缓存 -> 不刷

    def test_src_newer_refresh(self, tmp_path, monkeypatch):
        c = _iso(tmp_path, monkeypatch)
        c.write_cache("usage", {"x": 1}, fetched_at=1000)
        assert c.needs_refresh("usage", 2000) is True

    def test_unknown_src_uses_cache_presence(self, tmp_path, monkeypatch):
        c = _iso(tmp_path, monkeypatch)
        c.write_cache("usage", {"x": 1})
        assert c.needs_refresh("usage", 0) is False   # 无法感知源: 有缓存则不刷
        assert c.needs_refresh("usage", None) is False


class TestDataChanged:
    def test_no_cached_is_changed(self, tmp_path, monkeypatch):
        c = _iso(tmp_path, monkeypatch)
        assert c.data_changed("usage", {"x": 1}) is True

    def test_identical_data_not_changed(self, tmp_path, monkeypatch):
        c = _iso(tmp_path, monkeypatch)
        c.write_cache("usage", {"a": [1, 2], "b": "x"})
        assert c.data_changed("usage", {"b": "x", "a": [1, 2]}) is False   # 键序无关

    def test_different_data_changed(self, tmp_path, monkeypatch):
        c = _iso(tmp_path, monkeypatch)
        c.write_cache("usage", {"a": [1, 2]})
        assert c.data_changed("usage", {"a": [1, 3]}) is True

    def test_json_sig_stable_and_distinct(self):
        from core.cache import json_sig
        assert json_sig({"x": 1, "y": [2, 3]}) == json_sig({"y": [2, 3], "x": 1})
        assert json_sig({"x": 1}) != json_sig({"x": 2})


class TestMtimeAndDataAggregators:
    def test_mtime_detectors_and_aggregators(self, tmp_path, monkeypatch):
        import core.data as d
        monkeypatch.setattr(d, "dsh_home", lambda: str(tmp_path))

        # 构造假的 sessions 目录与 workspace.json
        sdir = tmp_path / "sessions" / "test_group" / "sess1"
        sdir.mkdir(parents=True)
        zfile = sdir / "session.jsonl.zstd"
        zfile.write_bytes(b"dummy")
        stdir = tmp_path / "storages"
        stdir.mkdir()
        wfile = stdir / "workspace.json"
        wfile.write_text('{"global": {"workspaceIds": ["w1"], "archivedSessionIds": []}}', encoding="utf-8")

        # 构造 profiles 目录
        pdir = tmp_path / "profiles" / "web"
        pdir.mkdir(parents=True)
        (pdir / "cordis.yml").write_text("name: web", encoding="utf-8")

        # 构造 task-board 目录
        tdir = tmp_path / "task-board"
        tdir.mkdir(parents=True)
        (tdir / "ledger-v2.json").write_text('{"tasks": []}', encoding="utf-8")

        # 构造 .agent-presets 目录
        adir = tmp_path / ".agent-presets" / "p1"
        adir.mkdir(parents=True)
        (adir / "preset.yml").write_text("description: test", encoding="utf-8")

        # 验证各探测函数返回时间戳 > 0
        assert d.sessions_source_mtime() > 0
        assert d.plugins_source_mtime("web") > 0
        assert d.taskboard_source_mtime() > 0
        assert d.agent_presets_source_mtime() > 0
        assert d.profiles_source_mtime() > 0
        assert d.overview_source_mtime() > 0

        # 验证 read_sessions_data
        sdata = d.read_sessions_data()
        assert "ws" in sdata and "groups" in sdata
        assert sdata["ws"].get("workspaceIds") == ["w1"]

        # 验证 collect_overview_data
        cfg = {"dash_port": 3080, "dash_repo": str(tmp_path)}
        ov = d.collect_overview_data(cfg, [], smoke=True)
        assert ov["dash_port"] == 3080
        assert isinstance(ov["deploys"], list)
        assert len(ov["deploys"]) >= 1
        assert d.overview_source_mtime(cfg) > 0

    def test_overview_source_mtime_tracks_config(self, tmp_path, monkeypatch):
        # config.json 变更必须让总览数据源时间戳前进, 否则缓存永不失效(端口/命名改动不生效)
        import core.data as d
        monkeypatch.setattr(d, "dsh_home", lambda: str(tmp_path))
        for name in ("sessions_source_mtime", "taskboard_source_mtime",
                     "profiles_source_mtime", "agent_presets_source_mtime"):
            monkeypatch.setattr(d, name, lambda *a, **k: 0.0)
        cfgfile = tmp_path / "config.json"
        cfgfile.write_text("{}", encoding="utf-8")
        monkeypatch.setenv("DSH_AIO_CONFIG", str(cfgfile))
        os.utime(str(cfgfile), (1000, 1000))
        before = d.overview_source_mtime({"dash_port": 3080})
        os.utime(str(cfgfile), (2000, 2000))
        after = d.overview_source_mtime({"dash_port": 3080})
        assert before >= 1000
        assert after > before


class _Ctx:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestProbeLocalWeb:
    # probe_local_web: 纯 socket + 运行时 token 的轻量本机探活(monkeypatch, 不真连 3080)。
    def test_online_with_token(self, monkeypatch):
        import core.data as d
        monkeypatch.setattr(d.socket, "create_connection", lambda *a, **k: _Ctx())
        monkeypatch.setattr("core.dshctl.get_runtime_token",
                            lambda name, refresh=False: "TOK")
        r = d.probe_local_web({"dash_port": 3080})
        assert r["web_ok"] is True and r["local_token"] == "TOK"
        assert r["local_auth_url"].endswith("/?token=TOK")
        assert r["web_ms"] >= 0

    def test_offline_clears_token(self, monkeypatch):
        import core.data as d

        def boom(*a, **k):
            raise OSError("refused")

        monkeypatch.setattr(d.socket, "create_connection", boom)
        r = d.probe_local_web({"dash_port": 3081})
        assert r["web_ok"] is False and r["local_token"] is None
        assert r["web_ms"] == -1 and r["dash_port"] == 3081


class TestKindRegistry:
    # 注册表: 固定 kind 说明 / 动态前缀说明 / 未登记回退。
    def test_describe_fixed(self):
        from core import cache as c
        assert c.describe_kind("overview") == "总览快照"
        assert c.describe_kind("usage") == "模型用量统计"

    def test_describe_prefix_and_unknown(self):
        from core import cache as c
        assert "插件" in c.describe_kind("plugins_web")
        assert c.describe_kind("nope") == "未登记"


class TestCacheManagement:
    # 管理 API: 概览/删除单类/清空全部(隔离到 tmp_path)。
    def test_list_cached_reports_meta(self, tmp_path, monkeypatch):
        c = _iso(tmp_path, monkeypatch)
        c.write_cache("overview", {"a": 1}, fetched_at=100)
        c.write_cache("plugins_web", {"b": 2}, fetched_at=200)
        rows = {r["kind"]: r for r in c.list_cached()}
        assert rows["overview"]["description"] == "总览快照"
        assert rows["overview"]["fetched_at"] == 100
        assert rows["plugins_web"]["description"] == "插件列表(按 profile)"
        assert rows["overview"]["bytes"] > 0

    def test_clear_cache_one_and_all(self, tmp_path, monkeypatch):
        c = _iso(tmp_path, monkeypatch)
        c.write_cache("overview", {"a": 1})
        c.write_cache("usage", {"b": 2})
        assert c.clear_cache("overview") is True
        assert c.read_cache("overview") == (None, None)
        assert c.read_cache("usage")[0] == {"b": 2}
        assert c.clear_cache("missing") is False
        assert c.clear_all_cache() == 1
        assert c.list_cached() == []
