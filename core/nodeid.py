# -*- coding: utf-8 -*-
# core/nodeid.py - 本机"节点码"生成与校验(纯 Python, 零 Qt)。
# 节点码 = MAC -> 短哈希, 首次生成后持久化到 config.json(node_id), 可手动改/重置;
# 纯 ASCII(公网信箱文件名要求), 与显示名(local_name)严格分离(见 ARCHITECTURE §3.1)。

import hashlib
import re

from core import config as dsh_config

_ID_RE = re.compile(r'^[A-Za-z0-9_\-]{4,32}$')


def machine_node_id():
    # 机器码: uuid.getnode()(通常为 MAC) -> sha1 前 10 位; 取不到网卡时 uuid 会回退随机值,
    # 但节点码会持久化到 config, 因此正常运行期稳定。
    import uuid
    mac = uuid.getnode()
    return hashlib.sha1(("dsh-console:" + str(mac)).encode("utf-8")).hexdigest()[:10]


def valid_node_id(s):
    return bool(s and _ID_RE.match(str(s)))


def new_node_id():
    # 全新随机节点码(10 位 hex): 用于"重新生成"(如克隆机/换网卡后想换一个标识)。
    import secrets
    return secrets.token_hex(5)


def regenerate_node_id(path=None):
    # 强制生成并持久化一个新的节点码; 返回新值(旧信箱条目会变成孤儿, 调用方需提示)。
    cfg = dsh_config.load_config(path)
    cfg["node_id"] = new_node_id()
    dsh_config.save_config(cfg, path)
    return cfg["node_id"]


def ensure_node_id(path=None):
    # 读取 config; node_id 缺失/非法则用 machine_node_id() 生成并写回; 返回最终 node_id。
    cfg = dsh_config.load_config(path)
    cur = str(cfg.get("node_id") or "")
    if valid_node_id(cur):
        return cur
    nid = machine_node_id()
    cfg["node_id"] = nid
    dsh_config.save_config(cfg, path)
    return nid


__all__ = ["machine_node_id", "new_node_id", "valid_node_id",
           "ensure_node_id", "regenerate_node_id"]
