# -*- coding: utf-8 -*-
# core/version.py - 控制台自身版本检查与自更新(纯 Python, 严禁 import PySide)。
#
# 由 ui/pages_version.py 抽出的业务: 版本比较/拉远程 version.json/读本地更新日志/
# 下载 zip 并备份替换程序文件/重启进程。通讯约定同 core 其他模块: 本模块不碰 UI,
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
# Release 下载源(打包版一键更新: 下载安装包 -> 退出 -> 运行安装器)
GITHUB_REPO = "https://github.com/JimyuAn-98/dsh-console-aio"
RELEASES_BASE = GITHUB_REPO + "/releases/download/"
INSTALLER_NAME = "dsh-console-aio-setup-%s.exe"   # 与 installer.iss OutputBaseFilename 一致
CHECKSUMS_NAME = "SHA256SUMS.txt"

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
    # 程序所在目录: 打包(exe)后为 exe 目录, 源码模式为仓库根(core/ 的上级,
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


def installer_url(version):
    # 安装包下载地址: Release 资产命名 = dsh-console-aio-setup-<ver>.exe, tag = v<ver>
    v = str(version or "").strip().lstrip("v")
    return "%sv%s/%s" % (RELEASES_BASE, v, INSTALLER_NAME % v)


def _download_file(url, dest, events=None, timeout=60):
    # 流式下载并周期上报进度(每 5% 或每 MB); 返回写入字节数。
    # 失败抛异常, 由 download_installer 统一转中文 err。
    req = urllib.request.Request(url, headers={"User-Agent": "dsh-console-aio"})
    got, last_pct, last_mb = 0, -10, -1
    with urllib.request.urlopen(req, timeout=timeout) as r:
        total = int(r.headers.get("Content-Length") or 0)
        with open(dest, "wb") as f:
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if total:
                    pct = min(100, int(got * 100 / total))
                    if pct - last_pct >= 5 or pct >= 100:
                        last_pct = pct
                        _status(events, "正在下载安装包… %d%% (%.1f/%.1f MB)"
                                % (pct, got / 1048576.0, total / 1048576.0))
                else:
                    mb = got // 1048576
                    if mb != last_mb:
                        last_mb = mb
                        _status(events, "正在下载安装包… %.1f MB" % (got / 1048576.0))
    return got


def _verify_installer(path, version, events=None):
    # 尽力校验 SHA256: 拉同 Release 的 SHA256SUMS.txt 比对。清单缺失/未命中只告警不阻断,
    # 命中且不符才返回中文错误(避免把损坏/被替换的安装包交给用户执行)。
    import hashlib
    v = str(version or "").strip().lstrip("v")
    try:
        text = fetch("%sv%s/%s" % (RELEASES_BASE, v, CHECKSUMS_NAME), timeout=15)
    except Exception:
        _log(events, "[版本管理] 未取到 %s, 跳过校验" % CHECKSUMS_NAME, "warn")
        return ""
    name = os.path.basename(path)
    want = ""
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*").strip() == name:
            want = parts[0].strip()
            break
    if not want:
        _log(events, "[版本管理] 校验清单未包含 %s, 跳过校验" % name, "warn")
        return ""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except OSError as e:
        return "读取安装包计算校验值失败: %s" % e
    if h.hexdigest().lower() != want.lower():
        return "安装包 SHA256 校验不通过(文件可能损坏或被篡改)"
    _log(events, "[版本管理] SHA256 校验通过", "ok")
    return ""


def download_installer(events=None, version="", dest_dir=None):
    # 下载最新安装包到本地(不执行)。成功 {"path","err"}, err 成功为空字符串。
    # 签名遵守 _run_result_op 契约: events 必须为首个位置参数。
    v = str(version or "").strip().lstrip("v")
    if not v:
        return {"path": "", "err": "版本号为空, 无法下载安装包"}
    dest_dir = dest_dir or os.path.join(os.environ.get("TEMP", "."), "dsh-aio-update")
    try:
        os.makedirs(dest_dir, exist_ok=True)
    except OSError as e:
        return {"path": "", "err": "无法创建下载目录: %s" % e}
    dest = os.path.join(dest_dir, INSTALLER_NAME % v)
    url = installer_url(v)
    _status(events, "正在下载安装包 v%s…" % v)
    _log(events, "[版本管理] 下载: %s" % url)
    try:
        got = _download_file(url, dest, events)
    except Exception as e:
        return {"path": "", "err": "下载安装包失败: %s" % e}
    if got <= 0:
        return {"path": "", "err": "下载的安装包为空文件"}
    # 防呆: 校验 exe 魔数(MZ), 避免把 HTML 错误页当成安装程序启动
    try:
        with open(dest, "rb") as f:
            if f.read(2) != b"MZ":
                return {"path": "", "err": "下载文件不是有效的 Windows 安装程序"}
    except OSError as e:
        return {"path": "", "err": "校验下载文件失败: %s" % e}
    verr = _verify_installer(dest, v, events)
    if verr:
        return {"path": "", "err": verr}
    _status(events, "安装包已就绪: %s" % dest)
    return {"path": dest, "err": ""}


def launch_installer(path):
    # 启动已下载的安装程序(UI 生命周期动作, 同步返回)。os.startfile 分离启动, 安装器
    # 自行处理覆盖安装; 调用方随后退出本进程以避免占用被替换的文件。
    if not path or not os.path.isfile(path):
        return {"err": "安装包不存在: %s" % path}
    startfile = getattr(os, "startfile", None)
    if startfile is None:
        return {"err": "当前平台不支持自动运行安装包, 请手动运行: %s" % path}
    try:
        startfile(path)
    except Exception as e:
        return {"err": "启动安装程序失败: %s" % e}
    return {"err": ""}


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
           "GITHUB_REPO", "RELEASES_BASE", "INSTALLER_NAME", "CHECKSUMS_NAME",
           "cmp_ver", "fetch", "program_dir", "resource_dir", "check_latest",
           "read_local_notes", "download_and_apply", "spawn_restart",
           "installer_url", "download_installer", "launch_installer"]
