# -*- coding: utf-8 -*-
# dsh_core/sessions.py - 会话域写业务(纯 Python, 零 Qt, 严禁 import PySide)。
# 由 pyside/pages_sessions.py 的内联业务下沉而来; 读取类(read_workspace/list_sessions)
# 仍在 dsh_data.py(阶段4 收敛), 本模块只做"写"。
#
# 通讯约定: 写操作遵循 app/services.py 的 _run_result_op 契约
# func(events=None, ...) -> dict payload; payload 恒含 "msg"/"err" 两个 key,
# 成功 err 为空字符串、失败 msg 为空字符串(对称成对)。进度与拒绝原因经
# events(kind, payload) 纯数据回调报告(仅 "log" 一种), 由 services 转发到 Qt Signal;
# 本模块绝不接触 UI。
#
# 安全红线(必须永久保持, 改动前先读懂):
#   1. delete_group 只允许删除 dsh_data.sessions_dir() 内的分组目录: normpath +
#      commonpath 判定目标在 base 内、不得等于 base 自身、目录必须存在; 任何越界
#      (../ 穿越 / 绝对路径 / 跨盘符)一律中文拒绝, 绝不 shutil.rmtree base 外路径;
#   2. 写 workspace.json 前必须先 dsh_data.backup_file 生成 .bak(覆盖旧备份),
#      再整体替换 archivedSessionIds, 绝不触碰该文件其他字段。

import io
import json
import os
import shutil

import dsh_data


def _log(events, msg, tag=""):
    # events 可为 None(直接调用方); service 注入的回调自身按 kind 分派到 Signal。
    if events:
        events("log", (msg, tag))


def _workspace_path():
    return os.path.join(dsh_data.dsh_home(), "storages", "workspace.json")


def _write_workspace_archived(events, session_ids):
    # 先 .bak 备份, 再整体替换 archivedSessionIds 后写回 workspace.json。
    # dsh_data.read_workspace 返回 {"global": ...} 的内层 global 字典(缺失/损坏返回 {}),
    # 写回时读原始文件保留未知顶层 key(读损坏则重建最小信封), 只替换 global。
    p = _workspace_path()
    dsh_data.backup_file(p)
    ws = dsh_data.read_workspace()
    ws["archivedSessionIds"] = sorted(session_ids)
    try:
        with io.open(p, encoding="utf-8", errors="replace") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    raw["global"] = ws
    with io.open(p, "w", encoding="utf-8", newline="") as fh:
        json.dump(raw, fh, ensure_ascii=False, indent=2)
    return ws["archivedSessionIds"]


def set_archived(events=None, session_ids=None):
    # 服务契约: {"msg": 成功文案, "err": 中文失败文案}。
    # session_ids 是归档后的完整 id 列表(整体替换 workspace.json, 不是增量)。
    if not isinstance(session_ids, list) or any(not isinstance(x, str) for x in session_ids):
        err = "归档列表不合法: 必须是字符串列表, 已取消写入 workspace.json"
        _log(events, "[会话管理] " + err, "err")
        return {"msg": "", "err": err}
    try:
        ids = _write_workspace_archived(events, session_ids)
    except Exception as e:
        err = "写入 workspace.json 失败: %s" % e
        _log(events, "[会话管理] " + err, "err")
        return {"msg": "", "err": err}
    msg = "已更新归档状态(%d 个)" % len(ids)
    _log(events, "[会话管理] " + msg, "ok")
    return {"msg": msg, "err": ""}


def delete_group(events=None, workdir=None):
    # 服务契约: {"msg": 成功文案, "err": 中文失败文案}。
    # 路径越界校验整体下沉在本函数(防线), 页面只负责确认框(交互)。
    if not isinstance(workdir, str) or not workdir.strip():
        err = "分组名不合法: 必须是非空字符串, 已取消删除"
        _log(events, "[会话管理] " + err, "err")
        return {"msg": "", "err": err}
    base = os.path.normpath(dsh_data.sessions_dir())
    target = os.path.normpath(os.path.join(base, workdir))
    try:
        inside = os.path.commonpath([base, target]) == base
    except ValueError:
        # 跨盘符等场景 commonpath 抛 ValueError, 一律视为越界
        inside = False
    if not inside or target == base:
        err = "拒绝删除: 分组路径越界, 目标(%s)不在会话目录内" % workdir
        _log(events, "[会话管理] " + err, "err")
        return {"msg": "", "err": err}
    if not os.path.isdir(target):
        err = "分组目录不存在: %s(可能已被删除, 请刷新后重试)" % workdir
        _log(events, "[会话管理] " + err, "err")
        return {"msg": "", "err": err}
    try:
        shutil.rmtree(target)
    except Exception as e:
        err = "删除分组失败: %s" % e
        _log(events, "[会话管理] " + err, "err")
        return {"msg": "", "err": err}
    msg = "已删除分组: %s" % workdir
    _log(events, "[会话管理] " + msg, "ok")
    return {"msg": msg, "err": ""}


__all__ = ["set_archived", "delete_group"]
