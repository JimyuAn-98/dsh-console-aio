# -*- coding: utf-8 -*-
# test_core_env.py - core/env.py 纯单元测试(零 Qt)。
#
# 安全边界: 子进程(shutil.which/subprocess.run)与 config 读写全部 monkeypatch,
# 绝不真跑 git/pnpm/ssh, 绝不写真实 config.json。

import json
import os

import pytest

from core import config as dsh_config
from core import env as env_mod


class TestGetVersion:
    def test_returns_first_line(self, monkeypatch):
        class R:
            stdout = "git version 2.53.0\nmore"
            stderr = ""
            returncode = 0

        monkeypatch.setattr(env_mod.subprocess, "run", lambda *a, **k: R())
        assert env_mod.get_version(["git", "--version"]) == "git version 2.53.0"

    def test_missing_command_returns_none(self, monkeypatch):
        def boom(*a, **k):
            raise FileNotFoundError("not found")

        monkeypatch.setattr(env_mod.subprocess, "run", boom)
        assert env_mod.get_version(["nope", "--version"]) is None


class TestToolVersions:
    def test_maps_by_key_and_survives_missing(self, monkeypatch):
        monkeypatch.setattr(env_mod, "get_version",
                            lambda cmd, timeout=8: "v1" if cmd[0] == "git" else None)
        res = env_mod.tool_versions([("git", "Git", ["git", "--version"]),
                                     ("pnpm", "pnpm", ["pnpm.cmd", "--version"])])
        assert res == {"git": "v1", "pnpm": None}


class TestMissingTools:
    def test_missing_and_present(self, monkeypatch):
        monkeypatch.setattr(env_mod.shutil, "which",
                            lambda t: "/x" if t in ("git", "node") else None)
        assert env_mod.missing_tools() == ["npm", "pnpm"]


class TestPnpmEnv:
    def test_injects_localappdata_pnpm_bin(self, monkeypatch):
        monkeypatch.setenv("LOCALAPPDATA", "C:/Users/x/AppData/Local")
        monkeypatch.setenv("PATH", "C:/Windows")
        env = env_mod.pnpm_env()
        expect = os.path.join(os.environ["LOCALAPPDATA"], "pnpm", "bin")
        assert expect in env["PATH"]

    def test_no_duplicate_when_already_present(self, monkeypatch):
        binp = os.path.join("C:/Users/x/AppData/Local", "pnpm", "bin")
        monkeypatch.setenv("LOCALAPPDATA", "C:/Users/x/AppData/Local")
        monkeypatch.setenv("PATH", binp)
        assert env_mod.pnpm_env()["PATH"] == binp


class TestRunCapture:
    def test_ok_tail(self, monkeypatch):
        class R:
            stdout = "out line"
            stderr = "err line"
            returncode = 0

        monkeypatch.setattr(env_mod.subprocess, "run", lambda *a, **k: R())
        ok, tail = env_mod.run_capture(["whatever"])
        assert ok is True and "out line" in tail and "err line" in tail

    def test_failure_returns_false(self, monkeypatch):
        def boom(*a, **k):
            raise OSError("nope")

        monkeypatch.setattr(env_mod.subprocess, "run", boom)
        ok, tail = env_mod.run_capture(["whatever"])
        assert ok is False and "nope" in tail


class TestTestSsh:
    def test_empty_input_refused(self):
        r = env_mod.test_ssh("", "")
        assert r["ok"] is False and "请先填" in r["detail"]

    def test_ok_and_failure(self, monkeypatch):
        calls = {}

        class R:
            def __init__(self, rc):
                self.returncode = rc
                self.stdout = ""
                self.stderr = "Permission denied (publickey)." if rc else ""

        def fake_run(cmd, **k):
            calls["cmd"] = cmd
            return R(0 if any("ok-host" in str(x) for x in cmd) else 255)

        monkeypatch.setattr(env_mod.shutil, "which", lambda t: "C:/Windows/System32/OpenSSH/ssh.exe")
        monkeypatch.setattr(env_mod.subprocess, "run", fake_run)
        ok = env_mod.test_ssh("ok-host", "me", "22")
        assert ok["ok"] is True and ok["detail"] == ""
        assert any("me@ok-host" == x for x in calls["cmd"]) and "-p" in calls["cmd"]
        bad = env_mod.test_ssh("bad-host", "me", "22")
        assert bad["ok"] is False and "Permission denied" in bad["detail"]

    def test_ssh_missing_from_path(self, monkeypatch):
        monkeypatch.setattr(env_mod.shutil, "which", lambda t: None)
        r = env_mod.test_ssh("h", "u")
        assert r["ok"] is False and "ssh 不在 PATH" in r["detail"]


class TestInstallDsh:
    def _ctl_ok(self, monkeypatch, fail_step=None):
        # 拦截 DshCtl.stream_cmd: 记录 (cmd, cwd), fail_step 命中时返回 False
        calls = []

        def fake_stream(self, cmd, cwd=None, env=None, events=None, timeout_override=None):
            calls.append((tuple(cmd), cwd))
            if fail_step and tuple(cmd) == tuple(fail_step):
                if events:
                    events("log", ("[stream] 命令失败 (exit 1)", "err"))
                return False
            return True

        monkeypatch.setattr(env_mod.DshCtl, "stream_cmd", fake_stream)
        return calls

    def test_full_flow_writes_dash_repo(self, tmp_path, monkeypatch):
        monkeypatch.setattr(env_mod, "missing_tools", lambda tools=None: [])
        calls = self._ctl_ok(monkeypatch)
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps({"dash_port": 3080}), encoding="utf-8")
        monkeypatch.setattr(dsh_config, "load_config", lambda path=None: {"dash_port": 3080})
        monkeypatch.setattr(dsh_config, "save_config",
                            lambda cfg, path=None: cfg_path.write_text(
                                json.dumps(cfg), encoding="utf-8") or True)
        got = []
        r = env_mod.install_dsh(lambda k, p: got.append((k, p)),
                                "https://example.com/repo.git", str(tmp_path / "dsh"))
        assert r["err"] == "" and "安装完成" in r["msg"]
        # 步骤事件 1..4 齐全; 三条命令依次为 clone/install/build
        assert [p[0] for k, p in got if k == "step"] == [1, 2, 3, 4]
        cmds = [c[0] for c in calls]
        assert cmds[0][:2] == ("git", "clone")
        assert cmds[1] == ("pnpm.cmd", "install")
        assert cmds[2] == ("pnpm.cmd", "run", "build")
        # install/build 的 cwd 是目标目录
        assert calls[1][1] == calls[2][1] == str(tmp_path / "dsh")
        # dash_repo 已写入 config
        assert json.loads(cfg_path.read_text(encoding="utf-8"))["dash_repo"] == str(tmp_path / "dsh")

    def test_missing_tools_aborts_before_clone(self, tmp_path, monkeypatch):
        monkeypatch.setattr(env_mod, "missing_tools", lambda tools=None: ["pnpm"])
        calls = []
        monkeypatch.setattr(env_mod.DshCtl, "stream_cmd",
                            lambda self, cmd, **k: calls.append(cmd) or True)
        got = []
        r = env_mod.install_dsh(lambda k, p: got.append((k, p)), "https://x.git", str(tmp_path / "d"))
        assert "缺少依赖" in r["err"] and calls == []
        assert not any(k == "step" for k, p in got)

    def test_build_failure_aborts(self, tmp_path, monkeypatch):
        monkeypatch.setattr(env_mod, "missing_tools", lambda tools=None: [])
        # 除 build 外全部成功: build 命令返回 False
        monkeypatch.setattr(env_mod.DshCtl, "stream_cmd",
                            lambda self, cmd, **k: tuple(cmd) != ("pnpm.cmd", "run", "build"))
        r = env_mod.install_dsh(None, "https://x.git", str(tmp_path / "d"))
        assert "pnpm run build 失败" in r["err"]

    def test_empty_url_refused(self, tmp_path, monkeypatch):
        r = env_mod.install_dsh(None, "  ", str(tmp_path))
        assert "git 仓库地址" in r["err"]


class TestUninstallDsh:
    # 与 TestInstallDsh 同构: 子进程(停 web)/config 读写/目录删除全部隔离, 绝不真删。
    def _fake_repo(self, tmp_path, name="dsh"):
        # 造一个"假安装": 源码目录含 package.json, 数据目录(~/.dsh)含一个文件
        repo = tmp_path / name
        repo.mkdir(parents=True, exist_ok=True)
        (repo / "package.json").write_text('{"name":"dsh"}', encoding="utf-8")
        data = tmp_path / ".dsh"
        data.mkdir(parents=True, exist_ok=True)
        (data / "meta.json").write_text("{}", encoding="utf-8")
        return str(repo), str(data)

    def _patch(self, monkeypatch, tmp_path, repo, data):
        # 拦截: 停 web 空跑; config 读写走 tmp 下的假 config; DSH_HOME 指到假数据目录
        monkeypatch.setattr(env_mod.DshCtl, "stop_dsh", lambda self, events=None: True)
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps({"dash_repo": repo}), encoding="utf-8")
        monkeypatch.setattr(dsh_config, "load_config",
                            lambda path=None: json.loads(cfg_path.read_text(encoding="utf-8")))
        monkeypatch.setattr(dsh_config, "save_config",
                            lambda cfg, path=None: cfg_path.write_text(
                                json.dumps(cfg), encoding="utf-8") or True)
        monkeypatch.setenv("DSH_HOME", data)

    def test_keep_data_removes_repo_and_clears_config(self, tmp_path, monkeypatch):
        repo, data = self._fake_repo(tmp_path)
        self._patch(monkeypatch, tmp_path, repo, data)
        got = []
        r = env_mod.uninstall_dsh(lambda k, p: got.append((k, p)), keep_data=True)
        assert r["err"] == "" and r["removed_repo"] is True
        assert r["removed_data"] is False
        # 数据目录保留
        assert (tmp_path / ".dsh" / "meta.json").exists()
        # 源码目录删除 + config.dash_repo 清空
        assert not (tmp_path / "dsh").exists()
        assert json.loads((tmp_path / "config.json").read_text(
            encoding="utf-8"))["dash_repo"] == ""
        # 保留数据 = 3 步, 不出现"删数据"步骤
        assert [p[0] for k, p in got if k == "step"] == [1, 2, 3]

    def test_remove_data_also_deletes_dsh_home(self, tmp_path, monkeypatch):
        repo, data = self._fake_repo(tmp_path)
        self._patch(monkeypatch, tmp_path, repo, data)
        got = []
        r = env_mod.uninstall_dsh(lambda k, p: got.append((k, p)), keep_data=False)
        assert r["err"] == "" and r["removed_repo"] is True
        assert r["removed_data"] is True and r["data_dir"] == data
        assert not (tmp_path / "dsh").exists() and not (tmp_path / ".dsh").exists()
        assert [p[0] for k, p in got if k == "step"] == [1, 2, 3, 4]

    def test_no_repo_reports_not_installed(self, monkeypatch):
        # config 里没有 dash_repo: 不报错, 标记未删除, 提示"未检测到已安装"
        monkeypatch.setattr(env_mod.DshCtl, "stop_dsh", lambda self, events=None: True)
        monkeypatch.setattr(dsh_config, "load_config", lambda path=None: {"dash_repo": ""})
        r = env_mod.uninstall_dsh(None, keep_data=True)
        assert r["err"] == "" and r["removed_repo"] is False and r["removed_data"] is False
        assert "未检测到" in r["msg"]

    def test_rmtree_failure_returns_error(self, tmp_path, monkeypatch):
        repo, data = self._fake_repo(tmp_path)
        self._patch(monkeypatch, tmp_path, repo, data)

        def boom(p):
            raise OSError("access denied")
        monkeypatch.setattr(env_mod.shutil, "rmtree", lambda p: boom(p))
        r = env_mod.uninstall_dsh(None, keep_data=True)
        assert "删除源码目录失败" in r["err"] and r["removed_repo"] is False

    def test_data_dir_guard_no_home_deletion(self, tmp_path, monkeypatch):
        # 数据目录绝不能等于用户主目录: 即使 dsh_home() 指向主目录, 守卫也不删(防灾难)
        import os as _os
        repo = tmp_path / "repo2"
        repo.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(env_mod.DshCtl, "stop_dsh", lambda self, events=None: True)
        monkeypatch.setattr(dsh_config, "load_config", lambda path=None: {"dash_repo": str(repo)})
        monkeypatch.setenv("DSH_HOME", _os.path.expanduser("~"))   # 数据目录 == 主目录
        monkeypatch.setattr(env_mod.shutil, "rmtree", lambda p, **k: None)  # 双保险绝不真删
        r = env_mod.uninstall_dsh(None, keep_data=False)
        assert r["err"] == "" and r["removed_repo"] is True
        assert r["removed_data"] is False    # 守卫拒绝删主目录


class TestSaveConfig:
    def test_bak_and_roundtrip(self, tmp_path):
        p = tmp_path / "config.json"
        p.write_text(json.dumps({"a": 1}), encoding="utf-8")
        assert dsh_config.save_config({"a": 2, "b": "x"}, str(p)) is True
        assert json.loads(p.read_text(encoding="utf-8")) == {"a": 2, "b": "x"}
        assert json.loads((tmp_path / "config.json.bak").read_text(encoding="utf-8")) == {"a": 1}

    def test_missing_file_no_bak(self, tmp_path):
        p = tmp_path / "fresh.json"
        assert dsh_config.save_config({"k": 1}, str(p)) is True
        assert not (tmp_path / "fresh.json.bak").exists()
