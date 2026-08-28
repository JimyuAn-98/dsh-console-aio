# -*- coding: utf-8 -*-
# test_core_plugins.py - core/plugins.py 纯单元测试(零 Qt)。
#
# 安全边界: DSH_HOME 指向 tmp_path 造假 ~/.dsh; load_entry_id_map(dump-config 子进程)
# 用 monkeypatch 拦截, 绝不真跑 pnpm; 不构造任何 Qt 对象。

import json
import pathlib
import os

from core import data as dsh_data
from core import plugins as pl


def _fake_profile(tmp_path, monkeypatch):
    # 造假 ~/.dsh/profiles/web: package.json(bundles+deps) + cordis.patch.yml
    home = tmp_path / "dshhome"
    prof = home / "profiles" / "web"
    prof.mkdir(parents=True)
    (prof / "package.json").write_text(json.dumps({
        "dependencies": {"dshmarket": "1.0.0", "@deepseek-ai/dsh-web": "0.1.0"},
        "dsh": {"profile": {"bundles": ["dshmarket", "@deepseek-ai/dsh-web"]}},
    }, ensure_ascii=False), encoding="utf-8")
    (prof / "cordis.patch.yml").write_text(
        "- id: dshmarket\n  disabled: true\n"
        "- id: dsh-market\n  insert:\n    - id: dsh-market\n      name: dsh-market\n",
        encoding="utf-8")
    monkeypatch.setenv("DSH_HOME", str(home))
    return prof


class TestProtected:
    def test_host_infra_ids_protected(self):
        assert pl.protected("cordis:core")
        assert pl.protected("@deepseek-ai/dsh-web")
        assert pl.protected("@deepseek-ai/dsh-agent-presets")
        assert pl.protected("@deepseek-ai/dsh-session")

    def test_user_plugins_not_protected(self):
        assert not pl.protected("dsh-market")
        assert not pl.protected("dshmarket")
        assert not pl.protected("my-extension")
        assert not pl.protected(None)
        assert not pl.protected("")


class TestMergeEntries:
    def test_bundles_patch_insert_and_overlay(self, tmp_path, monkeypatch):
        _fake_profile(tmp_path, monkeypatch)
        entries = pl.merge_entries("web")
        by_id = {e["id"]: e for e in entries}
        # bundle 基线 + 版本来自 dependencies; patch 同名行覆盖后来源标记为 patch
        assert by_id["dshmarket"]["version"] == "1.0.0"
        assert by_id["dshmarket"]["disabled"] is True
        assert by_id["dshmarket"]["_src"] == "patch"
        # insert 行新增, 不与 bundles 重复
        assert by_id["dsh-market"]["_src"] == "patch"

    def test_missing_profile_yields_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DSH_HOME", str(tmp_path / "empty"))
        assert pl.merge_entries("web") == []


class TestLoadView:
    def test_payload_with_id_map(self, tmp_path, monkeypatch):
        _fake_profile(tmp_path, monkeypatch)
        monkeypatch.setattr(dsh_data, "load_entry_id_map",
                            lambda profile, dash_repo=None: {"dshmarket": "dsh-market"})
        r = pl.load_view(None, "web", None, "D:/repo")
        assert r["err"] == ""
        assert len(r["entries"]) == 3
        assert r["id_map"] == {"dshmarket": "dsh-market"}

    def test_remote_skips_dump_config(self, tmp_path, monkeypatch):
        _fake_profile(tmp_path, monkeypatch)
        called = []
        monkeypatch.setattr(dsh_data, "load_entry_id_map",
                            lambda *a, **k: called.append(1) or {})

        class FakeRemote:
            # 假远程: read_file 直读假 home(避免真 ssh), 只为走 remote 分支
            is_remote = True

            def read_file(self, rel):
                return (pathlib.Path(os.environ["DSH_HOME"]) / rel).read_text(
                    encoding="utf-8")

        r = pl.load_view(None, "web", FakeRemote(), "D:/repo")
        assert r["err"] == "" and r["id_map"] == {} and called == []
        assert len(r["entries"]) == 3

    def test_map_failure_degrades_to_empty(self, tmp_path, monkeypatch):
        _fake_profile(tmp_path, monkeypatch)

        def boom(*a, **k):
            raise OSError("pnpm missing")

        monkeypatch.setattr(dsh_data, "load_entry_id_map", boom)
        r = pl.load_view(None, "web", None, "D:/repo")
        assert r["err"] == "" and r["id_map"] == {}   # 映射失败不阻断列表

    def test_empty_profile_refused(self):
        r = pl.load_view(None, "  ", None, None)
        assert r["entries"] == [] and "profile 不能为空" in r["err"]


class TestSetDisabled:
    def test_disable_appends_row_with_bak(self, tmp_path, monkeypatch):
        prof = _fake_profile(tmp_path, monkeypatch)
        r = pl.set_disabled(None, "web", "my-ext", True)
        assert r["err"] == "" and "已停用 my-ext" in r["msg"]
        rows = dsh_data.read_cordis_patch("web")
        row = [x for x in rows if isinstance(x, dict) and x.get("id") == "my-ext"]
        assert row and row[0]["disabled"] is True
        assert os.path.isfile(str(prof / "cordis.patch.yml") + ".bak")

    def test_enable_removes_bare_row(self, tmp_path, monkeypatch):
        _fake_profile(tmp_path, monkeypatch)
        r = pl.set_disabled(None, "web", "dshmarket", False)
        assert r["err"] == "" and "已启用 dshmarket" in r["msg"]
        rows = dsh_data.read_cordis_patch("web")
        ids = [x.get("id") for x in rows if isinstance(x, dict)]
        # 只剩 id 的裸行整行删除, insert 行不受影响
        assert "dshmarket" not in ids
        assert "dsh-market" in ids

    def test_enable_keeps_row_with_other_keys(self, tmp_path, monkeypatch):
        _fake_profile(tmp_path, monkeypatch)
        pl.set_disabled(None, "web", "my-ext", True)
        r = pl.set_disabled(None, "web", "my-ext", False)
        assert r["err"] == ""
        # 该行无其它字段 -> 整行删除; patch 其余行保持
        rows = dsh_data.read_cordis_patch("web")
        assert all(x.get("id") != "my-ext" for x in rows if isinstance(x, dict))

    def test_protected_refused_in_core(self, tmp_path, monkeypatch):
        _fake_profile(tmp_path, monkeypatch)
        r = pl.set_disabled(None, "web", "@deepseek-ai/dsh-web", True)
        assert r["msg"] == "" and "宿主基础插件" in r["err"]

    def test_empty_args_refused(self, tmp_path, monkeypatch):
        _fake_profile(tmp_path, monkeypatch)
        assert "不能为空" in pl.set_disabled(None, "", "x", True)["err"]
        assert "不能为空" in pl.set_disabled(None, "web", "", True)["err"]
