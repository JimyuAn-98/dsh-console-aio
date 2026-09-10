# -*- coding: utf-8 -*-
# core/cache.py - 页面数据本地缓存层(零 Qt, 纯 stdlib)。
# 目标: 各 dsh 数据页进页时, 先读缓存直接呈现; 再比对"数据源时间戳"判断有无新数据,
#       有新数据才重新拉取(避免每次进页全量重扫/长时间加载)。
# 存到软件路径(与 config.json / model_prices.json 同目录): dsh_aio_cache.json。
# 结构: { "<kind>": {"fetched_at": <epoch秒>, "data": <原始数据>} }
import hashlib
import io
import json
import os
import sys


def cache_file_path():
    # 优先 DSH_AIO_CONFIG(文件)所在目录 > frozen(exe)目录 > 源码目录; 与 core/data 保持一致。
    override = os.environ.get('DSH_AIO_CONFIG')
    if override:
        base = os.path.dirname(os.path.abspath(override))
    elif getattr(sys, 'frozen', False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, 'dsh_aio_cache.json')


def _read_all():
    # 读整份缓存文件; 损坏/缺失返回 {}。
    p = cache_file_path()
    try:
        with io.open(p, encoding='utf-8', errors='replace') as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def read_cache(kind):
    # 返回 (data, fetched_at); 无该 kind 缓存返回 (None, None)。
    d = _read_all().get(kind)
    if not isinstance(d, dict):
        return None, None
    return d.get("data"), d.get("fetched_at")


def _write_all(d):
    # 整份写回缓存文件; 失败(权限/占用)返回 False。
    p = cache_file_path()
    try:
        with io.open(p, 'w', encoding='utf-8', newline='') as fh:
            json.dump(d, fh, ensure_ascii=False, indent=1)
    except OSError:
        return False
    return True


def write_cache(kind, data, fetched_at=None):
    # 写某 kind 的缓存(合并保留其他 kind); fetched_at 缺省=当下。返回是否成功。
    import time
    fetched_at = fetched_at if fetched_at is not None else time.time()
    d = _read_all()
    d[kind] = {"fetched_at": fetched_at, "data": data}
    return _write_all(d)


def needs_refresh(kind, src_mtime):
    # 是否需重新拉取: 无缓存, 或 数据源时间戳晚于缓存抓取时间 -> 需要刷新。
    # src_mtime: 该页数据源的最新时间戳(秒); 传 0/None 表示"无法感知变化"(视为始终需要刷新)。
    if src_mtime is None or not src_mtime:
        return not read_cache(kind)[0]  # 无法感知源变化: 只看有没有缓存
    data, fetched = read_cache(kind)
    if data is None:
        return True
    if src_mtime > (fetched or 0):
        return True
    return False


def json_sig(obj):
    # 数据签名: JSON 序列化(键排序)取哈希, 用于"数据是否真的变化"的字节级比较。
    # default=str 兜底非 JSON 原生的值(如 datetime), 保证任意 dict 可比较。
    s = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def data_changed(kind, new_data):
    # 新拉取的数据与缓存中的旧数据相比是否真的有变化; 无缓存视为变化。
    # 注意: 不改写缓存; 由调用方决定是否 write_cache(并更新 fetched_at)。
    data, _ = read_cache(kind)
    if data is None:
        return True
    return json_sig(data) != json_sig(new_data)


# ── 缓存种类注册表(元数据, 供管理/诊断/校验; 不含数据) ──
# 固定 kind -> 中文说明; 动态 kind(按 profile 等拼接)用前缀登记。
KINDS = {
    "overview": "总览快照",
    "sessions": "会话与工作区",
    "profiles": "Profile 列表",
    "agents": "Agent 模式列表",
    "taskboard": "任务看板",
    "usage": "模型用量统计",
}
PREFIX_KINDS = {
    "plugins_": "插件列表(按 profile)",
}


def describe_kind(kind):
    # 给一个缓存 key 返回中文说明(固定名优先, 否则匹配前缀); 未登记返回"未登记"。
    if kind in KINDS:
        return KINDS[kind]
    for prefix, desc in PREFIX_KINDS.items():
        if kind.startswith(prefix):
            return desc
    return "未登记"


def list_cached():
    # 当前缓存概览(只读): [{kind, description, fetched_at, bytes}], 按 kind 排序。
    d = _read_all()
    out = []
    for kind, item in d.items():
        if not isinstance(item, dict):
            continue
        try:
            size = len(json.dumps(item.get("data"), ensure_ascii=False,
                                  default=str).encode("utf-8"))
        except (TypeError, ValueError):
            size = 0
        out.append({"kind": kind, "description": describe_kind(kind),
                    "fetched_at": item.get("fetched_at") or 0, "bytes": size})
    out.sort(key=lambda r: r["kind"])
    return out


def clear_cache(kind):
    # 删除某一 kind 的缓存; 该 kind 不存在返回 False, 否则返回是否写回成功。
    d = _read_all()
    if kind not in d:
        return False
    d.pop(kind, None)
    return _write_all(d)


def clear_all_cache():
    # 清空全部缓存; 返回删除的 kind 个数(写回失败返回 0)。
    n = len(_read_all())
    return n if _write_all({}) else 0
