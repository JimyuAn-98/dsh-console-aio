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
