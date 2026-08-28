# -*- coding: utf-8 -*-
# core/ops.py - 本机运维: dsh web 日志目录读取与 ~/.dsh 一键备份(纯 Python, 零 Qt,
# 严禁 import PySide)。由 ui/pages_ops.py 的内联业务下沉而来。
#
# 通讯约定: backup_dsh_home 遵循 app/services.py 的 _run_result_op 契约
# func(events=None, ...) -> dict payload; payload 至少含 "err"(成功为空字符串,
# 失败为中文文案)。进度/结果日志经 events(kind, payload) 纯数据回调报告(仅 "log" 一种),
# 由 services 转发到 Qt Signal; 本模块绝不接触 UI。
# log_dir/log_entries/read_tail 是本地小 IO, 由页面同步直调(不经 service 线程)。
# 备份走 dsh_data.backup_dsh_home(数据层自动排除凭据/密钥/sessions/node_modules),
# 本模块只负责调数据层 + 统计 zip 大小 + 组装 payload, 不重复实现排除逻辑。

import os
import tempfile

from core import data as dsh_data

TAIL_BYTES = 16384   # 查看日志尾部最多读取的字节数


def _log(events, msg, tag=""):
    # events 可为 None(直接调用方); service 注入的回调自身按 kind 分派到 Signal。
    if events:
        events("log", (msg, tag))


def log_dir():
    # dsh web 日志目录: 固定 %TEMP%/dsh-dash
    return os.path.join(os.environ.get("TEMP") or tempfile.gettempdir(), "dsh-dash")


def log_entries(d=None):
    # 列出日志目录 d(缺省 log_dir())下 *.log 的文件名/大小/修改时间。
    # 契约: 不向调用方抛异常 —— 目录不存在/读取失败返回空表, 单个文件 stat 失败跳过;
    # 筛选只看扩展名(不区分大小写)且必须是文件, 名字像 .log 的子目录不算。
    d = d or log_dir()
    out = []
    if not os.path.isdir(d):
        return out
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return out
    for fn in names:
        if not fn.lower().endswith(".log"):
            continue
        fp = os.path.join(d, fn)
        if not os.path.isfile(fp):
            continue
        try:
            st = os.stat(fp)
        except OSError:
            continue
        out.append({"name": fn, "size": st.st_size, "mtime": st.st_mtime})
    return out


def read_tail(path, limit=TAIL_BYTES):
    # 从文件尾部读最多 limit 字节, 避免大文件整读; 截断时丢弃首行残余半行。
    # 统一换行符, 避免 Windows 日志的 \r 残留显示; 截断区无换行符时保留残余原样。
    # 读失败(如文件不存在)抛 OSError, 由调用方转中文提示。
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        start = max(0, size - limit)
        fh.seek(start)
        data = fh.read()
    text = data.decode("utf-8", errors="replace")
    text = text.replace("\r\n", "\n")
    if start > 0:
        nl = text.find("\n")
        if nl >= 0:
            text = text[nl + 1:]
    return text


def backup_dsh_home(events=None, target=None):
    # 备份 ~/.dsh 到 target 指定的 zip, 返回 {"count": 文件数, "size": zip 字节数,
    # "msg": 中文成功文案, "err": 中文失败文案}; err 成功为空字符串, 两者恒成对
    # (对称取值, 成功时 msg 非空/err 为空, 失败反之)。
    target = target.strip() if isinstance(target, str) else ""
    if not target:
        err = "备份路径不能为空"
        _log(events, "[运维] " + err, "err")
        return {"count": 0, "size": 0, "msg": "", "err": err}
    try:
        count = dsh_data.backup_dsh_home(target)
        size = os.path.getsize(target)
    except Exception as e:
        # 数据层写 zip / 统计大小的任何异常都转中文文案收场, 不抛出到 service 线程外
        err = "备份失败: %s" % e
        _log(events, "[运维] " + err, "err")
        return {"count": 0, "size": 0, "msg": "", "err": err}
    msg = "已备份 %d 个文件: %s" % (count, target)
    _log(events, "[运维] " + msg, "ok")
    return {"count": count, "size": size, "msg": msg, "err": ""}


__all__ = ["TAIL_BYTES", "log_dir", "log_entries", "read_tail", "backup_dsh_home"]
