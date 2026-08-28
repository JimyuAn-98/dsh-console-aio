# -*- coding: utf-8 -*-
# test_core_keys.py - core/keys.py 纯单元测试(零 Qt, 零真实 ~/.ssh, 零真实子进程)。
#
# 安全边界: 不构造 MainWindow/任何 Qt 对象; ssh-keygen 一律经 monkeypatch 拦截
# subprocess.run(绝不真跑); HOME/USERPROFILE 指向 tmp_path 伪造 ~/.ssh, 与用户真实
# 密钥目录零交集。覆盖: list_keys 公私钥分类、fingerprint 命令参数与失败占位、
# read_pubkey 只读 .pub(私钥红线)、generate_key 命令参数/重名/失败中文文案、
# payload "err" 契约与 events 日志回调。

import json
import os
import subprocess

import pytest

from core import keys as dsh_keys

SECRET = "SUPER-SECRET-PRIVATE-BODY"   # 假私钥内容: 任何输出里都不允许出现


class _R:
    # subprocess.run 返回值的假对象(只需要 returncode/stdout/stderr 三个字段)
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _fake_home(monkeypatch, tmp_path):
    # Windows 下 expanduser 只认 USERPROFILE(不认 HOME), POSIX 认 HOME, 两者都设。
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    return os.path.join(str(tmp_path), ".ssh")


def _patch_run(monkeypatch, result=None, exc=None):
    # 拦截 core.keys 走到的 subprocess.run, 记录 (cmd, kwargs), 绝不真跑 ssh-keygen。
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((list(cmd), kwargs))
        if exc is not None:
            raise exc
        return result if result is not None else _R()

    monkeypatch.setattr(dsh_keys.subprocess, "run", fake_run)
    return calls


def _write(ssh, fn, content=""):
    p = os.path.join(ssh, fn)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(content)
    return p


class TestSshDir:
    def test_ssh_dir_under_fake_home(self, tmp_path, monkeypatch):
        d = _fake_home(monkeypatch, tmp_path)
        assert dsh_keys.ssh_dir() == d


class TestListKeys:
    # 服务契约: service._run_result_op 以 func(ev) 位置参数调用, 返回 dict 至少含 "err"。
    def test_missing_ssh_dir_returns_empty_ok(self, tmp_path, monkeypatch):
        _fake_home(monkeypatch, tmp_path)
        calls = _patch_run(monkeypatch)
        p = dsh_keys.list_keys(None)
        assert p == {"keys": [], "err": ""}
        assert calls == []   # 无 .ssh 目录时绝不触发 ssh-keygen

    def test_pub_priv_classification(self, tmp_path, monkeypatch):
        ssh = _fake_home(monkeypatch, tmp_path)
        os.makedirs(ssh)
        for fn in ("id_ed25519", "id_ed25519.pub", "id_rsa", "id_rsa.pub",
                   "id_ecdsa_sk", "random.pub", "known_hosts", "authorized_keys"):
            _write(ssh, fn)
        # 假 ssh-keygen: 输出第 2 列是指纹
        calls = _patch_run(monkeypatch, result=_R(0, "3091 SHA256:FAKEFP me@host (ED25519)"))
        p = dsh_keys.list_keys()
        assert p["err"] == ""
        got = sorted((k["name"], k["is_pub"]) for k in p["keys"])
        # 私钥: id_* 无后缀; 公钥: *.pub(名字去掉 .pub); known_hosts 等无关文件不入选
        assert got == sorted([("id_ecdsa_sk", False), ("id_ed25519", False),
                              ("id_ed25519", True), ("id_rsa", False),
                              ("id_rsa", True), ("random", True)])
        assert len(p["keys"]) == 6
        assert all(k["fp"] == "SHA256:FAKEFP" for k in p["keys"])
        # 每次指纹调用都是 ssh-keygen -lf <.ssh 内文件>, 带超时
        assert len(calls) == 6
        for cmd, kwargs in calls:
            assert cmd[0] == "ssh-keygen" and cmd[1] == "-lf"
            assert os.path.dirname(cmd[2]) == ssh
            assert kwargs.get("timeout") == 10

    def test_directory_entries_skipped(self, tmp_path, monkeypatch):
        ssh = _fake_home(monkeypatch, tmp_path)
        os.makedirs(os.path.join(ssh, "id_dir"))
        calls = _patch_run(monkeypatch)
        p = dsh_keys.list_keys()
        assert p == {"keys": [], "err": ""}
        assert calls == []   # 目录不算密钥文件

    def test_listdir_error_reports_chinese_err_and_log(self, tmp_path, monkeypatch):
        ssh = _fake_home(monkeypatch, tmp_path)
        os.makedirs(ssh)

        def boom(path):
            raise OSError("disk gone")

        monkeypatch.setattr(dsh_keys.os, "listdir", boom)
        events = []
        p = dsh_keys.list_keys(lambda kind, payload: events.append((kind, payload)))
        assert p["keys"] == []
        assert "失败" in p["err"] and "disk gone" in p["err"]
        assert events and events[0][0] == "log" and events[0][1][1] == "err"

    def test_private_content_never_in_output(self, tmp_path, monkeypatch):
        # 安全红线: 私钥文件内容绝不进任何返回值(列表只含名字/类型/指纹/mtime)。
        ssh = _fake_home(monkeypatch, tmp_path)
        os.makedirs(ssh)
        _write(ssh, "id_ed25519", SECRET)
        _patch_run(monkeypatch, result=_R(0, "3091 SHA256:FAKEFP x (ED25519)"))
        p = dsh_keys.list_keys()
        assert SECRET not in json.dumps(p, ensure_ascii=False)


class TestFingerprint:
    def test_parses_second_column_with_timeout(self, tmp_path, monkeypatch):
        calls = _patch_run(monkeypatch,
                           result=_R(0, "3091 SHA256:abc123 me@host (ED25519)"))
        p = os.path.join(str(tmp_path), "k")
        assert dsh_keys.fingerprint(p) == "SHA256:abc123"
        cmd, kwargs = calls[0]
        assert cmd == ["ssh-keygen", "-lf", p]
        assert kwargs.get("timeout") == 10

    def test_nonzero_exit_returns_none(self, tmp_path, monkeypatch):
        _patch_run(monkeypatch, result=_R(1, "", "is not a public key file"))
        assert dsh_keys.fingerprint("k") is None

    def test_short_output_returns_none(self, tmp_path, monkeypatch):
        _patch_run(monkeypatch, result=_R(0, "onlyonefield"))
        assert dsh_keys.fingerprint("k") is None

    def test_exception_returns_none(self, tmp_path, monkeypatch):
        # ssh-keygen 缺失/超时都只降级为无指纹, 不向外抛
        _patch_run(monkeypatch, exc=FileNotFoundError())
        assert dsh_keys.fingerprint("k") is None
        _patch_run(monkeypatch, exc=subprocess.TimeoutExpired(cmd="ssh-keygen", timeout=10))
        assert dsh_keys.fingerprint("k") is None


class TestReadPubkey:
    def test_reads_pub_stripped(self, tmp_path, monkeypatch):
        ssh = _fake_home(monkeypatch, tmp_path)
        os.makedirs(ssh)
        _write(ssh, "id_x.pub", "ssh-ed25519 AAA comment\n")
        assert dsh_keys.read_pubkey("id_x") == "ssh-ed25519 AAA comment"

    def test_missing_pub_returns_none(self, tmp_path, monkeypatch):
        _fake_home(monkeypatch, tmp_path)
        assert dsh_keys.read_pubkey("nope") is None

    def test_never_returns_private_key_content(self, tmp_path, monkeypatch):
        # 安全红线: 无 .pub 后缀的私钥永远读不到(路径恒为 <name>.pub)。
        ssh = _fake_home(monkeypatch, tmp_path)
        os.makedirs(ssh)
        _write(ssh, "id_secret", SECRET)
        assert dsh_keys.read_pubkey("id_secret") is None


class TestGenerateKey:
    # service._run_result_op 以 func(ev, name) 位置参数调用; 测试保持同一调用形态。
    def test_success_command_and_payload(self, tmp_path, monkeypatch):
        ssh = _fake_home(monkeypatch, tmp_path)
        calls = _patch_run(monkeypatch, result=_R(0))
        payload = dsh_keys.generate_key(None, "id_my")
        assert payload == {"msg": "已生成: id_my (ed25519)", "err": ""}
        cmd, kwargs = calls[0]
        assert cmd == ["ssh-keygen", "-t", "ed25519", "-f", os.path.join(ssh, "id_my"),
                       "-N", "", "-C", "dsh-console-aio"]
        assert kwargs.get("timeout") == 30
        assert os.path.isdir(ssh)   # .ssh 目录不存在时自动创建

    def test_success_emits_ok_log(self, tmp_path, monkeypatch):
        _fake_home(monkeypatch, tmp_path)
        _patch_run(monkeypatch, result=_R(0))
        events = []
        dsh_keys.generate_key(lambda kind, payload: events.append((kind, payload)), "id_my")
        assert events == [("log", ("[SSH密钥] 已生成: id_my (ed25519)", "ok"))]

    def test_duplicate_name_rejected_without_subprocess(self, tmp_path, monkeypatch):
        ssh = _fake_home(monkeypatch, tmp_path)
        os.makedirs(ssh)
        _write(ssh, "id_x")
        calls = _patch_run(monkeypatch)
        payload = dsh_keys.generate_key(None, "id_x")
        assert payload["err"] and "已存在" in payload["err"]
        assert payload["msg"] == ""
        assert calls == []   # 重名在起子进程前就被拒绝

    def test_empty_and_path_like_names_rejected(self, tmp_path, monkeypatch):
        _fake_home(monkeypatch, tmp_path)
        calls = _patch_run(monkeypatch)
        for bad in ("", "   ", "..", ".", "a/b", "a" + os.sep + "b"):
            payload = dsh_keys.generate_key(None, bad)
            assert payload["err"], bad
            assert payload["msg"] == ""
        assert calls == []   # 非法名称绝不触发子进程

    def test_failure_stderr_becomes_chinese_err(self, tmp_path, monkeypatch):
        _fake_home(monkeypatch, tmp_path)
        calls = _patch_run(monkeypatch, result=_R(1, "", "key size too small"))
        payload = dsh_keys.generate_key(None, "id_bad")
        assert payload["err"] == "生成失败: key size too small"
        assert payload["msg"] == ""
        assert len(calls) == 1   # 失败也不再重试

    def test_failure_empty_stderr_shows_exit_code(self, tmp_path, monkeypatch):
        _fake_home(monkeypatch, tmp_path)
        _patch_run(monkeypatch, result=_R(3, "", ""))
        payload = dsh_keys.generate_key(None, "id_bad")
        assert payload["err"] == "生成失败: 退出码 3"

    def test_missing_ssh_keygen_chinese_err(self, tmp_path, monkeypatch):
        _fake_home(monkeypatch, tmp_path)
        _patch_run(monkeypatch, exc=FileNotFoundError())
        payload = dsh_keys.generate_key(None, "id_my")
        assert "找不到 ssh-keygen" in payload["err"]

    def test_timeout_chinese_err(self, tmp_path, monkeypatch):
        _fake_home(monkeypatch, tmp_path)
        _patch_run(monkeypatch,
                   exc=subprocess.TimeoutExpired(cmd="ssh-keygen", timeout=30))
        payload = dsh_keys.generate_key(None, "id_my")
        assert "超时" in payload["err"]

    def test_failure_emits_err_log(self, tmp_path, monkeypatch):
        _fake_home(monkeypatch, tmp_path)
        _patch_run(monkeypatch, result=_R(1, "", "boom"))
        events = []
        dsh_keys.generate_key(lambda kind, payload: events.append((kind, payload)), "id_bad")
        assert events and events[0][0] == "log" and "生成失败" in events[0][1][0]


class TestErrContract:
    # payload 契约: 两个异步操作的返回 dict 都至少含 "err"(成功为空字符串)。
    def test_list_payload_has_err_key(self, tmp_path, monkeypatch):
        _fake_home(monkeypatch, tmp_path)
        _patch_run(monkeypatch, result=_R(0))
        assert dsh_keys.list_keys(None)["err"] == ""

    def test_gen_payload_has_err_key(self, tmp_path, monkeypatch):
        _fake_home(monkeypatch, tmp_path)
        _patch_run(monkeypatch, result=_R(0))
        p = dsh_keys.generate_key(None, "id_c")
        assert p["err"] == "" and p["msg"] == "已生成: id_c (ed25519)"
