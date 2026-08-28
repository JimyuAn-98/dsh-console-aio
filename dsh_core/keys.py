# -*- coding: utf-8 -*-
# dsh_core/keys.py - 本机 ~/.ssh 密钥清单/指纹/公钥读取/生成(纯 Python, 零 Qt,
# 严禁 import PySide)。由 pyside/pages_keys.py 的内联业务下沉而来。
#
# 通讯约定: 异步操作(list_keys/generate_key)遵循 app/services.py 的 _run_result_op 契约
# func(events, ...) -> dict payload; payload 至少含 "err"(成功为空字符串, 失败为中文文案)。
# 进度/结果日志经 events(kind, payload) 纯数据回调报告(仅 "log" 一种), 由 services 转发到
# Qt Signal; 本模块绝不接触 UI。同步轻量操作(ssh_dir/read_pubkey/fingerprint)由页面直调。
#
# 安全红线(必须永久保持, 改动前先读懂):
#   1. 私钥文件内容绝不读取、绝不写日志、绝不进任何返回值 —— 私钥只允许
#      "存在性 + ssh-keygen -lf 公钥指纹" 两种接触方式;
#   2. 公钥(.pub)是公开信息, 可读取并展示/复制;
#   3. ssh-keygen 调用必须带超时, 失败只报中文文案, 不把进程原始输出当成功。

import os
import io
import subprocess


# 私钥文件名模式(只按文件名判断存在性, 不读内容)
_PRIV_PREFIXES = ("id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",
                  "id_ecdsa_sk", "id_ed25519_sk")


def _log(events, msg, tag=""):
    # events 可为 None(直接调用方); service 注入的回调自身按 kind 分派到 Signal。
    if events:
        events("log", (msg, tag))


def ssh_dir():
    return os.path.join(os.path.expanduser("~"), ".ssh")


def fingerprint(path):
    # 公钥指纹: ssh-keygen -lf 输出的第 2 列(如 SHA256:xxxx), 不泄露私钥。
    # 失败返回 None(页面把 falsy 显示为 "—" 占位): ssh-keygen 缺失/超时/坏文件
    # 都只导致指纹列显示占位符, 不影响列表其余字段。
    try:
        r = subprocess.run(["ssh-keygen", "-lf", path], capture_output=True,
                           text=True, errors="replace", timeout=10,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        if r.returncode == 0:
            parts = r.stdout.split()
            if len(parts) >= 2:
                return parts[1]
    except Exception:
        # 吞掉一切异常: 平台差异/ssh-keygen 缺失/超时都只降级为无指纹, 不应崩页面
        pass
    return None


def list_keys(events=None):
    # 服务契约: {"keys": [{name, is_pub, fp, mtime}], "err": ""}。
    # 私钥不读内容; 每个入选文件跑一次 ssh-keygen -lf 取指纹(见安全红线)。
    out = []
    d = ssh_dir()
    if not os.path.isdir(d):
        return {"keys": out, "err": ""}
    try:
        names = sorted(os.listdir(d))
    except Exception as e:
        err = "读取 ~/.ssh 目录失败: %s" % e
        _log(events, "[SSH密钥] " + err, "err")
        return {"keys": out, "err": err}
    for fn in names:
        p = os.path.join(d, fn)
        if not os.path.isfile(p):
            continue
        is_pub = fn.endswith(".pub")
        is_priv = (not is_pub) and fn.startswith(_PRIV_PREFIXES)
        if not (is_pub or is_priv):
            continue  # known_hosts/config/authorized_keys 等无关文件不入选
        out.append({
            "name": fn[:-4] if is_pub else fn,
            "is_pub": is_pub,
            "fp": fingerprint(p),
            "mtime": os.path.getmtime(p),
        })
    return {"keys": out, "err": ""}


def read_pubkey(name):
    # 读公钥文本(.pub, 公开信息, 可展示/复制); 私钥绝不读 —— 路径恒为 <name>.pub。
    # 无 .pub 文件返回 None; 读失败抛 OSError 由调用方决定文案。
    p = os.path.join(ssh_dir(), name + ".pub")
    if not os.path.isfile(p):
        return None
    with io.open(p, encoding="utf-8", errors="replace") as fh:
        return fh.read().strip()


def generate_key(events, name):
    # 生成 ed25519 密钥(无口令): ssh-keygen -t ed25519 -f <路径> -N "" -C dsh-console-aio。
    # 契约: {"msg": 成功文案, "err": 中文失败文案}; 两者恒成对出现(对称取值)。
    name = (name or "").strip()
    if not name:
        return {"msg": "", "err": "密钥名称不能为空"}
    if os.path.basename(name) != name or name in (".", ".."):
        # 名称会拼进 ~/.ssh/ 路径, 必须是纯文件名(防路径分隔符/相对路径穿越)
        return {"msg": "", "err": "密钥名称不合法: 只能是文件名, 不能含路径分隔符"}
    d = ssh_dir()
    path = os.path.join(d, name)
    if os.path.exists(path):
        err = "已存在同名密钥文件: %s(请换一个名称, 或手动处理后重试)" % name
        _log(events, "[SSH密钥] 生成失败: " + err, "err")
        return {"msg": "", "err": err}
    try:
        os.makedirs(d, exist_ok=True)
    except Exception as e:
        err = "创建 %s 目录失败: %s" % (d, e)
        _log(events, "[SSH密钥] " + err, "err")
        return {"msg": "", "err": err}
    cmd = ["ssh-keygen", "-t", "ed25519", "-f", path, "-N", "", "-C", "dsh-console-aio"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                           timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    except FileNotFoundError:
        # ssh-keygen 不在 PATH(未装 OpenSSH); 与其他子进程异常分开提示
        err = "生成失败: 找不到 ssh-keygen 命令(请确认系统已安装 OpenSSH)"
        _log(events, "[SSH密钥] " + err, "err")
        return {"msg": "", "err": err}
    except subprocess.TimeoutExpired:
        err = "生成失败: ssh-keygen 执行超时(30s), 已终止"
        _log(events, "[SSH密钥] " + err, "err")
        return {"msg": "", "err": err}
    except Exception as e:
        err = "生成异常: %s" % e
        _log(events, "[SSH密钥] " + err, "err")
        return {"msg": "", "err": err}
    if r.returncode == 0:
        msg = "已生成: %s (ed25519)" % name
        _log(events, "[SSH密钥] " + msg, "ok")
        return {"msg": msg, "err": ""}
    detail = (r.stderr or "").strip() or ("退出码 %d" % r.returncode)
    err = "生成失败: " + detail
    _log(events, "[SSH密钥] " + err, "err")
    return {"msg": "", "err": err}


__all__ = ["ssh_dir", "fingerprint", "list_keys", "read_pubkey", "generate_key"]
