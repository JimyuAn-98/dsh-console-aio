# -*- coding: utf-8 -*-
# dsh_core/tunnels.py - Python 隧道启停/常驻重连(纯 Python, 不 import PySide)。
#
# 由 dsh-console-aio.py 抽出: _build_tunnel_obj / _run_python_tunnel / _start_persist /
# _stop_py_tunnel。依赖 dsh_core/config 派生的配置, 不依赖 UI globals。
#
# 通讯约定: 经 events(kind, payload) 回调向外报纯数据:
#   events('log',    (text, tag))
#   events('status', text)
#   events('card',   (key, online_bool))
# 由 app/services.py 转发到 Qt Signal。

import threading

from tunnel_mgr import Tunnel  # 仓库根在 sys.path 时可导入(与主程序一致)


class TunnelManager:
    """隧道启停 + 常驻重连。d 为 config.derived(); base_dir 为 PID/日志所在目录。"""

    def __init__(self, base_dir, d):
        self.base_dir = base_dir
        self.d = d
        self._py_persist = {}  # key -> threading.Event

    # ---------- 构造 tunnel_mgr.Tunnel(原 _build_tunnel_obj) ----------
    def build(self, key, events=None):
        FORWARD_PORTS = self.d.get("forward_ports") or []
        SSH_SERVER = self.d.get("ssh_server") or ""
        SSH_USER = self.d.get("ssh_user") or ""
        LAB_SERVER = self.d.get("lab_server") or ""
        LAB_USER = self.d.get("lab_user") or ""
        LAB_PORT = self.d.get("lab_port") or 3090
        REVERSE_PORT = self.d.get("reverse_port") or 8091
        DASH_PORT = self.d.get("dash_port") or 3080

        if key == "dsh-tunnel":
            forwards = [(p, "127.0.0.1", p) for p in FORWARD_PORTS]
            host, user, mode = SSH_SERVER, SSH_USER, "forward"
            watch = FORWARD_PORTS[0] if FORWARD_PORTS else None
        elif key == "connect-lab-dsh":
            forwards = [(LAB_PORT, "127.0.0.1", LAB_PORT)]
            host, user, mode = LAB_SERVER, LAB_USER, "forward"
            watch = LAB_PORT
        elif key == "dsh-tunnel-reverse":
            forwards = [(REVERSE_PORT, "127.0.0.1", DASH_PORT)]
            host, user, mode = SSH_SERVER, SSH_USER, "reverse"
            watch = None
        else:
            raise ValueError("unknown tunnel: " + key)

        t = Tunnel(self.base_dir, key, host, user, mode=mode,
                   forwards=forwards, watch_port=watch)

        def _logger(msg, tag=""):
            if events:
                events("log", ("  " + msg, tag))
        t.set_logger(_logger)
        return t

    # ---------- 启停(原 _run_python_tunnel / _stop_py_tunnel) ----------
    def start(self, key, mode, events=None):
        if mode == "stop":
            return self.stop(key, events)
        t = self.build(key, events)
        ok = t.start()
        if not ok:
            if events:
                events("status", "启动失败: %s" % key)
                events("card", (key, False))
            return False
        if events:
            events("status", "%s 已启动 (Python)" % key)
            events("card", (key, True))
        if mode == "persist":
            self._persist(key, t, events)
        return True

    def stop(self, key, events=None):
        if key in self._py_persist and self._py_persist.get(key):
            self._py_persist[key].set()
            self._py_persist.pop(key, None)
            if events:
                events("log", ("  [%s] 已取消常驻重连" % key, "warn"))
        t = self.build(key, events)
        n = t.stop()
        if events:
            events("status", "%s 已停止 (Python)" % key if n else "%s 停止(无进程)" % key)
            events("card", (key, False))
        return n

    def _persist(self, key, t, events):
        # 原 _start_persist: 断开自动重连(single 常驻线程, run 到 stop 事件)。
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
                    t.start()
                stop_flag.wait(5)
        threading.Thread(target=loop, daemon=True).start()

    def cancel_persist(self):
        for flag in list(self._py_persist.values()):
            flag.set()
        self._py_persist.clear()


__all__ = ["TunnelManager"]
