# -*- coding: utf-8 -*-
# core/data.py deployment_access_port 单元测试(纯函数)。
# 覆盖: 显式 access_port > 关联隧道 > web_port > port(非22) > host 命中隧道 >
# forward_ports > lab_port/dash_port 的优先级与非法入参。

from core.data import deployment_access_port as ap

CFG = {
    "dash_port": 3080, "lab_port": 3090, "forward_ports": [8090, 8022, 8091],
    "tunnels": [{"id": "t_lab", "mode": "forward", "host": "h1",
                 "forwards": [{"local_port": 3090, "remote_port": 3090}]}],
}


class TestDeploymentAccessPort:
    def test_explicit_access_port_wins(self):
        assert ap({"access_port": 4000, "web_port": 3090}, CFG) == 4000

    def test_tunnel_id_local_port(self):
        assert ap({"tunnel_id": "t_lab"}, CFG) == 3090

    def test_web_port(self):
        assert ap({"web_port": 3500}, CFG) == 3500

    def test_port_field_non_22(self):
        assert ap({"port": 2222}, CFG) == 2222

    def test_host_match_forward_tunnel(self):
        assert ap({"host": "h1"}, CFG) == 3090

    def test_fallbacks(self):
        assert ap({}, CFG) == 8090                       # forward_ports[0]
        assert ap({}, {"forward_ports": [], "lab_port": 3090}) == 3090
        assert ap({"port": 22}, {}) == 3080              # 22 不算 + 兜底 3080

    def test_non_dict_returns_none(self):
        assert ap(None, CFG) is None
        assert ap("x", CFG) is None
