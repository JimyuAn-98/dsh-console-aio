# -*- coding: utf-8 -*-
# test_dsh_core_version.py - dsh_core/version.py 纯单元测试(零 Qt, 零真实网络/进程)。
#
# 安全边界: 不构造任何 Qt 对象; check_latest 经 monkeypatch 拦截 fetch(绝不联网);
# download_and_apply 拦截 urlretrieve/ZipFile/subprocess.run(绝不真下载/真替换/
# 真起子进程), TEMP 重定向到工作区临时目录; spawn_restart 拦截 Popen, 绝不真起进程。
# 覆盖: cmp_ver 边界 / 常量与更新源契约 / 替换脚本内容(进程内 exec 真文件操作) /
# check_latest 成功与失败 / download_and_apply 编排与失败分支 / spawn_restart 分支。

import io
import json
import os
import sys
import types

import pytest

import dsh_core.version as vmod
from dsh_core.version import check_latest, cmp_ver, download_and_apply, spawn_restart


class TestCmpVerEdges:
    # cmp_ver 边界: 多位数/位数不等长/前缀关系, 均按整数逐段比较而非字典序。
    def test_two_digits_not_lexicographic(self):
        assert cmp_ver("1.10.0", "1.9.0") == 1
        assert cmp_ver("1.9.0", "1.10.0") == -1

    def test_shorter_vs_longer_prefix(self):
        # (1,0) < (1,0,0): 缺段视为更小
        assert cmp_ver("0.5", "0.5.0") == -1
        assert cmp_ver("1.0", "1.0.0") == -1

    def test_extra_segment(self):
        assert cmp_ver("1.0.0.1", "1.0.0") == 1

    def test_single_segment(self):
        assert cmp_ver("2", "10") == -1
        assert cmp_ver("10", "2") == 1

    def test_invalid_against_valid(self):
        # 非数字串按 (0,), 一定小于任何 >=1 的首段
        assert cmp_ver("abc", "1.0.0") == -1
        assert cmp_ver("1.0.0", "abc") == 1

    def test_non_string_input(self):
        # int 版本号也允许(契约: str(v) 后比较)
        assert cmp_ver(1, "0.9") == 1

    def test_symmetric_zero(self):
        assert cmp_ver("2.3.4", "2.3.4") == 0


class TestConstants:
    # 常量契约: 保留清单与更新源 URL(与页面/主程序同一套来源)。
    def test_keep_files_covers_user_data(self):
        assert {"config.json", "dsh使用指南.txt", "tunnel-pids.json"} <= vmod.KEEP_FILES

    def test_version_url_derived_from_raw(self):
        assert vmod.VERSION_URL == vmod.GITHUB_RAW + "version.json"
        assert vmod.VERSION_URL.endswith("version.json")

    def test_zip_url_is_codeload_https(self):
        assert vmod.GITHUB_ZIP.startswith("https://")

    def test_replace_code_is_ascii_and_compilable(self):
        # 脚本经 python -c 子进程执行, 必须纯 ASCII 且语法可编译(keep 清单经 argv 传入)
        code = vmod._REPLACE_CODE.encode("ascii")   # 非 ASCII 会抛 UnicodeEncodeError
        compile(code, "<replace-code>", "exec")


class TestReplaceScript:
    # 替换脚本内容: 进程内 exec 真文件操作, 验证 备份/替换/保留/.git 跳过 四个契约。
    def _run_replace(self, tmp_path, src_files, base_files):
        src = tmp_path / "src"
        base = tmp_path / "base"
        bak = tmp_path / "bak"
        src.mkdir()
        base.mkdir()
        for name, content in src_files.items():
            p = src / name
            if content is None:      # None 表示目录(如 .git)
                p.mkdir()
                continue
            p.write_text(content, encoding="utf-8")
        for name, content in base_files.items():
            (base / name).write_text(content, encoding="utf-8")
        argv = [sys.executable, str(src), str(base), str(bak),
                json.dumps(sorted(vmod.KEEP_FILES))]
        old_argv = sys.argv
        sys.argv = argv
        try:
            code = compile(vmod._REPLACE_CODE, "<replace-code>", "exec")
            exec(code, {"__name__": "replace_subproc"})   # 脚本自带 import
        finally:
            sys.argv = old_argv
        return src, base, bak

    def test_replace_backups_and_skips_keep_and_git(self, tmp_path, capsys):
        src, base, bak = self._run_replace(
            tmp_path,
            {"a.py": "new", "b.txt": "nb", "config.json": "{}", ".git": None},
            {"a.py": "old"})
        # 替换: 新文件落位
        assert (base / "a.py").read_text(encoding="utf-8") == "new"
        assert (base / "b.txt").read_text(encoding="utf-8") == "nb"
        # 备份: base 里的旧文件先复制进 bak
        assert (bak / "a.py").read_text(encoding="utf-8") == "old"
        # 保留: KEEP_FILES 不动
        assert not (base / "config.json").exists()
        assert not (bak / "config.json").exists()
        # 跳过: .git 不进 base
        assert not (base / ".git").exists()
        # 输出: replaced 计数为 2(a.py + b.txt)
        assert capsys.readouterr().out.strip() == "2"

    def test_replace_new_file_without_backup(self, tmp_path, capsys):
        # base 里不存在的文件直接落位, 不产生备份
        src, base, bak = self._run_replace(
            tmp_path, {"only_new.py": "v"}, {})
        assert (base / "only_new.py").read_text(encoding="utf-8") == "v"
        assert bak.exists()          # 脚本开头 makedirs(bak)
        assert not any(bak.iterdir())
        assert capsys.readouterr().out.strip() == "1"


class TestCheckLatest:
    # check_latest: monkeypatch 拦截 fetch, 绝不真联网。
    def test_ok(self, monkeypatch):
        seen = {}

        def fake_fetch(url, timeout=15):
            seen["url"] = url
            return json.dumps({"version": "1.2.3", "notes": "n"})

        monkeypatch.setattr(vmod, "fetch", fake_fetch)
        r = check_latest(None)
        assert r == {"latest": "1.2.3", "notes": "n", "err": ""}
        assert seen["url"] == vmod.VERSION_URL

    def test_missing_fields_become_empty(self, monkeypatch):
        monkeypatch.setattr(vmod, "fetch", lambda url, timeout=15: "{}")
        r = check_latest(None)
        assert r["err"] == ""
        assert r["latest"] == ""
        assert r["notes"] == ""

    def test_network_error_returns_chinese_err(self, monkeypatch):
        def boom(url, timeout=15):
            raise OSError("connection refused")

        monkeypatch.setattr(vmod, "fetch", boom)
        r = check_latest(None)
        assert r["latest"] == ""
        assert "更新源" in r["err"] and "connection refused" in r["err"]

    def test_events_receive_status(self, monkeypatch):
        monkeypatch.setattr(vmod, "fetch", lambda url, timeout=15: "{}")
        seen = []
        r = check_latest(lambda kind, payload: seen.append((kind, payload)))
        assert r["err"] == ""
        assert ("status", "正在连接更新源…") in seen


class TestDownloadAndApply:
    # download_and_apply 步骤编排: 拦截 urlretrieve/ZipFile/subprocess.run, 不真下载。
    class _FakeZip:
        # 假 zip: 模拟 GitHub zip 的顶层目录 dsh-console-aio-main/ 与一个待替换文件
        def __init__(self, path):
            self.path = path

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extractall(self, dest):
            root = os.path.join(dest, "dsh-console-aio-main")
            os.makedirs(root, exist_ok=True)
            with io.open(os.path.join(root, "dsh-console-aio.py"), "w",
                         encoding="utf-8") as f:
                f.write("# new")

    def _patch_io(self, monkeypatch, tmp_path, rc=0, out="3", err=""):
        # 返回 calls 字典记录 urlretrieve 的 url 与 subprocess.run 的 cmd
        calls = {}

        def fake_retrieve(url, path):
            calls["url"] = url
            with io.open(path, "wb") as f:
                f.write(b"zip")
            return path, None

        def fake_run(cmd, **kw):
            calls["cmd"] = cmd
            calls["kw"] = kw
            return types.SimpleNamespace(returncode=rc, stdout=out, stderr=err)

        monkeypatch.setattr(vmod.urllib.request, "urlretrieve", fake_retrieve)
        monkeypatch.setattr(vmod.zipfile, "ZipFile", self._FakeZip)
        monkeypatch.setattr(vmod.subprocess, "run", fake_run)
        # TEMP 重定向到工作区临时目录, 不触碰系统 Temp
        monkeypatch.setenv("TEMP", str(tmp_path))
        return calls

    def test_happy_path_orchestration(self, monkeypatch, tmp_path):
        calls = self._patch_io(monkeypatch, tmp_path)
        seen = []
        base = str(tmp_path / "base")
        r = download_and_apply(lambda k, p: seen.append((k, p)), base)
        assert r["err"] == ""
        assert "3 个文件" in r["msg"]
        assert r["replaced"] == "3"
        assert r["backup"] == os.path.join(str(tmp_path), "dsh-aio-update", "backup")
        # 编排: 下载源是 GITHUB_ZIP; 替换子进程是 python -c 脚本 + src/base/bak/keep argv
        assert calls["url"] == vmod.GITHUB_ZIP
        cmd = calls["cmd"]
        assert cmd[0] == sys.executable and cmd[1] == "-c"
        assert cmd[2] == vmod._REPLACE_CODE
        src, b, bak, keep_json = cmd[3], cmd[4], cmd[5], cmd[6]
        assert src == os.path.join(str(tmp_path), "dsh-aio-update", "x",
                                   "dsh-console-aio-main")
        assert b == base
        assert bak == r["backup"]
        assert json.loads(keep_json) == sorted(vmod.KEEP_FILES)
        # 安全细节: 子进程超时 + 不弹黑窗
        assert calls["kw"]["timeout"] == 300
        assert calls["kw"]["creationflags"] == vmod.subprocess.CREATE_NO_WINDOW
        # 进度经 events 上报(下载/解压/替换三个 status)
        kinds = [k for k, _ in seen]
        assert kinds.count("status") == 3

    def test_replace_failure_returns_chinese_err(self, monkeypatch, tmp_path):
        calls = self._patch_io(monkeypatch, tmp_path, rc=1,
                               out="", err="Traceback: disk full")
        r = download_and_apply(None, str(tmp_path / "base"))
        assert r["msg"] == ""
        assert r["err"].startswith("替换程序文件失败")
        assert "disk full" in r["err"]

    def test_replace_failure_without_stderr_shows_rc(self, monkeypatch, tmp_path):
        self._patch_io(monkeypatch, tmp_path, rc=2, out="", err="")
        r = download_and_apply(None, str(tmp_path / "base"))
        assert "退出码 2" in r["err"]

    def test_download_error_returns_chinese_err(self, monkeypatch, tmp_path):
        def boom(url, path):
            raise OSError("http 502")

        monkeypatch.setattr(vmod.urllib.request, "urlretrieve", boom)
        monkeypatch.setattr(vmod.zipfile, "ZipFile", self._FakeZip)
        monkeypatch.setattr(vmod.subprocess, "run",
                            lambda cmd, **kw: pytest.fail("不应执行替换子进程"))
        monkeypatch.setenv("TEMP", str(tmp_path))
        r = download_and_apply(None, str(tmp_path / "base"))
        assert r["msg"] == ""
        assert r["err"].startswith("更新失败")
        assert "http 502" in r["err"]


class TestSpawnRestart:
    # spawn_restart: 拦截 Popen, 不真起进程; 验证 bug 修复(源码入口 = dsh-console-aio.py)。
    def test_source_mode_uses_real_entry(self, monkeypatch, tmp_path):
        spawned = {}

        def fake_popen(cmd, **kw):
            spawned["cmd"] = cmd
            spawned["kw"] = kw
            return object()

        monkeypatch.setattr(vmod.subprocess, "Popen", fake_popen)
        # 源码模式入口存在性检查是真文件检查: 先在临时目录造出 dsh-console-aio.py
        (tmp_path / "dsh-console-aio.py").write_text("# entry", encoding="utf-8")
        r = spawn_restart(str(tmp_path))
        assert r["err"] == ""
        # 旧页面写死 app_pyside.py(不存在, FileNotFoundError 被吞) —— 现必须指向真实入口
        assert spawned["cmd"] == [sys.executable,
                                  os.path.join(str(tmp_path), "dsh-console-aio.py")]
        assert spawned["kw"]["cwd"] == str(tmp_path)
        assert spawned["kw"]["creationflags"] == vmod.subprocess.CREATE_NO_WINDOW

    def test_source_mode_missing_entry_reports_err(self, tmp_path):
        # 入口不存在必须报中文错误(不静默、不 Popen): tmp 目录里没有 dsh-console-aio.py
        r = spawn_restart(str(tmp_path))
        assert "找不到主程序入口" in r["err"]
        assert "dsh-console-aio.py" in r["err"]

    def test_frozen_mode_restarts_executable(self, monkeypatch, tmp_path):
        spawned = {}

        def fake_popen(cmd, **kw):
            spawned["cmd"] = cmd
            return object()

        monkeypatch.setattr(vmod.subprocess, "Popen", fake_popen)
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        r = spawn_restart(str(tmp_path))
        assert r["err"] == ""
        # frozen 直接重启 exe 本体, 不带脚本参数
        assert spawned["cmd"] == [sys.executable]

    def test_popen_error_returns_chinese_err(self, monkeypatch, tmp_path):
        def boom(cmd, **kw):
            raise OSError("spawn denied")

        monkeypatch.setattr(vmod.subprocess, "Popen", boom)
        (tmp_path / "dsh-console-aio.py").write_text("# entry", encoding="utf-8")
        r = spawn_restart(str(tmp_path))
        assert "启动新进程失败" in r["err"] and "spawn denied" in r["err"]


class TestReadLocalNotes:
    # read_local_notes: 资源目录定位真实文件; 缺失时返回占位文案(不抛异常)。
    def test_missing_notes_degrades(self, monkeypatch, tmp_path):
        monkeypatch.setattr(vmod, "resource_dir", lambda: str(tmp_path))
        assert vmod.read_local_notes() == "(未找到 RELEASE_NOTES.md)"

    def test_reads_repo_release_notes(self):
        # 源码模式下资源目录即仓库根, RELEASE_NOTES.md 必然存在
        text = vmod.read_local_notes()
        assert "(未找到" not in text
        assert len(text) > 0


# 防御: 确认 core 模块没有任何 PySide import(红线; 注释里的字样不算)
def test_core_module_has_no_pyside_import():
    src = io.open(vmod.__file__, encoding="utf-8").read()
    for ln in src.splitlines():
        s = ln.strip()
        assert not s.startswith(("import PySide", "from PySide")), s
