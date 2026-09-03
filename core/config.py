# -*- coding: utf-8 -*-
# core/config.py - 配置加载与派生常量(纯 Python, 不 import PySide)。
# 与 dsh-console-aio.py 顶层的 _load_config + 派生常量保持同一套规则, 但独立于此,
# 可被 UI 之外的任何调用方(含单测/CLI)复用。

import os
import sys
import json
import shutil
from datetime import datetime


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


def normalize_tunnels(cfg, allow_empty_ports=False):
    # 规范化与向后兼容转换: 若配置中显式存在 tunnels 列表(即便为空列表)直接返回标准结构;
    # 仅当未配置 tunnels(raw is None)时才从旧字段自动生成默认隧道列表。
    raw = (cfg or {}).get("tunnels")
    if raw is not None and isinstance(raw, list):
        out = []
        for idx, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            tid = str(item.get("id") or ("tun_%d" % (idx + 1))).strip()
            mode = item.get("mode") or "forward"
            fw_list = []
            for fw in (item.get("forwards") or []):
                if isinstance(fw, (list, tuple)) and len(fw) >= 3:
                    fw_list.append({
                        "local_port": int(fw[0]),
                        "remote_host": str(fw[1] or "127.0.0.1"),
                        "remote_port": int(fw[2]),
                        "desc": str(fw[3]) if len(fw) >= 4 else ""
                    })
                elif isinstance(fw, dict):
                    fw_list.append({
                        "local_port": int(fw.get("local_port") or 0),
                        "remote_host": str(fw.get("remote_host") or "127.0.0.1"),
                        "remote_port": int(fw.get("remote_port") or 0),
                        "desc": str(fw.get("desc") or "")
                    })
            out.append({
                "id": tid,
                "name": str(item.get("name") or tid),
                "mode": mode,
                "host": str(item.get("host") or "").strip(),
                "user": str(item.get("user") or "").strip(),
                "ssh_port": int(item.get("ssh_port") or 22),
                "forwards": fw_list,
                "auto_restart": bool(item.get("auto_restart", True)),
                "enabled": bool(item.get("enabled", True)),
                "desc": str(item.get("desc") or ""),
            })
        return out

    # 无 tunnels 时从旧字段合成
    local = (cfg or {}).get("local_name") or "本机"
    lab = (cfg or {}).get("lab_name") or "实验室"
    ssh = (cfg or {}).get("ssh_name") or "公网中转"
    ssh_srv = (cfg or {}).get("ssh_server") or ""
    ssh_usr = (cfg or {}).get("ssh_user") or ""
    lab_srv = (cfg or {}).get("lab_server") or ""
    lab_usr = (cfg or {}).get("lab_user") or ""

    if allow_empty_ports:
        lab_p = int((cfg or {}).get("lab_port") or 0)
        rev_p = int((cfg or {}).get("reverse_port") or 0)
        dash_p = int((cfg or {}).get("dash_port") or 0)
        fwd_pts = list((cfg or {}).get("forward_ports") or [])
    else:
        lab_p = int((cfg or {}).get("lab_port") or 3090)
        rev_p = int((cfg or {}).get("reverse_port") or 8091)
        dash_p = int((cfg or {}).get("dash_port") or 3080)
        fwd_pts = list((cfg or {}).get("forward_ports") or [8090, 8022, 8091])

    tunnels = []
    # 1. 中继正向隧道
    tunnels.append({
        "id": "dsh-tunnel",
        "name": "%s正向隧道" % ssh,
        "mode": "forward",
        "host": ssh_srv,
        "user": ssh_usr,
        "ssh_port": 22,
        "forwards": [
            {"local_port": p, "remote_host": "127.0.0.1", "remote_port": p,
             "desc": "转发端口 %d" % p} for p in fwd_pts
        ],
        "auto_restart": True,
        "enabled": bool(ssh_srv),
        "desc": "打通公网中转服务器的转发端口 (%s)" % (", ".join(str(p) for p in fwd_pts)),
    })
    # 2. 实验室直连隧道
    lab_fws = [{"local_port": lab_p, "remote_host": "127.0.0.1", "remote_port": lab_p,
                "desc": "%s dsh GUI" % lab}] if lab_p else []
    tunnels.append({
        "id": "connect-lab-dsh",
        "name": "%s直连隧道" % lab,
        "mode": "forward",
        "host": lab_srv,
        "user": lab_usr,
        "ssh_port": 22,
        "forwards": lab_fws,
        "auto_restart": True,
        "enabled": bool(lab_srv),
        "desc": "局域网直连 %s dsh GUI (: %d)" % (lab, lab_p),
    })
    # 3. 本机反向隧道
    rev_fws = [{"local_port": rev_p, "remote_host": "127.0.0.1", "remote_port": dash_p,
                "desc": "反向暴露本机 dsh"}] if (rev_p and dash_p) else []
    tunnels.append({
        "id": "dsh-tunnel-reverse",
        "name": "%s反向隧道" % local,
        "mode": "reverse",
        "host": ssh_srv,
        "user": ssh_usr,
        "ssh_port": 22,
        "forwards": rev_fws,
        "auto_restart": True,
        "enabled": bool(ssh_srv),
        "desc": "%s dsh -> %s反向隧道 (%s:%d -> 本机 %d)" % (local, ssh, ssh, rev_p, dash_p),
    })
    return tunnels


def derived(cfg, allow_empty_ports=False):
    # 从 config dict 派生主程序要用到的常量。默认分支的空值 0/空列表会被 or 兜底为
    # 真实默认端口, 必须与 dsh-console-aio.py 顶层的同名派生保持一致。
    # allow_empty_ports=True: 端口类配置不做真实端口兜底(空/0 原样保留为 0/空列表)。
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
    d['remote_poll_seconds'] = cfg.get('remote_poll_seconds') or 20

    # 动态隧道清单与监测端口合成
    d['tunnels'] = normalize_tunnels(cfg, allow_empty_ports=allow_empty_ports)

    if allow_empty_ports:
        d['local_ports'] = []
        d['remote_tunnels'] = []
    else:
        # 单一事实源: 监控端口始终由当前启用的 tunnels 与 dash_port 动态合成
        # 兼容保留原配置中对应端口自定义的中文备注
        cfg_loc_meta = {}
        for item in (cfg.get("local_ports") or []):
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                cfg_loc_meta[item[0]] = (item[1], item[2] if len(item) >= 3 else "")

        loc_pts = []
        dash_p = d['dash_port']
        if dash_p:
            dash_meta = cfg_loc_meta.get(dash_p, ("%s dsh" % d['local_name'], "GUI"))
            loc_pts.append([dash_p, dash_meta[0], dash_meta[1]])
        seen = {dash_p} if dash_p else set()

        for tun in d['tunnels']:
            if tun.get("mode") == "forward":
                for fw in tun.get("forwards") or []:
                    lp = fw.get("local_port") if isinstance(fw, dict) else (fw[0] if fw else None)
                    if lp and lp not in seen:
                        seen.add(lp)
                        def_lbl = "%s" % (tun.get("name") or ("本地:%d" % lp))
                        def_desc = fw.get("desc") if isinstance(fw, dict) else (fw[3] if len(fw) >= 4 else "")
                        meta = cfg_loc_meta.get(lp, (def_lbl, def_desc or tun.get("name") or "本地转发"))
                        loc_pts.append([lp, meta[0], meta[1]])
        d['local_ports'] = loc_pts

        cfg_rem_meta = {}
        for item in (cfg.get("remote_tunnels") or []):
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                cfg_rem_meta[item[0]] = (item[1], item[2] if len(item) >= 3 else "")

        rem_pts = []
        seen_rem = set()
        for tun in d['tunnels']:
            if tun.get("mode") == "reverse":
                for fw in tun.get("forwards") or []:
                    rp = fw.get("local_port") if isinstance(fw, dict) else (fw[0] if fw else None)
                    if rp and rp not in seen_rem:
                        seen_rem.add(rp)
                        def_lbl = "%s:%d" % (d['ssh_name'], rp)
                        def_desc = fw.get("desc") if isinstance(fw, dict) else (fw[3] if len(fw) >= 4 else "")
                        meta = cfg_rem_meta.get(rp, (def_lbl, def_desc or tun.get("name") or "反向暴露"))
                        rem_pts.append([rp, meta[0], meta[1]])
        d['remote_tunnels'] = rem_pts

    return d


def load_derived(path=None, allow_empty_ports=False):
    return derived(load_config(path), allow_empty_ports=allow_empty_ports)


# ── 配置导出/导入(GUI↔CLI 共享格式, OTP deploy.xml 思想) ──
# 信封 = 类型/格式版本/时间戳 + 完整 config。导出内容含真实 IP/用户名(gitignored 的
# config.json 本就如此), 由 UI 提示用户妥善保管; 导入是覆盖式(调用方先确认 + save_config
# 自动 .bak + 热重载)。校验失败一律返回中文文案, 不抛异常(脏文件不致命)。
EXPORT_TYPE = "dsh-console-config"
EXPORT_VERSION = 1


def export_envelope(cfg, now=None):
    return {"_type": EXPORT_TYPE, "_version": EXPORT_VERSION,
            "_exported_at": now or datetime.now().isoformat(timespec="seconds"),
            "config": dict(cfg or {})}


def load_tunnels(path=None):
    # 读取配置中的动态隧道列表(自动向后兼容)
    cfg = load_config(path)
    return normalize_tunnels(cfg)


def save_tunnels(tunnels, path=None):
    # 保存动态隧道列表写回 config.json(保留其他配置项, 写前备份)
    cfg = load_config(path)
    cfg["tunnels"] = list(tunnels)
    return save_config(cfg, path=path)


def parse_import(data):
    # 校验导入数据: (config dict, "") 或 (None, 中文错误文案)。只认信封格式 ——
    # 裸 config dict 拒绝(避免把随手导出的半截文件当配置写盘)。
    if not isinstance(data, dict):
        return None, "导入文件不是 JSON 对象"
    if data.get("_type") != EXPORT_TYPE:
        return None, "不是本应用的配置导出文件(缺少 _type: %s), 请用「导出配置」生成" % EXPORT_TYPE
    cfg = data.get("config")
    if not isinstance(cfg, dict):
        return None, "导出文件缺少 config 字段或其不是对象"
    return cfg, ""


__all__ = ['load_config', 'save_config', 'load_derived', 'derived',
           'normalize_tunnels', 'load_tunnels', 'save_tunnels',
           'export_envelope', 'parse_import']
