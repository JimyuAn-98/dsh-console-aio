# -*- coding: utf-8 -*-
# core/env.py - 开发环境探测 / SSH 免密测试 / dsh 一键安装流(纯 Python, 零 Qt,
# 严禁 import PySide)。由旧 ui/dialogs.py 的内联子进程业务下沉而来(ConfigDialog 的
# SSH 测试 / InstallDialog 的安装流 / EnvDialog 的版本探测与工具命令)—— 弹窗收敛后
# 环境检查与安装向导改为 DSH 管理页(ui/pages_dsh.py)页面内分步, 业务仍在本模块。
#
# 通讯约定: install_dsh 遵循 events(kind, payload) 纯数据回调:
#   events("log", text)            逐行输出/说明
#   events("step", (n, text))      安装步骤进度(1..4)
# 其余函数为同步调用(对话框在其自有线程中调用, 线程归 UI 层所有 —— 阶段3 决策:
# 业务全部下沉本模块, 对话框线程保留, 详见 docs/ARCHITECTURE.md)。
# 子进程一律 CREATE_NO_WINDOW + text=True errors="replace" + 超时(AGENTS.md 约定)。

import os
import shutil
import subprocess

from core import config as dsh_config
from core.dshctl import DshCtl

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW


def _rmtree_force(path, log=None):
    # Windows 递归删除加固 + 全程日志。顺序:
    #   1) 原生 cmd rmdir /s /q 快删(大树/junction 最快; 只读文件会被跳过);
    #   2) Python 精修残留: 迭代式后序, 就地清只读, junction/符号链接只删链接(防环),
    #      每 2000 项打一条进度日志(避免"看着像卡死");
    #   3) 存在性检查, 仍未删净则列出残留路径并抛 OSError(带路径)。
    # log: 可选单参回调(逐行中文输出, 交调用方透传到控制台/操作日志)。
    import stat as _stat
    import time as _t

    def _log(msg):
        if log:
            log(msg)

    if not os.path.exists(path):
        _log("[删除] 路径不存在, 跳过: " + path)
        return
    _log("[删除] 开始: " + path)
    t0 = _t.time()

    failed = []

    def _clear(node):
        try:
            os.chmod(node, _stat.S_IWRITE)
        except OSError:
            pass

    def _is_reparse(st):
        # junction/符号链接等重解析点: 只能删链接本身, 绝不能递归进目标(否则可能成环/误删)
        attr = getattr(st, "st_file_attributes", 0)
        return bool(attr & getattr(_stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))

    def _rm_leaf(p):
        # 叶子(文件 / junction / 符号链接): 先直删, 失败清只读再试; 文件用 remove, 目录链接用 rmdir。
        for fn in (os.remove, os.rmdir):
            try:
                fn(p)
                return True
            except OSError:
                continue
        _clear(p)
        for fn in (os.remove, os.rmdir):
            try:
                fn(p)
                return True
            except OSError:
                continue
        return False

    def _purge(root):
        # 显式后序遍历(不递归进 junction): 每个条目只访问一次; 每 2000 项打进度日志。
        count = 0
        stack = [(root, False)]
        while stack:
            cur, expanded = stack.pop()
            if expanded:
                _clear(cur)
                try:
                    os.rmdir(cur)
                except OSError as e:
                    if os.path.exists(cur) and len(failed) < 20:
                        failed.append((cur, str(e)))
                continue
            try:
                entries = list(os.scandir(cur))
            except OSError as e:
                _log("[删除] 无法列出: %s (%s)" % (cur, e))
                continue
            stack.append((cur, True))
            for ent in entries:
                p = ent.path
                try:
                    st = ent.stat(follow_symlinks=False)
                    is_dir = ent.is_dir(follow_symlinks=False)
                    is_link = ent.is_symlink() or _is_reparse(st)
                except OSError:
                    is_dir, is_link = False, False
                if is_dir and not is_link:
                    stack.append((p, False))
                    continue
                if not _rm_leaf(p) and len(failed) < 20:
                    failed.append((p, "删除失败(占用/权限?)"))
                count += 1
                if count % 2000 == 0:
                    _log("[删除] 已清理 %d 项..." % count)
        return count

    sep = os.sep
    target = path
    if os.name == "nt":
        ap = os.path.abspath(path)
        if not ap.startswith(sep + sep + "?" + sep):
            if ap.startswith(sep + sep):
                ap = sep + sep + "?" + sep + "UNC" + sep + ap[2:]
            else:
                ap = sep + sep + "?" + sep + ap
        target = ap

    # 1) 原生快删: 一次性删掉绝大多数条目(junction 只删链接), 只读文件会被跳过留给精修。
    if os.name == "nt":
        _log("[删除] 快速清理(cmd rmdir /s /q)...")
        try:
            # Popen + 轮询而非 run(): 大树原生删除可能数十秒, 每 15s 打一条心跳,
            # 保证界面/日志全程有反馈(不会"看着像卡死")。
            proc = subprocess.Popen(["cmd", "/c", 'rmdir /s /q "%s"' % path],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    creationflags=CREATE_NO_WINDOW)
            t_fast = _t.time()
            beat = 0
            while proc.poll() is None:
                elapsed = _t.time() - t_fast
                if elapsed > 900:
                    proc.kill()
                    _log("[删除] cmd rmdir 超时(900s), 转 Python 精修")
                    break
                if int(elapsed) // 15 > beat:
                    beat = int(elapsed) // 15
                    _log("[删除] 快速清理中... 已 %.0fs" % elapsed)
                _t.sleep(0.5)
        except Exception as e:
            _log("[删除] cmd rmdir 异常: %s" % e)
        _log("[删除] 快速清理结束(累计 %.1fs)" % (_t.time() - t0))

    # 2) Python 精修残留(只读 / junction / 长路径)
    if os.path.exists(path):
        _log("[删除] 精修残留(清只读 / 跳过 junction)...")
        try:
            n = _purge(target)
            _log("[删除] 精修完成, 处理 %d 项(累计 %.1fs)" % (n, _t.time() - t0))
        except Exception as e:
            _log("[删除] 精修异常: %s" % e)

    # 3) 收尾判定: 列出残留清单, 让失败可见
    if os.path.exists(path):
        leftovers = []
        try:
            for base, _dirs, files in os.walk(target, onerror=lambda _e: None):
                for f in files:
                    leftovers.append(os.path.join(base, f))
                if len(leftovers) >= 10:
                    break
        except Exception:
            pass
        for p in leftovers[:10]:
            _log("[删除] 残留: " + p)
        for p, why in failed[:10]:
            _log("[删除] 无法删除: %s (%s)" % (p, why))
        _log("[删除] 失败: 仍有残留 " + path)
        raise OSError("部分文件无法删除(可能被占用或权限不足): " + path)
    _log("[删除] 完成: %s (耗时 %.1fs)" % (path, _t.time() - t0))


def get_version(cmd, timeout=8):
    # 版本命令输出首行; 命令缺失/超时/失败返回 None(展示为"未安装")。
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                           timeout=timeout, creationflags=CREATE_NO_WINDOW)
        if r.stdout or r.stderr:
            return (r.stdout or r.stderr or "").strip().splitlines()[0]
    except Exception:
        # 命令不存在/超时等一律降级为 None, 由 UI 显示占位
        pass
    return None


def tool_versions(tools):
    # tools: [(key, name, cmd), ...] -> {key: 版本行或 None}; 逐个执行, 缺失不中断。
    return {key: get_version(cmd) for key, _name, cmd in tools}


def missing_tools(tools=("git", "node", "npm", "pnpm")):
    # 返回 PATH 中缺失的工具名列表(安装流预检用)。
    return [t for t in tools if not shutil.which(t)]


def pnpm_env():
    # pnpm 要求全局 bin 目录在 PATH 中, 自动注入避免报错; 委托 core.pkgmgr(单一实现,
    # 统一处理 PNPM_HOME / 前置 PATH / Windows PATH 大小写), 这里只保留稳定入口。
    from core import pkgmgr
    return pkgmgr.pnpm_env()


def run_capture(cmd, timeout=600):
    # 捕获式执行(无主界面时的兜底路径): 返回 (ok, 尾部输出)。
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                           timeout=timeout, creationflags=CREATE_NO_WINDOW)
        tail = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()[-600:]
        return r.returncode == 0, tail
    except Exception as e:
        return False, str(e)


def test_ssh(host, user, port="22"):
    # SSH 免密连通测试(ssh BatchMode + echo ok)。契约: {"ok": bool, "detail": str, "err": ""};
    # detail 为失败原因片段(给 UI 拼 ❌ 文案), 成功为空; err 仅在探测本身异常时非空。
    host = str(host or "").strip()
    user = str(user or "").strip()
    port = str(port or "").strip() or "22"
    if not host or not user:
        return {"ok": False, "detail": "请先填服务器 IP 和用户名", "err": ""}
    try:
        ssh = shutil.which("ssh")
        if not ssh:
            raise FileNotFoundError("ssh 不在 PATH 中")
        r = subprocess.run(
            [ssh, "-o", "BatchMode=yes", "-o", "ConnectTimeout=6",
             "-o", "StrictHostKeyChecking=accept-new",
             "-p", port, user + "@" + host, "echo ok"],
            capture_output=True, text=True, errors="replace", timeout=18,
            creationflags=CREATE_NO_WINDOW)
        if r.returncode == 0:
            return {"ok": True, "detail": "", "err": ""}
        detail = (r.stderr or r.stdout or "").strip().replace("\n", " ")[:180]
        return {"ok": False, "detail": detail, "err": ""}
    except Exception as e:
        return {"ok": False, "detail": str(e)[:140], "err": ""}


def _bridge(events):
    # dshctl.stream_cmd 的 events("log", (text, tag)) -> 本模块 events("log", text)
    def cb(kind, payload):
        if kind == "log":
            events("log", payload[0])
    return cb


def _is_dsh_checkout(path):
    # 目录是否为 dsh 的 git 工作区: 供"目标目录已存在"时决定能否跳过 clone(重装/修复)。
    # 复用 core.pkgmgr.source_info 的 dsh 仓库识别, 不在此另写一份判断。
    from core import pkgmgr
    if not os.path.isdir(os.path.join(path, ".git")):
        return False
    return bool(pkgmgr.source_info(os.path.abspath(path))["ok"])


def install_dsh(events=None, url=None, target=None, version=""):
    # 一键安装 dsh: 环境预检 -> git clone -> (指定版本时 checkout) -> pnpm install -> pnpm build
    # -> 写 config.dash_repo(指定版本时同时写 dsh_version_pin)。
    # 契约: {"msg", "err", "target", "version"}; 任一步失败立即返回(已执行的步骤不回滚)。
    # version 留空=跟随默认分支。
    url = (url or "").strip()
    target = (target or "").strip() or os.path.join(os.path.expanduser("~"), "dsh")
    version = (version or "").strip()

    def step(n, text):
        if events:
            events("step", (n, text))

    def line(text):
        if events:
            events("log", text)

    if not url:
        return {"msg": "", "err": "请填写 dsh 的 git 仓库地址", "target": target}
    # 0) 环境预检
    need = missing_tools()
    if need:
        line("[安装] 缺少依赖: " + ", ".join(need))
        line("  请先安装 Node.js(含 npm) 和 git; 然后 npm install -g pnpm")
        return {"msg": "", "err": "缺少依赖: " + ", ".join(need), "target": target}
    # 流式执行经 dshctl.stream_cmd(超时/kill/找不到命令统一处理, 超时取用户 config)
    ctl = DshCtl(dsh_config.load_derived())
    bridge = _bridge(events)
    # 1) clone(完整克隆, 便于后续 update 的 git pull)
    #    非空目录: 仅当确实是 dsh 的 git 工作区才跳过 clone; 否则明确报错, 避免后续
    #    git fetch/checkout 以 "not a git repository" 失败(BUG-014)。
    if os.path.isdir(target) and os.listdir(target):
        if _is_dsh_checkout(target):
            line("[安装] 目录已存在且是 dsh 仓库, 跳过 clone: " + target)
        else:
            line("[安装] 目标目录已存在且不是 dsh 仓库: " + target)
            return {"msg": "", "err": "目标目录已存在且不是 dsh 仓库，请换一个空目录，或先清空该目录再安装",
                    "target": target}
    else:
        step(1, "步骤 1/3: git clone ...")
        if not ctl.stream_cmd(["git", "clone", url, target], events=bridge):
            return {"msg": "", "err": "git clone 失败(详见安装日志)", "target": target}
    # 1.5) 指定版本: 拉 tags 并切换到目标 tag(留空则跟随默认分支)
    if version:
        line("[安装] 切换到指定版本: " + version)
        if not ctl.stream_cmd(["git", "fetch", "--tags", "--prune"], cwd=target, events=bridge):
            return {"msg": "", "err": "获取 tags 失败(详见安装日志)", "target": target}
        if not ctl.stream_cmd(["git", "checkout", version], cwd=target, events=bridge):
            return {"msg": "", "err": "切换到版本 %s 失败(详见安装日志)" % version,
                    "target": target}
    # 2) install
    step(2, "步骤 2/3: pnpm install")
    if not ctl.stream_cmd(["pnpm.cmd", "install"], cwd=target, events=bridge):
        return {"msg": "", "err": "pnpm install 失败(详见安装日志)", "target": target}
    # 3) build
    step(3, "步骤 3/3: pnpm run build")
    if not ctl.stream_cmd(["pnpm.cmd", "run", "build"], cwd=target, events=bridge):
        return {"msg": "", "err": "pnpm run build 失败(详见安装日志)", "target": target}
    # 4) 写 config.dash_repo(core.config: DSH_AIO_CONFIG 感知 + 写前 .bak)
    step(4, "写 config.json(dash_repo)")
    try:
        cfg = dsh_config.load_config()
        cfg["dash_repo"] = target
        if version:
            cfg["dsh_version_pin"] = version
        else:
            cfg.pop("dsh_version_pin", None)
        if dsh_config.save_config(cfg):
            line("[安装] 已把 dash_repo 写入 config.json, 重启后生效。")
        else:
            line("[安装] 无法写 config.json(权限?), 请在配置向导里手动设置 dash_repo。")
    except Exception as e:
        line("[安装] 写 config 失败: " + str(e))
    msg = "dsh 安装完成 目标目录: " + target
    if version:
        msg += "(版本 " + version + ")"
    return {"msg": msg, "err": "", "target": target, "version": version}


def install_dsh_pkg(events=None, version=""):
    # 全局包安装: npm install -g @deepseek-ai/dsh[@版本](npm 扁平布局, 与官方 npx 同源); 成功后写
    # config.dsh_install_mode=package, 保证启动/更新/卸载一致。契约同 install_dsh + mode。
    from core import pkgmgr
    version = (version or "").strip()

    def step(n, text):
        if events:
            events("step", (n, text))

    def line(text):
        if events:
            events("log", text)

    need = missing_tools(("node", "npm"))   # 包模式只需要 node + npm(git/pnpm 非必需)
    if need:
        line("[安装] 缺少依赖: " + ", ".join(need))
        return {"msg": "", "err": "缺少依赖: " + ", ".join(need), "target": "", "version": version}

    ctl = DshCtl(dsh_config.load_derived())
    bridge = _bridge(events)
    step(1, "步骤 1/2: " + " ".join(pkgmgr.install_cmd(version)))
    line("[安装] 全局包安装: " + " ".join(pkgmgr.install_cmd(version)))
    if not ctl.stream_cmd(pkgmgr.install_cmd(version), cwd=pkgmgr.npm_cwd(),
                          env=pkgmgr.npm_env(), events=bridge):
        return {"msg": "", "err": "npm install -g 失败(详见安装日志)", "target": "", "version": version}

    step(2, "步骤 2/2: 校验安装结果")
    info = pkgmgr.package_info(force=True)
    if not info.get("ok"):
        return {"msg": "", "err": info.get("error") or "安装完成但未检测到全局包",
                "target": "", "version": version}
    line("[安装] 已安装 %s %s" % (pkgmgr.DSH_PKG, info["version"]))
    try:
        cfg = dsh_config.load_config()
        cfg["dsh_install_mode"] = "package"
        if dsh_config.save_config(cfg):
            line("[安装] 已把 dsh_install_mode=package 写入 config.json。")
    except Exception as e:
        line("[安装] 写 config 失败: " + str(e))
    return {"msg": "dsh 全局包安装完成: %s %s" % (pkgmgr.DSH_PKG, info["version"]),
            "err": "", "target": "", "version": info["version"], "mode": "package"}


def uninstall_dsh(events=None, keep_data=True):
    # 卸载本机 dsh(与 install_dsh 对应的纯业务, 零 Qt): 停 web -> 删源码目录(dash_repo)
    # -> 清 config.dash_repo; keep_data=False 时再删 ~/.dsh 数据目录。
    # 契约: {"msg", "err", "removed_repo": bool, "removed_data": bool, "data_dir": 数据目录}
    # 危险操作: 本函数只执行, 由 UI 层先弹强确认框(逐条列出将删的具体路径)。
    # 删除守卫: 仅当路径非空、绝对、且确实存在时才删, 绝不手拼/通配, 防误删用户关键目录。
    def step(n, text):
        if events:
            events("step", (n, text))

    def line(text):
        if events:
            events("log", text)

    cfg = dsh_config.load_config()
    from core import pkgmgr
    if pkgmgr.detect_mode(cfg).get("mode") == "package":
        return _uninstall_dsh_pkg(events, keep_data)
    repo = (cfg.get("dash_repo") or "").strip()
    ctl = DshCtl(dsh_config.load_derived())

    removed_repo = False
    removed_data = False
    data_dir = ""

    # 0) 停 web(先停再用, 避免删到被占用/运行中的目录)
    step(1, "步骤 1/3: 停止本机 dsh web")
    ctl.stop_dsh(events=_bridge(events))

    # 1) 删源码目录
    if repo and os.path.isabs(repo) and os.path.isdir(repo):
        step(2, "步骤 2/3: 删除源码目录 " + repo)
        line("[卸载] 删除源码目录: " + repo)
        try:
            _rmtree_force(repo, log=line)
            removed_repo = True
        except Exception as e:
            line("[卸载] 删除源码目录失败: " + str(e))
            return {"msg": "", "err": "删除源码目录失败: %s" % e,
                    "removed_repo": False, "removed_data": False, "data_dir": ""}
    else:
        line("[卸载] 未检测到 dsh 源码目录(跳过): " + (repo or "config 未设置 dash_repo"))

    # 2) 清 config.dash_repo
    step(3, "步骤 3/3: 清空 config.json 的 dash_repo")
    try:
        cfg2 = dsh_config.load_config()
        if cfg2.get("dash_repo"):
            cfg2["dash_repo"] = ""
            if dsh_config.save_config(cfg2):
                line("[卸载] 已清空 config.json 的 dash_repo(写前已 .bak)。")
    except Exception as e:
        line("[卸载] 清 config.dash_repo 失败(请手动在配置向导里清): " + str(e))

    # 3) 数据目录(仅"彻底卸载"删)
    if not keep_data:
        from core import data as dsh_data
        data_dir = dsh_data.dsh_home()
        if os.path.isabs(data_dir) and os.path.isdir(data_dir) \
                and os.path.abspath(data_dir) != os.path.abspath(os.path.expanduser("~")):
            step(4, "删除数据目录 ~/.dsh")
            line("[卸载] 删除数据目录: " + data_dir)
            try:
                _rmtree_force(data_dir, log=line)
                removed_data = True
            except Exception as e:
                line("[卸载] 删除数据目录失败: " + str(e))
                return {"msg": "", "err": "删除数据目录失败: %s" % e, "removed_repo": removed_repo,
                        "removed_data": False, "data_dir": data_dir}
        else:
            line("[卸载] 未检测到数据目录(跳过): " + data_dir)

    parts = []
    if removed_repo:
        parts.append("源码目录已删除")
    if not keep_data and removed_data:
        parts.append("数据目录(~/.dsh)已删除")
    if not parts:
        parts = ["未检测到已安装的 dsh(无可删)"]
    return {"msg": "dsh 卸载完成: " + "; ".join(parts), "err": "", "removed_repo": removed_repo,
            "removed_data": removed_data, "data_dir": data_dir}


def _uninstall_dsh_pkg(events=None, keep_data=True):
    # 全局包卸载: 停 web -> npm uninstall -g @deepseek-ai/dsh -> 清模式配置
    # -> (keep_data=False) 删 ~/.dsh 数据目录。契约与 uninstall_dsh 一致。
    from core import pkgmgr

    def step(n, text):
        if events:
            events("step", (n, text))

    def line(text):
        if events:
            events("log", text)

    ctl = DshCtl(dsh_config.load_derived())
    bridge = _bridge(events)
    removed_data = False
    data_dir = ""

    step(1, "步骤 1/3: 停止本机 dsh web")
    ctl.stop_dsh(events=bridge)

    step(2, "步骤 2/3: " + " ".join(pkgmgr.remove_cmd()))
    line("[卸载] 全局包卸载: " + " ".join(pkgmgr.remove_cmd()))
    if not ctl.stream_cmd(pkgmgr.remove_cmd(), cwd=pkgmgr.npm_cwd(),
                          env=pkgmgr.npm_env(), events=bridge):
        return {"msg": "", "err": "npm uninstall -g 失败(详见卸载日志)", "removed_repo": False,
                "removed_data": False, "data_dir": ""}
    pkgmgr.package_info(force=True)
    try:
        cfg2 = dsh_config.load_config()
        if cfg2.get("dsh_install_mode"):
            cfg2["dsh_install_mode"] = ""
            dsh_config.save_config(cfg2)
    except Exception as e:
        line("[卸载] 清 config.dsh_install_mode 失败: " + str(e))

    if not keep_data:
        from core import data as dsh_data
        data_dir = dsh_data.dsh_home()
        if os.path.isabs(data_dir) and os.path.isdir(data_dir) \
                and os.path.abspath(data_dir) != os.path.abspath(os.path.expanduser("~")):
            step(3, "删除数据目录 ~/.dsh")
            line("[卸载] 删除数据目录: " + data_dir)
            try:
                _rmtree_force(data_dir, log=line)
                removed_data = True
            except Exception as e:
                line("[卸载] 删除数据目录失败: " + str(e))
                return {"msg": "", "err": "删除数据目录失败: %s" % e, "removed_repo": True,
                        "removed_data": False, "data_dir": data_dir}
        else:
            line("[卸载] 未检测到数据目录(跳过): " + data_dir)

    parts = ["全局包已卸载"]
    if not keep_data and removed_data:
        parts.append("数据目录(~/.dsh)已删除")
    return {"msg": "dsh 卸载完成: " + "; ".join(parts), "err": "", "removed_repo": True,
            "removed_data": removed_data, "data_dir": data_dir}


__all__ = ["get_version", "tool_versions", "missing_tools", "pnpm_env",
           "run_capture", "test_ssh", "install_dsh", "install_dsh_pkg", "uninstall_dsh"]
