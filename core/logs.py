# -*- coding: utf-8 -*-
# core/logs.py - dsh web 落盘日志读取/解析(纯 Python, 零 Qt, 严禁 import PySide)。
# 数据源: 控制台 start_dsh(core/dshctl.py)重定向的 %TEMP%/dsh-dash/dsh-web.{out,err}.log,
# 追加模式。边界: 用户自己在终端启动的 dsh 不落盘, 查看器只覆盖控制台拉起的实例。
# 页面(ui/pages_logs.py)只做 QTimer 轮询与渲染; 本模块全部可单测。

import os
import re

# web 登录 token 打码(仅展示层; 日志文件本身不动)。token 值是 base64url 形态。
_TOKEN_RE = re.compile(r"(token=)[A-Za-z0-9_\-]+")

# 行 -> 着色 tag 关键词(小写匹配, 严重度优先 err > warn > ok)。关键词取自真实日志:
# err.log 的 Node 堆栈/[ELIFECYCLE] failed; out.log 的 "dsh web: http://..." 启动成功行。
_ERR_KEYWORDS = ("error", "failed", "fatal", "exception", "elifecycle", "失败")
_WARN_KEYWORDS = ("warn", "deprecat")
_OK_KEYWORDS = ("dsh web:", "listening", "ready", "started")

MAX_TAIL_LINES = 2000     # 初始加载尾部行数
MAX_BUFFER_ROWS = 5000    # 页面行缓冲上限(超限丢最旧)


def log_dir():
    # 与 core/dshctl.start_dsh 的落盘目录保持一致
    return os.path.join(os.environ.get("TEMP", "."), "dsh-dash")


def log_path(stream):
    # stream: "out" | "err"
    return os.path.join(log_dir(), "dsh-web." + stream + ".log")


def mask_tokens(text):
    # 展示层脱敏: token 值打码, URL 其余部分保留
    return _TOKEN_RE.sub(r"\1***", text)


def classify_line(text):
    # 行 -> 着色 tag: "err"/"warn"/"ok"/""(正文)。大小写不敏感。
    low = text.lower()
    if any(k in low for k in _ERR_KEYWORDS):
        return "err"
    if any(k in low for k in _WARN_KEYWORDS):
        return "warn"
    if any(k in low for k in _OK_KEYWORDS):
        return "ok"
    return ""


def classify_stream(stream, text):
    # err 流整文件按错误红显示(它本身就是 stderr); out 流逐行分级
    return "err" if stream == "err" else classify_line(text)


def read_tail(path, max_lines=MAX_TAIL_LINES, max_bytes=2 * 1024 * 1024):
    # 读文件尾部最多 max_lines 行(最多回读 max_bytes 字节, 防追加型大文件全量载入)。
    # 文件不存在/不可读返回 []。
    try:
        size = os.path.getsize(path)
        capped = size > max_bytes
        with open(path, "rb") as fh:
            if capped:
                fh.seek(size - max_bytes)
            data = fh.read()
    except OSError:
        return []
    lines = data.decode("utf-8", "replace").splitlines()
    if capped and lines:
        # seek 可能落在行中间(或多字节字符中间): 首行是残行, 整行丢弃
        lines = lines[1:]
    return lines[-max_lines:]


class Tailer:
    # 增量 tail: 记字节 offset 只返回新产生的完整行; 半行留给下次(写入方还没写完 \n);
    # 文件被截断/重建(size < offset)时 reset=True 并从头重读, 调用方应清空缓冲。
    def __init__(self, path):
        self.path = path
        self.offset = 0

    def read_new(self):
        # 返回 (lines, reset); 文件不存在时视为空(size=0), offset>0 则报告 reset
        try:
            size = os.path.getsize(self.path)
        except OSError:
            size = 0
        reset = size < self.offset
        if reset:
            self.offset = 0
        try:
            with open(self.path, "rb") as fh:
                fh.seek(self.offset)
                data = fh.read()
        except OSError:
            return [], reset
        nl = data.rfind(b"\n") + 1   # 最后一个 \n 之后的半行不消费
        lines = [l.decode("utf-8", "replace").rstrip("\r")
                 for l in data[:nl].split(b"\n")[:-1]]
        self.offset += nl
        return lines, reset


def filter_rows(rows, include="", exclude=""):
    # rows: [(text, tag)]; include 命中才保留, exclude 命中则剔除, 均大小写不敏感。
    # 空串条件跳过。返回过滤后的新列表, 不改入参。
    inc = include.strip().lower()
    exc = exclude.strip().lower()
    out = []
    for text, tag in rows:
        low = text.lower()
        if inc and inc not in low:
            continue
        if exc and exc in low:
            continue
        out.append((text, tag))
    return out


__all__ = ["MAX_BUFFER_ROWS", "MAX_TAIL_LINES", "Tailer", "classify_line",
           "classify_stream", "filter_rows", "log_dir", "log_path",
           "mask_tokens", "read_tail"]
