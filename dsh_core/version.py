# -*- coding: utf-8 -*-
# dsh_core/version.py - 控制台自身版本检查与自更新(纯 Python, 严禁 import PySide)。
#
# 由 pyside/pages_version.py 抽出的业务: 版本比较/拉远程 version.json/读本地更新日志/
# 下载 zip 并备份替换程序文件/重启进程。通讯约定同 dsh_core 其他模块: 本模块不碰 UI,
# 进度经 events(kind, payload) 回调向外报告(纯数据):
#   events('status', text)
#   events('log',    (text, tag))
# 由 app/services.py 把 events 转发到 Qt Signal。异步操作遵循 services 契约:
# func(events=None, ...) -> dict payload, payload 至少含 "err"(成功为空字符串,
# 失败为中文文案)。spawn_restart 是 UI 生命周期动作, 同步由页面直接调用。

import io
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

# 与主程序一致的更新源(检查更新/自动更新共用)
GITHUB_RAW = "https://raw.githubusercontent.com/JimyuAn-98/dsh-console-aio/main/"
GITHUB_ZIP = "https://codeload.github.com/JimyuAn-98/dsh-console-aio/zip/refs/heads/main"
VERSION_URL = GITHUB_RAW + "version.json"
RELEASE_URL = GITHUB_RAW + "RELEASE_NOTES.md"

# 更新时保留的本地文件(用户数据/配置, 不替换)
KEEP_FILES = {"config.json", "dsh使用指南.txt", "tunnel-pids.json"}

# 备份+替换在子进程(python -c)里执行, 不占住调用线程; 脚本纯 ASCII(keep 清单经 argv 传入)
_REPLACE_CODE = (
    "import json, os, shutil, sys\n"
    "src, base, bak, keep_json = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]\n"
    "keep = set(json.loads(keep_json))\n"
    "os.makedirs(bak, exist_ok=True)\n"
    "replaced = 0\n"
    "for fn in os.listdir(src):\n"
    "    if fn in keep or fn == '.git':\n"
    "        continue\n"
    "    s = os.path.join(src, fn)\n"
    "    d = os.path.join(base, fn)\n"
    "    if os.path.isfile(s):\n"
    "        if os.path.exists(d):\n"
    "            shutil.copy2(d, os.path.join(bak, fn))\n"
    "        shutil.copy2(s, d)\n"
    "        replaced += 1\n"
    "print(replaced)\n"
)


def _log(events, msg, tag=""):
    if events:
        events("log", (msg, tag))


def _status(events, msg):
    if events:
        events("status", msg)


def cmp_ver(a, b):
    # 版本号 "x.y.z" 比较, 返回 -1/0/1; 非数字版本串整体按 (0,) 处理(不崩溃)。
    def t(v):
        try:
            return tuple(int(x) for x in str(v).split("."))
        except ValueError:
            return (0,)
    x, y = t(a), t(b)
    return (x > y) - (x < y)


def fetch(url, timeout=15):
    # 下载文本(utf-8), 失败抛异常, 由调用方转成 err 中文文案。
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def program_dir():
    # 程序所在目录: 打包(exe)后为 exe 目录, 源码模式为仓库根(dsh_core/ 的上级,
    # 与 app/services.py 的 base_dir、旧 pages_version._base_dir 同一定位)。
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_dir():
    # 打包资源目录: onefile 下资源在 _MEIPASS(临时解压), 源码模式为仓库根。
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def check_latest(events=None):
    # 检查远程版本: 拉远程 version.json -> {"latest","notes","err"}。
    # err 成功为空字符串, 失败为中文文案(网络/解析异常都不抛出到线程外)。
    _status(events, "正在连接更新源…")
    try:
        data = json.loads(fetch(VERSION_URL))
    except Exception as e:
        return {"latest": "", "notes": "", "err": "连接更新源失败: %s" % e}
    return {"latest": str(data.get("version") or ""),
            "notes": str(data.get("notes") or ""),
            "err": ""}


def read_local_notes():
    # 读本地更新日志 RELEASE_NOTES.md(资源目录, 小文件同步读, 离线可用);
    # 缺失/不可读返回占位文案, 不抛异常(展示用途, 失败可降级)。
    p = os.path.join(resource_dir(), "RELEASE_NOTES.md")
    try:
        with io.open(p, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return "(未找到 RELEASE_NOTES.md)"


def download_and_apply(events=None, base_dir=None):
    # 一键更新: 下载 main 分支 zip -> 解压 -> 子进程备份+替换程序文件(keep 清单与
    # .git 跳过)。返回 {"msg","replaced","backup","err"}; err 成功为空字符串,
    # 失败为中文文案; 失败时程序文件未改动(替换在子进程整体执行, 或成功或不动)。
    base = base_dir or program_dir()
    tmp = os.path.join(os.environ.get("TEMP", "."), "dsh-aio-update")
    try:
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp, exist_ok=True)
        zip_path = os.path.join(tmp, "update.zip")
        _status(events, "下载更新包中(约几百 KB~几 MB)…")
        urllib.request.urlretrieve(GITHUB_ZIP, zip_path)
        _status(events, "解压中…")
        extract = os.path.join(tmp, "x")
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(extract)
        # zip 顶层目录: dsh-console-aio-main/
        roots = [d for d in os.listdir(extract)
                 if os.path.isdir(os.path.join(extract, d))]
        src = os.path.join(extract, roots[0]) if roots else extract
        bak = os.path.join(tmp, "backup")
        _status(events, "替换程序文件(自动备份)…")
        _log(events, "[版本管理] 替换源: %s -> %s" % (src, base))
        r = subprocess.run(
            [sys.executable, "-c", _REPLACE_CODE, src, base, bak,
             json.dumps(sorted(KEEP_FILES))],
            capture_output=True, text=True, errors="replace", timeout=300,
            creationflags=subprocess.CREATE_NO_WINDOW)
        if r.returncode != 0:
            detail = (r.stderr or "").strip() or ("退出码 %d" % r.returncode)
            return {"msg": "", "replaced": "", "backup": bak,
                    "err": "替换程序文件失败: %s" % detail}
        replaced = (r.stdout or "").strip()
        return {"msg": "更新完成(%s 个文件), 备份在: %s" % (replaced, bak),
                "replaced": replaced, "backup": bak, "err": ""}
    except Exception as e:
        return {"msg": "", "replaced": "", "backup": "",
                "err": "更新失败: %s" % e}


def spawn_restart(base_dir=None):
    # 重启程序(同步调用, Popen 即返回): frozen 直接重启 exe; 源码模式启动仓库根
    # dsh-console-aio.py(真实入口; 旧页面写死 app_pyside.py, FileNotFoundError 被
    # 吞掉导致更新后不重启 —— 本函数即该 bug 的修复)。重启是 UI 生命周期动作, 由页面
    # 调用: 返回 {"err": ""} 视为成功, 页面才关窗/退出。
    base = base_dir or program_dir()
    try:
        if getattr(sys, "frozen", False):
            subprocess.Popen([sys.executable], cwd=base, text=True,
                             errors="replace",
                             creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            main = os.path.join(base, "dsh-console-aio.py")
            if not os.path.isfile(main):
                return {"err": "找不到主程序入口: %s" % main}
            subprocess.Popen([sys.executable, main], cwd=base, text=True,
                             errors="replace",
                             creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception as e:
        return {"err": "启动新进程失败: %s" % e}
    return {"err": ""}


__all__ = ["GITHUB_RAW", "GITHUB_ZIP", "VERSION_URL", "RELEASE_URL", "KEEP_FILES",
           "cmp_ver", "fetch", "program_dir", "resource_dir", "check_latest",
           "read_local_notes", "download_and_apply", "spawn_restart"]
