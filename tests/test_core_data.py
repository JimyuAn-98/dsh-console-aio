# -*- coding: utf-8 -*-
# core/data.py 数据层单元测试。
# 覆盖: YAML 解析/序列化、路径定位、备份、会话/Profile/配置/用量统计/费用估算等纯函数。
# 依赖 fixture: tmp_path / fake_dsh_home / fake_profile (见 conftest.py)。

import os
import io
import json
import time
import datetime
import zipfile

import pytest


# ── YAML 解析 ──────────────────────────────────────────

class TestParseYamlText:
    """parse_yaml_text: 最小子集 YAML 解析器(缩进嵌套 dict/list/标量/注释)。"""

    def test_empty_input(self):
        from core.data import parse_yaml_text
        assert parse_yaml_text("") == {}
        assert parse_yaml_text("   ") == {}
        assert parse_yaml_text("# only comment") == {}

    def test_simple_dict(self):
        from core.data import parse_yaml_text
        raw = "name: test\nport: 3080\nenabled: true\n"
        d = parse_yaml_text(raw)
        assert d["name"] == "test"
        assert d["port"] == 3080
        assert d["enabled"] is True

    def test_nested_dict(self):
        from core.data import parse_yaml_text
        raw = "outer:\n  inner: value\n  count: 5\n"
        d = parse_yaml_text(raw)
        assert d["outer"]["inner"] == "value"
        assert d["outer"]["count"] == 5

    def test_list_scalar(self):
        from core.data import parse_yaml_text
        raw = "items:\n  - alpha\n  - beta\n  - gamma\n"
        d = parse_yaml_text(raw)
        assert d["items"] == ["alpha", "beta", "gamma"]

    def test_list_of_dicts(self):
        from core.data import parse_yaml_text
        raw = "entries:\n  - id: first\n    name: A\n  - id: second\n    name: B\n"
        d = parse_yaml_text(raw)
        assert len(d["entries"]) == 2
        assert d["entries"][0]["id"] == "first"
        assert d["entries"][1]["name"] == "B"

    def test_comment_stripping(self):
        from core.data import parse_yaml_text
        raw = "key: value  # this is comment\nother: 42\n"
        d = parse_yaml_text(raw)
        assert d["key"] == "value"
        assert d["other"] == 42

    def test_boolean_and_null(self):
        from core.data import parse_yaml_text
        raw = "a: true\nb: false\nc: null\nd: ~\n"
        d = parse_yaml_text(raw)
        assert d["a"] is True
        assert d["b"] is False
        assert d["c"] is None
        assert d["d"] is None

    def test_quoted_strings(self):
        from core.data import parse_yaml_text
        raw = 'q1: "hello world"\nq2: \'single quotes\'\n'
        d = parse_yaml_text(raw)
        assert d["q1"] == "hello world"
        assert d["q2"] == "single quotes"

    def test_float_value(self):
        from core.data import parse_yaml_text
        raw = "ratio: 3.14\n"
        d = parse_yaml_text(raw)
        assert d["ratio"] == pytest.approx(3.14)

    def test_key_with_colon_in_value(self):
        from core.data import parse_yaml_text
        raw = 'url: "http://example.com"\n'
        d = parse_yaml_text(raw)
        assert d["url"] == "http://example.com"

    def test_complex_cordis_style(self):
        """模拟真实 cordis.yml 结构。"""
        from core.data import parse_yaml_text
        raw = (
            "- id: core\n"
            "  name: @deepseek-ai/core\n"
            "  description: 核心插件\n"
            "- id: market\n"
            "  name: dsh-market\n"
            "  disabled: true\n"
        )
        d = parse_yaml_text(raw)
        assert isinstance(d, list)
        assert len(d) == 2
        assert d[0]["id"] == "core"
        assert d[1]["disabled"] is True

    def test_list_item_multi_fields(self):
        """list item 含多个同级字段(id + name + description)时应全部收集。"""
        from core.data import parse_yaml_text
        raw = (
            "- id: core\n"
            "  name: @deepseek-ai/core\n"
            "  description: 核心插件\n"
            "- id: market\n"
            "  name: dsh-market\n"
        )
        d = parse_yaml_text(raw)
        assert d[0]["id"] == "core"
        assert d[0]["name"] == "@deepseek-ai/core"
        assert d[0]["description"] == "核心插件"
        assert d[1]["name"] == "dsh-market"

    def test_list_item_with_nested_insert(self):
        """cordis.patch.yml 的 insert 嵌套结构。"""
        from core.data import parse_yaml_text
        raw = (
            "- id: dsh-market\n"
            "  insert:\n"
            "    - id: dsh-market\n"
            "      name: dsh-market\n"
            "      description: 插件市场\n"
        )
        d = parse_yaml_text(raw)
        assert isinstance(d, list)
        assert len(d) == 1
        assert d[0]["id"] == "dsh-market"
        insert = d[0]["insert"]
        assert isinstance(insert, list)
        assert insert[0]["id"] == "dsh-market"
        assert insert[0]["name"] == "dsh-market"
        assert insert[0]["description"] == "插件市场"


# ── YAML 序列化 ─────────────────────────────────────────

class TestDumpYaml:
    """_dump_yaml + write_yaml: 序列化回 YAML 格式。"""

    def test_simple_dict(self):
        from core.data import _dump_yaml
        lines = _dump_yaml({"name": "test", "port": 3080})
        text = "\n".join(lines)
        assert "name: test" in text
        assert "port: 3080" in text

    def test_nested_dict(self):
        from core.data import _dump_yaml
        lines = _dump_yaml({"outer": {"inner": "value"}})
        text = "\n".join(lines)
        assert "outer:" in text
        assert "inner: value" in text

    def test_list_of_scalars(self):
        from core.data import _dump_yaml
        lines = _dump_yaml({"items": ["a", "b", "c"]})
        text = "\n".join(lines)
        assert "- a" in text
        assert "- b" in text

    def test_roundtrip_simple(self):
        """简单 dict 序列化再解析应保持一致。"""
        from core.data import parse_yaml_text, _dump_yaml
        original = {"name": "test", "port": 3080, "enabled": True}
        lines = _dump_yaml(original)
        restored = parse_yaml_text("\n".join(lines) + "\n")
        for k, v in original.items():
            assert restored.get(k) == v, "roundtrip 失败: %s=%s -> %s" % (k, v, restored.get(k))

    def test_roundtrip_with_list(self):
        """含列表的 dict 序列化再解析。"""
        from core.data import parse_yaml_text, _dump_yaml
        original = {"tags": ["alpha", "beta"]}
        lines = _dump_yaml(original)
        restored = parse_yaml_text("\n".join(lines) + "\n")
        assert restored["tags"] == ["alpha", "beta"]

    def test_write_yaml_creates_file(self, tmp_path):
        from core.data import write_yaml
        p = str(tmp_path / "test.yml")
        write_yaml(p, {"hello": "world"})
        assert os.path.isfile(p)
        with open(p, encoding="utf-8") as f:
            content = f.read()
        assert "hello: world" in content

    def test_write_yaml_creates_backup(self, tmp_path):
        from core.data import write_yaml
        p = str(tmp_path / "test.yml")
        # 先写一个旧文件
        with open(p, "w", encoding="utf-8") as f:
            f.write("old: data\n")
        write_yaml(p, {"new": "data"})
        bak = p + ".bak"
        assert os.path.isfile(bak)
        with open(bak, encoding="utf-8") as f:
            assert "old: data" in f.read()

    def test_write_yaml_empty_list_is_valid_array(self, tmp_path):
        # BUG-001 回归: 空 list 不能写成空文件(空文档解析为 null, dsh patch 层拒绝加载)
        from core.data import write_yaml
        p = str(tmp_path / "patch.yml")
        write_yaml(p, [])
        with open(p, "rb") as f:
            assert f.read() == b"[]\n"

    def test_write_yaml_empty_dict_is_valid_mapping(self, tmp_path):
        from core.data import write_yaml
        p = str(tmp_path / "settings.yml")
        write_yaml(p, {})
        with open(p, "rb") as f:
            assert f.read() == b"{}\n"

    def test_special_chars_quoted(self):
        """包含 : # \n 的值应被引号包裹。"""
        from core.data import _dump_scalar
        assert _dump_scalar("has:colon") == '"has:colon"'
        assert _dump_scalar("has#hash") == '"has#hash"'


# ── dir_stats 会话大小 ───────────────────────────────────

class TestDirStats:
    """DshRemote.dir_stats 本地分支: 嵌套目录大小统计。"""

    def test_nested_dirs_counted(self, tmp_path, monkeypatch):
        # 回归: 会话目录是 组/会话/文件 三层, 旧实现只数直接文件 -> total 恒 0
        from core import data as d
        base = tmp_path / "sessions"
        (base / "g1" / "s1").mkdir(parents=True)
        (base / "g1" / "s1" / "a.jsonl").write_bytes(b"x" * 100)
        (base / "g1" / "s2").mkdir()
        (base / "g1" / "s2" / "b.jsonl").write_bytes(b"x" * 30)
        (base / "g1" / "empty").mkdir()
        monkeypatch.setenv("DSH_HOME", str(tmp_path))
        st = d.DshRemote(None).dir_stats("sessions")
        assert st["total"] == 130
        assert st["dirs"]["g1"] == 130   # 空嵌套目录不影响合计

    def test_missing_dir_zero(self, tmp_path, monkeypatch):
        from core import data as d
        monkeypatch.setenv("DSH_HOME", str(tmp_path))
        st = d.DshRemote(None).dir_stats("nope")
        assert st == {"dirs": {}, "total": 0}


# ── dump-config 解析 ─────────────────────────────────────

class TestDumpEntryStates:
    """dump_entry_states: dump-config 输出 -> id 映射 + cordis 生效状态(逐行缩进栈解析)。"""

    # 仿真 dump-config 输出: # == 分组注释 + js-yaml 缩进 2 的条目列表,
    # 覆盖 config 同名键噪音 / 嵌套 group 子条目 / group 尾部字段 / !!js 表达式
    FAKE_DUMP = (
        "# == @deepseek-ai/dsh-base\n"
        "- id: webserver\n"
        "  name: '@deepseek-ai/dsh-web'\n"
        "  config:\n"
        "    port: 3080\n"
        "    disabled: true\n"
        "- id: hmr\n"
        "  name: cordis:@deepseek-ai/cordis-plugin-hmr\n"
        "# == dshmarket\n"
        "- id: dsh-market\n"
        "  name: dshmarket\n"
        "- id: group-x\n"
        "  group: true\n"
        "  disabled: false\n"
        "  config:\n"
        "    - id: inner-1\n"
        "      name: inner-one\n"
        "      disabled: true\n"
        "    - id: inner-2\n"
        "      name: inner-two\n"
        "- id: jsentry\n"
        "  name: js-one\n"
        "  disabled: !!js process.env.FOO\n"
    )

    def _parse(self, monkeypatch):
        from core import data as d
        monkeypatch.setattr(d, "_dump_config_output",
                            lambda profile, dash_repo=None, remote=None: self.FAKE_DUMP)
        return d.dump_entry_states("web", "D:/repo")

    def test_id_map_and_states(self, monkeypatch):
        r = self._parse(monkeypatch)
        assert r["id_map"]["dshmarket"] == "dsh-market"
        assert r["id_map"]["dsh-market"] == "dsh-market"   # entry id 自映射
        assert r["id_map"]["@deepseek-ai/dsh-web"] == "webserver"
        assert r["states"]["dsh-market"]["disabled"] is False

    def test_config_disabled_key_not_attributed(self, monkeypatch):
        # webserver 的 config 里恰好叫 disabled 的键是配置内容, 不是 entry 字段
        r = self._parse(monkeypatch)
        assert r["states"]["webserver"]["disabled"] is False

    def test_nested_group_children_and_tail_field(self, monkeypatch):
        # 嵌套子条目各自归属; group 尾部 disabled(缩进 2)不被深层子条目吃掉
        r = self._parse(monkeypatch)
        assert r["states"]["inner-1"]["disabled"] is True
        assert r["states"]["inner-2"]["disabled"] is False
        assert r["id_map"]["inner-one"] == "inner-1"
        assert r["states"]["group-x"]["disabled"] is False

    def test_js_expression_disabled_counts_false(self, monkeypatch):
        r = self._parse(monkeypatch)
        assert r["states"]["jsentry"]["disabled"] is False
        assert r["id_map"]["js-one"] == "jsentry"

    def test_dump_failure_yields_empty(self, monkeypatch):
        from core import data as d
        monkeypatch.setattr(d, "_dump_config_output", lambda *a, **k: "")
        assert d.dump_entry_states("web") == {"id_map": {}, "states": {}}

    def test_yaml_blocks(self, monkeypatch):
        # 配置栏数据源: 每条 entry 的原始 YAML 块(到下一个不深于它的 entry 前)
        r = self._parse(monkeypatch)
        assert r["states"]["webserver"]["yaml"] == (
            "- id: webserver\n"
            "  name: '@deepseek-ai/dsh-web'\n"
            "  config:\n"
            "    port: 3080\n"
            "    disabled: true")
        # 父 entry 块包含嵌套子条目; # == 分组注释不进块
        assert "- id: inner-1" in r["states"]["group-x"]["yaml"]
        assert "# ==" not in r["states"]["group-x"]["yaml"]
        assert r["states"]["dsh-market"]["yaml"] == "- id: dsh-market\n  name: dshmarket"


# ── 路径定位 ──────────────────────────────────────────

class TestPaths:
    def test_dsh_home_default(self, monkeypatch):
        from core.data import dsh_home
        monkeypatch.delenv("DSH_HOME", raising=False)
        result = dsh_home()
        assert result.endswith(".dsh")
        assert os.path.expanduser("~") in result

    def test_dsh_home_env_override(self, monkeypatch, tmp_path):
        from core.data import dsh_home
        monkeypatch.setenv("DSH_HOME", str(tmp_path / "custom"))
        assert dsh_home() == str(tmp_path / "custom")

    def test_profiles_dir(self, monkeypatch, tmp_path):
        from core.data import profiles_dir
        monkeypatch.setenv("DSH_HOME", str(tmp_path))
        assert profiles_dir() == os.path.join(str(tmp_path), "profiles")

    def test_sessions_dir(self, monkeypatch, tmp_path):
        from core.data import sessions_dir
        monkeypatch.setenv("DSH_HOME", str(tmp_path))
        assert sessions_dir() == os.path.join(str(tmp_path), "sessions")


# ── 备份 ──────────────────────────────────────────────

class TestBackup:
    def test_backup_creates_bak(self, tmp_path):
        from core.data import backup_file
        p = str(tmp_path / "data.json")
        with open(p, "w") as f:
            f.write('{"v":1}')
        bak = backup_file(p)
        assert bak == p + ".bak"
        assert os.path.isfile(bak)

    def test_backup_nonexistent(self, tmp_path):
        from core.data import backup_file
        bak = backup_file(str(tmp_path / "missing.txt"))
        assert bak is None

    def test_backup_overwrites_old(self, tmp_path):
        from core.data import backup_file
        p = str(tmp_path / "data.json")
        bak = p + ".bak"
        with open(p, "w") as f:
            f.write("v2")
        with open(bak, "w") as f:
            f.write("old_backup")
        backup_file(p)
        with open(bak) as f:
            assert f.read() == "v2"


# ── 会话 / 工作区 ─────────────────────────────────────

class TestWorkspace:
    def test_read_workspace(self, fake_dsh_home, monkeypatch):
        from core.data import read_workspace
        monkeypatch.setenv("DSH_HOME", fake_dsh_home)
        ws = read_workspace()
        assert "workspaceIds" in ws
        assert "archivedSessionIds" in ws

    def test_read_workspace_missing_file(self, fake_dsh_home, monkeypatch):
        from core.data import read_workspace
        monkeypatch.setenv("DSH_HOME", fake_dsh_home)
        os.remove(os.path.join(fake_dsh_home, "storages", "workspace.json"))
        ws = read_workspace()
        assert isinstance(ws, dict)

    def test_list_sessions_empty(self, fake_dsh_home, monkeypatch):
        from core.data import list_sessions
        monkeypatch.setenv("DSH_HOME", fake_dsh_home)
        result = list_sessions()
        assert isinstance(result, list)

    def test_list_sessions_with_data(self, fake_dsh_home, monkeypatch):
        from core.data import list_sessions
        monkeypatch.setenv("DSH_HOME", fake_dsh_home)
        # 创建一个会话目录结构
        sess_dir = os.path.join(fake_dsh_home, "sessions", "work-abc", "sess-001")
        os.makedirs(sess_dir)
        with open(os.path.join(sess_dir, "meta.json"), "w") as f:
            f.write('{"id":"sess-001"}')
        result = list_sessions()
        assert len(result) == 1
        assert result[0]["workdir"] == "work-abc"
        assert result[0]["count"] == 1


# ── Profile / 插件 ────────────────────────────────────

class TestProfiles:
    def test_list_profiles(self, fake_dsh_home, monkeypatch):
        from core.data import list_profiles
        monkeypatch.setenv("DSH_HOME", fake_dsh_home)
        # 创建 profile 目录
        prof = os.path.join(fake_dsh_home, "profiles", "web")
        os.makedirs(prof)
        with open(os.path.join(prof, "cordis.yml"), "w") as f:
            f.write("- id: core\n")
        result = list_profiles()
        names = [p["name"] for p in result]
        assert "web" in names
        web = [p for p in result if p["name"] == "web"][0]
        assert web["cordis"] is True

    def test_read_cordis(self, fake_profile, monkeypatch):
        from core.data import read_cordis
        monkeypatch.setenv("DSH_HOME", fake_profile)
        entries = read_cordis("web")
        assert len(entries) == 2
        assert entries[0]["id"] == "core"

    def test_read_cordis_patch(self, fake_profile, monkeypatch):
        from core.data import read_cordis_patch
        monkeypatch.setenv("DSH_HOME", fake_profile)
        entries = read_cordis_patch("web")
        assert len(entries) == 2
        assert entries[0]["disabled"] is True

    def test_read_profile_package(self, fake_profile, monkeypatch):
        from core.data import read_profile_package
        monkeypatch.setenv("DSH_HOME", fake_profile)
        pkg = read_profile_package("web")
        assert "@deepseek-ai/core" in pkg["dependencies"]
        assert pkg["dependencies"]["@deepseek-ai/core"] == "1.0.0"
        assert "@deepseek-ai/core" in pkg["bundles"]

    def test_write_cordis_patch(self, fake_profile, monkeypatch):
        from core.data import write_cordis_patch, read_cordis_patch
        monkeypatch.setenv("DSH_HOME", fake_profile)
        new_entries = [{"id": "ext", "disabled": True}]
        write_cordis_patch("web", new_entries)
        restored = read_cordis_patch("web")
        assert len(restored) == 1
        assert restored[0]["id"] == "ext"
        # 检查 backup 被创建
        bak = os.path.join(fake_profile, "profiles", "web", "cordis.patch.yml.bak")
        assert os.path.isfile(bak)


# ── settings.yaml ─────────────────────────────────────

class TestSettings:
    def test_read_settings(self, fake_dsh_home, monkeypatch):
        from core.data import read_settings
        monkeypatch.setenv("DSH_HOME", fake_dsh_home)
        settings = read_settings()
        assert isinstance(settings, dict)

    def test_write_and_read_settings(self, fake_dsh_home, monkeypatch):
        from core.data import read_settings, write_settings
        monkeypatch.setenv("DSH_HOME", fake_dsh_home)
        data = {"agent-default-model": {"provider": "deepseek-official", "model": "deepseek-v4-flash"}}
        write_settings(data)
        restored = read_settings()
        assert restored["agent-default-model"]["model"] == "deepseek-v4-flash"

    def test_write_settings_backup(self, fake_dsh_home, monkeypatch):
        from core.data import write_settings
        monkeypatch.setenv("DSH_HOME", fake_dsh_home)
        with open(os.path.join(fake_dsh_home, "settings.yaml"), "w", encoding="utf-8") as f:
            f.write("old: value\n")
        write_settings({"new": "data"})
        bak = os.path.join(fake_dsh_home, "settings.yaml.bak")
        assert os.path.isfile(bak)


# ── 任务看板 ──────────────────────────────────────────

class TestTaskboard:
    def test_read_taskboard_empty(self, fake_dsh_home, monkeypatch):
        from core.data import read_taskboard
        monkeypatch.setenv("DSH_HOME", fake_dsh_home)
        result = read_taskboard()
        assert "ledger" in result
        assert "scheduler" in result

    def test_read_taskboard_with_data(self, fake_dsh_home, monkeypatch):
        from core.data import read_taskboard
        monkeypatch.setenv("DSH_HOME", fake_dsh_home)
        ledger = {"tasks": [{"id": "t1", "name": "test"}]}
        with open(os.path.join(fake_dsh_home, "task-board", "ledger-v2.json"), "w") as f:
            json.dump(ledger, f)
        result = read_taskboard()
        assert len(result["ledger"]["tasks"]) == 1


# ── 用量统计 ──────────────────────────────────────────

class TestUsageStats:
    def test_usage_stats_no_sessions(self, fake_dsh_home, monkeypatch):
        from core.data import usage_stats
        monkeypatch.setenv("DSH_HOME", fake_dsh_home)
        result = usage_stats()
        assert result["ok"] is True
        assert result["sessions"] == 0
        assert result["models"] == {}

    def test_usage_stats_without_zstd(self, fake_dsh_home, monkeypatch):
        """没有 zstandard 库时应返回明确错误。"""
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "zstandard":
                raise ImportError("mock missing")
            return real_import(name, *args, **kwargs)

        monkeypatch.setenv("DSH_HOME", fake_dsh_home)
        monkeypatch.setattr(builtins, "__import__", mock_import)
        # 需要清除缓存
        from core import data as dsh_data
        monkeypatch.setattr(dsh_data, "zstd_available", lambda: False)
        result = dsh_data.usage_stats()
        assert result["ok"] is False
        assert "zstandard" in result["error"]


# ── 费用估算 ──────────────────────────────────────────

class TestCostEstimation:
    def test_estimate_cost_known_model(self):
        from core.data import estimate_cost
        # deepseek-v4-flash 空闲: in_miss=1.5, out=4.5, in_cached=0.05
        # 1000 in, 500 out, 0 cache => 1000/1M*1.5 + 500/1M*4.5 = 0.0015 + 0.00225 = 0.00375
        cost = estimate_cost("deepseek-v4-flash", 1000, 500, 0)
        assert cost is not None
        assert cost > 0

    def test_estimate_cost_with_cache(self):
        from core.data import estimate_cost
        # 1000 in, 500 out, 800 cache => miss=200
        cost = estimate_cost("deepseek-v4-flash", 1000, 500, 800)
        assert cost is not None
        # 应该比无缓存便宜(200 miss vs 1000 miss)
        cost_no_cache = estimate_cost("deepseek-v4-flash", 1000, 500, 0)
        assert cost < cost_no_cache

    def test_estimate_cost_unknown_model(self):
        from core.data import estimate_cost
        cost = estimate_cost("gpt-4-turbo", 1000, 500, 0)
        assert cost is None

    def test_estimate_cost_zero_tokens(self):
        from core.data import estimate_cost
        cost = estimate_cost("deepseek-v4-flash", 0, 0, 0)
        assert cost == 0.0

    def test_estimate_cost_custom_prices(self):
        from core.data import estimate_cost
        prices = {"my-model": {"in_cached": [1.0, 2.0], "in_miss": [3.0, 4.0], "out": [5.0, 6.0]}}
        cost = estimate_cost("my-model", 1000000, 0, 0, prices=prices)
        assert cost == pytest.approx(3.0)  # 1M * 3.0/M = 3.0


class TestIsPeakHour:
    def test_weekday_peak_morning(self):
        from core.data import is_peak_hour
        # 周一 10:00
        dt = datetime.datetime(2025, 1, 6, 10, 0)  # Monday
        assert is_peak_hour(dt) is True

    def test_weekday_peak_afternoon(self):
        from core.data import is_peak_hour
        dt = datetime.datetime(2025, 1, 6, 15, 0)  # Monday 15:00
        assert is_peak_hour(dt) is True

    def test_weekday_off_peak(self):
        from core.data import is_peak_hour
        dt = datetime.datetime(2025, 1, 6, 20, 0)  # Monday 20:00
        assert is_peak_hour(dt) is False

    def test_weekend_not_peak(self):
        from core.data import is_peak_hour
        dt = datetime.datetime(2025, 1, 4, 10, 0)  # Saturday
        assert is_peak_hour(dt) is False

    def test_weekday_gap(self):
        from core.data import is_peak_hour
        dt = datetime.datetime(2025, 1, 6, 13, 0)  # Monday 13:00 (午休)
        assert is_peak_hour(dt) is False


# ── 部署 ──────────────────────────────────────────────

class TestDeployments:
    def test_load_deployments_no_config(self, monkeypatch):
        """config.json 不存在时返回空列表。"""
        from core.data import load_deployments
        monkeypatch.setattr("core.data.os.path.dirname", lambda x: "/nonexistent")
        result = load_deployments()
        assert isinstance(result, list)

    def test_load_deployments_with_data(self, tmp_path):
        """有 deployments 数组时正确读取。"""
        from core.data import load_deployments
        import core.data as dd
        # 临时覆盖 __file__ 路径(阶段4 后 _config_path 在 core.data, 按其 __file__ 定位)
        cfg = {"deployments": [
            {"name": "lab", "host": "192.168.1.100", "user": "admin", "port": 22}
        ]}
        cfg_path = os.path.join(str(tmp_path), "config.json")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        old = dd.__file__
        dd.__file__ = os.path.join(str(tmp_path), "data.py")
        try:
            result = load_deployments()
            assert len(result) == 1
            assert result[0]["name"] == "lab"
        finally:
            dd.__file__ = old

    def test_save_and_load_deployments(self, tmp_path):
        from core.data import save_deployments, load_deployments
        import core.data as dd
        cfg_path = os.path.join(str(tmp_path), "config.json")
        with open(cfg_path, "w") as f:
            json.dump({}, f)
        old = dd.__file__
        dd.__file__ = os.path.join(str(tmp_path), "data.py")
        try:
            depls = [{"name": "test", "host": "1.2.3.4", "user": "u", "port": 22}]
            save_deployments(depls)
            loaded = load_deployments()
            assert len(loaded) == 1
            assert loaded[0]["name"] == "test"
            # 检查 backup
            assert os.path.isfile(cfg_path + ".bak")
        finally:
            dd.__file__ = old


# ── DshRemote (本机模式) ──────────────────────────────

class TestDshRemoteLocal:
    def test_read_file(self, fake_dsh_home, monkeypatch):
        from core.data import DshRemote
        monkeypatch.setenv("DSH_HOME", fake_dsh_home)
        # 写一个测试文件
        with open(os.path.join(fake_dsh_home, "test.txt"), "w", encoding="utf-8") as f:
            f.write("hello world")
        remote = DshRemote(None)
        content = remote.read_file("test.txt")
        assert content == "hello world"

    def test_list_dir(self, fake_dsh_home, monkeypatch):
        from core.data import DshRemote
        monkeypatch.setenv("DSH_HOME", fake_dsh_home)
        remote = DshRemote(None)
        items = remote.list_dir("profiles")
        assert isinstance(items, list)

    def test_list_dir_nonexistent(self, fake_dsh_home, monkeypatch):
        from core.data import DshRemote
        monkeypatch.setenv("DSH_HOME", fake_dsh_home)
        remote = DshRemote(None)
        items = remote.list_dir("nonexistent_dir")
        assert items == []

    def test_dir_stats(self, fake_dsh_home, monkeypatch):
        from core.data import DshRemote
        monkeypatch.setenv("DSH_HOME", fake_dsh_home)
        # 创建一些文件
        d = os.path.join(fake_dsh_home, "sessions", "group1")
        os.makedirs(d)
        with open(os.path.join(d, "a.txt"), "w") as f:
            f.write("x" * 100)
        remote = DshRemote(None)
        stats = remote.dir_stats("sessions")
        assert "dirs" in stats
        assert "total" in stats
        assert stats["total"] >= 100

    def test_is_remote_false(self):
        from core.data import DshRemote
        r = DshRemote(None)
        assert r.is_remote is False

    def test_is_remote_true(self):
        from core.data import DshRemote
        r = DshRemote({"host": "1.2.3.4", "user": "test"})
        assert r.is_remote is True


# ── Agent 预设 ─────────────────────────────────────────

class TestAgentPresets:
    def test_list_agent_presets_empty(self, fake_dsh_home, monkeypatch):
        from core.data import list_agent_presets
        monkeypatch.setenv("DSH_HOME", fake_dsh_home)
        result = list_agent_presets()
        assert isinstance(result, list)

    def test_list_agent_presets_with_data(self, fake_dsh_home, monkeypatch):
        from core.data import list_agent_presets
        monkeypatch.setenv("DSH_HOME", fake_dsh_home)
        preset_dir = os.path.join(fake_dsh_home, ".agent-presets", "my-preset")
        os.makedirs(preset_dir)
        with open(os.path.join(preset_dir, "preset.yml"), "w", encoding="utf-8") as f:
            f.write("description: 测试预设\n")
        result = list_agent_presets()
        assert len(result) == 1
        assert result[0]["name"] == "my-preset"
        assert "测试" in result[0]["desc"]


# ── 备份全量 ──────────────────────────────────────────

class TestBackupDshHome:
    def test_backup_creates_zip(self, fake_dsh_home, monkeypatch, tmp_path):
        from core.data import backup_dsh_home
        monkeypatch.setenv("DSH_HOME", fake_dsh_home)
        # 写一些文件
        with open(os.path.join(fake_dsh_home, "settings.yaml"), "w") as f:
            f.write("test: data\n")
        with open(os.path.join(fake_dsh_home, ".credentials.yaml"), "w") as f:
            f.write("secret: key\n")  # 应被排除
        zip_path = str(tmp_path / "backup.zip")
        count = backup_dsh_home(zip_path)
        assert count > 0
        assert os.path.isfile(zip_path)
        # 验证 credentials 被排除
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
            assert not any("credentials" in n for n in names)


# ── SSH 命令组装 ──────────────────────────────────────

class TestSshBase:
    def test_ssh_base(self):
        from core.data import _ssh_base
        cmd = _ssh_base("1.2.3.4", "admin", 22)
        assert "ssh" in cmd
        assert "admin@1.2.3.4" in cmd
        assert "-p" in cmd
        assert "22" in cmd

    def test_ssh_base_custom_port(self):
        from core.data import _ssh_base
        cmd = _ssh_base("host.example.com", "user", 2222)
        assert "2222" in cmd
        assert "user@host.example.com" in cmd


# ── plugin_cmd ─────────────────────────────────────────

class TestPluginCmd:
    def test_plugin_cmd_add(self):
        from core.data import plugin_cmd
        cmd = plugin_cmd("web", "add", "my-plugin")
        assert cmd == ["pnpm.cmd", "dsh", "plugin", "--profile", "web", "add", "my-plugin"]

    def test_plugin_cmd_remove(self):
        from core.data import plugin_cmd
        cmd = plugin_cmd("default", "remove", "old-plugin")
        assert "remove" in cmd
        assert "--profile" in cmd


class TestDefaultConfigPath:
    """default_config_path: 源码运行=仓库根/config.json(frozen 分支无法离线模拟, 打包验证)。"""

    def test_source_mode_repo_root(self):
        from core import config as dsh_config
        import core
        expect = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(core.__file__))),
                              "config.json")
        assert dsh_config.default_config_path() == expect
