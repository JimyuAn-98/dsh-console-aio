# -*- coding: utf-8 -*-
# app/services.py - 接口层(可 import PySide): 唯一"起后端线程 + 转结果"的地方。
#
# 硬约束(见 docs/ARCHITECTURE.md): 后端(core)与 UI 之间一律走 Qt 信号-槽。
# 本类持有 QObject + Signal; 后台线程跑 core 的函数, 把它的 events 回调转发到
# Signal.emit —— Qt 会自动把信号排队到接收者线程(线程安全)。后端线程绝不直接改 UI,
# UI 只 connect 信号 + 调本类的触发方法。

import os
import re
import tempfile
import threading
import time

from PySide6.QtCore import QObject, Signal

from core import config as dsh_config
from core.dshctl import DshCtl
from core.tunnels import TunnelManager

# 操作日志会持久化到磁盘: 落盘前抹掉鉴权 Token(控制台内存显示保持原样,
# 不影响"鉴权链接"等现有功能, 也守住"Token 绝不写入日志"的安全红线)。
_SECRET_RE = re.compile(r"(?i)(token=)[A-Za-z0-9_\-]{6,}|(bearer\s+)[A-Za-z0-9._\-]{6,}")


def _redact_secrets(text):
    def _sub(m):
        return (m.group(1) or m.group(2) or "") + "***"
    return _SECRET_RE.sub(_sub, text)


class DshService(QObject):
    # 后端 -> UI 的唯一通道(线程安全, 由 events 回调转发)
    status   = Signal(str)               # 一条状态文案
    log      = Signal(str, str)          # (text, tag)
    step     = Signal(int, str)          # (step_idx, step_text) 步骤进度
    card     = Signal(str, bool)         # (隧道key, 是否在线)
    monitor  = Signal(object)            # (local_map, ssh_count, remote) 探测结果;
                                         # None 哨兵 = 本轮探测线程异常, UI 只解除 busy 不刷新
    finished = Signal(str, bool)         # (操作key, ok)
    result   = Signal(str, object)       # (操作key, payload dict) 带数据的操作结果,
                                         # 契约见 _run_result_op

    def __init__(self, base_dir, config_path=None, parent=None):
        super().__init__(parent)
        self.base_dir = base_dir
        self._config_path = config_path
        self._cfg = dsh_config.load_derived(config_path)
        self.ctl = DshCtl(self._cfg)
        self.tunnels = TunnelManager(base_dir, self._cfg)
        # 长操作完整输出落盘(页面日志控件有行数上限, 安装/更新可达上千行):
        # 每次操作一个 <temp>/dsh-console-ops/<op>-<时间戳>.log, 页面可"打开操作日志"复查。
        self._op_logs = {}          # op -> 打开的文件句柄
        self._op_log_lock = threading.Lock()
        self._last_op_log = ""      # 最近一次操作日志路径(UI 按钮用)

    def reload_config(self, config_path=None):
        # 热重载(P0): 重读配置并更新 ctl/tunnels 的派生 dict——监控探测点/卡片状态等
        # 随之跟随; UI 侧需另行重建依赖 CONFIG 的视图(右栏/窄条/卡片/部署列表)。
        if config_path is not None:
            self._config_path = config_path
        self._cfg = dsh_config.load_derived(self._config_path)
        self.ctl.d = self._cfg
        self.tunnels.d = self._cfg

    # ---- 长操作完整输出日志(与 Qt 信号并列的一条"落盘"通道) ----
    def _op_log_path(self, op):
        # 操作名仅用于文件名, 过滤掉路径分隔符等非法字符。
        safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in str(op)) or "op"
        base = os.path.join(tempfile.gettempdir(), "dsh-console-ops")
        try:
            os.makedirs(base, exist_ok=True)
        except OSError:
            return ""
        return os.path.join(base, "%s-%s.log" % (safe, time.strftime("%Y%m%d-%H%M%S")))

    def _op_log_open(self, op):
        # 建文件并写头; 失败返回 ""(磁盘权限等, 不阻断操作本身)。
        path = self._op_log_path(op)
        if not path:
            return ""
        try:
            fh = open(path, "a", encoding="utf-8", errors="replace")
            fh.write("# dsh 控制台操作日志 op=%s started=%s\n"
                     % (op, time.strftime("%Y-%m-%d %H:%M:%S")))
            fh.flush()
        except OSError:
            return ""
        with self._op_log_lock:
            old = self._op_logs.pop(op, None)   # 同名 op 重入: 关掉上一个, 不泄漏句柄
            self._op_logs[op] = fh
            self._last_op_log = path
        if old is not None:
            try:
                old.close()
            except OSError:
                pass
        return path

    def _op_log_write(self, op, text):
        with self._op_log_lock:
            fh = self._op_logs.get(op)
        if fh is None:
            return
        try:
            fh.write(_redact_secrets(text) + "\n")
            fh.flush()
        except (OSError, ValueError):
            # 句柄已关(收尾竞态)/磁盘写失败: 日志本身不得影响主流程, 静默丢弃。
            pass

    def _op_log_close(self, op):
        with self._op_log_lock:
            fh = self._op_logs.pop(op, None)
        if fh is not None:
            try:
                fh.close()
            except OSError:
                pass

    def latest_op_log(self):
        # 最近一次长操作的完整日志路径(空字符串 = 本次会话尚无长操作)。
        return self._last_op_log

    def _begin_op(self, op, log_full=True):
        # 长操作统一入口: 返回 events 回调; log_full 时同时把全过程写进操作日志,
        # 并把路径作为一条主日志提示(用户据此打开文件复查完整输出)。
        ev = self._events(op if log_full else None)
        if log_full:
            path = self._op_log_open(op)
            if path:
                self.log.emit("[日志] 完整输出: " + path, "ok")
        return ev

    # ---- events 回调 -> Qt Signal ----
    def _events(self, op=None):
        def cb(kind, payload):
            if kind == "log":
                if isinstance(payload, tuple) and len(payload) == 2:
                    text, tag = payload
                else:
                    text, tag = str(payload), ""
                self.log.emit(text, tag)
                if op:
                    self._op_log_write(op, text)
            elif kind == "status":
                self.status.emit(str(payload))
                if op:
                    self._op_log_write(op, "[状态] " + str(payload))
            elif kind == "step":
                if isinstance(payload, (tuple, list)) and len(payload) >= 2:
                    self.step.emit(int(payload[0]), str(payload[1]))
                    if op:
                        self._op_log_write(op, "[步骤 %s] %s" % (payload[0], payload[1]))
            elif kind == "card":
                key, on = payload
                self.card.emit(key, on)
            elif kind == "monitor":
                self.monitor.emit(payload)
            elif kind == "result":
                op2, payload2 = payload
                self.result.emit(op2, payload2)
        return cb

    # ---- UI 触发方法(每个都起后台线程, 不阻塞 UI) ----
    def start_dsh(self, mode="start", op="dsh"):
        if not isinstance(mode, str):
            mode = "start"
        ev = self._begin_op(op)

        def run():
            try:
                ok = self.ctl.run_dsh(mode, ev)
            except Exception as e:
                ev("log", ("[dsh] 异常: %s" % e, "err"))
                ok = False
            self._op_log_close(op)
            self.finished.emit(op, bool(ok))
        threading.Thread(target=run, daemon=True).start()

    def stop_dsh(self, op="dsh-stop"):
        self.start_dsh("stop", op=op)

    def restart_dsh(self, op="dsh-restart"):
        self.start_dsh("restart", op=op)

    def update_dsh(self, to_main=False, op="update-dsh"):
        # dsh 完整更新(停 web -> 拉取 -> 依赖 -> 构建 -> 重启), 业务在 dshctl.update_dsh。
        # to_main=True: 从固定版本切回默认分支再更新(UI 在固定状态下确认后传入)。
        ev = self._begin_op(op)

        def run():
            try:
                ok = self.ctl.update_dsh(ev, to_main=to_main)
            except Exception as e:
                ev("log", ("[update] 异常: %s" % e, "err"))
                ok = False
            self._op_log_close(op)
            self.finished.emit(op, bool(ok))
        threading.Thread(target=run, daemon=True).start()

    def deploy_dsh_version(self, tag, allow_dirty=False, op="dsh-deploy-version"):
        # 部署指定版本(切/回退到某个 Release tag), 业务在 dshctl.deploy_dsh_version;
        # 工作区脏时 core 只回 {"dirty": True} 哨兵, 由页面二次确认后以 allow_dirty=True 重发。
        self._run_result_op(op, self.ctl.deploy_dsh_version, tag, allow_dirty,
                            log_full=True)

    def start_tunnel(self, key, mode="start", op=None):
        op = op or key
        ev = self._begin_op(op)

        def run():
            try:
                self.tunnels.start(key, mode, ev)
                ok = True
            except Exception as e:
                ev("log", ("[%s] 异常: %s" % (key, e), "err"))
                ok = False
            self._op_log_close(op)
            self.finished.emit(op, ok)
        threading.Thread(target=run, daemon=True).start()

    def stop_tunnel(self, key, op=None):
        op = op or key
        ev = self._begin_op(op)

        def run():
            try:
                self.tunnels.stop(key, ev)
                ok = True
            except Exception as e:
                ev("log", ("[%s] 停止异常: %s" % (key, e), "err"))
                ok = False
            self._op_log_close(op)
            self.finished.emit(op, ok)
        threading.Thread(target=run, daemon=True).start()

    def start_all_tunnels(self, op="start-all-tunnels"):
        ev = self._begin_op(op)

        def run():
            try:
                n = self.tunnels.start_all(events=ev)
                ok = n > 0
            except Exception as e:
                ev("log", ("[tunnels] 批量启动异常: %s" % e, "err"))
                ok = False
            self._op_log_close(op)
            self.finished.emit(op, ok)
        threading.Thread(target=run, daemon=True).start()

    def stop_all_tunnels(self, op="stop-all-tunnels"):
        ev = self._begin_op(op)

        def run():
            try:
                self.tunnels.stop_all(events=ev)
                ok = True
            except Exception as e:
                ev("log", ("[tunnels] 批量停止异常: %s" % e, "err"))
                ok = False
            self._op_log_close(op)
            self.finished.emit(op, ok)
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
    def _run_result_op(self, op, func, *args, log_full=False):
        ev = self._begin_op(op, log_full=log_full)

        def run():
            try:
                payload = dict(func(ev, *args) or {})
                payload.setdefault("err", "")
            except Exception as e:
                ev("log", ("[%s] 异常: %s" % (op, e), "err"))
                payload = {"err": str(e)}
            self._op_log_close(op)
            self.result.emit(op, payload)
            self.finished.emit(op, not payload.get("err"))
        threading.Thread(target=run, daemon=True).start()

    # core 模块懒加载: 对应 core/<域>.py 由阶段2 各波次落地, 未落地前本类仍可导入。
    def check_console_update(self, op="version-check"):
        from core import version as _version
        self._run_result_op(op, _version.check_latest)

    def update_console(self, op="version-update"):
        from core import version as _version
        self._run_result_op(op, _version.download_and_apply, self.base_dir, log_full=True)

    def download_console_installer(self, version, op="version-installer"):
        # 安装版自更新: 下载最新安装包(不执行), 完成后由页面启动安装器并退出。
        from core import version as _version
        self._run_result_op(op, _version.download_installer, version, log_full=True)

    def list_ssh_keys(self, op="keys-list"):
        from core import keys as _keys
        self._run_result_op(op, _keys.list_keys)

    def generate_ssh_key(self, name, op="keys-gen"):
        from core import keys as _keys
        self._run_result_op(op, _keys.generate_key, name)

    # ---- 阶段2 波2: 写盘类操作(core 懒加载) ----
    # 远程只读红线在页面侧执行(_current_deploy 非 None 时拒绝写操作并中文提示)。
    def backup_dsh_home(self, target, op="ops-backup"):
        from core import ops as _ops
        self._run_result_op(op, _ops.backup_dsh_home, target, log_full=True)

    def copy_profile(self, src, new, op="profile-copy"):
        from core import profiles as _profiles
        self._run_result_op(op, _profiles.copy_profile, src, new)

    def delete_profile(self, name, op="profile-delete"):
        from core import profiles as _profiles
        self._run_result_op(op, _profiles.delete_profile, name)

    def set_sessions_archived(self, session_ids, op="sessions-archive"):
        # session_ids 为归档后的完整 id 列表(整体替换 workspace.json 的 archivedSessionIds)。
        from core import sessions as _sessions
        self._run_result_op(op, _sessions.set_archived, session_ids)

    def delete_session_group(self, workdir, op="sessions-delete"):
        from core import sessions as _sessions
        self._run_result_op(op, _sessions.delete_group, workdir)

    # ---- 阶段2 波3: 插件/部署域(core 懒加载) + 通用流式命令 ----
    def run_cmd(self, cmd, cwd=None, env=None, op="run-cmd"):
        # 通用流式命令(dshctl.stream_cmd 的 service 入口): 逐行输出经 log 信号回主日志,
        # 完成 finished(op, ok)。插件安装/卸载、环境工具命令等共用的统一出口。
        ev = self._begin_op(op)

        def run():
            try:
                ok = self.ctl.stream_cmd(cmd, cwd=cwd, env=env, events=ev)
            except Exception as e:
                ev("log", ("[%s] 异常: %s" % (op, e), "err"))
                ok = False
            self._op_log_close(op)
            self.finished.emit(op, bool(ok))
        threading.Thread(target=run, daemon=True).start()

    def load_plugins(self, profile, remote=None, op="plugins-load"):
        from core import plugins as _plugins
        self._run_result_op(op, _plugins.load_view, profile, remote,
                            self.ctl.d.get("dash_repo") or "")

    def toggle_plugin(self, profile, eid, disabled, op="plugins-toggle"):
        from core import plugins as _plugins
        self._run_result_op(op, _plugins.set_disabled, profile, eid, disabled)

    def refresh_deployments(self, deps, op="deploy-refresh"):
        from core import deployments as _deployments
        self._run_result_op(op, _deployments.snapshot_all, deps)

    def test_deployment(self, dep, op="deploy-test"):
        from core import deployments as _deployments
        self._run_result_op(op, _deployments.test_conn, dep)

    def save_deployments(self, depls, op="deploy-save"):
        from core import deployments as _deployments
        self._run_result_op(op, _deployments.save, depls)

    # ---- 阶段4: 纯读/轻写页统一经 service(core.data 懒加载) ----
    def _run_core_op(self, op, func, *args):
        # 通用 core 调用: func 为 core.data 的纯数据函数(签名不带 events 回调, 与
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
        from core import data as _data
        self._run_core_op(op, _data.list_agent_presets, remote)

    def read_taskboard(self, remote=None, op="taskboard-read"):
        from core import data as _data
        self._run_core_op(op, _data.read_taskboard, remote)

    def read_usage_stats(self, remote=None, op="usage-read"):
        from core import data as _data
        self._run_core_op(op, _data.usage_stats, remote)

    def read_settings(self, remote=None, op="llm-read"):
        from core import data as _data
        self._run_core_op(op, _data.read_settings, remote)

    def write_settings(self, data, op="llm-save"):
        # 写 settings.yaml(数据层写前 .bak); 写业务唯一出口, 页面组装好完整 data 传入。
        from core import data as _data
        self._run_core_op(op, _data.write_settings, data)

    # ---- 阶段4 扩充: 总览/会话/Profile/环境/安装/设置 统一经 service ----
    def read_overview(self, cfg, depls, smoke=False, op="overview-read"):
        from core import data as _data
        self._run_core_op(op, _data.collect_overview_data, cfg, depls, smoke)

    def probe_overview_local(self, cfg, op="overview-live"):
        # 总览命中缓存时刷新"实时"字段(本机 web 探活 + 运行时 token), 不写缓存
        from core import data as _data
        self._run_core_op(op, _data.probe_local_web, cfg)

    def read_sessions(self, remote=None, op="sessions-read"):
        from core import data as _data
        self._run_core_op(op, _data.read_sessions_data, remote)

    def list_profiles(self, remote=None, op="profiles-list"):
        from core import data as _data
        self._run_core_op(op, _data.list_profiles, remote)

    def publish_local_token(self, cfg, op="node-publish"):
        # 本机 Token -> runtime.json -> 公网信箱(设置页「立即同步」)
        from core import runtime as _runtime
        self._run_core_op(op, _runtime.sync_local_token, cfg)

    def list_mailbox_nodes(self, cfg, op="mailbox-list"):
        # 列举公网信箱节点(部署页「从公网信箱发现」)
        from core import runtime as _runtime
        self._run_core_op(op, _runtime.list_mailbox, cfg)

    def delete_mailbox_node(self, cfg, key, op="mailbox-del"):
        from core import runtime as _runtime
        self._run_core_op(op, _runtime.delete_mailbox_node, cfg, key)

    def regenerate_node_id(self, op="node-regen"):
        from core import nodeid as _nodeid
        self._run_core_op(op, _nodeid.regenerate_node_id)

    def check_tool_versions(self, tools, op="dsh-tool-versions"):
        from core import env as _env
        self._run_core_op(op, _env.tool_versions, tools)

    def fetch_dsh_releases(self, force=False, op="dsh-releases"):
        # dsh 本体 GitHub Releases(含更新日志正文); force=True 绕过 core 的 TTL 缓存
        from core.dshctl import fetch_dsh_releases
        self._run_core_op(op, fetch_dsh_releases, force)

    def detect_dsh_mode(self, force=False, op="dsh-mode"):
        # 检测本机 dsh 安装方式(源码/全局包/未安装) + 版本, 供 DSH 管理页展示与分流。
        from core import pkgmgr
        self._run_core_op(op, pkgmgr.detect_mode, self._cfg, force)

    def install_dsh(self, url, target, version="", op="dsh-install"):
        from core import env as _env
        self._run_result_op(op, _env.install_dsh, url, target, version, log_full=True)

    def install_dsh_pkg(self, version="", op="dsh-install-pkg"):
        # 官方全局包安装(npm): npm install -g @deepseek-ai/dsh[@版本]。
        from core import env as _env
        self._run_result_op(op, _env.install_dsh_pkg, version, log_full=True)

    def uninstall_dsh(self, keep_data=True, op="dsh-uninstall"):
        from core import env as _env
        self._run_result_op(op, _env.uninstall_dsh, keep_data, log_full=True)

    def test_ssh(self, host, user, port=22, op="settings-test-ssh"):
        from core import env as _env
        self._run_core_op(op, _env.test_ssh, host, user, port)

    def generate_diagnostics(self, cfg, app_version, base_dir, op="settings-gen-diag"):
        from core import diagnostics as _diag
        def _gen():
            data = _diag.collect(None, cfg, app_version, base_dir)
            return _diag.render(data)
        self._run_core_op(op, _gen)

    # ---- 构造 ----
    @classmethod
    def from_env(cls, base_dir=None, parent=None):
        # base_dir 默认取仓库根(config 同目录)。config 走 DSH_AIO_CONFIG(与主程序一致)。
        # 打包运行(onefile)时 __file__ 在临时解压目录, 而 TunnelManager 的 PID 文件等
        # 需要跨启动持久化 —— base_dir 必须落在 exe 所在安装目录(与主程序 BASE_DIR 同规则)。
        import os, sys
        if base_dir is None:
            if getattr(sys, "frozen", False):
                base_dir = os.path.dirname(os.path.abspath(sys.executable))
            else:
                here = os.path.dirname(os.path.abspath(__file__))
                base_dir = os.path.dirname(here)  # 仓库根
        return cls(base_dir, config_path=os.environ.get("DSH_AIO_CONFIG"), parent=parent)


__all__ = ["DshService"]
