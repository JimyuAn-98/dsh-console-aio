# -*- coding: utf-8 -*-
# core/plugins.py - 插件域业务(纯 Python, 零 Qt, 严禁 import PySide)。
# 由 ui/pages_plugins.py 的内联业务下沉而来; 安装/卸载命令组装在 dsh_data.plugin_cmd,
# 流式执行在 dshctl.stream_cmd(经 services.run_cmd), 本模块负责列表汇总与 patch 层写。
#
# 通讯约定: 异步操作遵循 app/services.py 的 _run_result_op 契约
# func(events=None, ...) -> dict payload; payload 至少含 "err"(成功为空字符串,
# 失败为中文文案)。日志经 events("log", (text, tag)) 纯数据回调报告, 本模块绝不接触 UI。
#
# 防线原则: 宿主基础设施插件(cordis:/dsh 宿主链)停用会破坏插件链本身, 页面有预检,
# core 的 set_disabled 不信任 UI, 再次拒绝。

import re

from core import data as dsh_data

# 宿主基础设施 id 前缀/名单: 停用会破坏插件链本身, 拒绝切换。
# 沿用 dsh-market 的防护思路(前缀匹配, 宁可多拦)。
PROTECTED_RE = re.compile(
    r"^(cordis:|@deepseek-ai/(cordis-plugin-|dsh-host-|dsh-client-|dsh-web|"
    r"dsh-settings|dsh-credentials|dsh-session|dsh-storage|dsh-typert|"
    r"dsh-api-remotes|dsh-tools|dsh-system-prompt|dsh-agent|dsh-llm|dsh-persona|"
    r"dsh-scope|dsh-launch-environment|dsh-shell|dsh-subprocess|dsh-fs|"
    r"dsh-sandbox|dsh-jobs|dsh-skill|dsh-goal|dsh-workflow|dsh-subagent|"
    r"dsh-workspace|dsh-user-approval|dsh-user-questions|dsh-commands|dsh-hook|"
    r"dsh-spill|dsh-guard|dsh-tool-call-timeout-policy|dsh-repeat-tool-reminder))"
)


def _log(events, msg, tag=""):
    if events:
        events("log", (msg, tag))


def protected(eid):
    # 宿主基础设施行拒绝安装/禁用/卸载
    return bool(eid and PROTECTED_RE.match(str(eid)))


def merge_entries(profile, remote=None):
    # 汇总插件列表: 基线 = read_profile_package 的 bundles(已装插件), 版本取 dependencies;
    # cordis.patch.yml 叠加 disabled 标记 / insert 新增; 返回 entry dict 列表。
    pkg = dsh_data.read_profile_package(profile, remote=remote)
    patch_rows = dsh_data.read_cordis_patch(profile, remote=remote) or []
    deps = pkg.get("dependencies") or {}
    out = []
    index = {}
    for bundle in pkg.get("bundles") or []:
        # bundle 行: id/name 就是 bundle 名(patch 里 - id: X 的 X 也是 bundle 名, 直接可覆盖)
        name = str(bundle)
        row = {"id": name, "name": name,
               "version": deps.get(name, ""), "_src": "bundle"}
        out.append(row)
        index.setdefault(name, row)
    for e in patch_rows:
        if not isinstance(e, dict):
            continue
        if isinstance(e.get("insert"), list):
            # insert 行: patch 新增的 loader entry(如 dsh-market 的 id=dsh-market)
            for sub in e["insert"]:
                if isinstance(sub, dict) and (sub.get("id") or sub.get("name")):
                    eid = sub.get("id") or sub.get("name")
                    if eid in index:
                        continue    # bundles 基线已有同名, 不重复列出
                    row = dict(sub)
                    row["_src"] = "patch"
                    row.setdefault("version", deps.get(sub.get("name") or eid, ""))
                    out.append(row)
                    index[eid] = row
            continue
        eid = e.get("id")
        if not eid:
            continue
        if eid in index:
            # patch 覆盖同名 bundle 行(disabled 标记等)
            index[eid].update({k: v for k, v in e.items() if k != "_src"})
            index[eid]["_src"] = "patch"
            if not index[eid].get("version"):
                index[eid]["version"] = deps.get(eid, "")
        else:
            # patch 里的其它行(如禁用不在 bundles 中的插件)也展示
            row = dict(e)
            row["_src"] = "patch"
            row.setdefault("name", eid)
            row.setdefault("version", deps.get(eid, ""))
            out.append(row)
            index[eid] = row
    return out


def load_view(events=None, profile=None, remote=None, dash_repo=None):
    # 服务契约: {"entries": [...], "id_map": {name->真实 entry id}, "err": ""}。
    # id 映射与 cordis 生效状态来自同一次 dsh --dump-config(子进程, 较慢), 每行附带
    # cordis 字段("enabled"/"disabled"/None=未知); 远程部署不跑 dump-config(退化 None),
    # dump 失败也只退化为空不阻断列表。
    profile = str(profile or "").strip()
    if not profile:
        return {"entries": [], "id_map": {}, "err": "profile 不能为空"}
    try:
        entries = merge_entries(profile, remote=remote)
    except Exception as e:
        return {"entries": [], "id_map": {}, "err": "读取插件列表失败: %s" % e}
    dump = {"id_map": {}, "states": {}}
    if not remote:
        try:
            dump = dsh_data.dump_entry_states(profile, dash_repo) or dump
        except Exception:
            # 映射/状态失败只影响徽章退化为 None, 不阻断列表
            pass
    id_map = dump.get("id_map") or {}
    states = dump.get("states") or {}
    for e in entries:
        st = states.get(id_map.get(e.get("id"), e.get("id")))
        e["cordis"] = None if st is None else ("disabled" if st.get("disabled") else "enabled")
    return {"entries": entries, "id_map": id_map, "err": ""}


def set_disabled(events=None, profile=None, eid=None, disabled=False):
    # patch 层停用/启用, 服务契约: {"msg": 成功文案, "err": 中文失败文案}。
    # 禁用: 无同名行则追加 id + disabled:true 行; 有则原地置 True。
    # 启用: 移除该行的 disabled 字段; 若只剩 id 则整行删除, 保持 patch 干净。
    # 关键: eid 必须是真实 entry id(dump-config 映射后的), 调用方负责映射, core 只防线。
    eid = str(eid or "").strip()
    profile = str(profile or "").strip()
    if not profile or not eid:
        return {"msg": "", "err": "profile 与插件 id 不能为空"}
    if protected(eid):
        # 防线: 页面已预检, core 不信任 UI —— 宿主基础设施禁用会破坏插件链本身
        err = "dsh 宿主基础插件不允许停用/启用: " + eid
        _log(events, "[插件] " + err, "err")
        return {"msg": "", "err": err}
    try:
        patch = dsh_data.read_cordis_patch(profile) or []
        new_rows = []
        touched = False
        for row in patch:
            if not isinstance(row, dict) or row.get("id") != eid:
                new_rows.append(row)
                continue
            touched = True
            row2 = dict(row)
            if disabled:
                row2["disabled"] = True
                new_rows.append(row2)
            else:
                row2.pop("disabled", None)
                if len(row2) > 1:
                    new_rows.append(row2)
                # 只剩 id 的裸行直接删除
        if disabled and not touched:
            new_rows.append({"id": eid, "disabled": True})
        elif not disabled and not touched:
            # 对齐 dshmarket enableRow: 禁用行不在本 patch(手改丢失或来自更低层
            # bundle patch)时, 追加 disabled:false 强启用行, 而不是静默空操作
            new_rows.append({"id": eid, "disabled": False})
        dsh_data.write_cordis_patch(profile, new_rows)
    except OSError as e:
        err = "无法写 cordis.patch.yml：" + str(e)
        _log(events, "[插件] " + err, "err")
        return {"msg": "", "err": err}
    except Exception as e:
        err = "读取/处理 cordis.patch.yml 失败：" + str(e)
        _log(events, "[插件] " + err, "err")
        return {"msg": "", "err": err}
    msg = "已" + ("停用" if disabled else "启用") + " " + eid + " (cordis.patch.yml)"
    _log(events, "[插件] " + msg, "ok")
    return {"msg": msg, "err": ""}


__all__ = ["PROTECTED_RE", "protected", "merge_entries", "load_view", "set_disabled"]
