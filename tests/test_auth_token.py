# -*- coding: utf-8 -*-
# test_auth_token.py - dsh 0.1.2+ 浏览器鉴权 Token 提取与信箱同步测试。

import os
import pytest
from core.dshctl import (
    extract_auth_token, get_runtime_token, set_runtime_token)
from core.tunnel_mgr import push_node_token, pull_node_token


class TestAuthTokenExtraction:
    def test_extract_from_full_url(self):
        line = "dsh web: http://127.0.0.1:3080/?token=abc1234567890defABCDEF_-xyz"
        tok, url = extract_auth_token(line)
        assert tok == "abc1234567890defABCDEF_-xyz"
        assert url == "http://127.0.0.1:3080/?token=abc1234567890defABCDEF_-xyz"

    def test_extract_from_localhost(self):
        line = "server ready at http://localhost:8090/?token=secret_token_123"
        tok, url = extract_auth_token(line)
        assert tok == "secret_token_123"
        assert url == "http://localhost:8090/?token=secret_token_123"

    def test_extract_query_param_only(self):
        line = "authenticated token is ?token=my_secret_token"
        tok, url = extract_auth_token(line)
        assert tok == "my_secret_token"
        assert url is None

    def test_no_token_returns_none(self):
        tok, url = extract_auth_token("normal server log message with no token")
        assert tok is None
        assert url is None

    def test_extract_with_ansi_escape_codes(self):
        line = "\x1b[32mdsh web: http://127.0.0.1:3080/?token=ansi_token_12345\x1b[0m"
        tok, url = extract_auth_token(line)
        assert tok == "ansi_token_12345"
        assert url == "http://127.0.0.1:3080/?token=ansi_token_12345"


class TestRuntimeTokenCache:
    def test_set_and_get(self):
        set_runtime_token("office", "tok_office_123")
        assert get_runtime_token("office") == "tok_office_123"
        set_runtime_token("lab", "tok_lab_456")
        assert get_runtime_token("lab") == "tok_lab_456"

    def test_chinese_node_name(self):
        set_runtime_token("实验室服务器", "tok_chinese_123")
        assert get_runtime_token("实验室服务器") == "tok_chinese_123"

    def test_invalid_node_returns_none(self):
        assert get_runtime_token("non_existent_node_xyz") is None


class TestTokenMailboxSecurity:
    def test_push_injection_guard(self):
        # 包含危险字符时直接拒绝执行
        assert push_node_token("127.0.0.1", "root", "node;rm -rf /", "token123") is False
        assert push_node_token("127.0.0.1", "root", "office", "tok'; DROP TABLE--") is False

    def test_pull_injection_guard(self):
        assert pull_node_token("127.0.0.1", "root", "node;cat /etc/passwd") is None


class TestOverviewDataLinks:
    def test_overview_local_and_remote_links(self, monkeypatch):
        from core.data import collect_overview_data
        from core.dshctl import set_runtime_token
        set_runtime_token("local", "tok_local_test")
        set_runtime_token("lab", "tok_lab_test")

        cfg = {
            "dash_port": 3080,
            "forward_ports": [8090, 8022],
            "local_name": "本机",
            "deployments": [
                {"name": "lab", "host": "1.2.3.4", "user": "test", "port": 22}
            ]
        }
        depls = cfg["deployments"]
        # smoke=True keeps it offline/dry-run
        payload = collect_overview_data(cfg, depls, smoke=True)
        assert len(payload["deploys"]) == 2
        # local
        loc = payload["deploys"][0]
        assert loc["local"] is True
        # remote
        rem = payload["deploys"][1]
        assert rem["local"] is False
        assert rem["token"] == "tok_lab_test"
        assert rem["auth_url"] == "http://127.0.0.1:8090/?token=tok_lab_test"
