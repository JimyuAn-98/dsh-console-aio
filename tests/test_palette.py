# -*- coding: utf-8 -*-
# test_palette.py - 命令面板过滤/排序纯函数单测(不构造窗口)。

from ui.palette import rank_commands

_CMDS = [
    {"title": "页面: 总览", "meta": "跳转", "run": None},
    {"title": "页面: 模型用量", "meta": "跳转", "run": None},
    {"title": "部署: 本机", "meta": "切换部署", "run": None},
    {"title": "动作: 立即刷新", "meta": "refresh", "run": None},
]


def test_empty_query_returns_all():
    assert rank_commands(_CMDS, "") == _CMDS
    assert rank_commands(_CMDS, "   ") == _CMDS


def test_substring_and_case_insensitive():
    out = rank_commands(_CMDS, "用量")
    assert len(out) == 1 and out[0]["title"] == "页面: 模型用量"
    out = rank_commands(_CMDS, "REFRESH")
    assert len(out) == 1 and out[0]["title"] == "动作: 立即刷新"


def test_prefix_ranks_first():
    # "页" 前缀命中所有"页面:"行且排前; "部署"行不含"页"被过滤
    out = rank_commands(_CMDS, "页")
    assert [c["title"] for c in out] == ["页面: 总览", "页面: 模型用量"]


def test_meta_match_and_no_hit():
    assert len(rank_commands(_CMDS, "切换")) == 1     # meta 含"切换部署"
    assert rank_commands(_CMDS, "不存在的命令") == []
