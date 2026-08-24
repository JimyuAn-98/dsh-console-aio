# -*- coding: utf-8 -*-
# dsh_data.py — dsh 数据层: 读取/写入 ~/.dsh 各数据域, 零依赖(仅 stdlib)。
# 纯函数、无 tkinter 依赖; 写入函数一律先 .bak 备份。
# 接口文档见 docs/ARCHITECTURE.md。

import os
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
                    break
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

def read_yaml(path):
    # 解析 YAML 文件; 不存在返回 None
    if not os.path.isfile(path):
        return None
    with io.open(path, encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    lines = [_strip_comment(l).rstrip() for l in raw.splitlines()]
    lines = [l for l in lines if l.strip() != ""]
    if not lines:
        return {}
    val, _ = _parse_yaml_block(lines, 0, 0)
    return val if val is not None else {}

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
    body = "\n".join(_dump_yaml(data)) + "\n"
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(body)
    return path

# ── 会话 / 工作区 ─────────────────────────────────────
def read_workspace():
    # workspace.json -> {workspaceIds: [], archivedSessionIds: []}
    p = os.path.join(dsh_home(), "storages", "workspace.json")
    try:
        with io.open(p, encoding="utf-8", errors="replace") as fh:
            d = json.load(fh)
        return d.get("global", {})
    except (OSError, ValueError):
        return {}

def list_sessions():
    # 按工作目录分组: [{workdir, count, bytes, sessions:[{name,size,mtime}]}]
    base = sessions_dir()
    groups = []
    if not os.path.isdir(base):
        return groups
    for d in sorted(os.listdir(base)):
        dp = os.path.join(base, d)
        if not os.path.isdir(dp):
            continue
        items = []
        total = 0
        for sd in sorted(os.listdir(dp)):
            sdp = os.path.join(dp, sd)
            if os.path.isdir(sdp):
                size = 0
                for fn in os.listdir(sdp):
                    fp = os.path.join(sdp, fn)
                    if os.path.isfile(fp):
                        size += os.path.getsize(fp)
                total += size
                items.append({"name": sd, "bytes": size,
                              "mtime": os.path.getmtime(sdp)})
        groups.append({"workdir": d, "count": len(items), "bytes": total, "sessions": items})
    return groups

# ── Profile / 插件 ────────────────────────────────────
def list_profiles():
    # 返回 [{name, cordis(bool), patch(bool), pkg(bool)}]
    base = profiles_dir()
    out = []
    if not os.path.isdir(base):
        return out
    for d in sorted(os.listdir(base)):
        dp = os.path.join(base, d)
        if os.path.isdir(dp):
            out.append({
                "name": d,
                "cordis": os.path.isfile(os.path.join(dp, "cordis.yml")),
                "patch": os.path.isfile(os.path.join(dp, "cordis.patch.yml")),
                "pkg": os.path.isfile(os.path.join(dp, "package.json")),
            })
    return out

def read_cordis(profile):
    # 解析 profile 的 cordis.yml(或 patch), 返回 entries list
    base = os.path.join(profiles_dir(), profile)
    d = read_yaml(os.path.join(base, "cordis.yml")) or {}
    if isinstance(d, dict):
        d = []
    return d if isinstance(d, list) else []

def read_cordis_patch(profile):
    base = os.path.join(profiles_dir(), profile)
    d = read_yaml(os.path.join(base, "cordis.patch.yml")) or {}
    if isinstance(d, dict):
        d = []
    return d if isinstance(d, list) else []

def write_cordis_patch(profile, entries):
    # 备份后写回 cordis.patch.yml
    base = os.path.join(profiles_dir(), profile)
    p = os.path.join(base, "cordis.patch.yml")
    return write_yaml(p, entries)

def plugin_cmd(profile, *args):
    # 组装 dsh plugin --profile X ... 命令(由 UI 层经 _stream_cmd 执行)
    return ["dsh", "plugin", "--profile", profile] + list(args)

def read_profile_package(profile):
    # 读 profile/package.json: 返回 {dependencies: {...}, bundles: [...]}
    base = os.path.join(profiles_dir(), profile)
    p = os.path.join(base, 'package.json')
    try:
        with io.open(p, encoding='utf-8', errors='replace') as fh:
            d = json.load(fh)
        dsh = d.get('dsh') or {}
        prof = dsh.get('profile') or {}
        return {
            'dependencies': d.get('dependencies') or {},
            'bundles': prof.get('bundles') or [],
        }
    except (OSError, ValueError):
        return {'dependencies': {}, 'bundles': []}


# ── settings.yaml ─────────────────────────────────────
def read_settings():
    return read_yaml(os.path.join(dsh_home(), "settings.yaml")) or {}

def write_settings(data):
    return write_yaml(os.path.join(dsh_home(), "settings.yaml"), data)

# ── 任务看板 ──────────────────────────────────────────
def read_taskboard():
    # 返回 {ledger: {...}, scheduler: {...}}; 文件缺失返回空 dict
    out = {}
    for key, fn in (("ledger", "ledger-v2.json"), ("scheduler", "scheduler-v2.json")):
        p = os.path.join(dsh_home(), "task-board", fn)
        try:
            with io.open(p, encoding="utf-8", errors="replace") as fh:
                out[key] = json.load(fh)
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

def usage_stats():
    # 解压全部 session jsonl.zstd, 聚合 token 用量。
    # 返回 {ok: bool, error?: str, models: {model: {provider, input, output, calls}},
    #        days: {date: {input, output}}, sessions: n}
    if not zstd_available():
        return {"ok": False, "error": "缺少 zstandard 库(pip install zstandard)"}
    import zstandard as zstd
    base = sessions_dir()
    models = {}
    days = {}
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
                                    m = cur_model or "unknown"
                                    mm = models.setdefault(m, {"provider": cur_provider, "input": 0, "output": 0, "calls": 0})
                                    mm["input"] += i
                                    mm["output"] += o
                                    mm["calls"] += 1
                                    ts = obj.get("time") or 0
                                    date = datetime.datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d") if ts else "?"
                                    dd = days.setdefault(date, {"input": 0, "output": 0})
                                    dd["input"] += i
                                    dd["output"] += o
            except (OSError, ValueError):
                continue
    return {"ok": True, "models": models, "days": days, "sessions": nsessions}

# 内置估算单价(元/百万 token), UI 可编辑覆盖
DEFAULT_PRICES = {
    "deepseek-v4-flash": {"input": 2.0, "output": 8.0},
    "deepseek-chat": {"input": 2.0, "output": 8.0},
    "deepseek-reasoner": {"input": 4.0, "output": 16.0},
}

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
def list_agent_presets():
    # .agent-presets/<name>/preset.yml
    base = os.path.join(dsh_home(), ".agent-presets")
    out = []
    if not os.path.isdir(base):
        return out
    for d in sorted(os.listdir(base)):
        dp = os.path.join(base, d)
        if os.path.isdir(dp):
            info = {"name": d, "desc": "", "files": 0}
            pp = os.path.join(dp, "preset.yml")
            if os.path.isfile(pp):
                try:
                    pdata = read_yaml(pp)
                    if isinstance(pdata, dict):
                        info["desc"] = str(pdata.get("description") or pdata.get("desc") or "")
                except Exception:
                    pass
            info["files"] = len([f for f in os.listdir(dp) if os.path.isfile(os.path.join(dp, f))])
            out.append(info)
    return out
