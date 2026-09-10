# -*- coding: utf-8 -*-
# core/dshctl.py 的 dsh 版本信息纯函数测试(零 Qt, 零真实网络)。
# 覆盖: fetch_dsh_releases 字段映射/前缀剥离/TTL 缓存与 force; dsh_local_version;
# cn_section 中文段切分; html_headings_to_md 标题转换与标签剥离。

import json
import time

import pytest

import core.dshctl as d


@pytest.fixture(autouse=True)
def _reset_release_cache():
    # fetch_dsh_releases 用模块级 TTL 缓存, 每个用例前清空, 避免相互污染
    d._DSH_RELEASES_CACHE["at"] = 0.0
    d._DSH_RELEASES_CACHE["data"] = []
    yield


class _FakeResp:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._raw


def _patch_urlopen(monkeypatch, payload, calls=None):
    calls = calls if calls is not None else []

    def fake(req, timeout=15):
        calls.append(getattr(req, "full_url", str(req)))
        return _FakeResp(payload)

    monkeypatch.setattr(d.urllib.request, "urlopen", fake)
    return calls


_RAW = [
    {"tag_name": "dsh-v0.1.5-rc.1", "name": "v0.1.5-rc.1",
     "published_at": "2026-09-10T03:09:00Z", "prerelease": True,
     "body": "x", "html_url": "https://example/rel/1"},
    {"tag_name": "dsh-v0.1.3-alpha.1", "name": "v0.1.3-alpha.1",
     "published_at": "2026-09-04T11:34:32Z", "prerelease": True,
     "body": "", "html_url": "https://example/rel/2"},
]


class TestFetchDshReleases:
    # 契约: events 无关的纯数据函数; 输出字段固定; 网络失败抛异常由 service 转中文。
    def test_field_mapping_and_prefix_strip(self, monkeypatch):
        _patch_urlopen(monkeypatch, _RAW)
        out = d.fetch_dsh_releases(force=True)
        assert [r["version"] for r in out] == ["0.1.5-rc.1", "0.1.3-alpha.1"]
        assert out[0]["tag"] == "dsh-v0.1.5-rc.1"
        assert out[0]["prerelease"] is True
        assert out[0]["html_url"] == "https://example/rel/1"
        assert out[1]["body"] == ""

    def test_request_hits_official_repo(self, monkeypatch):
        calls = _patch_urlopen(monkeypatch, _RAW)
        d.fetch_dsh_releases(force=True)
        assert d.DSH_REPO in calls[0]
        assert "/releases" in calls[0]

    def test_malformed_entries_skipped(self, monkeypatch):
        _patch_urlopen(monkeypatch, [{"name": "no-tag"}, "junk",
                                     {"tag_name": "v1.0.0"}])
        out = d.fetch_dsh_releases(force=True)
        assert [r["version"] for r in out] == ["1.0.0"]

    def test_ttl_cache_and_force(self, monkeypatch):
        calls = _patch_urlopen(monkeypatch, _RAW)
        d.fetch_dsh_releases()
        d.fetch_dsh_releases()
        assert len(calls) == 1                    # 命中缓存不再请求
        d.fetch_dsh_releases(force=True)
        assert len(calls) == 2                    # force 绕过缓存

    def test_expired_cache_refetches(self, monkeypatch):
        calls = _patch_urlopen(monkeypatch, _RAW)
        d.fetch_dsh_releases()
        d._DSH_RELEASES_CACHE["at"] = time.time() - (d._DSH_RELEASES_TTL + 1)
        d.fetch_dsh_releases()
        assert len(calls) == 2

    def test_non_list_response_returns_empty(self, monkeypatch):
        _patch_urlopen(monkeypatch, {"message": "rate limited"})
        assert d.fetch_dsh_releases(force=True) == []

    def test_network_error_propagates(self, monkeypatch):
        def boom(req, timeout=15):
            raise OSError("no network")

        monkeypatch.setattr(d.urllib.request, "urlopen", boom)
        with pytest.raises(OSError):
            d.fetch_dsh_releases(force=True)


class TestDshLocalVersion:
    def test_reads_package_json(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "package.json").write_text(json.dumps({"version": "0.1.5-rc.1"}),
                                           encoding="utf-8")
        assert d.dsh_local_version({"dash_repo": str(repo)}) == "0.1.5-rc.1"

    def test_missing_repo_returns_none(self, tmp_path):
        assert d.dsh_local_version({"dash_repo": str(tmp_path / "nope")}) is None
        assert d.dsh_local_version({}) is None


class TestCnSection:
    _BODY = (
        "[中文](#cn-1) | [English](#en-1)\n\n"
        "这是中文正文。\n\n"
        "<h3 id=\"cn-1\">新增功能</h3>\n- 功能 A\n\n"
        "<h3 id=\"en-1\">New Features</h3>\n- Feature A\n")

    def test_splits_at_english_anchor(self):
        out = d.cn_section(self._BODY)
        assert "这是中文正文" in out
        assert "新增功能" in out
        assert "New Features" not in out
        assert "[English]" not in out            # 语言导航行被剥掉

    def test_chinese_anchor_variant(self):
        body = ("[中文](#chinese) | [English](#english)\n\n"
                "中文内容\n\n<h2 id=\"chinese\">更新</h2>\n\n"
                "<h2 id=\"english\">Changes</h2>\nEnglish\n")
        out = d.cn_section(body)
        assert "中文内容" in out and "English" not in out

    def test_no_english_anchor_returns_all(self):
        assert d.cn_section("只有中文\n没有英文段") == "只有中文\n没有英文段"

    def test_empty(self):
        assert d.cn_section("") == ""
        assert d.cn_section(None) == ""


class TestHtmlHeadingsToMd:
    def test_headings_become_markdown(self):
        out = d.html_headings_to_md("<h3 id=\"x\">新增功能</h3>\n- a")
        assert out.startswith("### 新增功能")
        assert "<h3" not in out and "id=" not in out

    def test_h2_and_inline_tags_stripped(self):
        out = d.html_headings_to_md('<h2 id="c">更新</h2>\n<b>粗体</b>')
        assert "## 更新" in out
        assert "<b>" not in out and "粗体" in out

    def test_plain_text_unchanged(self):
        assert d.html_headings_to_md("- a\n- b") == "- a\n- b"
