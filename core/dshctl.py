# -*- coding: utf-8 -*-
# core/dshctl.py - 本机 dsh 启停 / 更新 / 监控探测(纯 Python, 不 import PySide)。
#
# 由 dsh-console-aio.py 中散落在 Qt 类里的业务逻辑抽出: _run_dsh/_dsh_start/_dsh_stop/
# _probe/_ssh_proc_count/_probe_remote_tunnels(原 _stream_cmd 流程已并入 stream_cmd)。
#
# 通讯约定: 本类不碰 UI。进度/结果通过 events(kind, payload) 回调向外报告(纯数据):
#   events('log',    (text, tag))
#   events('status', text)
#   events('card',   (key, online_bool))
# 由 app/services.py 把 events 转发到 Qt Signal。绝无跨线程直接改 UI。

import json
import os
import re
import socket
import subprocess
import threading
import urllib.request

_RUNTIME_TOKENS = {}


def extract_auth_token(text):
    # 从 dsh 启动输出或日志中提取 32 字节鉴权 Token 与完整链接
    if not text:
        return None, None
    clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', str(text))
    m = re.search(r'https?://(?:127\.0\.0\.1|localhost):\d+/\?token=([a-zA-Z0-9_-]+)', clean)
    if m:
        return m.group(1), m.group(0)
    m2 = re.search(r'\?token=([a-zA-Z0-9_-]+)', clean)
    if m2:
        return m2.group(1), None
    return None, None


def get_runtime_token(node_name="local", refresh=False):
    # 获取节点的运行时鉴权 Token (local 节点支持从最新日志实时刷新)
    if node_name == "local":
        if refresh or "local" not in _RUNTIME_TOKENS or not _RUNTIME_TOKENS["local"]:
            tok = scan_log_for_token()
            if tok:
                _RUNTIME_TOKENS["local"] = tok
                return tok
    return _RUNTIME_TOKENS.get(node_name)


def clear_runtime_token(node_name="local"):
    _RUNTIME_TOKENS.pop(node_name, None)


def set_runtime_token(node_name, token):
    if token and isinstance(token, str):
        _RUNTIME_TOKENS[node_name] = token.strip()


def scan_log_for_token():
    # 从本地 dsh-web.out.log / dsh-web.err.log 倒序扫描提取最新 Token
    logdir = os.path.join(os.environ.get("TEMP", "."), "dsh-dash")
    for fname in ("dsh-web.out.log", "dsh-web.err.log"):
        log_file = os.path.join(logdir, fname)
        if not os.path.isfile(log_file):
            continue
        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()[-100:]
            for line in reversed(lines):
                token, _ = extract_auth_token(line)
                if token:
                    return token
        except Exception:
            pass
    return None


DSH_REPO = "deepseek-ai/deepseek-harness"   # 固定官方仓库(版本信息来源, 不随 remote 推导)
_DSH_RELEASES_TTL = 600                       # 秒; 匿名 GitHub API 限流 60/h, 进页复用缓存
_DSH_RELEASES_CACHE = {"at": 0.0, "data": []}
_EN_ANCHOR_RE = re.compile(r'<h[1-6][^>]*id="en[^"]*"', re.IGNORECASE)
_HEAD_TAG_RE = re.compile(r"<h([1-6])[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)
_ANY_TAG_RE = re.compile(r"<[^>]+>")


def fetch_dsh_releases(force=False, per_page=30):
    # 拉取 dsh 本体 GitHub Releases(新->旧): tag/版本号/发布日期/预发布标记/更新日志正文。
    # 会话内 TTL 缓存(force=True 绕过, 供「刷新」按钮用); 网络失败抛异常, 由 service
    # 转成中文 err 交页面展示。走 api.github.com 官方接口, 不爬 HTML。
    import time
    from core import pkgmgr as _pkgmgr   # tag -> npm 版本规范化(tag 可能是 dsh-v0.1.5-rc.2)
    now = time.time()
    cache = _DSH_RELEASES_CACHE
    if (not force and cache["data"]
            and now - cache["at"] < _DSH_RELEASES_TTL):
        return cache["data"]
    url = ("https://api.github.com/repos/%s/releases?per_page=%d"
           % (DSH_REPO, int(per_page)))
    req = urllib.request.Request(url, headers={"User-Agent": "dsh-console-aio"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.load(r)
    out = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        tag = str(item.get("tag_name") or "")
        if not tag:
            continue
        ver = _pkgmgr.npm_version(tag)
        out.append({
            "tag": tag,
            "version": ver,
            "name": str(item.get("name") or ver),
            "published_at": str(item.get("published_at") or ""),
            "prerelease": bool(item.get("prerelease")),
            "body": str(item.get("body") or ""),
            "html_url": str(item.get("html_url") or ""),
        })
    cache["at"] = now
    cache["data"] = out
    return out


def dsh_local_version(cfg=None, mode=None):
    # 本机 dsh 版本: package 模式取全局包版本, 否则取 dash_repo/package.json;
    # 未配置/未安装/损坏返回 None。mode 由调用方传入(避免此处再跑一次模式探测)。
    if cfg is None:
        from core import config as _cfg
        cfg = _cfg.load_config()
    if mode is None:
        mode = str((cfg or {}).get("dsh_install_mode") or "").strip().lower() or None
    if mode == "package":
        from core import pkgmgr
        return pkgmgr.package_info().get("version") or None
    repo = (cfg or {}).get("dash_repo") or ""
    try:
        with open(os.path.join(repo, "package.json"), encoding="utf-8") as f:
            return (json.load(f) or {}).get("version")
    except Exception:
        return None


def cn_section(body):
    # 取 Release 正文的中文段: 截到首个英文锚点(<h3 id="en-...">)之前; 找不到英文锚点则
    # 返回全文(兜底)。再剥掉顶部 "[中文](#..) | [English](#..)" 语言导航行。
    if not body:
        return ""
    text = str(body)
    m = _EN_ANCHOR_RE.search(text)
    if m:
        text = text[:m.start()]
    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and "[中文]" in lines[0] and "[English]" in lines[0]:
        lines.pop(0)
    return "\n".join(lines).strip()


def html_headings_to_md(text):
    # Release 正文用 HTML 标题(<h3 id="..">新增功能</h3>); QTextDocument.setMarkdown 不认
    # 块级 HTML。转成 Markdown 标题, 其余标签剥掉, 保证正文可读。
    if not text:
        return ""
    t = _HEAD_TAG_RE.sub(
        lambda m: ("#" * int(m.group(1))) + " " + m.group(2).strip(), str(text))
    return _ANY_TAG_RE.sub("", t)



def _git_run(cmd, cwd, timeout=120):
    # 捕获式 git 调用(与 stream_cmd 的流式不同): 返回 (rc, stdout, stderr)。
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           errors="replace", timeout=timeout,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except FileNotFoundError:
        return 127, "", "找不到命令: " + str(cmd[0] if cmd else "?")
    except subprocess.TimeoutExpired:
        return 124, "", "命令超时"
    except Exception as e:
        return 1, "", str(e)


def dsh_repo_state(cfg=None):
    # 本机 dsh 仓库 git 状态(纯读): {"exists","ref","detached","dirty","head","pin","err"}
    if cfg is None:
        from core import config as _cfg
        cfg = _cfg.load_config()
    repo = (cfg or {}).get("dash_repo") or ""
    state = {"exists": False, "ref": "", "detached": False, "dirty": False,
             "head": "", "pin": str((cfg or {}).get("dsh_version_pin") or ""),
             "err": ""}
    if not repo or not os.path.isdir(repo):
        return state
    rc, out, err = _git_run(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo)
    if rc != 0:
        state["err"] = err or "读取 git 状态失败"
        return state
    state["exists"] = True
    state["ref"] = out
    state["detached"] = (out == "HEAD")
    rc, out, _ = _git_run(["git", "rev-parse", "--short", "HEAD"], repo)
    state["head"] = out if rc == 0 else ""
    rc, out, _ = _git_run(["git", "status", "--porcelain"], repo)
    state["dirty"] = bool(rc == 0 and out)
    return state


def _default_branch(repo):
    # 远程默认分支名(origin/HEAD 未设置时回退 main)
    rc, out, _ = _git_run(["git", "symbolic-ref", "--short",
                           "refs/remotes/origin/HEAD"], repo)
    if rc == 0 and out.startswith("origin/"):
        return out[len("origin/"):]
    return "main"


class DshCtl:
    """本机 dsh 启停 + 健康监控探测。d 为 config.derived() 的结果(无 globals 依赖)。"""

    def __init__(self, d):
        self.d = d

    # ---------- 日志/状态工具(经 events 回 UI, 不直接碰 UI) ----------
    def _log(self, events, msg, tag=""):
        if events:
            events("log", (msg, tag))

    def _status(self, events, msg):
        if events:
            events("status", msg)

    def _capture_local_token(self, tok, events=None):
        # 捕获到本机 Token: 内存缓存 + 落盘 dsh_home/.console/runtime.json + (配了公网)镜像到信箱。
        if not tok:
            return
        set_runtime_token("local", tok)
        try:
            from core import config as _cfg
            from core import nodeid as _nodeid
            from core import runtime as _runtime
            cfg = _cfg.load_config()
            nid = str(cfg.get("node_id") or "")
            if not _nodeid.valid_node_id(nid):
                nid = _nodeid.ensure_node_id()
                cfg = _cfg.load_config()
            _runtime.write_runtime(nid, tok)
            if cfg.get("ssh_server") and cfg.get("ssh_user"):
                ok = _runtime.publish_mailbox(cfg, nid, tok)
                self._log(events, "  [信箱] Token 已同步到公网 (%s)" % nid,
                          "ok" if ok else "warn")
        except Exception as e:
            # 记录/投递失败不影响启动主流程, 仅告警
            self._log(events, "  [信箱] 记录本机 Token 失败: %s" % e, "warn")

    # ---------- 本机 dsh 启停 ----------
    def run_dsh(self, mode, events=None):
        if mode == "stop":
            return self.stop_dsh(events)
        elif mode == "start":
            return self.start_dsh(events)
        elif mode == "restart":
            self.stop_dsh(events)
            self._log(events, "  停止完成, 重新启动...", "warn")
            import time as _t
            _t.sleep(1)
            return self.start_dsh(events)
        return False

    def start_dsh(self, events=None):
        dash_repo = self.d.get("dash_repo") or ""
        dash_cmd = self.d.get("dash_cmd") or []
        dash_port = self.d.get("dash_port") or 3080
        from core import pkgmgr
        mode = pkgmgr.detect_mode(self.d).get("mode")
        proc_env = None
        cwd = dash_repo
        if mode == "package":
            # 全局包模式: 用 npm 全局前缀下的 dsh shim 启动, 环境把该目录前置进 PATH。
            dash_cmd = pkgmgr.start_cmd()
            cwd = None
            proc_env = pkgmgr.npm_env()
            self._log(events, "  [模式] 全局包模式: " + " ".join(dash_cmd))
        elif not os.path.isdir(dash_repo):
            self._log(events, "  仓库不存在: %s" % dash_repo, "err")
            self._status(events, "启动失败: 仓库目录不存在")
            return False

        # 启动前端口占用检测与旧实例清理
        is_busy, _ = self.probe("127.0.0.1", dash_port)
        if is_busy:
            self._log(events, "  [提示] 检测到端口 %d 已被占用，尝试停止旧实例..." % dash_port, "warn")
            self.stop_dsh(events)
            import time as _t
            for _ in range(4):
                _t.sleep(0.5)
                if not self.probe("127.0.0.1", dash_port)[0]:
                    break
            if self.probe("127.0.0.1", dash_port)[0]:
                self._log(events, "  [警告] 端口 %d 仍被占用，启动可能遇到冲突" % dash_port, "warn")

        self._log(events, "  $ cd %s && %s" % (cwd or "(继承当前目录)", " ".join(dash_cmd)))
        try:
            logdir = os.path.join(os.environ.get("TEMP", "."), "dsh-dash")
            os.makedirs(logdir, exist_ok=True)
            out_file = os.path.join(logdir, "dsh-web.out.log")
            err_file = os.path.join(logdir, "dsh-web.err.log")

            from core.logs import Tailer, classify_line
            out_tailer = Tailer(out_file)
            out_tailer.offset = os.path.getsize(out_file) if os.path.isfile(out_file) else 0
            err_tailer = Tailer(err_file)
            err_tailer.offset = os.path.getsize(err_file) if os.path.isfile(err_file) else 0

            out = open(out_file, "ab")
            err = open(err_file, "ab")
            proc = subprocess.Popen(dash_cmd, cwd=cwd, env=proc_env, stdout=out, stderr=err,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            self._log(events, "  进程已启动 (PID %d), 正在检测运行状态..." % proc.pid, "ok")
            self._status(events, "正在启动本机 dsh (PID %d)..." % proc.pid)

            # 初始观测 (最多等待 15 秒，以 500ms 间隔轮询，由工作线程执行，不卡 GUI 主线程)
            import time as _t
            started_ok = False
            for _ in range(30):
                _t.sleep(0.5)
                err_lines, _ = err_tailer.read_new()
                for ln in err_lines:
                    self._log(events, "    " + ln, "err")
                out_lines, _ = out_tailer.read_new()
                for ln in out_lines:
                    self._log(events, "    " + ln, classify_line(ln))
                    tok, _ = extract_auth_token(ln)
                    if tok:
                        self._capture_local_token(tok, events)

                # 检查进程是否已提前退出 (如崩溃/语法错误/缺少导出/端口冲突)
                rc = proc.poll()
                if rc is not None:
                    _t.sleep(0.2)
                    rem_err, _ = err_tailer.read_new()
                    for ln in rem_err:
                        self._log(events, "    " + ln, "err")
                    rem_out, _ = out_tailer.read_new()
                    for ln in rem_out:
                        self._log(events, "    " + ln, classify_line(ln))
                    self._log(events, "  [dsh-web] 启动失败: 进程已异常退出 (退出码 %s)" % rc, "err")
                    self._status(events, "启动失败: 进程已退出 (code %s)" % rc)
                    if events:
                        events("card", ("dsh-web", False))
                    clear_runtime_token("local")
                    return False

                # 检查端口是否已就绪
                ok, lat = self.probe("127.0.0.1", dash_port)
                if ok:
                    self._log(events, "  dsh web 已就绪 -> http://127.0.0.1:%d (%dms)" % (dash_port, lat), "ok")
                    self._status(events, "dsh web 已就绪 -> http://127.0.0.1:%d" % dash_port)
                    if events:
                        events("card", ("dsh-web", True))
                    started_ok = True
                    break

            if not started_ok:
                self._log(events, "  进程仍在后台运行, 15s 内尚未检测到端口监听, 等待 %d 端口就绪..." % dash_port, "warn")
                self._status(events, "已触发本机 dsh 启动 -> http://127.0.0.1:%d" % dash_port)
                if events:
                    events("card", ("dsh-web", True))

            # 启动持续 15 秒的后台监视器，捕捉启动后插件加载阶段的输出或崩溃
            def _watch_proc():
                for _ in range(30):
                    _t.sleep(0.5)
                    el, _ = err_tailer.read_new()
                    for ln in el:
                        self._log(events, "    " + ln, "err")
                    ol, _ = out_tailer.read_new()
                    for ln in ol:
                        self._log(events, "    " + ln, classify_line(ln))
                        tok, _ = extract_auth_token(ln)
                        if tok:
                            self._capture_local_token(tok, events)
                    rc = proc.poll()
                    if rc is not None:
                        _t.sleep(0.2)
                        rem_err, _ = err_tailer.read_new()
                        for ln in rem_err:
                            self._log(events, "    " + ln, "err")
                        rem_out, _ = out_tailer.read_new()
                        for ln in rem_out:
                            self._log(events, "    " + ln, classify_line(ln))
                        self._log(events, "  [dsh-web] 进程后续退出 (退出码 %s)" % rc, "err")
                        self._status(events, "dsh 进程已退出 (code %s)" % rc)
                        if events:
                            events("card", ("dsh-web", False))
                        clear_runtime_token("local")
                        break
            threading.Thread(target=_watch_proc, daemon=True).start()
            return True
        except FileNotFoundError:
            self._log(events, "  找不到 %s, 请确认 pnpm 在 PATH 或修改配置" % dash_cmd[0], "err")
            self._status(events, "启动失败: 找不到启动命令")
            return False
        except Exception as e:
            self._log(events, "  异常: %s" % e, "err")
            self._status(events, "启动出错: %s" % e)
            return False

    def stop_dsh(self, events=None):
        dash_port = self.d.get("dash_port") or 3080
        ps = (
            "$n=0\n"
            "$port=%d\n"
            "# 1. 查找并停止占用 dash_port 的进程\n"
            "$conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue\n"
            "if ($conns) {\n"
            "  foreach ($c in $conns) {\n"
            "    $p = $c.OwningProcess\n"
            "    if ($p -gt 4) {\n"
            "      Write-Output ('stop port ' + $port + ' listener PID ' + $p)\n"
            "      taskkill /PID $p /T /F | Out-Null\n"
            "      $n++\n"
            "    }\n"
            "  }\n"
            "}\n"
            "# 2. 匹配并停止 dsh web 相关的 node.exe 进程\n"
            "Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" -ErrorAction SilentlyContinue |\n"
            "  Where-Object { ($_.CommandLine -match 'dsh' -or $_.CommandLine -match 'apps[\\\\/]cli' -or $_.CommandLine -match 'bin\\.(ts|js)' -or $_.CommandLine -match 'deepseek-harness') -and ($_.CommandLine -match 'web' -or $_.CommandLine -match 'apps[\\\\/]cli') } |\n"
            "  ForEach-Object { Write-Output ('stop node ' + $_.ProcessId); taskkill /PID $_.ProcessId /T /F | Out-Null; $n++ }\n"
            "if($n -eq 0){ Write-Output 'no dsh web process' }\n" % dash_port
        )
        self._log(events, "  $ stopping dsh web (端口 %d & node 进程)..." % dash_port)
        try:
            r = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy",
                                "Bypass", "-Command", ps],
                               capture_output=True, text=True, errors="replace",
                               timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
            for ln in ((r.stdout or "").splitlines() or ["(无输出)"]):
                self._log(events, "    " + ln, "ok" if r.returncode == 0 else "err")
            self._status(events, "已停止本机 dsh web" if r.returncode == 0
                         else "停止本机 dsh 出错")
            if events:
                events("card", ("dsh-web", False))
            if r.returncode == 0:
                clear_runtime_token("local")
            return r.returncode == 0
        except subprocess.TimeoutExpired:
            self._log(events, "  [停止] 超时(60s)", "err")
            self._status(events, "停止本机 dsh 超时")
            return False
        except Exception as e:
            self._log(events, "  异常: %s" % e, "err")
            self._status(events, "停止出错: %s" % e)
            return False

    # ---------- dsh 完整更新(原 tkinter 主程序 _run_update, PySide6 迁移时丢失, 现恢复) ----------
    def update_dsh(self, events=None, to_main=False):
        # 步骤: 停 web -> (固定版本时先切回默认分支) -> git 拉取 -> 清理 -> 依赖 -> 构建 -> 重启;
        # 任一命令失败即中止。to_main=True 由 UI 在"已固定版本"确认后传入; 每步发 step 事件供
        # 页面进度条。清理一步不可省: dsh 的 lib/ 构建产物被 gitignore, git pull 不动它, 上游
        # 改名/删导出后过期生成物会让 tsdown 报 MISSING_EXPORT。
        from core import pkgmgr
        if pkgmgr.detect_mode(self.d).get("mode") == "package":
            return self.update_dsh_pkg(events)
        dash_repo = self.d.get("dash_repo") or ""
        if not os.path.isdir(dash_repo):
            self._log(events, "  仓库不存在: %s" % dash_repo, "err")
            self._status(events, "更新失败: 仓库目录不存在")
            return False

        def step(n, text):
            if events:
                events("step", (n, text))

        step(1, "步骤1/7: 停止当前 dsh web")
        self._log(events, "[更新] 步骤1/7: 停止当前 dsh web", "warn")
        self.stop_dsh(events)
        import time as _t
        _t.sleep(2)
        if to_main:
            branch = _default_branch(dash_repo)
            self._log(events, "[更新] 切回默认分支: %s" % branch, "warn")
            if not self.stream_cmd(["git", "checkout", branch], cwd=dash_repo, events=events):
                self._status(events, "更新失败: 切回默认分支")
                return False
        steps = [
            (2, "步骤2/7: git fetch", ["git", "fetch", "origin", "--prune"]),
            (3, "步骤3/7: git pull --ff-only", ["git", "pull", "--ff-only"]),
            (4, "步骤4/7: 清理旧构建产物", ["pnpm.cmd", "run", "clean"]),
            (5, "步骤5/7: pnpm install", ["pnpm.cmd", "install"]),
            (6, "步骤6/7: pnpm run build", ["pnpm.cmd", "run", "build"]),
        ]
        for n, label, cmd in steps:
            step(n, label)
            self._log(events, "[更新] " + label, "warn")
            # 旧版 tkinter 的 git fetch cwd 传了 None(会在控制台目录而非 dsh 仓库执行,
            # 是隐患), 此处统一在 dsh 仓库内执行。
            if not self.stream_cmd(cmd, cwd=dash_repo, events=events):
                self._status(events, "更新失败: " + label)
                return False
        step(7, "步骤7/7: 重启 dsh web")
        self._log(events, "[更新] 步骤7/7: 重启 dsh web", "warn")
        if to_main:
            self._clear_pin(events)
        if not self.start_dsh(events):
            self._log(events, "  [更新] 构建完成，但 dsh web 启动失败，请查看上方控制台报错", "err")
            self._status(events, "更新完成但启动失败")
            return False
        self._log(events, "  [更新] 完成, 访问 http://127.0.0.1:%d" % self.d["dash_port"], "ok")
        self._status(events, "更新完成")
        return True

    def update_dsh_pkg(self, events=None):
        # 全局包模式更新: 停 web -> npm install -g @deepseek-ai/dsh@latest -> 重启(3 步)。
        from core import pkgmgr

        def step(n, text):
            if events:
                events("step", (n, text))

        step(1, "步骤1/3: 停止当前 dsh web")
        self._log(events, "[更新] 步骤1/3: 停止当前 dsh web", "warn")
        self.stop_dsh(events)
        import time as _t
        _t.sleep(1)
        step(2, "步骤2/3: npm install -g " + pkgmgr.DSH_PKG + "@latest")
        self._log(events, "[更新] npm install -g " + pkgmgr.DSH_PKG + "@latest", "warn")
        if not self.stream_cmd(pkgmgr.update_cmd(), cwd=pkgmgr.npm_cwd(),
                               env=pkgmgr.npm_env(), events=events):
            self._status(events, "更新失败: npm install -g @latest")
            return False
        step(3, "步骤3/3: 重启 dsh web")
        self._log(events, "[更新] 步骤3/3: 重启 dsh web", "warn")
        if not self.start_dsh(events):
            self._log(events, "  [更新] 包已更新, 但 dsh web 启动失败, 请查看上方控制台报错", "err")
            self._status(events, "更新完成但启动失败")
            return False
        pkgmgr.package_info(force=True)   # 刷新版本缓存
        self._log(events, "  [更新] 完成, 访问 http://127.0.0.1:%d" % self.d["dash_port"], "ok")
        self._status(events, "更新完成")
        return True

    # ---------- 版本固定状态(config.dsh_version_pin) ----------
    def _set_pin(self, tag, events=None):
        try:
            from core import config as _cfg
            cfg = _cfg.load_config()
            cfg["dsh_version_pin"] = tag or ""
            if not _cfg.save_config(cfg):
                self._log(events, "  [警告] 版本固定状态写入 config.json 失败", "warn")
            elif tag:
                self._log(events, "  已记录版本固定: %s (config.json)" % tag)
        except Exception as e:
            self._log(events, "  [警告] 写入版本固定状态失败: %s" % e, "warn")

    def _clear_pin(self, events=None):
        self._set_pin("", events)

    # ---------- 部署指定版本(切换/回退到某个 Release tag) ----------
    def deploy_dsh_version(self, events=None, tag="", allow_dirty=False):
        # 停 web -> fetch tags -> 校验 -> 工作区脏检查 -> checkout tag -> install -> clean -> build
        # -> 重启, 并写 config.dsh_version_pin。工作区有本地改动且未 allow_dirty 时, 不改动任何
        # 东西, 只返回哨兵 {"dirty": True}(UI 二次确认后再以 allow_dirty=True 调用)。
        # 契约: {"err","dirty","msg","tag"}; events 为首参(配合 services._run_result_op)。
        dash_repo = self.d.get("dash_repo") or ""
        tag = str(tag or "").strip()
        from core import pkgmgr
        if pkgmgr.detect_mode(self.d).get("mode") == "package":
            return self._deploy_pkg_version(events, tag)
        if not os.path.isdir(dash_repo):
            self._log(events, "  仓库不存在: %s" % dash_repo, "err")
            self._status(events, "部署失败: 仓库目录不存在")
            return {"err": "仓库目录不存在", "dirty": False, "msg": "", "tag": tag}
        if not tag:
            return {"err": "版本 tag 为空", "dirty": False, "msg": "", "tag": tag}
        if not allow_dirty:
            rc, out, _ = _git_run(["git", "status", "--porcelain"], dash_repo)
            if rc == 0 and out:
                self._log(events, "  [部署] 检测到工作区有未提交改动, 等待确认", "warn")
                return {"err": "", "dirty": True, "msg": "", "tag": tag}

        def step(n, text):
            if events:
                events("step", (n, text))

        def fail(reason):
            self._status(events, "部署失败: " + reason)
            return {"err": reason, "dirty": False, "msg": "", "tag": tag}

        step(1, "步骤1/7: 停止当前 dsh web")
        self._log(events, "[部署] 步骤1/7: 停止当前 dsh web", "warn")
        self.stop_dsh(events)
        import time as _t
        _t.sleep(1)

        step(2, "步骤2/7: git fetch --tags")
        self._log(events, "[部署] 步骤2/7: git fetch --tags --prune", "warn")
        if not self.stream_cmd(["git", "fetch", "--tags", "--prune"],
                               cwd=dash_repo, events=events):
            return fail("git fetch 失败")

        step(3, "步骤3/7: 校验版本 " + tag)
        self._log(events, "[部署] 步骤3/7: 校验版本 " + tag, "warn")
        rc, _out, err = _git_run(["git", "rev-parse", "--verify", tag + "^{commit}"],
                                 dash_repo)
        if rc != 0:
            self._log(events, "  版本不存在: %s (%s)" % (tag, err or "rev-parse 失败"), "err")
            return fail("版本不存在: " + tag)

        step(4, "步骤4/7: git checkout " + tag)
        self._log(events, "[部署] 步骤4/7: git checkout " + tag, "warn")
        if not self.stream_cmd(["git", "checkout", tag], cwd=dash_repo, events=events):
            return fail("git checkout 失败")
        self._set_pin(tag, events)

        step(5, "步骤5/7: pnpm install")
        self._log(events, "[部署] 步骤5/7: pnpm install", "warn")
        if not self.stream_cmd(["pnpm.cmd", "install"], cwd=dash_repo, events=events):
            return fail("pnpm install 失败")

        step(6, "步骤6/7: 清理并构建")
        self._log(events, "[部署] 步骤6/7: 清理旧构建产物", "warn")
        if not self.stream_cmd(["pnpm.cmd", "run", "clean"], cwd=dash_repo, events=events):
            return fail("清理构建产物失败")
        self._log(events, "[部署] 步骤6/7: pnpm run build", "warn")
        if not self.stream_cmd(["pnpm.cmd", "run", "build"], cwd=dash_repo, events=events):
            return fail("pnpm run build 失败")

        step(7, "步骤7/7: 重启 dsh web")
        self._log(events, "[部署] 步骤7/7: 重启 dsh web", "warn")
        if not self.start_dsh(events):
            self._log(events, "  [部署] 构建完成，但 dsh web 启动失败，请查看上方控制台报错", "err")
            self._status(events, "部署完成但启动失败")
            return {"err": "部署完成但启动失败", "dirty": False, "msg": "", "tag": tag}
        self._log(events, "  [部署] 完成, 已切换到 %s" % tag, "ok")
        self._status(events, "已部署版本 " + tag)
        return {"err": "", "dirty": False, "msg": "已部署 " + tag, "tag": tag}

    def _deploy_pkg_version(self, events=None, tag=""):
        # 全局包模式的"部署指定版本" = npm install -g @deepseek-ai/dsh@<版本>(tag 归一为 npm 版本)。
        from core import pkgmgr
        tag = str(tag or "").strip()
        if not tag:
            return {"err": "版本为空", "dirty": False, "msg": "", "tag": tag}
        ver = pkgmgr.npm_version(tag)

        def step(n, text):
            if events:
                events("step", (n, text))

        step(1, "步骤1/3: 停止当前 dsh web")
        self._log(events, "[部署] 步骤1/3: 停止当前 dsh web", "warn")
        self.stop_dsh(events)
        import time as _t
        _t.sleep(1)
        step(2, "步骤2/3: 安装 %s@%s" % (pkgmgr.DSH_PKG, ver))
        self._log(events, "[部署] 步骤2/3: npm install -g %s@%s" % (pkgmgr.DSH_PKG, ver), "warn")
        if not self.stream_cmd(pkgmgr.install_cmd(ver), cwd=pkgmgr.npm_cwd(),
                               env=pkgmgr.npm_env(), events=events):
            self._status(events, "部署失败: npm install -g")
            return {"err": "npm install -g 失败", "dirty": False, "msg": "", "tag": tag}
        step(3, "步骤3/3: 重启 dsh web")
        self._log(events, "[部署] 步骤3/3: 重启 dsh web", "warn")
        if not self.start_dsh(events):
            self._log(events, "  [部署] 包已切换, 但 dsh web 启动失败", "err")
            self._status(events, "部署完成但启动失败")
            return {"err": "部署完成但启动失败", "dirty": False, "msg": "", "tag": tag}
        pkgmgr.package_info(force=True)
        self._log(events, "  [部署] 完成, 全局包已切到 %s" % ver, "ok")
        self._status(events, "已部署版本 " + ver)
        return {"err": "", "dirty": False, "msg": "已部署 " + ver, "tag": tag}

    # ---------- 通用命令流(流式打日志) ----------
    def stream_cmd(self, cmd, cwd=None, env=None, events=None, timeout_override=None,
                   heartbeat=15):
        # 流式执行: 逐行转 events(log)。读管子用独立线程 + 队列, 主循环每 0.5s 醒一次——
        # 这样长命令"静默"期间也能按 heartbeat 打心跳(每 N 秒一条), 且超时判断真正生效
        # (此前直接在 stdout.readline() 上阻塞, 静默命令既不心跳也不超时)。
        self._log(events, "  $ " + " ".join(cmd))
        timeout = timeout_override or self.d.get("update_timeout") or 1800
        try:
            p = subprocess.Popen(cmd, cwd=cwd, env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 encoding="utf-8", errors="replace", bufsize=1, text=True,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        except FileNotFoundError:
            self._log(events, "  找不到命令: " + str(cmd[0] if cmd else "?"), "err")
            return False
        import queue
        import threading
        import time as _t
        q = queue.Queue()
        done = object()

        def _reader(pipe):
            try:
                for line in iter(pipe.readline, ""):
                    q.put(line)
            except Exception:
                pass   # 读线程异常只能来自管道关闭/进程被杀, 由主循环的 poll/deadline 收场
            finally:
                q.put(done)

        threading.Thread(target=_reader, args=(p.stdout,), daemon=True).start()
        deadline = _t.time() + timeout
        t0 = _t.time()
        last = _t.time()
        errs = []   # 错误行(供失败时给出简短摘要, 不让几千行日志淹没根因)
        while True:
            try:
                line = q.get(timeout=0.5)
            except queue.Empty:
                line = None
            if line is done:
                break
            if line is not None:
                text = line.rstrip()
                self._log(events, "    " + text)
                low = text.strip().lower()
                if (low.startswith("error") or low.startswith("npm error")
                        or "err!" in low or "etarget" in low or "notarget" in low):
                    errs.append(text.strip())
                    if len(errs) > 8:
                        errs.pop(0)
                last = _t.time()
                continue
            now = _t.time()
            if now > deadline:
                p.kill()
                self._log(events, "  [stream] 超时, 已强制终止", "err")
                return False
            if heartbeat and now - last >= heartbeat:
                last = now
                self._log(events, "  ... 已运行 %d 秒(命令仍在执行)" % int(now - t0), "warn")
        rc = p.wait()
        if rc != 0:
            for e in errs[-5:]:
                self._log(events, "  [失败摘要] " + e[:300], "err")
            if any("etarget" in e.lower() or "notarget" in e.lower() for e in errs):
                self._log(events, "  [提示] 依赖版本解析失败: 多为 npm 镜像尚未同步或该版本"
                                  "未发布; 可稍后重试, 或在「安装 dsh」卡指定一个已发布版本", "warn")
            self._log(events, "  [stream] 命令失败 (exit %s)" % rc, "err")
            return False
        return True

    # ---------- 健康监控探测(原 _probe / _ssh_proc_count / _probe_remote_tunnels) ----------
    def probe(self, host, port):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(self.d.get("tcp_timeout") or 0.8)
            import time as _t
            t0 = _t.time()
            s.connect((host, port))
            s.close()
            return True, int((_t.time() - t0) * 1000)
        except Exception:
            return False, -1

    def ssh_proc_count(self):
        try:
            out = subprocess.run(
                ["tasklist", "/NH", "/FI", "IMAGENAME eq ssh.exe"],
                capture_output=True, text=True, errors="replace", timeout=8,
                creationflags=subprocess.CREATE_NO_WINDOW).stdout
            return sum(1 for ln in out.splitlines() if "ssh.exe" in ln)
        except Exception:
            return -1

    def probe_remote_tunnels(self):
        pts = [p for p, _, _ in self.d.get("remote_tunnels", [])]
        if not pts:
            return {}
        server = self.d.get("ssh_server") or ""
        user = self.d.get("ssh_user") or ""
        ports = "|".join(str(p) for p in pts)
        cmd = "ss -tln | grep -E ':(%s) '" % ports
        try:
            p = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
                 "-o", "LogLevel=ERROR", "%s@%s" % (user, server), cmd],
                capture_output=True, text=True, errors="replace", timeout=8,
                creationflags=subprocess.CREATE_NO_WINDOW)
            if p.returncode != 0:
                return None
            text = p.stdout or ""
            return {pt: (":%d " % pt) in text or (":%d" % pt) in text for pt in pts}
        except Exception:
            return None

    def monitor_tick(self, on_result=None):
        "# 一次性探测本机端口+ssh+远程隧道(供后台线程调用)。on_result(kind,payload) 纯数据回调。"
        local = {}
        for port, _, _ in self.d.get("local_ports", []):
            local[port] = self.probe("127.0.0.1", port)
        if self.d.get("ssh_server"):
            local["__ssh__"] = self.probe(self.d["ssh_server"], 22)
        ssh_count = self.ssh_proc_count()
        remote = self.probe_remote_tunnels()
        if on_result:
            on_result("monitor", (local, ssh_count, remote))
        return local, ssh_count, remote


__all__ = ["DshCtl"]
