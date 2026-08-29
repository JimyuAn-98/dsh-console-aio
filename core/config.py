# -*- coding: utf-8 -*-
# core/config.py - 配置加载与派生常量(纯 Python, 不 import PySide)。
# 与 dsh-console-aio.py 顶层的 _load_config + 派生常量保持同一套规则, 但独立于此,
# 可被 UI 之外的任何调用方(含单测/CLI)复用。

import os
import sys
import json
import shutil


def default_config_path():
    # config.json 与主程序同目录(源码=仓库根; 打包=exe 所在安装目录, 用户可写)。
    # 打包运行(onefile)时 __file__ 在临时解压目录(_MEIPASS), 每次启动都会变 —— 必须用
    # exe 目录(与 dsh-console-aio.py 顶层 BASE_DIR 同规则), 否则配置写进临时目录退出
    # 即丢失、安装路径里粘贴的 config.json 也不会被读取。
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "config.json")


def _default_config_path():
    return default_config_path()


def load_config(path=None):
    """读取配置: 优先显式 path, 其次 DSH_AIO_CONFIG, 最后 default_config_path()。"""
    if path is None:
        path = os.environ.get('DSH_AIO_CONFIG') or default_config_path()
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f) or {}
    except Exception:
        return {}


def save_config(cfg, path=None):
    # 写回配置(调用方传入合并后的完整 cfg); 写前复制 .bak(AGENTS.md 约定)。
    # 成功返回 True; OSError(权限/占用)返回 False 由调用方提示。
    if path is None:
        path = os.environ.get('DSH_AIO_CONFIG') or default_config_path()
    try:
        if os.path.exists(path):
            shutil.copy2(path, path + ".bak")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


def derived(cfg, allow_empty_ports=False):
    # 从 config dict 派生主程序要用到的常量。默认分支的空值 0/空列表会被 or 兜底为
    # 真实默认端口, 必须与 dsh-console-aio.py 顶层的同名派生保持一致。
    # allow_empty_ports=True: 端口类配置不做真实端口兜底(空/0 原样保留为 0/空列表)。
    # 仅供单测/纯 UI 测试用假配置与真实端口隔离(曾因假端口被兜底回 3080 干掉运行中的
    # dsh); 真实 GUI 主链路一律用默认 False, 行为与主程序完全一致。
    def _or(v, default):
        return v if v not in (None, '') else default
    d = {}
    d['dash_repo'] = _or(cfg.get('dash_repo'), '')
    if allow_empty_ports:
        d['dash_port'] = cfg.get('dash_port') or 0
        d['lab_port'] = cfg.get('lab_port') or 0
        d['reverse_port'] = cfg.get('reverse_port') or 0
        d['forward_ports'] = list(cfg.get('forward_ports') or [])
    else:
        d['dash_port'] = cfg.get('dash_port') or 3080
        d['lab_port'] = cfg.get('lab_port') or 3090
        d['reverse_port'] = cfg.get('reverse_port') or 8091
        d['forward_ports'] = list(cfg.get('forward_ports') or [8090, 8022, 8091])
    d['dash_cmd'] = list(cfg.get('dash_cmd') or ['pnpm.cmd', 'dsh', 'web'])
    d['ssh_server'] = _or(cfg.get('ssh_server'), '')
    d['ssh_user'] = _or(cfg.get('ssh_user'), '')
    d['lab_server'] = _or(cfg.get('lab_server'), '')
    d['lab_user'] = _or(cfg.get('lab_user'), '')
    # 三处机器命名(自定义, P0): 本机/实验室/公网中转
    d['local_name'] = _or(cfg.get('local_name'), '本机')
    d['lab_name'] = _or(cfg.get('lab_name'), '实验室')
    d['ssh_name'] = _or(cfg.get('ssh_name'), '公网中转')
    d['tcp_timeout'] = cfg.get('tcp_timeout') or 0.8
    d['update_timeout'] = cfg.get('update_timeout') or 1800
    d['poll_seconds'] = cfg.get('poll_seconds') or 4
    d['local_ports'] = list(cfg.get('local_ports') or [])
    d['remote_tunnels'] = list(cfg.get('remote_tunnels') or [])
    return d


def load_derived(path=None, allow_empty_ports=False):
    return derived(load_config(path), allow_empty_ports=allow_empty_ports)


__all__ = ['load_config', 'save_config', 'load_derived', 'derived']
