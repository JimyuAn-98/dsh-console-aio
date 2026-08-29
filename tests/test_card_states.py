# -*- coding: utf-8 -*-
# test_card_states.py - 隧道卡片状态映射纯函数测试(不构造 MainWindow, 不碰真实资源)。
# 被测对象: dsh-console-aio.card_states_from_monitor —— 监控探测结果 -> 卡片状态。
# 模块导入在假 DSH_AIO_CONFIG 下进行(模块级只读假配置, 不启动任何线程/窗口)。

import os
import sys
import importlib
import importlib.util

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def mod(tmp_path_factory):
    cfg = tmp_path_factory.mktemp("card-cfg") / "config.json"
    cfg.write_text("{}", encoding="utf-8")
    os.environ["DSH_AIO_CONFIG"] = str(cfg)
    try:
        spec = importlib.util.spec_from_file_location(
            "dsh_console_aio", os.path.join(ROOT_DIR, "dsh-console-aio.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    finally:
        os.environ.pop("DSH_AIO_CONFIG", None)


class TestCardStatesFromMonitor:
    def test_dsh_web_follows_local_port(self, mod):
        local = {3080: (True, 3), 8090: (False, -1), 3090: (False, -1)}
        s = mod.card_states_from_monitor(local, {}, {"reverse_port": 8091})
        assert s["dsh-web"] is True
        assert s["dsh-tunnel"] is False
        assert s["connect-lab-dsh"] is False

    def test_local_down_reports_false(self, mod):
        local = {3080: (False, -1), 8090: (True, 5), 3090: (True, 5)}
        s = mod.card_states_from_monitor(local, {}, {})
        assert s["dsh-web"] is False
        assert s["dsh-tunnel"] is True
        assert s["connect-lab-dsh"] is True

    def test_reverse_from_remote_probe(self, mod):
        s = mod.card_states_from_monitor({}, {8091: True}, {"reverse_port": 8091})
        assert s["dsh-tunnel-reverse"] is True
        s2 = mod.card_states_from_monitor({}, {8091: False}, {"reverse_port": 8091})
        assert s2["dsh-tunnel-reverse"] is False

    def test_no_remote_data_keeps_reverse_unknown(self, mod):
        # remote 为 None(探测失败)时不下结论, key 不出现。
        s = mod.card_states_from_monitor({}, None, {"reverse_port": 8091})
        assert "dsh-tunnel-reverse" not in s

    def test_no_probe_data_no_crash(self, mod):
        s = mod.card_states_from_monitor(None, None, {})
        assert s == {"dsh-web": False, "dsh-tunnel": False, "connect-lab-dsh": False}


class TestBuildItems:
    # P0: 卡片清单的命名来自配置(local/lab/ssh 三处可自定义)
    def test_custom_names_used(self, mod):
        items = mod.build_items({"local_name": "家里", "lab_name": "机房",
                                 "ssh_name": "中转", "dash_port": 3080})
        d = {i["key"]: i for i in items}
        assert d["dsh-web"]["title"] == "家里 dsh"
        assert "机房" in d["connect-lab-dsh"]["desc"]
        assert "中转" in d["dsh-tunnel-reverse"]["desc"]
        assert "家里" in d["dsh-tunnel-reverse"]["desc"]

    def test_default_names(self, mod):
        items = mod.build_items({})
        d = {i["key"]: i for i in items}
        assert d["dsh-web"]["title"] == "本机 dsh"
        assert "实验室" in d["connect-lab-dsh"]["desc"]
        assert "公网中转" in d["dsh-tunnel-reverse"]["desc"]

    def test_all_five_cards(self, mod):
        items = mod.build_items({})
        assert [i["key"] for i in items] == [
            "dsh-web", "dsh-tunnel", "connect-lab-dsh", "dsh-tunnel-reverse", "update-dsh"]
