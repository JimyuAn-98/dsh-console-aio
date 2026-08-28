# -*- coding: utf-8 -*-
# dsh_data.py — 兼容 shim: 数据层已归并 dsh_core/data.py(阶段4, 2026-08-29)。
# 本文件仅为保留旧 import 路径(dsh_data.xxx)而存在 —— tests/OverviewPage/主窗口等
# 现有引用不改即可工作; 新代码一律 from dsh_core import data。
# 注: DEFAULT_PRICES 为共享 dict 对象, 经 shim 原地修改与经 dsh_core.data 修改等价。

from dsh_core.data import *  # noqa: F401,F403
from dsh_core.data import (  # noqa: F401 显式列出符号(含测试引用的私有 YAML/SSH 助手)
    DEFAULT_PRICES,
    DshRemote,
    _config_path,
    _dump_scalar,
    _dump_yaml,
    _lead_spaces,
    _parse_scalar,
    _parse_yaml_block,
    _read_cordis_file,
    _ssh_base,
    _ssh_run,
    _strip_comment,
    backup_dsh_home,
    backup_file,
    deployment_snapshot,
    dsh_home,
    estimate_cost,
    is_peak_hour,
    list_agent_presets,
    list_profiles,
    list_sessions,
    load_deployments,
    load_entry_id_map,
    parse_yaml_text,
    plugin_cmd,
    profiles_dir,
    read_cordis,
    read_cordis_patch,
    read_profile_package,
    read_settings,
    read_taskboard,
    read_workspace,
    read_yaml,
    save_deployments,
    sessions_dir,
    usage_stats,
    write_cordis_patch,
    write_settings,
    write_yaml,
    zstd_available,
)
