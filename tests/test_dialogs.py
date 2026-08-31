# -*- coding: utf-8 -*-
# ui/pages_settings.py 设置页 + DSH 管理页(弹窗收敛后: 环境检查/安装向导页面内分步)测试。
# 验证: SettingsPage 构造/模板/保存合并 + DshManagePage 环境表/安装向导构造冒烟。
# 环境: QT_QPA_PLATFORM=offscreen; 配置读写/后台读/网络 monkeypatch 拦截, 绝不落真实资源。

import os

import pytest

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp_mod():
    """模块级 QApplication。"""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class _FakeApp:
    # 设置页依赖的最小 app: 热重载调用记账
    _pending_settings_tab = None

    def __init__(self):
        self.reloaded = False

    def reload_config(self):
        self.reloaded = True

    def loge(self, *a):
        pass

    def log(self, *a):
        pass


class TestSettingsPage:
    """SettingsPage: 配置弹窗标签化(A1)后的构造/模板/保存合并。"""

    CFG = {
        "ssh_server": "YOUR_PUBLIC_IP", "ssh_user": "YOUR_USER",
        "dash_repo": "D:/x", "dash_port": 3080,
        "dash_cmd": ["pnpm.cmd", "dsh", "web"],
        "forward_ports": [8090, 8022, 8091], "lab_server": "", "lab_user": "",
        "lab_port": 3090, "reverse_port": 8091, "poll_seconds": 4,
        "remote_poll_seconds": 20, "local_name": "本机", "lab_name": "实验室",
        "ssh_name": "公网中转", "local_ports": [[3080, "dsh web", ""]],
        "remote_tunnels": [[8091, "reverse", ""]],
    }

    def test_construction_prefill(self, qapp_mod, monkeypatch):
        from ui.pages_settings import SettingsPage
        import core.config as dsh_config
        monkeypatch.setattr(dsh_config, "load_config", lambda path=None: dict(self.CFG))
        page = SettingsPage(_FakeApp())
        assert page._vars["dash_port"].text() == "3080"
        assert page._vars["dash_cmd"].text() == "pnpm.cmd dsh web"
        assert page._local_tbl.rowCount() == 1
        assert page._in_local.text() == "本机"
        page.close()
        qapp_mod.processEvents()

    def test_template_fill(self, qapp_mod, monkeypatch):
        from ui.pages_settings import SettingsPage
        import core.config as dsh_config
        monkeypatch.setattr(dsh_config, "load_config", lambda path=None: {})
        page = SettingsPage(_FakeApp())
        page._apply("在家→中继隧道")
        assert page._vars["ssh_server"].text() == "YOUR_PUBLIC_IP"
        page.close()
        qapp_mod.processEvents()

    def test_save_merges_and_reloads(self, qapp_mod, monkeypatch):
        from ui.pages_settings import SettingsPage
        import core.config as dsh_config
        monkeypatch.setattr(dsh_config, "load_config", lambda path=None: dict(self.CFG))
        saved = {}
        monkeypatch.setattr(dsh_config, "save_config",
                            lambda cfg, path=None: saved.update(cfg) or True)
        app = _FakeApp()
        page = SettingsPage(app)
        page._on_save()
        assert saved["dash_port"] == 3080
        assert saved["local_ports"] == [[3080, "dsh web", ""]]
        assert saved["ssh_server"] == "YOUR_PUBLIC_IP"
        assert app.reloaded is True
        page.close()
        qapp_mod.processEvents()

    def test_save_invalid_integer_refused(self, qapp_mod, monkeypatch):
        from ui.pages_settings import SettingsPage
        import core.config as dsh_config
        monkeypatch.setattr(dsh_config, "load_config", lambda path=None: dict(self.CFG))
        saved = {}
        monkeypatch.setattr(dsh_config, "save_config",
                            lambda cfg, path=None: saved.update(cfg) or True)
        page = SettingsPage(_FakeApp())
        page._vars["dash_port"].setText("abc")
        page._on_save()
        assert saved == {}   # 非法整数不落盘
        assert "整数" in page._save_lbl.text()
        page.close()
        qapp_mod.processEvents()


class _FakeService:
    # DshManagePage 依赖的 service 最小接口(构造用; card 信号仅 connect 记账)
    def __init__(self):
        self.card = _FakeSignal()

    def run_cmd(self, *a, **k):
        pass

    def start_dsh(self, *a, **k):
        pass


class _FakeSignal:
    def connect(self, *a, **k):
        pass


class TestDshManagePage:
    """DSH 管理页: 弹窗收敛后, 环境检查 / 安装向导以页面内分步呈现(退役 EnvDialog/InstallDialog)。"""

    class _FakeApp:
        NAME = "dsh"

        def __init__(self):
            self._card_state = {}
            self.service = _FakeService()
            self.logs = []

        def loge(self, *a):
            self.logs.append(a)

        def set_status(self, *a):
            pass

        def _refresh_deploy_list(self):
            pass

    def test_construct_with_env_and_install_cards(self, qapp_mod, monkeypatch):
        # 镜像旧 InstallDialog/EnvDialog 的构造冒烟: 页面能构建, 且包含环境表与安装向导卡
        from ui.pages_dsh import DshManagePage
        # 拦截后台读/网络: 环境探测返回固定值, tags 拉取直接抛错(避免真网络)
        import core.env as _env
        def _fake_tools(tools):
            return {"git": "git version 2.53.0", "node": "v24.19.0",
                    "npm": "11.17.0", "pnpm": "11.7.0"}
        monkeypatch.setattr(_env, "tool_versions", _fake_tools)
        import core.dshctl as _dshctl
        def _boom():
            raise RuntimeError("no network in test")
        monkeypatch.setattr(_dshctl, "fetch_dsh_tags", _boom)
        app = self._FakeApp()
        page = DshManagePage(app)
        qapp_mod.processEvents()
        # 页面已建; 环境表两条目的版本探测结果经信号回到主线程
        assert page.env_rows  # 4 个工具行
        assert page._inst_url is not None
        assert page._inst_bar is not None
        page.close()
        qapp_mod.processEvents()

    def test_install_validation_requires_url(self, qapp_mod, monkeypatch):
        # 安装向导: 空仓库地址拒绝启动(与旧 InstallDialog 同源校验)
        from ui.pages_dsh import DshManagePage
        # 拦截弹窗(空 URL 会 QMessageBox.critical)与后台读/网络
        monkeypatch.setattr("ui.pages_dsh.QMessageBox.critical", lambda *a, **k: None)
        import core.env as _env
        monkeypatch.setattr(_env, "tool_versions", lambda tools: {})
        import core.dshctl as _dshctl
        monkeypatch.setattr(_dshctl, "fetch_dsh_tags", lambda: (_ for _ in ()).throw(RuntimeError("x")))
        app = self._FakeApp()
        page = DshManagePage(app)
        qapp_mod.processEvents()
        page._inst_url.setText("")
        # 直接触发安装应被 URL 校验拦截(_inst_running 仍为 False)
        page._start_install()
        assert page._inst_running is False
        page.close()
        qapp_mod.processEvents()


class TestHumanSize:
    """pages_sessions._human_size / pages_deployments._human_size: 人性化字节格式化。"""

    def test_zero(self):
        from ui.pages_sessions import _human_size
        assert _human_size(0) == "0.0B"

    def test_bytes(self):
        from ui.pages_sessions import _human_size
        result = _human_size(500)
        assert "B" in result

    def test_kb(self):
        from ui.pages_sessions import _human_size
        result = _human_size(2048)
        assert "KB" in result

    def test_mb(self):
        from ui.pages_sessions import _human_size
        result = _human_size(1024 * 1024 * 5)
        assert "MB" in result

    def test_none_input(self):
        from ui.pages_sessions import _human_size
        assert _human_size(None) == "0.0B"


class TestFmtTime:
    """pages_sessions._fmt_time: 时间戳格式化。"""

    def test_valid_timestamp(self):
        from ui.pages_sessions import _fmt_time
        result = _fmt_time(1700000000)
        assert "-" in result  # 至少有日期分隔符

    def test_invalid_timestamp(self):
        from ui.pages_sessions import _fmt_time
        assert _fmt_time(None) == "-"
        assert _fmt_time("abc") == "-"


class TestCostText:
    """pages_usage._cost_text: 费用文本渲染。"""

    def test_known_model(self):
        from ui.pages_usage import _cost_text
        result = _cost_text("deepseek-v4-flash", 1000, 500, 0)
        assert "元" in result

    def test_unknown_model(self):
        from ui.pages_usage import _cost_text
        result = _cost_text("gpt-4", 1000, 500, 0)
        assert result == "未定价"

    def test_zero_tokens(self):
        from ui.pages_usage import _cost_text
        result = _cost_text("deepseek-v4-flash", 0, 0, 0)
        assert "0.00" in result


class TestNum:
    """pages_usage._num: 数字千分位格式化。"""

    def test_zero(self):
        from ui.pages_usage import _num
        assert _num(0) == "0"

    def test_thousand(self):
        from ui.pages_usage import _num
        assert _num(1234) == "1,234"

    def test_none(self):
        from ui.pages_usage import _num
        assert _num(None) == "0"

    def test_large(self):
        from ui.pages_usage import _num
        result = _num(1234567890)
        assert "1,234,567,890" == result


class TestProvidersMap:
    """pages_llm._providers_map / _provider_options / _models_for: LLM 配置解析。"""

    def test_providers_map_empty(self):
        from ui.pages_llm import _providers_map
        assert _providers_map({}) == {}

    def test_providers_map_valid(self):
        from ui.pages_llm import _providers_map
        settings = {"llm-pi-ai": {"providers": {"my-p": {"api": "openai"}}}}
        result = _providers_map(settings)
        assert "my-p" in result

    def test_provider_options_builtin(self):
        from ui.pages_llm import _provider_options
        opts = _provider_options({})
        assert "deepseek-official" in opts

    def test_models_for_builtin(self):
        from ui.pages_llm import _models_for
        models = _models_for({}, "deepseek-official")
        assert "deepseek-v4-flash" in models

    def test_models_for_unknown_provider(self):
        from ui.pages_llm import _models_for
        models = _models_for({}, "nonexistent")
        assert models == []

    def test_env_txt_empty(self):
        from ui.pages_llm import _env_txt
        assert _env_txt("") == ""
        assert _env_txt(None) == ""


class TestReadTail:
    """core.ops.read_tail: 文件尾部读取。"""

    def test_small_file(self, tmp_path):
        from core.ops import read_tail as _read_tail
        p = tmp_path / "test.log"
        p.write_text("line1\nline2\nline3\n", encoding="utf-8")
        result = _read_tail(str(p))
        assert "line3" in result

    def test_empty_file(self, tmp_path):
        from core.ops import read_tail as _read_tail
        p = tmp_path / "empty.log"
        p.write_text("", encoding="utf-8")
        result = _read_tail(str(p))
        assert result == ""

    def test_truncation(self, tmp_path):
        from core.ops import read_tail as _read_tail, TAIL_BYTES
        p = tmp_path / "big.log"
        # 写入超过 TAIL_BYTES 的内容
        content = "A" * (TAIL_BYTES + 1000) + "\nTAIL_LINE\n"
        p.write_text(content, encoding="utf-8")
        result = _read_tail(str(p))
        assert "TAIL_LINE" in result
        assert len(result) <= TAIL_BYTES + 100  # 允许一点余量


class TestLogEntries:
    """core.ops.log_entries: 日志目录扫描。"""

    def test_empty_dir(self, tmp_path):
        from core.ops import log_entries as _log_entries
        result = _log_entries(str(tmp_path))
        assert result == []

    def test_nonexistent_dir(self, tmp_path):
        from core.ops import log_entries as _log_entries
        result = _log_entries(str(tmp_path / "nonexistent"))
        assert result == []

    def test_with_logs(self, tmp_path):
        from core.ops import log_entries as _log_entries
        (tmp_path / "test.log").write_text("content")
        (tmp_path / "test.txt").write_text("not a log")
        result = _log_entries(str(tmp_path))
        assert len(result) == 1
        assert result[0]["name"] == "test.log"
