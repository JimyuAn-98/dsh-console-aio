# -*- coding: utf-8 -*-
# core/profiles.py - ~/.dsh/profiles 的复制/删除(纯 Python 零 Qt, 严禁 import PySide)。
# 由 ui/pages_profiles.py 的内联写操作下沉而来。
#
# 通讯约定: 遵循 app/services.py 的 _run_result_op 契约
# func(events, ...) -> dict payload; payload 恒含 "msg" 与 "err" 两个键(对称取值:
# 成功时 err 为空字符串, 失败时 msg 为空字符串)。进度/结果日志经 events(kind, payload)
# 纯数据回调报告(仅 "log" 一种), 由 services 转发到 Qt Signal; 本模块绝不接触 UI。
#
# 防线原则: 页面(UI 层)有同名预检与确认框, 但 core 不信任 UI —— 名称合法性/重名/
# 源存在性等校验在本层全部重做, 校验失败不产生任何文件系统副作用。

import os
import shutil

from core import data as dsh_data

# Profile 名称禁用字符: 防止名称拼路径时引入分隔符/通配符/Windows 保留字符
_BAD_CHARS = '\\/:*?"<>|'


def _log(events, msg, tag=""):
    # events 可为 None(直接调用方); service 注入的回调自身按 kind 分派到 Signal。
    if events:
        events("log", (msg, tag))


def _name_err(name):
    # 返回名称不合法的中文原因; 合法返回 None。
    # 合法 = 非空、纯文件名(basename 不变, 防路径穿越)、不含禁用字符、不是 . ..
    n = (name or "").strip()
    if not n:
        return "名称不能为空"
    if n in (".", "..") or os.path.basename(n) != n:
        return "名称只能是纯文件名, 不能含路径分隔符或相对路径"
    if any(ch in n for ch in _BAD_CHARS):
        return '名称不能含 \\ / : * ? " < > | 等字符'
    return None


def _in_profiles(base, name):
    # 拼出 profiles 根下的目录路径; 二次防线: commonpath 确认严格位于根下
    # (名称已校验为纯文件名, 这里防名称校验被绕过或 dsh_data 行为变化)。
    # 不在根下/无法求公共前缀(如跨盘符)一律返回 None。
    d = os.path.join(base, name)
    try:
        if os.path.commonpath([base, d]) != base:
            return None
    except ValueError:
        return None
    return d


def copy_profile(events=None, src=None, new=None):
    # 复制 Profile 目录(排除 node_modules)。契约: {"msg": 成功文案, "err": 中文失败文案}。
    src = (src or "").strip()
    new = (new or "").strip()
    err = _name_err(src)
    if err:
        return {"msg": "", "err": "源 Profile " + err}
    err = _name_err(new)
    if err:
        return {"msg": "", "err": "新 Profile " + err}
    if src == new:
        return {"msg": "", "err": "新名称不能与源 Profile 相同"}
    base = dsh_data.profiles_dir()
    src_dir = _in_profiles(base, src)
    new_dir = _in_profiles(base, new)
    if src_dir is None or new_dir is None:
        return {"msg": "", "err": "Profile 路径不合法"}
    if not os.path.isdir(src_dir):
        err = "源 Profile 目录不存在: %s" % src
        _log(events, "[Profile管理] " + err, "err")
        return {"msg": "", "err": err}
    if os.path.exists(new_dir):
        err = "名为 %s 的 Profile 已存在" % new
        _log(events, "[Profile管理] " + err, "err")
        return {"msg": "", "err": err}
    try:
        shutil.copytree(src_dir, new_dir,
                        ignore=shutil.ignore_patterns("node_modules"))
    except Exception as e:
        # 文件系统失败(权限/占用/磁盘等)统一转中文文案, 不向外抛
        err = "复制失败: %s" % e
        _log(events, "[Profile管理] " + err, "err")
        return {"msg": "", "err": err}
    msg = "已复制 %s → %s" % (src, new)
    _log(events, "[Profile管理] " + msg, "ok")
    return {"msg": msg, "err": ""}


def delete_profile(events=None, name=None):
    # 删除 Profile 目录。契约: {"msg": 成功文案, "err": 中文失败文案}。
    # web 是默认 Profile, 永久拒删(该检查先于目录存在性, 保证文案稳定)。
    name = (name or "").strip()
    if name == "web":
        return {"msg": "", "err": "web 是默认 Profile，不可删除"}
    err = _name_err(name)
    if err:
        return {"msg": "", "err": "Profile " + err}
    base = dsh_data.profiles_dir()
    target = _in_profiles(base, name)
    if target is None:
        return {"msg": "", "err": "Profile 路径不合法"}
    if not os.path.isdir(target):
        err = "Profile 目录不存在: %s" % name
        _log(events, "[Profile管理] " + err, "err")
        return {"msg": "", "err": err}
    try:
        shutil.rmtree(target)
    except Exception as e:
        # 文件系统失败(文件被占用/权限等)统一转中文文案, 不向外抛
        err = "删除失败: %s" % e
        _log(events, "[Profile管理] " + err, "err")
        return {"msg": "", "err": err}
    msg = "已删除 %s" % name
    _log(events, "[Profile管理] " + msg, "ok")
    return {"msg": msg, "err": ""}


__all__ = ["copy_profile", "delete_profile"]
