# -*- coding: utf-8 -*-
# dsh_core/deployments.py - 部署域业务(纯 Python, 零 Qt, 严禁 import PySide)。
# 由 pyside/pages_deployments.py 的内联编排下沉而来: 快照/测试连接/保存。
#
# 通讯约定: 异步操作遵循 app/services.py 的 _run_result_op 契约
# func(events=None, ...) -> dict payload; payload 至少含 "err"(成功为空字符串)。
# snapshot_all 每完成一个部署经 events("result", ("deploy-snap", {"idx": i, "snap": {...}}))
# 上报单行结果(services 转发为 result("deploy-snap", payload) 信号), 页面按 idx 应用。
# 本模块绝不接触 UI; DshRemote 走 ssh BatchMode(免密), 不收集/保存密码明文。

import dsh_data

_LOCAL_NAME = "本机"


def _log(events, msg, tag=""):
    if events:
        events("log", (msg, tag))


def snapshot_one(dep):
    # 单个部署快照: dep=None 表示本机(DshRemote 本地模式)。
    # 数据层异常统一转 {"ok": False, "error": 中文/原始信息}, 不向外抛。
    try:
        snap = dsh_data.deployment_snapshot(dsh_data.DshRemote(dep))
        if not isinstance(snap, dict):
            snap = {"ok": False, "error": "快照返回格式错误"}
    except Exception as e:
        snap = {"ok": False, "error": str(e)}
    return snap


def snapshot_all(events=None, deps=None):
    # 服务契约: 对 deps(首个元素可为 None=本机)逐个快照。
    # 串行执行(部署数少, 替代旧页面"每部署一线程 + 代数/计数丢弃过期回调"的编排),
    # 每完成一个立即经 events("result", ("deploy-snap", {"idx","snap"})) 上报,
    # 全部完成后返回 {"err": "", "count": n}。
    deps = list(deps or [])
    for idx, dep in enumerate(deps):
        snap = snapshot_one(dep)
        if events:
            events("result", ("deploy-snap", {"idx": idx, "snap": snap}))
    return {"err": "", "count": len(deps)}


def test_conn(events=None, dep=None):
    # 测试连接: 对远程部署 ssh 执行 "echo ok"。契约: {"host", "msg", "err"}。
    if not isinstance(dep, dict) or not (dep.get("host") or "").strip():
        return {"host": "", "msg": "", "err": "请先选择一个远程部署"}
    host = dep.get("host") or "-"
    try:
        remote = dsh_data.DshRemote(dep)
        remote.exec("echo ok")
    except Exception as e:
        err = "连接失败：%s 不可达（%s）" % (host, e)
        _log(events, "[部署管理] " + err, "err")
        return {"host": host, "msg": "", "err": err}
    msg = "连接正常：%s 返回 ok" % host
    _log(events, "[部署管理] " + msg, "ok")
    return {"host": host, "msg": msg, "err": ""}


def save(events=None, depls=None):
    # 写回 config.json 的 deployments(数据层自动 .bak 备份)。
    # 契约: {"msg": 成功文案, "err": 中文失败文案}。
    try:
        dsh_data.save_deployments(list(depls or []))
    except Exception as e:
        err = "写入 config.json 失败: %s" % e
        _log(events, "[部署管理] " + err, "err")
        return {"msg": "", "err": err}
    return {"msg": "部署列表已保存", "err": ""}


__all__ = ["_LOCAL_NAME", "snapshot_one", "snapshot_all", "test_conn", "save"]
