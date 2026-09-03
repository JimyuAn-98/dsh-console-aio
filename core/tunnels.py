# -*- coding: utf-8 -*-
# core/tunnels.py - Python 隧道启停/常驻重连(纯 Python, 不 import PySide)。
#
# 由 dsh-console-aio.py 抽出: _build_tunnel_obj / _run_python_tunnel / _start_persist /
# _stop_py_tunnel。依赖 core/config 派生的配置, 不依赖 UI globals。
#
# 通讯约定: 经 events(kind, payload) 回调向外报纯数据:
#   events('log',    (text, tag))
#   events('status', text)
#   events('card',   (key, online_bool))
# 由 app/services.py 转发到 Qt Signal。

import threading

from core.tunnel_mgr import (
    Tunnel, push_node_token, pull_node_token)


class TunnelManager:
    """通用动态隧道启停 + 常驻重连 + 批量调度。d 为 config.derived(); base_dir 为 PID/日志目录。"""

    def __init__(self, base_dir, d):
        self.base_dir = base_dir
        self.d = d
        self._py_persist = {}  # key -> threading.Event

    def list_tunnels(self):
        # 获取当前所有已配置的隧道列表
        return list(self.d.get("tunnels") or [])

    def find_tunnel(self, key_or_id):
        # 按 ID 或名称查找隧道配置
        tunnels = self.list_tunnels()
        for t in tunnels:
            if t.get("id") == key_or_id or t.get("name") == key_or_id:
                return t
        for t in tunnels:
            if t.get("id") in (key_or_id, "tun_" + str(key_or_id)):
                return t
        return None

    # ---------- 构造 tunnel_mgr.Tunnel ----------
    def build(self, key_or_id, events=None):
        item = self.find_tunnel(key_or_id)
        if not item:
            FORWARD_PORTS = self.d.get("forward_ports") or []
            SSH_SERVER = self.d.get("ssh_server") or ""
            SSH_USER = self.d.get("ssh_user") or ""
            LAB_SERVER = self.d.get("lab_server") or ""
            LAB_USER = self.d.get("lab_user") or ""
            LAB_PORT = self.d.get("lab_port") or 3090
            REVERSE_PORT = self.d.get("reverse_port") or 8091
            DASH_PORT = self.d.get("dash_port") or 3080

            if key_or_id == "dsh-tunnel":
                forwards = [(p, "127.0.0.1", p) for p in FORWARD_PORTS]
                host, user, mode = SSH_SERVER, SSH_USER, "forward"
                watch = FORWARD_PORTS[0] if FORWARD_PORTS else None
            elif key_or_id == "connect-lab-dsh":
                forwards = [(LAB_PORT, "127.0.0.1", LAB_PORT)]
                host, user, mode = LAB_SERVER, LAB_USER, "forward"
                watch = LAB_PORT
            elif key_or_id == "dsh-tunnel-reverse":
                forwards = [(REVERSE_PORT, "127.0.0.1", DASH_PORT)]
                host, user, mode = SSH_SERVER, SSH_USER, "reverse"
                watch = None
            else:
                # 兼容从 tunnel-pids.json 恢复已停止/旧方案隧道的停机签名
                from core.tunnel_mgr import _read_pids
                pids = _read_pids(self.base_dir)
                rec = pids.get(key_or_id)
                if rec and isinstance(rec, dict):
                    host = rec.get("host") or ""
                    user = rec.get("user") or ""
                    mode = rec.get("mode") or "forward"
                    raw_fw = rec.get("forwards") or []
                    forwards = []
                    for fw in raw_fw:
                        if isinstance(fw, (list, tuple)) and len(fw) >= 3:
                            forwards.append((int(fw[0]), str(fw[1] or "127.0.0.1"), int(fw[2])))
                        elif isinstance(fw, dict):
                            forwards.append((int(fw.get("local_port") or 0),
                                             str(fw.get("remote_host") or "127.0.0.1"),
                                             int(fw.get("remote_port") or 0)))
                    watch = rec.get("watch")
                    t = Tunnel(self.base_dir, str(key_or_id), host, user, mode=mode,
                               forwards=forwards, watch_port=watch)
                    def _logger(msg, tag=""):
                        if events:
                            events("log", ("  " + msg, tag))
                    t.set_logger(_logger)
                    return t
                raise ValueError("unknown tunnel: " + str(key_or_id))
            item_id = str(key_or_id)
        else:
            item_id = item.get("id")
            host = item.get("host") or ""
            user = item.get("user") or ""
            mode = item.get("mode") or "forward"
            forwards = []
            for fw in item.get("forwards") or []:
                if isinstance(fw, dict):
                    forwards.append((int(fw.get("local_port") or 0),
                                     str(fw.get("remote_host") or "127.0.0.1"),
                                     int(fw.get("remote_port") or 0)))
                elif isinstance(fw, (list, tuple)) and len(fw) >= 3:
                    forwards.append((int(fw[0]), str(fw[1] or "127.0.0.1"), int(fw[2])))
            watch = item.get("watch_port")
            if not watch and mode == "forward" and forwards:
                watch = forwards[0][0]

        t = Tunnel(self.base_dir, item_id, host, user, mode=mode,
                   forwards=forwards, watch_port=watch)

        def _logger(msg, tag=""):
            if events:
                events("log", ("  " + msg, tag))
        t.set_logger(_logger)
        return t

    # ---------- 启停 ----------
    def start(self, key_or_id, mode="start", events=None):
        if mode == "stop":
            return self.stop(key_or_id, events)
        if mode == "restart":
            self.stop(key_or_id, events)
        t = self.build(key_or_id, events)
        ok = t.start()
        if not ok:
            if events:
                events("status", "启动失败: %s" % key_or_id)
                events("card", (key_or_id, False))
            return False
        if events:
            events("status", "%s 已启动 (Python)" % key_or_id)
            events("card", (key_or_id, True))
        item = self.find_tunnel(key_or_id)
        if (item and item.get("mode") == "reverse") or key_or_id == "dsh-tunnel-reverse":
            self._sync_push_token(events, item)
        if mode == "persist":
            self._persist(key_or_id, t, events, item)
        return True

    def _sync_push_token(self, events=None, item=None):
        from core.dshctl import get_runtime_token
        tok = get_runtime_token("local")
        if not tok:
            return
        ssh_server = (item.get("host") if item else None) or self.d.get("ssh_server") or ""
        ssh_user = (item.get("user") if item else None) or self.d.get("ssh_user") or ""
        local_name = self.d.get("local_name") or "local"

        def _push():
            ok = push_node_token(ssh_server, ssh_user, local_name, tok)
            if ok and events:
                events("log", ("  [信箱] 鉴权 Token 已同步至公网信箱 (%s)" % local_name, "ok"))
        threading.Thread(target=_push, daemon=True).start()

    def stop(self, key_or_id, events=None):
        if key_or_id in self._py_persist and self._py_persist.get(key_or_id):
            self._py_persist[key_or_id].set()
            self._py_persist.pop(key_or_id, None)
            if events:
                events("log", ("  [%s] 已取消常驻重连" % key_or_id, "warn"))
        t = self.build(key_or_id, events)
        n = t.stop()
        if events:
            events("status", "%s 已停止 (Python)" % key_or_id if n else "%s 停止(无进程)" % key_or_id)
            events("card", (key_or_id, False))
        return n

    def _persist(self, key, t, events, item=None):
        stop_flag = threading.Event()
        old = self._py_persist.get(key)
        if old:
            old.set()
        self._py_persist[key] = stop_flag

        def loop():
            while not stop_flag.is_set():
                if not t.is_running():
                    if events:
                        events("log", ("  [%s] 隧道断开, 尝试重连..." % key, "warn"))
                    if t.start():
                        if (item and item.get("mode") == "reverse") or key == "dsh-tunnel-reverse":
                            self._sync_push_token(events, item)
                stop_flag.wait(5)
        threading.Thread(target=loop, daemon=True).start()

    def start_all(self, events=None, persist_default=True):
        # 批量启动所有启用的隧道
        tunnels = self.list_tunnels()
        started = 0
        for tun in tunnels:
            if not tun.get("enabled", True):
                continue
            tid = tun.get("id")
            mode = "persist" if (persist_default and tun.get("auto_restart", True)) else "start"
            if self.start(tid, mode=mode, events=events):
                started += 1
        if events:
            events("status", "已启动 %d 条隧道" % started)
        return started

    def stop_all(self, events=None):
        # 批量停止所有隧道(含当前方案及 PID 文件中记录的所有活跃进程)
        self.cancel_persist()
        from core.tunnel_mgr import _read_pids, _pid_alive, _taskkill
        pids = _read_pids(self.base_dir)
        stopped = 0
        handled_keys = set()

        # 1. 停止当前拓扑中已知的所有隧道
        tunnels = self.list_tunnels()
        for tun in tunnels:
            tid = tun.get("id")
            if tid:
                handled_keys.add(tid)
                if self.stop(tid, events=events):
                    stopped += 1

        # 2. 停止 PID 文件中记录且尚未停止的所有存活进程(含历史方案残留)
        for key, rec in list(pids.items()):
            if key not in handled_keys:
                handled_keys.add(key)
                try:
                    if self.stop(key, events=events):
                        stopped += 1
                except Exception:
                    if isinstance(rec, dict) and rec.get("pid") and _pid_alive(rec["pid"]):
                        _taskkill(rec["pid"])
                        stopped += 1

        for legacy_key in ("dsh-tunnel", "connect-lab-dsh", "dsh-tunnel-reverse"):
            if legacy_key not in handled_keys:
                self.stop(legacy_key, events=None)

        if events:
            events("status", "已停止全部隧道")
        return stopped

    def stop_active_tunnels(self, events=None):
        # 切换方案或热重载时安全终止全部运行中的隧道
        return self.stop_all(events=events)

    def cancel_persist(self):
        for flag in list(self._py_persist.values()):
            flag.set()
        self._py_persist.clear()

    def get_tunnel_status(self, key_or_id):
        # 获取单条隧道实时状态: {"running": bool, "persisting": bool, "pid": int|None}
        t = self.build(key_or_id)
        running = t.is_running()
        persisting = bool(key_or_id in self._py_persist and not self._py_persist[key_or_id].is_set())
        pids = _read_pids(self.base_dir)
        rec = pids.get(key_or_id) or {}
        pid = rec.get("pid") if (rec and _pid_alive(rec.get("pid"))) else None
        return {"running": running, "persisting": persisting, "pid": pid}


__all__ = ["TunnelManager", "push_node_token", "pull_node_token"]
