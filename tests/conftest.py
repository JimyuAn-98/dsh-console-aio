# -*- coding: utf-8 -*-
# conftest.py - pytest 公共配置与 fixture。
# 运行: python -m pytest tests/ -v
#
# 安全边界: 本仓库默认只跑"纯单元测试"。任何构造真实 MainWindow / 触发真实监控线程 /
# 真实 SSH/端口/进程资源的测试(GUI 冒烟)都必须打 @pytest.mark.gui, 由 pytest.ini 的
# `-m "not gui"` 默认跳过, 仅 `-m gui` 显式手动执行 —— 绝不自动触碰正在运行的
# dsh(端口 3080)或真实 config.json 里的服务器。

import os
import sys
import json
import shutil
import tempfile
import pathlib

import pytest

# 全局无头: 任何 GUI 相关代码在离屏平台下运行, 避免弹出真实窗口。
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# 项目根目录加入 sys.path(确保 import core.data / core.tunnel_mgr 可达)
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# 工作区内的临时目录(绕过系统 Temp 沙盒限制)
_PYTEST_TMP = os.path.join(ROOT_DIR, ".pytest-tmp")
os.makedirs(_PYTEST_TMP, exist_ok=True)


# 覆盖 tmp_path: 用 tempfile.mkdtemp 在工作区内创建, 绕过 pytest basetemp 机制
@pytest.fixture
def tmp_path():
    d = tempfile.mkdtemp(dir=_PYTEST_TMP)
    p = pathlib.Path(d)
    yield p
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def tmp_base(tmp_path):
    """提供一个临时目录作为 tunnel_mgr 的 base_dir（含空 config）。"""
    return str(tmp_path)


@pytest.fixture
def fake_dsh_home(tmp_path):
    """构造一个模拟 ~/.dsh 目录结构, 返回路径。"""
    home = tmp_path / ".dsh"
    home.mkdir()
    (home / "profiles").mkdir()
    (home / "sessions").mkdir()
    (home / "storages").mkdir()
    (home / "task-board").mkdir()
    (home / ".agent-presets").mkdir()
    # 空 workspace.json
    (home / "storages" / "workspace.json").write_text(
        json.dumps({"global": {"workspaceIds": [], "archivedSessionIds": []}}),
        encoding="utf-8")
    # 空 settings.yaml
    (home / "settings.yaml").write_text("{}", encoding="utf-8")
    return str(home)


@pytest.fixture
def fake_config(tmp_path):
    """构造一个最小 config.json, 返回路径。"""
    cfg = {
        "ssh_server": "YOUR_PUBLIC_IP",
        "ssh_user": "YOUR_USER",
        "dash_repo": "",
        "dash_port": 3080,
        "dash_cmd": ["pnpm.cmd", "dsh", "web"],
        "poll_seconds": 4,
        "local_ports": [[3080, "本机 dsh", "http://127.0.0.1:3080"]],
        "remote_tunnels": [],
    }
    p = tmp_path / "config.json"
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(p)


@pytest.fixture
def fake_profile(tmp_path):
    """构造一个带 cordis.yml + cordis.patch.yml + package.json 的 profile 目录。"""
    prof = tmp_path / "profiles" / "web"
    prof.mkdir(parents=True)

    (prof / "cordis.yml").write_text(
        "- id: core\n  name: @deepseek-ai/core\n  description: 核心插件\n"
        "- id: ext\n  name: my-extension\n  description: 扩展插件\n",
        encoding="utf-8")

    (prof / "cordis.patch.yml").write_text(
        "- id: ext\n  disabled: true\n"
        "- id: dsh-market\n  insert:\n    - id: dsh-market\n      name: dsh-market\n",
        encoding="utf-8")

    (prof / "package.json").write_text(json.dumps({
        "dependencies": {
            "@deepseek-ai/core": "1.0.0",
            "my-extension": "0.5.0",
            "dsh-market": "2.0.0",
        },
        "dsh": {
            "profile": {
                "bundles": ["@deepseek-ai/core", "my-extension"],
            }
        }
    }, indent=2), encoding="utf-8")

    return str(tmp_path)


@pytest.fixture
def qapp():
    """创建 QApplication 实例(共享, 用于 PySide6 测试)。"""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app
