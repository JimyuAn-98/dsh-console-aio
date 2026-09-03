# -*- coding: utf-8 -*-
# fake_env.py - 为 GUI 纯 UI 测试准备的假数据 + 假环境构造器。
#
# 目标: 完全不打开真实 GUI、不连真实 SSH/端口/进程, 只验证 GUI 元素及其事件/数据流是否生效。
# 实现: 在内存里构造离屏(offscreen)的 MainWindow, 并用假 config/DSH_HOME 替换真实资源。
#
# 使用:
#   from fake_env import make_fake_home, point_dsh_data_to, ...
#
# 注意: 本模块仅构造假数据, 绝不触碰真实 config.json / ~/.dsh / 真实端口与进程。

import os
import sys
import json
import shutil
import pathlib
import tempfile

# 仓库根(ui/.. 与 conftest 同规则)
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _wd(path):
    """统一路径处理: 传入 str 或 pathlib.Path 都返回 str。"""
    return str(path)


def make_fake_home(tmp_root):
    """构造一个模拟 ~/.dsh 目录结构, 返回目录路径(str)。
    tmp_root 用 pytest 的 tmp_path 即可(root 为绝对路径, 不会被真实 DSH_HOME 踩到)。
    """
    home = pathlib.Path(_wd(tmp_root)) / ".dsh-fake"
    home.mkdir(parents=True, exist_ok=True)
    (home / "profiles").mkdir(exist_ok=True)
    (home / "sessions").mkdir(exist_ok=True)
    (home / "storages").mkdir(exist_ok=True)
    (home / "task-board").mkdir(exist_ok=True)
    (home / ".agent-presets").mkdir(exist_ok=True)
    (home / "storages" / "workspace.json").write_text(
        json.dumps({"global": {"workspaceIds": [], "archivedSessionIds": []}}),
        encoding="utf-8")
    (home / "settings.yaml").write_text("{}\n", encoding="utf-8")
    return _wd(home)


def make_fake_config_dict():
    # 假配置: 所有端口/服务器全部留空或占位, 与真实 3080/8090/8022/8091/3090 完全脱钩。
    # GUI 纯 UI 测试只验证"UI 是否正确响应并调到后端函数", 不真正连任何端口/服务器。
    return {
        "ssh_server": "YOUR_PUBLIC_IP",
        "ssh_user": "YOUR_USER",
        "dash_repo": "",
        "dash_port": 0,
        "dash_cmd": ["pnpm.cmd", "dsh", "web"],
        "poll_seconds": 4,
        "tunnels": [],
        "local_ports": [],
        "remote_tunnels": [],
        "forward_ports": [],
        "reverse_port": 0,
        "lab_port": 0,
    }


def make_fake_config_file(tmp_root):
    """把假 config.json 写到 tmp_root 下, 返回路径(str)。"""
    cfg = make_fake_config_dict()
    p = pathlib.Path(_wd(tmp_root)) / "config.json"
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return _wd(p)


def point_dsh_data_to(fake_config_file_or_dir, fake_home_dir):
    """让 config.json 定位与 DSH_HOME 都落到假目录(纯环境变量, 不侵入代码逻辑)。

    - DSH_AIO_CONFIG 指向假 config.json 文件: 主程序 dsh-console-aio.py 与 core.data._config_path()
      都会优先读它, 从而 load_deployments/save_deployments/主程序 CONFIG 全用假配置(占位符)。
    - DSH_HOME 指向假目录: profiles/sessions/settings 等读假数据。
    返回 (恢复函数)。
    """
    cfg_path = _wd(fake_config_file_or_dir)
    if os.path.isdir(cfg_path):
        cfg_path = os.path.join(cfg_path, "config.json")
    _old_cfg = os.environ.get("DSH_AIO_CONFIG")
    _old_home = os.environ.get("DSH_HOME")
    os.environ["DSH_AIO_CONFIG"] = cfg_path
    os.environ["DSH_HOME"] = _wd(fake_home_dir) if fake_home_dir is not None else _old_home
    if fake_home_dir is None:
        os.environ.pop("DSH_HOME", None)
    def _restore():
        if _old_cfg is None:
            os.environ.pop("DSH_AIO_CONFIG", None)
        else:
            os.environ["DSH_AIO_CONFIG"] = _old_cfg
        if _old_home is None:
            os.environ.pop("DSH_HOME", None)
        else:
            os.environ["DSH_HOME"] = _old_home
    return _restore


def default_env(tmp_path):
    """一键: 构造假 config + 假 DSH_HOME, 返回 (fake_config_file, fake_home, restore)。
    之后 dsh-console-aio / dsh_data 的 config.json 全落在 fake, DSH_HOME 落在 fake。
    """
    cfg_dir = pathlib.Path(_wd(tmp_path)) / "cfg"
    cfg_dir.mkdir(exist_ok=True)
    cfg_file = make_fake_config_file(cfg_dir)
    fake_home = make_fake_home(_wd(tmp_path))
    restore = point_dsh_data_to(cfg_file, fake_home)
    return _wd(cfg_file), fake_home, restore
