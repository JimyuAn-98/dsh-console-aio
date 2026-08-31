# -*- coding: utf-8 -*-
# core/data.py — dsh 数据层(阶段4 自仓库根 dsh_data.py 归并而来): 读取/写入 ~/.dsh
# 各数据域, 零依赖(仅 stdlib), 纯函数零 Qt; 写入函数一律先 .bak 备份。
# 兼容: 仓库根保留 dsh_data.py shim(旧 import 路径), 新代码一律 from core import data。
# 接口文档见 docs/ARCHITECTURE.md。

import os
import re
import sys
import io
import json
import zipfile
import datetime
import shutil

# ── 定位 ──────────────────────────────────────────────
def dsh_home():
    # DSH_HOME 环境变量优先, 否则用户主目录/.dsh
    h = os.environ.get("DSH_HOME") or os.path.join(os.path.expanduser("~"), ".dsh")
    return h

def profiles_dir():
    return os.path.join(dsh_home(), "profiles")

def sessions_dir():
    return os.path.join(dsh_home(), "sessions")

# ── 通用备份 ──────────────────────────────────────────
def backup_file(path):
    # 写前备份: 复制 <file>.bak(覆盖旧的), 返回备份路径
    if not os.path.isfile(path):
        return None
    bak = path + ".bak"
    try:
        shutil.copy2(path, bak)
    except OSError:
        pass
    return bak

# ── 最小 YAML 子集解析/序列化 ─────────────────────────
# 支持: 缩进嵌套 dict, "- " 列表(list of dict / list of scalar),
#       标量(字符串/数字/布尔/null), # 注释。够用即可, 不追求完整 YAML。

def _strip_comment(line):
    # 去掉行内注释(# 前导), 简单处理: 引号内 # 不处理
    in_s = None
    for i, ch in enumerate(line):
        if ch in "'\"":
            if in_s == ch:
                in_s = None
            elif in_s is None:
                in_s = ch
        elif ch == "#" and in_s is None:
            return line[:i]
    return line

def _parse_scalar(s):
    s = s.strip()
    if s == "" or s.lower() in ("null", "~"):
        return None
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    # 数字
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s

def _lead_spaces(s):
    # 前导空格数
    n = 0
    while n < len(s) and s[n] == " ":
        n += 1
    return n

def _parse_yaml_block(lines, idx, indent):
    # 解析一个缩进块, 返回 (value, next_idx)。lines 已剥注释。
    # 块内元素: 前导空格 == indent; 更浅缩进属于外层(break);
    # 更深缩进只允许出现在 key: / - key: 之后, 由递归按实际缩进处理。
    if idx >= len(lines):
        return None, idx
    first = lines[idx]
    if first[indent:].startswith("- "):
        # list
        out = []
        while idx < len(lines):
            line = lines[idx]
            if not line.strip():
                idx += 1
                continue
            lead = _lead_spaces(line)
            if lead < indent:
                break
            if lead > indent:
                idx += 1
                continue
            if not line[lead:].startswith("- "):
                break
            rest = line[lead + 2:].strip()
            if not rest:
                idx += 1
                continue
            if ":" in rest:
                key, _, val = rest.partition(":")
                key = key.strip()
                val = val.strip()
                item = {key: _parse_scalar(val) if val else None}
                idx += 1
                # 收集 item 的后续字段(更深缩进)
                while idx < len(lines):
                    nxt = lines[idx]
                    if not nxt.strip():
                        idx += 1
                        continue
                    nlead = _lead_spaces(nxt)
                    if nlead <= lead:
                        break
                    if nxt[nlead:].startswith("- "):
                        # item 内嵌套 list, 赋给值为 None 的 key(如 insert)
                        sub, idx = _parse_yaml_block(lines, idx, nlead)
                        for k in item:
                            if item[k] is None:
                                item[k] = sub
                                break
                        continue
                    sub, idx = _parse_yaml_block(lines, idx, nlead)
                    if isinstance(sub, dict):
                        item.update(sub)
                    # 继续循环: 同级字段(如 description:)尚未处理, 不 break
                out.append(item)
            else:
                out.append(_parse_scalar(rest))
                idx += 1
        return out, idx
    # dict
    out = {}
    while idx < len(lines):
        line = lines[idx]
        if not line.strip():
            idx += 1
            continue
        lead = _lead_spaces(line)
        if lead < indent:
            break
        if lead > indent:
            idx += 1
            continue
        if line[lead] == "-":
            break
        rest = line[lead:]
        if ":" not in rest:
            idx += 1
            continue
        key, _, val = rest.partition(":")
        key = key.strip()
        val = val.strip()
        if val == "":
            idx += 1
            if idx < len(lines):
                sub_indent = _lead_spaces(lines[idx])
                if sub_indent > lead:
                    out[key], idx = _parse_yaml_block(lines, idx, sub_indent)
                else:
                    out[key] = None
            else:
                out[key] = None
        else:
            out[key] = _parse_scalar(val)
            idx += 1
    return out, idx

def parse_yaml_text(raw):
    # 从文本解析 YAML(供本地文件与远程 cat 复用)
    lines = [_strip_comment(l).rstrip() for l in raw.splitlines()]
    lines = [l for l in lines if l.strip() != ""]
    if not lines:
        return {}
    val, _ = _parse_yaml_block(lines, 0, 0)
    return val if val is not None else {}


def read_yaml(path):
    # 解析 YAML 文件; 不存在返回 None
    if not os.path.isfile(path):
        return None
    with io.open(path, encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    return parse_yaml_text(raw)

def _dump_scalar(v):
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if any(ch in s for ch in ": #\n"):
        return '"' + s.replace('"', '\\"') + '"'
    return s

def _dump_yaml(data, indent=0):
    pad = " " * indent
    lines = []
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, dict):
                lines.append(pad + k + ":")
                lines.extend(_dump_yaml(v, indent + 2))
            elif isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                lines.append(pad + k + ":")
                lines.extend(_dump_yaml(v, indent + 2))
            elif isinstance(v, list):
                lines.append(pad + k + ":")
                for x in v:
                    if isinstance(x, dict):
                        lines.extend(_dump_yaml(x, indent + 2))
                    else:
                        lines.append(pad + "  - " + _dump_scalar(x))
            else:
                lines.append(pad + k + ": " + _dump_scalar(v))
    elif isinstance(data, list):
        for x in data:
            if isinstance(x, dict):
                if not x:
                    lines.append(pad + "- {}")
                    continue
                items = list(x.items())
                k0, v0 = items[0]
                if isinstance(v0, dict):
                    lines.append(pad + "- " + k0 + ":")
                    lines.extend(_dump_yaml(v0, indent + 4))
                elif isinstance(v0, list):
                    lines.append(pad + "- " + k0 + ":")
                    lines.extend(_dump_yaml(v0, indent + 4))
                else:
                    lines.append(pad + "- " + k0 + ": " + _dump_scalar(v0))
                for k, v in items[1:]:
                    if isinstance(v, dict):
                        lines.append(pad + "  " + k + ":")
                        lines.extend(_dump_yaml(v, indent + 4))
                    elif isinstance(v, list):
                        lines.append(pad + "  " + k + ":")
                        lines.extend(_dump_yaml(v, indent + 4))
                    else:
                        lines.append(pad + "  " + k + ": " + _dump_scalar(v))
            else:
                lines.append(pad + "- " + _dump_scalar(x))
    return lines

def write_yaml(path, data):
    # 备份后写回 YAML, 返回备份路径
    backup_file(path)
    lines = _dump_yaml(data)
    if not lines:
        # 空 list/dict 必须写成合法 YAML 文档: 空文件解析为 null 而非空容器,
        # dsh patch 层等消费方会拒绝加载(HMR 失效, profile 重启即启动失败)
        lines = ["[]" if isinstance(data, list) else "{}"]
    body = "\n".join(lines) + "\n"
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(body)
    return path

# ── 会话 / 工作区 ─────────────────────────────────────
def read_workspace(remote=None):
    # workspace.json -> {workspaceIds: [], archivedSessionIds: []}
    _r = remote if remote is not None else DshRemote(None)
    try:
        d = json.loads(_r.read_file("storages/workspace.json"))
        return d.get("global", {})
    except (OSError, ValueError):
        return {}

def list_sessions(remote=None):
    # 按工作目录分组: [{workdir, count, bytes, sessions:[{name,size,mtime}]}]
    _r = remote if remote is not None else DshRemote(None)
    groups = []
    try:
        dirs = _r.list_dir("sessions")
    except OSError:
        return groups
    for d in sorted(dirs):
        try:
            st = _r.dir_stats("sessions/" + d)
        except OSError:
            continue
        items = []
        for name in sorted(st["dirs"]):
            items.append({"name": name, "bytes": st["dirs"][name], "mtime": 0})
        groups.append({"workdir": d, "count": len(items), "bytes": st["total"], "sessions": items})
    return groups

# ── Profile / 插件 ────────────────────────────────────
def list_profiles(remote=None):
    # 返回 [{name, cordis(bool), patch(bool), pkg(bool)}]
    _r = remote if remote is not None else DshRemote(None)
    out = []
    try:
        dirs = _r.list_dir("profiles")
    except OSError:
        return out
    for d in sorted(dirs):
        try:
            files = set(_r.list_dir("profiles/" + d))
        except OSError:
            files = set()
        out.append({
            "name": d,
            "cordis": "cordis.yml" in files,
            "patch": "cordis.patch.yml" in files,
            "pkg": "package.json" in files,
        })
    return out

def _read_cordis_file(profile, fn, remote):
    _r = remote if remote is not None else DshRemote(None)
    try:
        d = parse_yaml_text(_r.read_file("profiles/" + profile + "/" + fn))
    except (OSError, ValueError):
        d = {}
    if isinstance(d, dict):
        d = []
    return d if isinstance(d, list) else []

def read_cordis(profile, remote=None):
    # 解析 profile 的 cordis.yml, 返回 entries list
    return _read_cordis_file(profile, "cordis.yml", remote)

def read_cordis_patch(profile, remote=None):
    return _read_cordis_file(profile, "cordis.patch.yml", remote)

def write_cordis_patch(profile, entries):
    # 备份后写回 cordis.patch.yml
    base = os.path.join(profiles_dir(), profile)
    p = os.path.join(base, "cordis.patch.yml")
    return write_yaml(p, entries)

def plugin_cmd(profile, *args):
    # 组装 dsh plugin 命令(由 UI 层经 service.run_cmd 在 dsh 仓库目录执行)
    # 注意: dsh 需经 pnpm 调用(pnpm.cmd dsh ...), 且在 DASH_REPO 目录下执行
    return ["pnpm.cmd", "dsh", "plugin", "--profile", profile] + list(args)


def _dump_config_output(profile, dash_repo, remote):
    # 跑 dsh --profile X --dump-config(纯读合成, 不启动 web), 返回 stdout; 失败返回空串。
    import subprocess as _sp
    _r = remote if remote is not None else DshRemote(None)
    cmd = ["pnpm.cmd", "dsh", "--profile", profile, "--dump-config"]
    try:
        if _r.is_remote:
            return _r.exec("cd " + (dash_repo or "~") + " && pnpm dsh --profile " + profile + " --dump-config")
        r = _sp.run(cmd, capture_output=True, text=True, errors="replace",
                    timeout=60, creationflags=_sp.CREATE_NO_WINDOW,
                    cwd=dash_repo or os.getcwd())
        return r.stdout or ""
    except Exception:
        # dump 失败只影响 id 映射/cordis 徽章退化为空, 不阻断插件列表
        return ""


def _entry_yaml_blocks(out):
    # 抓每条 entry 的原始 YAML 块(从 `- id:` 行到下一个不深于它的行前),
    # 供插件页"配置"栏只读展示; `# ==` 分组注释不属于任何 entry, 剔除。
    lines = out.splitlines()
    starts = []
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)- id:\s*(.+?)\s*$", line)
        if m:
            starts.append((i, len(m.group(1)), m.group(2).strip("'\"")))
    blocks = {}
    for pos, (i, indent, eid) in enumerate(starts):
        end = len(lines)
        for j, ind2, _eid2 in starts[pos + 1:]:
            if ind2 <= indent:
                end = j
                break
        blocks[eid] = "\n".join(l for l in lines[i:end] if not l.startswith("# =="))
    return blocks


def dump_entry_states(profile, dash_repo=None, remote=None):
    # 解析 dump-config 输出, 返回 {"id_map": name->真实 entry id, "states": {entry id: {name, disabled}}}。
    # 停用/启用必须用真实 entry id(如 dshmarket 的 id 是 dsh-market), 不能用 bundle 名;
    # states 即 cordis 合成生效状态(disabled 含 patch 层停用与强制启用的 false)。
    # 逐行解析而非完整 YAML: 输出可含 !!js 表达式, 且缩进契约稳定(js-yaml 缩进 2):
    # `- id:` 行开启一条 entry(任意层级), 其字段在 缩进+2; 用缩进栈归属, group 条目的
    # 尾部字段与嵌套子条目互不串扰, config 里恰好叫 disabled 的键(更深缩进)不会误归属。
    # !!js 的 disabled 无法离线求值, 视为未停用。
    out = _dump_config_output(profile, dash_repo, remote)
    id_map = {}
    states = {}
    stack = []       # (字段缩进, entry id), 缩进随嵌套递增
    for line in out.splitlines():
        m = re.match(r"^(\s*)- id:\s*(.+?)\s*$", line)
        if m:
            indent = len(m.group(1))
            eid = m.group(2).strip("'\"")
            while stack and stack[-1][0] >= indent:
                stack.pop()
            stack.append((indent, eid))
            states.setdefault(eid, {"name": eid, "disabled": False})
            id_map[eid] = eid
            continue
        m = re.match(r"^(\s*)(name|disabled):\s*(.*?)\s*$", line)
        if m:
            indent = len(m.group(1))
            while stack and stack[-1][0] >= indent:
                stack.pop()
            if stack and stack[-1][0] == indent - 2:
                eid = stack[-1][1]
                if m.group(2) == "name":
                    nm = m.group(3).strip("'\"")
                    states[eid]["name"] = nm
                    id_map[nm] = eid
                else:
                    states[eid]["disabled"] = m.group(3) == "true"
    blocks = _entry_yaml_blocks(out)
    for eid, st in states.items():
        if eid in blocks:
            st["yaml"] = blocks[eid]
    return {"id_map": id_map, "states": states}


def read_profile_package(profile, remote=None):
    # 读 profile/package.json: 返回 {dependencies: {...}, bundles: [...]}
    _r = remote if remote is not None else DshRemote(None)
    try:
        d = json.loads(_r.read_file("profiles/" + profile + "/package.json"))
        dsh = d.get('dsh') or {}
        prof = dsh.get('profile') or {}
        return {
            'dependencies': d.get('dependencies') or {},
            'bundles': prof.get('bundles') or [],
        }
    except (OSError, ValueError):
        return {'dependencies': {}, 'bundles': []}


# ── settings.yaml ─────────────────────────────────────
def read_settings(remote=None):
    _r = remote if remote is not None else DshRemote(None)
    try:
        return parse_yaml_text(_r.read_file("settings.yaml")) or {}
    except (OSError, ValueError):
        return {}

def write_settings(data):
    return write_yaml(os.path.join(dsh_home(), "settings.yaml"), data)

# ── 任务看板 ──────────────────────────────────────────
def read_taskboard(remote=None):
    # 返回 {ledger: {...}, scheduler: {...}}; 文件缺失返回空 dict
    _r = remote if remote is not None else DshRemote(None)
    out = {}
    for key, fn in (("ledger", "ledger-v2.json"), ("scheduler", "scheduler-v2.json")):
        try:
            out[key] = json.loads(_r.read_file("task-board/" + fn))
        except (OSError, ValueError):
            out[key] = {}
    return out

# ── 用量统计 ──────────────────────────────────────────
def zstd_available():
    try:
        import zstandard  # noqa
        return True
    except ImportError:
        return False

def usage_stats(remote=None):
    # 解压全部 session jsonl.zstd, 聚合 token 用量。
    # 返回 {ok: bool, error?: str, models: {model: {provider, input, output, calls}},
    #        days: {date: {input, output}}, days_models: {date: {model: {input, output}}},
    #        sessions: n}
    # days_models 为趋势图维度(天×模型, 只计输入+输出, 不含缓存命中), 与 days 同源累加。
    if remote is not None and remote.is_remote:
        return {"ok": False, "error": "远程用量统计暂不支持(需远程 Python + zstandard)"}
    if not zstd_available():
        return {"ok": False, "error": "缺少 zstandard 库(pip install zstandard)"}
    import zstandard as zstd
    base = sessions_dir()
    models = {}
    days = {}
    days_models = {}
    nsessions = 0
    if not os.path.isdir(base):
        return {"ok": True, "models": models, "days": days, "sessions": 0}
    d = zstd.ZstdDecompressor()
    for g in os.listdir(base):
        gp = os.path.join(base, g)
        if not os.path.isdir(gp):
            continue
        for sd in os.listdir(gp):
            f = os.path.join(gp, sd, "session.jsonl.zstd")
            if not os.path.isfile(f):
                continue
            nsessions += 1
            try:
                with open(f, "rb") as fh:
                    reader = d.stream_reader(fh)
                    cur_model = None
                    cur_provider = None
                    while True:
                        chunk = reader.read(65536)
                        if not chunk:
                            break
                        for line in chunk.decode("utf-8", errors="replace").splitlines():
                            try:
                                obj = json.loads(line)
                            except ValueError:
                                continue
                            t = obj.get("type", "")
                            if t in ("request/header", "request/context"):
                                data = obj.get("data", {})
                                hdr = data.get("header", data)
                                cfg = hdr.get("config", hdr) if isinstance(hdr, dict) else hdr
                                cur_provider = cfg.get("provider") or data.get("provider")
                                cur_model = cfg.get("model") or data.get("model")
                            elif t == "assistant/chunk":
                                data = obj.get("data", {})
                                ck = data.get("chunk", {})
                                if ck.get("type") == "usage" and isinstance(ck.get("usage"), dict):
                                    u = ck["usage"]
                                    i = int(u.get("inputTokens") or 0)
                                    o = int(u.get("outputTokens") or 0)
                                    cr = int(u.get("cacheReadTokens") or 0)   # 缓存命中 tokens
                                    m = cur_model or "unknown"
                                    mm = models.setdefault(m, {"provider": cur_provider, "input": 0, "output": 0, "cache": 0, "calls": 0})
                                    mm["input"] += i
                                    mm["output"] += o
                                    mm["cache"] += cr
                                    mm["calls"] += 1
                                    ts = obj.get("time") or 0
                                    date = datetime.datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d") if ts else "?"
                                    dd = days.setdefault(date, {"input": 0, "output": 0, "cache": 0})
                                    dd["input"] += i
                                    dd["output"] += o
                                    dd["cache"] += cr
                                    dm = days_models.setdefault(date, {}).setdefault(m, {"input": 0, "output": 0})
                                    dm["input"] += i
                                    dm["output"] += o
            except (OSError, ValueError):
                continue
    return {"ok": True, "models": models, "days": days,
            "days_models": days_models, "sessions": nsessions}

# 内置官方单价(元/百万 token), UI 可编辑覆盖。
# 结构: {"in_cached": [空闲, 高峰], "in_miss": [空闲, 高峰], "out": [空闲, 高峰],
#        "billing": "token"|"token-plan"}
# 高峰时段: 北京时间周一至五 9:00-12:00, 14:00-18:00; 其余为空闲。
# billing=="token" 按 token 用量计费(estimate_cost); "token-plan" 为按月订阅, 不走按量估算。
BILLING_TOKEN = "token"
BILLING_PLAN = "token-plan"
DEFAULT_PRICES = {
    "deepseek-v4-flash":        {"in_cached": [0.05, 0.10], "in_miss": [1.5, 3.0], "out": [4.5, 9.0], "billing": BILLING_TOKEN},
    "deepseek-v4-pro":          {"in_cached": [0.15, 0.30], "in_miss": [4.5, 9.0], "out": [13.5, 27.0], "billing": BILLING_TOKEN},
    "deepseek-v4-flash-vision": {"in_cached": [0.05, 0.10], "in_miss": [1.5, 3.0], "out": [4.5, 9.0], "billing": BILLING_TOKEN},
}


_price_cache = None   # 生效价格缓存(读文件一次; save_prices 后失效), None=未加载

# token-plan(订阅)模型的月/年费默认值
DEFAULT_MONTHLY = 0.0
DEFAULT_YEARLY = 0.0


def price_file_path():
    # 价格持久化文件: 与 config.json 同路径(软件路径), 名为 model_prices.json。
    # 优先级同 _config_path: DSH_AIO_CONFIG(文件) / frozen(exe 目录) / 源码目录。
    override = os.environ.get('DSH_AIO_CONFIG')
    if override:
        base = os.path.dirname(os.path.abspath(override))
    elif getattr(sys, 'frozen', False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, 'model_prices.json')


def _validate_price_spec(spec):
    # 校验/归一化一条价格记录, 按 billing 分支:
    #   token      -> {in_cached, in_miss, out, billing} (三组双档单价)
    #   token-plan -> {monthly, yearly, billing}         (按月/年订阅费, 不走按量)
    # 非法字段用默认兜底; spec 非 dict / 无法解析返回 None(整条舍弃)。
    if not isinstance(spec, dict):
        return None
    billing = spec.get("billing")
    if billing == BILLING_PLAN:
        def fee(k, dft):
            try:
                return float(spec.get(k))
            except (TypeError, ValueError):
                return dft
        return {"monthly": fee("monthly", DEFAULT_MONTHLY),
                "yearly": fee("yearly", DEFAULT_YEARLY),
                "billing": BILLING_PLAN}
    # 默认按 token 处理(含 billing 缺失/未知 -> 视为按量)
    out = {}
    for k, dft in (("in_cached", [0.05, 0.10]), ("in_miss", [1.5, 3.0]),
                   ("out", [4.5, 9.0])):
        v = spec.get(k)
        if not isinstance(v, (list, tuple)) or len(v) != 2:
            v = dft
        try:
            out[k] = [float(v[0]), float(v[1])]
        except (TypeError, ValueError):
            out[k] = dft
    out["billing"] = BILLING_TOKEN
    return out


def load_prices():
    # 读取持久化的价格覆盖: {model: {token 结构 或 token-plan 结构}}。
    # 缺失/损坏返回默认(DEFAULT_PRICES)。只返回 files 里出现的模型, 与内置合并由 effective_prices 负责。
    p = price_file_path()
    try:
        with io.open(p, encoding='utf-8', errors='replace') as fh:
            d = json.load(fh)
        if not isinstance(d, dict):
            return {}
        out = {}
        for name, spec in d.items():
            if not name:
                continue
            ok_spec = _validate_price_spec(spec)
            if ok_spec is not None:
                out[name] = ok_spec
        return out
    except (OSError, ValueError):
        return {}


def _norm_fee(v, dft):
    # 月/年费转 float; 空/非法用默认。
    try:
        return float(v)
    except (TypeError, ValueError):
        return dft


def save_prices(prices):
    # 把 {model: {token 结构 或 token-plan 结构}} 写回 model_prices.json(写前备份)。
    # 参数为空 dict 时写成空对象(等价于清空所有覆盖, 全部回默认)。
    p = price_file_path()
    backup_file(p)
    clean = {}
    for name, spec in prices.items():
        if not name or not isinstance(spec, dict):
            continue
        if spec.get("billing") == BILLING_PLAN:
            clean[name] = {"monthly": _norm_fee(spec.get("monthly"), DEFAULT_MONTHLY),
                           "yearly": _norm_fee(spec.get("yearly"), DEFAULT_YEARLY),
                           "billing": BILLING_PLAN}
        else:
            clean[name] = {
                "in_cached": list(spec.get("in_cached") or [0.05, 0.10]),
                "in_miss": list(spec.get("in_miss") or [1.5, 3.0]),
                "out": list(spec.get("out") or [4.5, 9.0]),
                "billing": BILLING_TOKEN,
            }
    try:
        with io.open(p, 'w', encoding='utf-8', newline='') as fh:
            json.dump(clean, fh, ensure_ascii=False, indent=2)
    except OSError:
        return False
    global _price_cache
    _price_cache = None   # 使生效价格缓存失效, 下次读取重新合并
    return True


def effective_prices():
    # 当前生效价格 = 内置 DEFAULT_PRICES 被(可选的)持久化覆盖合并:
    # 文件中出现的模型覆盖内置; 其余保持内置。返回一个新 dict, 不改动全局。
    # 结果按模块级缓存保存(避免每次估算都读盘), save_prices 后失效。
    global _price_cache
    if _price_cache is not None:
        return _price_cache
    out = {}
    for name, spec in DEFAULT_PRICES.items():
        out[name] = dict(spec)
    for name, spec in load_prices().items():
        out[name] = spec
    _price_cache = out
    return _price_cache


def subscription_cost(prices=None):
    # 汇总所有订阅(token-plan)模型的月费/年费合计, 返回 (monthly_total, yearly_total)。
    # 供用量页信息条展示"订阅费合计"; prices 缺省用 effective_prices()。
    p = effective_prices() if prices is None else prices
    m = y = 0.0
    for spec in p.values():
        if isinstance(spec, dict) and spec.get("billing") == BILLING_PLAN:
            m += _norm_fee(spec.get("monthly"), DEFAULT_MONTHLY)
            y += _norm_fee(spec.get("yearly"), DEFAULT_YEARLY)
    return m, y

def is_peak_hour(now=None):
    # 高峰时段: 北京时间周一至五 9:00-12:00, 14:00-18:00
    now = now or datetime.datetime.now()
    if now.weekday() >= 5:
        return False
    h = now.hour
    return (9 <= h < 12) or (14 <= h < 18)


def estimate_cost(model, input_tokens, output_tokens, cache_tokens, prices=None):
    # 估算费用(元): 按缓存命中/未命中 + 高峰/空闲区分。
    # prices 默认取 effective_prices()(内置 + 持久化覆盖); token-plan(订阅)模型不走按量 -> None。
    p = (effective_prices() if prices is None else prices).get(model)
    if not p:
        return None
    if p.get("billing") == BILLING_PLAN:
        return None
    peak = 1 if is_peak_hour() else 0
    miss = max(0, input_tokens - (cache_tokens or 0))
    return (miss / 1000000.0 * p["in_miss"][peak]
            + (cache_tokens or 0) / 1000000.0 * p["in_cached"][peak]
            + output_tokens / 1000000.0 * p["out"][peak])


def usage_source_mtime():
    # 用量统计数据源时间戳(秒): 所有 session.jsonl.zstd 的最新 mtime。
    # 用作"数据是否变化"的比对基准: 源 mtime 晚于缓存抓取时间即视为有新数据需重扫。
    base = sessions_dir()
    latest = 0
    if os.path.isdir(base):
        for g in os.listdir(base):
            gp = os.path.join(base, g)
            if not os.path.isdir(gp):
                continue
            for sd in os.listdir(gp):
                f = os.path.join(gp, sd, "session.jsonl.zstd")
                try:
                    mt = os.path.getmtime(f)
                    if mt > latest:
                        latest = mt
                except OSError:
                    continue
    return latest


# ── 备份 ──────────────────────────────────────────────
def backup_dsh_home(out_zip):
    # 备份 ~/.dsh 到 zip, 排除凭据/密钥类文件。返回文件数。
    home = dsh_home()
    count = 0
    skip_names = (".credentials.yaml", ".anonymous-user-id")
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, dirs, files in os.walk(home):
            dirs[:] = [d for d in dirs if d not in ("node_modules", "sessions")]
            for fn in files:
                low = fn.lower()
                if any(s in low for s in ("credential", "secret", "key", ".env", "token")):
                    continue
                if fn in skip_names:
                    continue
                fp = os.path.join(dirpath, fn)
                try:
                    z.write(fp, os.path.relpath(fp, home))
                    count += 1
                except OSError:
                    continue
    return count

# ── Agent 模式 ────────────────────────────────────────
def list_agent_presets(remote=None):
    # .agent-presets/<name>/preset.yml
    _r = remote if remote is not None else DshRemote(None)
    out = []
    try:
        dirs = _r.list_dir(".agent-presets")
    except OSError:
        return out
    for d in sorted(dirs):
        info = {"name": d, "desc": "", "files": 0}
        try:
            pdata = parse_yaml_text(_r.read_file(".agent-presets/" + d + "/preset.yml"))
            if isinstance(pdata, dict):
                info["desc"] = str(pdata.get("description") or pdata.get("desc") or "")
        except (OSError, ValueError):
            pass
        try:
            info["files"] = len(_r.list_dir(".agent-presets/" + d))
        except OSError:
            pass
        out.append(info)
    return out

def _config_path():
    # config.json 路径: 优先级 DSH_AIO_CONFIG(测试隔离用) > frozen(exe)exe 目录 > 源码 __file__ 目录。
    # 与主程序 dsh-console-aio.py 的 BASE_DIR / DSH_AIO_CONFIG 逻辑保持一致。
    override = os.environ.get('DSH_AIO_CONFIG')
    if override:
        return override
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, 'config.json')


def load_deployments():
    # 部署清单: config.json 的 deployments 数组(gitignored, 含主机信息)
    p = _config_path()
    try:
        with io.open(p, encoding='utf-8', errors='replace') as fh:
            d = json.load(fh)
        depl = d.get('deployments') or []
        return [x for x in depl if isinstance(x, dict)]
    except (OSError, ValueError):
        return []


def save_deployments(deployments):
    # 写回 config.json 的 deployments(保留其他字段, 写前备份)
    p = _config_path()
    backup_file(p)
    try:
        with io.open(p, encoding='utf-8', errors='replace') as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        d = {}
    d['deployments'] = deployments
    with io.open(p, 'w', encoding='utf-8', newline='') as fh:
        json.dump(d, fh, ensure_ascii=False, indent=2)
    return p


# ── 多部署远程抽象 ────────────────────────────────────
# DshRemote: 统一"本机/远程部署"数据访问。本机=直接文件系统; 远程=ssh 只读命令+文件拉取。
# 部署清单在 config.json 的 deployments(见 docs/ARCHITECTURE.md 第 5 节)。

def _ssh_base(host, user, port):
    # 组装 ssh 前缀(免密, 静默, 超时)
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
            "-p", str(port), user + "@" + host]


def _ssh_run(cmd_list, timeout=15):
    # 执行远程命令, 返回 stdout(utf-8, errors=replace); 失败抛异常
    import subprocess
    r = subprocess.run(cmd_list, capture_output=True, text=True, errors="replace",
                       timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)
    if r.returncode != 0:
        raise OSError((r.stderr or "").strip() or ("ssh 退出码 %d" % r.returncode))
    return r.stdout


class DshRemote:
    # deployment: None=本机; 否则 {"name","host","user","port","dsh_home"}
    def __init__(self, deployment=None):
        self.deployment = deployment
        self.is_remote = bool(deployment and deployment.get("host"))

    def _home(self):
        # 远程 dsh_home 默认 ~/.dsh
        if self.is_remote:
            return self.deployment.get("dsh_home") or "~/.dsh"
        return dsh_home()

    def read_file(self, rel_path):
        # 读取 dsh_home 下的相对文件(文本)
        if self.is_remote:
            return _ssh_run(_ssh_base(self.deployment["host"], self.deployment["user"],
                                      self.deployment.get("port") or 22) +
                            ["cat", self._home() + "/" + rel_path])
        with io.open(os.path.join(self._home(), rel_path), encoding="utf-8",
                     errors="replace") as fh:
            return fh.read()

    def list_dir(self, rel_path):
        # 列出目录项名
        if self.is_remote:
            out = _ssh_run(_ssh_base(self.deployment["host"], self.deployment["user"],
                                     self.deployment.get("port") or 22) +
                           ["ls", "-1", self._home() + "/" + rel_path])
            return [l for l in out.splitlines() if l.strip()]
        p = os.path.join(self._home(), rel_path)
        if not os.path.isdir(p):
            return []
        return sorted(os.listdir(p))

    def dir_stats(self, rel_path):
        # 返回 {dirs: {name: bytes}, total: bytes} 用于会话/目录大小统计
        if self.is_remote:
            out = _ssh_run(_ssh_base(self.deployment["host"], self.deployment["user"],
                                     self.deployment.get("port") or 22) +
                           ["bash", "-lc",
                            "du -sb " + self._home() + "/" + rel_path + "/* 2>/dev/null | tail -200"])
            res = {}
            total = 0
            for line in out.splitlines():
                parts = line.split("\t")
                if len(parts) == 2:
                    try:
                        b = int(parts[0])
                    except ValueError:
                        continue
                    name = parts[1].rstrip("/").split("/")[-1]
                    res[name] = b
                    total += b
            return {"dirs": res, "total": total}
        base = os.path.join(self._home(), rel_path)
        res = {}
        total = 0
        if os.path.isdir(base):
            for d in os.listdir(base):
                dp = os.path.join(base, d)
                if os.path.isdir(dp):
                    b = _tree_size(dp)
                    res[d] = b
                    total += b
        return {"dirs": res, "total": total}

    def exec(self, cmd):
        # 执行任意命令(本地 subprocess / 远程 ssh), 返回 stdout
        if self.is_remote:
            return _ssh_run(_ssh_base(self.deployment["host"], self.deployment["user"],
                                      self.deployment.get("port") or 22) + [cmd])
        import subprocess
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                           timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
        if r.returncode != 0:
            raise OSError((r.stderr or "").strip() or ("退出码 %d" % r.returncode))
        return r.stdout


def _tree_size(root, max_depth=4):
    # 有界递归目录大小(字节)。会话目录是 组/会话/文件 三层, 旧实现只数直接文件恒为 0;
    # 限深防符号链接环与大目录失控。
    total = 0
    stack = [(root, 0)]
    while stack:
        cur, lvl = stack.pop()
        try:
            for name in os.listdir(cur):
                p = os.path.join(cur, name)
                if os.path.isdir(p):
                    if lvl < max_depth:
                        stack.append((p, lvl + 1))
                else:
                    try:
                        total += os.path.getsize(p)
                    except OSError:
                        pass
        except OSError:
            pass
    return total


def deployment_snapshot(remote):
    # 单部署只读状态总览(轻量指标, 不用远程解压)
    snap = {"ok": False, "error": None, "name": None, "version": None,
            "web_ok": False, "sessions": 0, "session_bytes": 0,
            "plugins": 0, "profiles": 0, "presets": 0}
    try:
        if remote.deployment:
            snap["name"] = remote.deployment.get("name") or remote.deployment.get("host")
        # profile 目录(含 dsh 版本线索)
        try:
            profiles = remote.list_dir("profiles")
        except OSError:
            profiles = []
        snap["profiles"] = len([p for p in profiles if p != "node_modules"])
        # web profile 的 package.json -> 读 dsh 相关版本
        try:
            if "web" in profiles:
                pkg = remote.read_file("profiles/web/package.json")
                import json as _json
                try:
                    d = _json.loads(pkg)
                    deps = d.get("dependencies") or {}
                    snap["version"] = deps.get("dsh") or deps.get("dshmarket") or "?"
                except ValueError:
                    pass
        except OSError:
            pass
        # 会话统计
        try:
            st = remote.dir_stats("sessions")
            snap["sessions"] = len(st["dirs"])
            snap["session_bytes"] = st["total"]
        except OSError:
            pass
        # 插件数: web profile bundles
        try:
            pkg = remote.read_file("profiles/web/package.json")
            import json as _json
            d = _json.loads(pkg)
            prof = d.get("dsh", {}).get("profile", {})
            snap["plugins"] = len(prof.get("bundles") or [])
        except (OSError, ValueError):
            pass
        # agent presets
        try:
            snap["presets"] = len(remote.list_dir(".agent-presets"))
        except OSError:
            pass
        snap["ok"] = True
    except Exception as e:
        snap["error"] = str(e)
    return snap
