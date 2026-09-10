# -*- coding: utf-8 -*-
# ui/cacheable.py CacheableMixin 纯单元测试(零 Qt)。
# 用假页面(duck-typed _spinner)验证: 命中缓存/未命中拉取/busy 防重入(含 force)/
# 回包写缓存与指示灯/错误态/自定义错误文案钩子。

import os

import core.cache as core_cache
from ui.cacheable import CacheableMixin


class _FakeSpinner:
    def __init__(self):
        self.loading = None
        self.status = None
        self.tip = None

    def set_loading(self, on):
        self.loading = on

    def set_status(self, s):
        self.status = s

    def setToolTip(self, t):
        self.tip = t


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(core_cache, "cache_file_path",
                        lambda: os.path.join(str(tmp_path), "dsh_aio_cache.json"))


class _Page(CacheableMixin):
    def __init__(self):
        self._busy = False
        self._spinner = _FakeSpinner()
        self.applied = []
        self.fetched = 0
        self.hit_extra = 0
        self.begun = 0
        self.ended = 0

    def _cache_kind(self):
        return "demo"

    def _cache_src_mtime(self):
        return 100

    def _cache_fetch(self):
        self.fetched += 1

    def _cache_apply(self, data, err=""):
        self.applied.append((data, err))

    def _cache_valid(self, data):
        return isinstance(data, dict)

    def _cache_empty_data(self):
        return {}

    def _cache_begin(self):
        self.begun += 1

    def _cache_end(self):
        self.ended += 1

    def _cache_hit_extra(self, data):
        self.hit_extra += 1


class TestCacheableMixin:
    def test_miss_fetches_and_sets_busy(self, tmp_path, monkeypatch):
        _isolate(monkeypatch, tmp_path)
        p = _Page()
        p._refresh()
        assert p.fetched == 1 and p._busy is True
        assert p._spinner.loading is True and p.begun == 1

    def test_hit_uses_cache_without_fetch(self, tmp_path, monkeypatch):
        _isolate(monkeypatch, tmp_path)
        core_cache.write_cache("demo", {"a": 1}, fetched_at=1000)
        p = _Page()
        p._refresh()                      # src_mtime=100 < fetched=1000 -> 命中
        assert p.fetched == 0 and p._busy is False
        assert p.applied == [({"a": 1}, "")]
        assert p._spinner.status == "ok" and p.hit_extra == 1

    def test_force_bypasses_cache(self, tmp_path, monkeypatch):
        _isolate(monkeypatch, tmp_path)
        core_cache.write_cache("demo", {"a": 1}, fetched_at=1000)
        p = _Page()
        p._refresh(force=True)
        assert p.fetched == 1

    def test_busy_guard_ignores_force(self, tmp_path, monkeypatch):
        _isolate(monkeypatch, tmp_path)
        p = _Page()
        p._busy = True
        p.refresh(force=True)
        assert p.fetched == 0

    def test_result_writes_cache_and_marks_changed(self, tmp_path, monkeypatch):
        _isolate(monkeypatch, tmp_path)
        core_cache.write_cache("demo", {"a": 1})
        p = _Page()
        p._busy = True
        assert p._cache_result({"a": 2}) is True
        assert p._busy is False and p.ended == 1
        assert core_cache.read_cache("demo")[0] == {"a": 2}
        assert p._spinner.status == "warn"
        assert p.applied[-1] == ({"a": 2}, "")

    def test_result_same_data_marks_ok(self, tmp_path, monkeypatch):
        _isolate(monkeypatch, tmp_path)
        core_cache.write_cache("demo", {"a": 1})
        p = _Page()
        p._cache_result({"a": 1})
        assert p._spinner.status == "ok"

    def test_result_error_uses_empty_and_err(self, tmp_path, monkeypatch):
        _isolate(monkeypatch, tmp_path)
        p = _Page()
        assert p._cache_result(None, "boom") is False
        assert p.applied[-1] == ({}, "boom")
        assert p._spinner.status == "err"
        assert p._busy is False

    def test_error_text_hook(self, tmp_path, monkeypatch):
        class P(_Page):
            def _cache_error_text(self, data, err):
                return "自定义: " + str(err)
        _isolate(monkeypatch, tmp_path)
        p = P()
        p._cache_result({}, "x")
        assert p.applied[-1][1] == "自定义: x"
