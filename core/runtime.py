# -*- coding: utf-8 -*-
# core/runtime.py - 节点运行态 Token 的落盘/公网信箱/远端直读(纯 Python, 零 Qt, 严禁 import PySide)。
#
# 设计(见 docs/plans/20260911-节点访问规划-v1.md):
#   - 远端控制台捕获到 dsh Token 后, 落盘本机 dsh_home/.console/runtime.json(唯一事实源);
#   - 若配置了公网中转, 再经 SSH 镜像一份到 ~/.dsh_runtime/<node_id>.json(覆盖写入);
#   - 近端取 Token 顺序: 运行时缓存 -> 公网信箱(node_key) -> 直连远端 runtime.json -> 手动。
# 文件格式(JSON, 兼容旧的裸 token 文件):
#   {"v":1,"node_id":...,"hostname":...,"token":...,"updated_at":<epoch>}
# 所有 ssh 一律 BatchMode + ConnectTimeout + 超时, 失败返回 None/False, 不抛到调用方。

import base64
import json
import os
import socket
import subprocess
import time

_NO_WINDOW = subprocess.CREATE_NO_WINDOW
_MAILBOX_DIR = "~/.dsh_runtime"


def _dsh_home():
    from core import data as dsh_data
    return dsh_data.dsh_home()


def runtime_path(dsh_home=None):
    return os.path.join(dsh_home or _dsh_home(), ".console", "runtime.json")


def read_runtime(path=None):
    # 读本机 runtime.json; 缺失/损坏返回 None。
    p = path or runtime_path()
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def write_runtime(node_id, token, hostname=None, path=None):
    # 原子写本机 runtime.json; 返回路径或 None。
    p = path or runtime_path()
    rec = {"v": 1, "node_id": node_id or "",
           "hostname": hostname or socket.gethostname(),
           "token": token or "", "updated_at": int(time.time())}
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
        return p
    except OSError:
        return None


def parse_runtime(text):
    # 解析 runtime 文件内容: 新格式 JSON 或旧的裸 token; 空/坏返回 None。
    t = (text or "").strip()
    if not t:
        return None
    if t.startswith("{"):
        try:
            d = json.loads(t)
        except ValueError:
            return None
        if not isinstance(d, dict):
            return None
        return {"node_id": str(d.get("node_id") or ""),
                "hostname": str(d.get("hostname") or ""),
                "token": str(d.get("token") or ""),
                "updated_at": int(d.get("updated_at") or 0)}
    return {"node_id": "", "hostname": "", "token": t, "updated_at": 0}


def _ssh(host, user, cmd, port=22, timeout=8):
    # 返回 (rc, stdout, stderr); 异常统一成 (1, "", msg)。
    try:
        r = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
             "-o", "LogLevel=ERROR", "-p", str(port), "%s@%s" % (user, host), cmd],
            capture_output=True, text=True, errors="replace", timeout=timeout,
            creationflags=_NO_WINDOW)
        return r.returncode, (r.stdout or ""), (r.stderr or "")
    except Exception as e:
        return 1, "", str(e)


def _relay(cfg):
    cfg = cfg or {}
    return (cfg.get("ssh_server") or ""), (cfg.get("ssh_user") or "")


def mailbox_record(node_id, token, hostname=None):
    return {"v": 1, "node_id": node_id, "hostname": hostname or socket.gethostname(),
            "token": token, "updated_at": int(time.time())}


def publish_mailbox(cfg, node_id, token, hostname=None):
    # 把本机 Token 镜像到公网信箱 <node_id>.json(覆盖写入); base64 传输避免引号问题。
    relay, user = _relay(cfg)
    if not relay or not user or not node_id or not token:
        return False
    rec = json.dumps(mailbox_record(node_id, token, hostname), ensure_ascii=False)
    b64 = base64.b64encode(rec.encode("utf-8")).decode("ascii")
    cmd = ("mkdir -p %s && echo '%s' | base64 -d > %s/%s.json && chmod 600 %s/%s.json"
           % (_MAILBOX_DIR, b64, _MAILBOX_DIR, node_id, _MAILBOX_DIR, node_id))
    rc, _, _ = _ssh(relay, user, cmd)
    return rc == 0


def pull_mailbox(cfg, node_key):
    # 按 node_key 读公网信箱; 新 .json 优先, 回退旧的裸 .token; 返回解析后的 dict 或 None。
    relay, user = _relay(cfg)
    if not relay or not user or not node_key:
        return None
    cmd = ("cat %s/%s.json 2>/dev/null || cat %s/%s.token 2>/dev/null"
           % (_MAILBOX_DIR, node_key, _MAILBOX_DIR, node_key))
    rc, out, _ = _ssh(relay, user, cmd)
    if rc != 0:
        return None
    return parse_runtime(out)


def list_mailbox(cfg):
    # 列出公网信箱条目: [{key, node_id, hostname, token, updated_at}], 按最后更新倒序。
    # 节点码只含 [A-Za-z0-9_-], 故 shell 里 $f 无需引号; @@ 作为条目分隔符。
    relay, user = _relay(cfg)
    if not relay or not user:
        return []
    cmd = ("cd %s 2>/dev/null || exit 0; for f in *.json *.token; do "
           "[ -f $f ] || continue; echo @@$f@@; cat $f; echo; done" % _MAILBOX_DIR)
    rc, out, _ = _ssh(relay, user, cmd)
    if rc != 0:
        return []
    parts = (out or "").split("@@")
    items = []
    for i in range(1, len(parts) - 1, 2):
        name = parts[i].strip()
        body = parts[i + 1]
        if not name:
            continue
        if name.endswith(".json"):
            key = name[:-5]
        elif name.endswith(".token"):
            key = name[:-6]
        else:
            key = name
        rec = parse_runtime(body) or {}
        items.append({"key": key, "node_id": rec.get("node_id") or key,
                      "hostname": rec.get("hostname") or "",
                      "token": rec.get("token") or "",
                      "updated_at": rec.get("updated_at") or 0})
    items.sort(key=lambda r: r.get("updated_at") or 0, reverse=True)
    return items


def delete_mailbox(cfg, key):
    # 删除公网信箱里的某个节点条目(.json 与旧 .token 都删); 返回 bool。
    relay, user = _relay(cfg)
    if not relay or not user or not key:
        return False
    cmd = "rm -f %s/%s.json %s/%s.token" % (_MAILBOX_DIR, key, _MAILBOX_DIR, key)
    rc, _, _ = _ssh(relay, user, cmd)
    return rc == 0


def read_remote_runtime(dep, timeout=8):
    # 直连远端机器, 读它的 dsh_home/.console/runtime.json(局域网场景, 不走公网信箱)。
    dep = dep or {}
    host = dep.get("host") or ""
    user = dep.get("user") or ""
    if not host or not user:
        return None
    port = dep.get("port") or 22
    home = (dep.get("dsh_home") or "~/.dsh").rstrip("/")
    cmd = "cat '%s/.console/runtime.json' 2>/dev/null" % home
    rc, out, _ = _ssh(host, user, cmd, port=port, timeout=timeout)
    if rc != 0:
        return None
    return parse_runtime(out)


def resolve_node_token(dep, cfg=None):
    # 近端取节点 Token: 运行时缓存 -> 公网信箱(node_key) -> 直连远端 runtime.json。
    # 返回 (token, source); source in {"cache","mailbox","remote"}; 取不到 (None, "")。
    from core.dshctl import get_runtime_token
    dep = dep or {}
    name = dep.get("name") or ""
    tok = get_runtime_token(name)
    if tok:
        return tok, "cache"
    key = str(dep.get("node_key") or "")
    if key:
        rec = pull_mailbox(cfg, key)
        if rec and rec.get("token"):
            return rec["token"], "mailbox"
    rec = read_remote_runtime(dep)
    if rec and rec.get("token"):
        return rec["token"], "remote"
    return None, ""


def sync_local_token(cfg=None):
    # 近端/本机: 解析本机 Token -> 落盘 runtime.json -> (配了公网)投递信箱。
    # 返回 {"ok","node_id","err"}; 供设置页「立即同步 Token」按钮调用。
    from core import config as dsh_config
    from core import nodeid
    from core.dshctl import get_runtime_token
    cfg = cfg or dsh_config.load_config()
    nid = str(cfg.get("node_id") or "")
    if not nodeid.valid_node_id(nid):
        nid = nodeid.ensure_node_id()
    tok = get_runtime_token("local", refresh=True)
    if not tok:
        return {"ok": False, "node_id": nid, "err": "未捕获到本机 dsh Token（请先启动 dsh）"}
    write_runtime(nid, tok)
    if not (cfg.get("ssh_server") and cfg.get("ssh_user")):
        return {"ok": False, "node_id": nid, "err": "未配置公网中转（请在设置页填写服务器）"}
    ok = publish_mailbox(cfg, nid, tok)
    return {"ok": bool(ok), "node_id": nid,
            "err": "" if ok else "投递到公网信箱失败"}


def delete_mailbox_node(cfg, key):
    # 删除公网信箱条目并回结构体(供 service._run_core_op)。
    ok = delete_mailbox(cfg, key)
    return {"ok": bool(ok), "key": key,
            "err": "" if ok else "删除失败或条目不存在"}


__all__ = ["runtime_path", "read_runtime", "write_runtime", "parse_runtime",
           "publish_mailbox", "pull_mailbox", "list_mailbox", "delete_mailbox",
           "read_remote_runtime", "resolve_node_token",
           "sync_local_token", "delete_mailbox_node"]
