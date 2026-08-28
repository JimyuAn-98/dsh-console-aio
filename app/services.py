# -*- coding: utf-8 -*-
# app/services.py - 接口层(可 import PySide): 唯一"起后端线程 + 转结果"的地方。
#
# 硬约束(见 docs/UI_LAYERING.md): 后端(dsh_core)与 UI 之间一律走 Qt 信号-槽。
# 本类持有 QObject + Signal; 后台线程跑 dsh_core 的函数, 把它的 events 回调转发到
# Signal.emit —— Qt 会自动把信号排队到接收者线程(线程安全)。后端线程绝不直接改 UI,
# UI 只 connect 信号 + 调本类的触发方法。

import threading

from PySide6.QtCore import QObject, Signal

from dsh_core import config as dsh_config
from dsh_core.dshctl import DshCtl
from dsh_core.tunnels import TunnelManager


class DshService(QObject):
    # 后端 -> UI 的唯一通道(线程安全, 由 events 回调转发)
    status   = Signal(str)               # 一条状态文案
    log      = Signal(str, str)          # (text, tag)
    card     = Signal(str, bool)         # (隧道key, 是否在线)
    monitor  = Signal(object)            # (local_map, ssh_count, remote) 探测结果;
                                         # None 哨兵 = 本轮探测线程异常, UI 只解除 busy 不刷新
    finished = Signal(str, bool)         # (操作key, ok)
    result   = Signal(str, object)       # (操作key, payload dict) 带数据的操作结果,
                                         # 契约见 _run_result_op

    def __init__(self, base_dir, config_path=None, parent=None):
        super().__init__(parent)
        self.base_dir = base_dir
        self._cfg = dsh_config.load_derived(config_path)
        self.ctl = DshCtl(self._cfg)
        self.tunnels = TunnelManager(base_dir, self._cfg)

    # ---- events 回调 -> Qt Signal ----
    def _events(self):
        def cb(kind, payload):
            if kind == "log":
                text, tag = payload
                self.log.emit(text, tag)
            elif kind == "status":
                self.status.emit(payload)
            elif kind == "card":
                key, on = payload
                self.card.emit(key, on)
            elif kind == "monitor":
                self.monitor.emit(payload)
            elif kind == "result":
                op, payload = payload
                self.result.emit(op, payload)
        return cb

    # ---- UI 触发方法(每个都起后台线程, 不阻塞 UI) ----
    def start_dsh(self, mode, op="dsh"):
        ev = self._events()

        def run():
            try:
                self.ctl.run_dsh(mode, ev)
                self.finished.emit(op, True)
            except Exception as e:
                ev("log", ("[dsh] 异常: %s" % e, "err"))
                self.finished.emit(op, False)
        threading.Thread(target=run, daemon=True).start()

    def update_dsh(self, op="update-dsh"):
        # dsh 完整更新(停 web -> git 拉取 -> 依赖 -> 构建 -> 重启), 业务在 dshctl.update_dsh。
        ev = self._events()

        def run():
            try:
                ok = self.ctl.update_dsh(ev)
                self.finished.emit(op, bool(ok))
            except Exception as e:
                ev("log", ("[update] 异常: %s" % e, "err"))
                self.finished.emit(op, False)
        threading.Thread(target=run, daemon=True).start()

    def start_tunnel(self, key, mode, op=None):
        op = op or key
        ev = self._events()

        def run():
            try:
                self.tunnels.start(key, mode, ev)
                self.finished.emit(op, True)
            except Exception as e:
                ev("log", ("[%s] 异常: %s" % (key, e), "err"))
                self.finished.emit(op, False)
        threading.Thread(target=run, daemon=True).start()

    def monitor_once(self):
        # 单次健康探测(原 _monitor_tick 的 worker 部分), 结果经 monitor 信号回 UI。
        # 兜底: 探测线程任何异常都必须以恰好一次 monitor 信号收场(正常结果或 None 哨兵),
        # 否则 UI 的 busy 标志永真, 监控从此停摆。
        ev = self._events()

        def run():
            try:
                self.ctl.monitor_tick(ev)
            except Exception as e:
                # 本层兜底: monitor_tick 内部已逐项吞异常, 这里只防配置结构异常等漏网情况。
                ev("log", ("[monitor] 探测异常: %s" % e, "err"))
                self.monitor.emit(None)
        threading.Thread(target=run, daemon=True).start()

    # ---- 阶段2 波0: 带数据结果的通用操作模板 ----
    # 契约: core 函数签名 func(events=None, ...) -> dict payload; payload 至少含 "err"
    # (成功为空字符串, 失败为中文文案), 其余字段由 core 模块与页面自行约定。本层只负责
    # 起线程与信号转发(result + finished), 不含业务; core 异常也以恰好一次信号收场,
    # 不让 UI 的 busy 状态卡死。页面 connect 本类 result/finished 时接收者是页面自身,
    # 页面销毁 Qt 自动断开(勿在页面 connect 到 app 级槽, 会随页面重建叠加连接)。
    def _run_result_op(self, op, func, *args):
        ev = self._events()

        def run():
            try:
                payload = dict(func(ev, *args) or {})
                payload.setdefault("err", "")
            except Exception as e:
                ev("log", ("[%s] 异常: %s" % (op, e), "err"))
                payload = {"err": str(e)}
            self.result.emit(op, payload)
            self.finished.emit(op, not payload.get("err"))
        threading.Thread(target=run, daemon=True).start()

    # core 模块懒加载: 对应 dsh_core/<域>.py 由阶段2 各波次落地, 未落地前本类仍可导入。
    def check_console_update(self, op="version-check"):
        from dsh_core import version as _version
        self._run_result_op(op, _version.check_latest)

    def update_console(self, op="version-update"):
        from dsh_core import version as _version
        self._run_result_op(op, _version.download_and_apply, self.base_dir)

    def list_ssh_keys(self, op="keys-list"):
        from dsh_core import keys as _keys
        self._run_result_op(op, _keys.list_keys)

    def generate_ssh_key(self, name, op="keys-gen"):
        from dsh_core import keys as _keys
        self._run_result_op(op, _keys.generate_key, name)

    # ---- 阶段2 波2: 写盘类操作(core 懒加载) ----
    # 远程只读红线在页面侧执行(_current_deploy 非 None 时拒绝写操作并中文提示)。
    def backup_dsh_home(self, target, op="ops-backup"):
        from dsh_core import ops as _ops
        self._run_result_op(op, _ops.backup_dsh_home, target)

    def copy_profile(self, src, new, op="profile-copy"):
        from dsh_core import profiles as _profiles
        self._run_result_op(op, _profiles.copy_profile, src, new)

    def delete_profile(self, name, op="profile-delete"):
        from dsh_core import profiles as _profiles
        self._run_result_op(op, _profiles.delete_profile, name)

    def set_sessions_archived(self, session_ids, op="sessions-archive"):
        # session_ids 为归档后的完整 id 列表(整体替换 workspace.json 的 archivedSessionIds)。
        from dsh_core import sessions as _sessions
        self._run_result_op(op, _sessions.set_archived, session_ids)

    def delete_session_group(self, workdir, op="sessions-delete"):
        from dsh_core import sessions as _sessions
        self._run_result_op(op, _sessions.delete_group, workdir)

    # ---- 阶段2 波3: 插件/部署域(core 懒加载) + 通用流式命令 ----
    def run_cmd(self, cmd, cwd=None, env=None, op="run-cmd"):
        # 通用流式命令(dshctl.stream_cmd 的 service 入口): 逐行输出经 log 信号回主日志,
        # 完成 finished(op, ok)。插件安装/卸载、环境工具命令等共用, 是页面脱开
        # app._stream_cmd 依赖的正式通道。
        ev = self._events()

        def run():
            try:
                ok = self.ctl.stream_cmd(cmd, cwd=cwd, env=env, events=ev)
            except Exception as e:
                ev("log", ("[%s] 异常: %s" % (op, e), "err"))
                ok = False
            self.finished.emit(op, bool(ok))
        threading.Thread(target=run, daemon=True).start()

    def load_plugins(self, profile, remote=None, op="plugins-load"):
        from dsh_core import plugins as _plugins
        self._run_result_op(op, _plugins.load_view, profile, remote,
                            self.ctl.d.get("dash_repo") or "")

    def toggle_plugin(self, profile, eid, disabled, op="plugins-toggle"):
        from dsh_core import plugins as _plugins
        self._run_result_op(op, _plugins.set_disabled, profile, eid, disabled)

    def refresh_deployments(self, deps, op="deploy-refresh"):
        from dsh_core import deployments as _deployments
        self._run_result_op(op, _deployments.snapshot_all, deps)

    def test_deployment(self, dep, op="deploy-test"):
        from dsh_core import deployments as _deployments
        self._run_result_op(op, _deployments.test_conn, dep)

    def save_deployments(self, depls, op="deploy-save"):
        from dsh_core import deployments as _deployments
        self._run_result_op(op, _deployments.save, depls)

    # ---- 阶段4: 纯读/轻写页统一经 service(dsh_core.data 懒加载) ----
    def _run_core_op(self, op, func, *args):
        # 通用 core 调用: func 为 dsh_core.data 的纯数据函数(签名不带 events 回调, 与
        # _run_result_op 的域函数不同), 返回值原样包装为 {"data":..., "err":...};
        # 异常以恰好一次 result/finished 收场, 不让 UI busy 卡死。
        def run():
            try:
                payload = {"data": func(*args), "err": ""}
            except Exception as e:
                self.log.emit("[%s] 异常: %s" % (op, e), "err")
                payload = {"data": None, "err": str(e)}
            self.result.emit(op, payload)
            self.finished.emit(op, not payload["err"])
        threading.Thread(target=run, daemon=True).start()

    def list_agent_presets(self, remote=None, op="agents-list"):
        from dsh_core import data as _data
        self._run_core_op(op, _data.list_agent_presets, remote)

    def read_taskboard(self, remote=None, op="taskboard-read"):
        from dsh_core import data as _data
        self._run_core_op(op, _data.read_taskboard, remote)

    def read_usage_stats(self, remote=None, op="usage-read"):
        from dsh_core import data as _data
        self._run_core_op(op, _data.usage_stats, remote)

    def read_settings(self, remote=None, op="llm-read"):
        from dsh_core import data as _data
        self._run_core_op(op, _data.read_settings, remote)

    def write_settings(self, data, op="llm-save"):
        # 写 settings.yaml(数据层写前 .bak); 写业务唯一出口, 页面组装好完整 data 传入。
        from dsh_core import data as _data
        self._run_core_op(op, _data.write_settings, data)

    # ---- 构造 ----
    @classmethod
    def from_env(cls, base_dir=None, parent=None):
        # base_dir 默认取仓库根(config 同目录)。config 走 DSH_AIO_CONFIG(与主程序一致)。
        import os
        if base_dir is None:
            here = os.path.dirname(os.path.abspath(__file__))
            base_dir = os.path.dirname(here)  # 仓库根
        return cls(base_dir, config_path=os.environ.get("DSH_AIO_CONFIG"), parent=parent)


__all__ = ["DshService"]
