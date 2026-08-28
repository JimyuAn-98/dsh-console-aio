# -*- coding: utf-8 -*-
# pyside/dialogs.py 对话框构造冒烟测试。
# 验证: ConfigDialog / InstallDialog / EnvDialog 构造不崩溃。
# 环境: QT_QPA_PLATFORM=offscreen。

import os
import sys
import json

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


class TestConfigDialog:
    """ConfigDialog: 配置向导构造冒烟。"""

    def test_construction(self, qapp_mod):
        from pyside.dialogs import ConfigDialog
        cfg = {
            "ssh_server": "YOUR_PUBLIC_IP",
            "ssh_user": "YOUR_USER",
            "dash_repo": "",
            "dash_port": 3080,
            "dash_cmd": ["pnpm.cmd", "dsh", "web"],
            "forward_ports": [8090, 8022, 8091],
            "lab_server": "",
            "lab_user": "",
            "lab_port": 3090,
            "reverse_port": 8091,
            "poll_seconds": 4,
            "remote_poll_seconds": 20,
        }
        dlg = ConfigDialog(cfg)
        assert dlg.windowTitle() == "隧道配置向导"
        assert dlg.result is None
        dlg.close()
        qapp_mod.processEvents()

    def test_template_fill(self, qapp_mod):
        from pyside.dialogs import ConfigDialog
        cfg = {}
        dlg = ConfigDialog(cfg)
        # 应用模板
        dlg._apply("在家→中继隧道")
        assert dlg._vars["ssh_server"].text() == "YOUR_PUBLIC_IP"
        dlg.close()
        qapp_mod.processEvents()

    def test_save_with_valid_data(self, qapp_mod):
        from pyside.dialogs import ConfigDialog
        cfg = {
            "dash_port": 3080,
            "forward_ports": [8090, 8022, 8091],
            "lab_port": 3090,
            "reverse_port": 8091,
            "poll_seconds": 4,
            "remote_poll_seconds": 20,
        }
        dlg = ConfigDialog(cfg)
        # 填入有效数据
        dlg._vars["dash_port"].setText("3080")
        dlg._vars["poll_seconds"].setText("4")
        dlg._vars["remote_poll_seconds"].setText("20")
        dlg._vars["forward_ports"].setText("8090,8022,8091")
        dlg._on_save()
        assert dlg.result is not None
        assert dlg.result["dash_port"] == 3080
        dlg.close()
        qapp_mod.processEvents()


class TestInstallDialog:
    """InstallDialog: 安装向导构造冒烟。"""

    def test_construction(self, qapp_mod):
        from pyside.dialogs import InstallDialog
        dlg = InstallDialog()
        assert dlg.windowTitle() == "安装 dsh"
        assert dlg.result is None
        dlg.close()
        qapp_mod.processEvents()


class TestEnvDialog:
    """EnvDialog: 环境检查构造冒烟。"""

    def test_construction(self, qapp_mod):
        from pyside.dialogs import EnvDialog
        dlg = EnvDialog()
        assert dlg.windowTitle() == "环境检查"
        dlg.close()
        qapp_mod.processEvents()


class TestDialogBase:
    """_DialogBase.safe_emit: 线程安全发射。"""

    def test_safe_emit_on_destroyed(self, qapp_mod):
        """对已销毁的 QObject emit 不应崩溃。"""
        from PySide6.QtCore import Signal, QObject
        from pyside.dialogs import _DialogBase

        class FakeDialog(_DialogBase):
            _sig = Signal(str)

        dlg = FakeDialog()
        sig = dlg._sig
        dlg.close()
        qapp_mod.processEvents()
        # safe_emit 应吞掉 RuntimeError
        dlg.safe_emit(sig, "test")
        qapp_mod.processEvents()


class TestLoadConfig:
    """dialogs._load_config: 防御模式读取。"""

    def test_load_config_missing_file(self, tmp_path, monkeypatch):
        from pyside.dialogs import _load_config
        monkeypatch.setattr("pyside.dialogs.CONFIG_PATH", str(tmp_path / "missing.json"))
        result = _load_config()
        assert result == {}

    def test_load_config_valid(self, tmp_path, monkeypatch):
        from pyside.dialogs import _load_config
        cfg = {"key": "value"}
        p = tmp_path / "config.json"
        p.write_text(json.dumps(cfg), encoding="utf-8")
        monkeypatch.setattr("pyside.dialogs.CONFIG_PATH", str(p))
        result = _load_config()
        assert result["key"] == "value"

    def test_load_config_corrupted(self, tmp_path, monkeypatch):
        from pyside.dialogs import _load_config
        p = tmp_path / "config.json"
        p.write_text("{bad json", encoding="utf-8")
        monkeypatch.setattr("pyside.dialogs.CONFIG_PATH", str(p))
        result = _load_config()
        assert result == {}


class TestHumanSize:
    """pages_sessions._human_size / pages_deployments._human_size: 人性化字节格式化。"""

    def test_zero(self):
        from pyside.pages_sessions import _human_size
        assert _human_size(0) == "0.0B"

    def test_bytes(self):
        from pyside.pages_sessions import _human_size
        result = _human_size(500)
        assert "B" in result

    def test_kb(self):
        from pyside.pages_sessions import _human_size
        result = _human_size(2048)
        assert "KB" in result

    def test_mb(self):
        from pyside.pages_sessions import _human_size
        result = _human_size(1024 * 1024 * 5)
        assert "MB" in result

    def test_none_input(self):
        from pyside.pages_sessions import _human_size
        assert _human_size(None) == "0.0B"


class TestFmtTime:
    """pages_sessions._fmt_time: 时间戳格式化。"""

    def test_valid_timestamp(self):
        from pyside.pages_sessions import _fmt_time
        result = _fmt_time(1700000000)
        assert "-" in result  # 至少有日期分隔符

    def test_invalid_timestamp(self):
        from pyside.pages_sessions import _fmt_time
        assert _fmt_time(None) == "-"
        assert _fmt_time("abc") == "-"


class TestCostText:
    """pages_usage._cost_text: 费用文本渲染。"""

    def test_known_model(self):
        from pyside.pages_usage import _cost_text
        result = _cost_text("deepseek-v4-flash", 1000, 500, 0)
        assert "元" in result

    def test_unknown_model(self):
        from pyside.pages_usage import _cost_text
        result = _cost_text("gpt-4", 1000, 500, 0)
        assert result == "未定价"

    def test_zero_tokens(self):
        from pyside.pages_usage import _cost_text
        result = _cost_text("deepseek-v4-flash", 0, 0, 0)
        assert "0.00" in result


class TestNum:
    """pages_usage._num: 数字千分位格式化。"""

    def test_zero(self):
        from pyside.pages_usage import _num
        assert _num(0) == "0"

    def test_thousand(self):
        from pyside.pages_usage import _num
        assert _num(1234) == "1,234"

    def test_none(self):
        from pyside.pages_usage import _num
        assert _num(None) == "0"

    def test_large(self):
        from pyside.pages_usage import _num
        result = _num(1234567890)
        assert "1,234,567,890" == result


class TestProvidersMap:
    """pages_llm._providers_map / _provider_options / _models_for: LLM 配置解析。"""

    def test_providers_map_empty(self):
        from pyside.pages_llm import _providers_map
        assert _providers_map({}) == {}

    def test_providers_map_valid(self):
        from pyside.pages_llm import _providers_map
        settings = {"llm-pi-ai": {"providers": {"my-p": {"api": "openai"}}}}
        result = _providers_map(settings)
        assert "my-p" in result

    def test_provider_options_builtin(self):
        from pyside.pages_llm import _provider_options
        opts = _provider_options({})
        assert "deepseek-official" in opts

    def test_models_for_builtin(self):
        from pyside.pages_llm import _models_for
        models = _models_for({}, "deepseek-official")
        assert "deepseek-v4-flash" in models

    def test_models_for_unknown_provider(self):
        from pyside.pages_llm import _models_for
        models = _models_for({}, "nonexistent")
        assert models == []

    def test_env_txt_empty(self):
        from pyside.pages_llm import _env_txt
        assert _env_txt("") == ""
        assert _env_txt(None) == ""


class TestReadTail:
    """pages_ops._read_tail: 文件尾部读取。"""

    def test_small_file(self, tmp_path):
        from pyside.pages_ops import _read_tail
        p = tmp_path / "test.log"
        p.write_text("line1\nline2\nline3\n", encoding="utf-8")
        result = _read_tail(str(p))
        assert "line3" in result

    def test_empty_file(self, tmp_path):
        from pyside.pages_ops import _read_tail
        p = tmp_path / "empty.log"
        p.write_text("", encoding="utf-8")
        result = _read_tail(str(p))
        assert result == ""

    def test_truncation(self, tmp_path):
        from pyside.pages_ops import _read_tail, TAIL_BYTES
        p = tmp_path / "big.log"
        # 写入超过 TAIL_BYTES 的内容
        content = "A" * (TAIL_BYTES + 1000) + "\nTAIL_LINE\n"
        p.write_text(content, encoding="utf-8")
        result = _read_tail(str(p))
        assert "TAIL_LINE" in result
        assert len(result) <= TAIL_BYTES + 100  # 允许一点余量


class TestLogEntries:
    """pages_ops._log_entries: 日志目录扫描。"""

    def test_empty_dir(self, tmp_path):
        from pyside.pages_ops import _log_entries
        result = _log_entries(str(tmp_path))
        assert result == []

    def test_nonexistent_dir(self, tmp_path):
        from pyside.pages_ops import _log_entries
        result = _log_entries(str(tmp_path / "nonexistent"))
        assert result == []

    def test_with_logs(self, tmp_path):
        from pyside.pages_ops import _log_entries
        (tmp_path / "test.log").write_text("content")
        (tmp_path / "test.txt").write_text("not a log")
        result = _log_entries(str(tmp_path))
        assert len(result) == 1
        assert result[0]["name"] == "test.log"
