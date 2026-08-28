# -*- coding: utf-8 -*-
# test_core_profiles.py - core/profiles.py 纯单元测试(零 Qt, 零子进程)。
#
# 安全边界: 不构造 MainWindow/任何 Qt 对象; monkeypatch 把 dsh_data.profiles_dir
# 指到 tmp_path 下的假 profiles 目录, 真拷贝/真删除(纯文件系统操作, 与用户真实
# ~/.dsh 零交集)。覆盖: copy_profile 成功且排除 node_modules、各类非法名/同名/
# 重名/源不存在拒绝、delete_profile web 拒删/路径穿越/目录不存在/rmtree 失败
# 分支中文 err、payload {"msg","err"} 对称契约与 events 日志回调。

import os

import pytest

from core import data as dsh_data
from core import profiles as dsh_profiles


@pytest.fixture
def prof_root(tmp_path, monkeypatch):
    # 假 profiles 根目录: dsh_data.profiles_dir() 指向 tmp_path/profiles
    root = os.path.join(str(tmp_path), "profiles")
    os.makedirs(root)
    monkeypatch.setattr(dsh_data, "profiles_dir", lambda: root)
    return root


def _mk_profile(root, name, with_nm=False):
    # 造一个假 Profile 目录: 两个文件 + 一层子目录(+可选 node_modules)
    d = os.path.join(root, name)
    os.makedirs(os.path.join(d, "sub"))
    for rel in ("cordis.yml", os.path.join("sub", "x.yml")):
        with open(os.path.join(d, rel), "w", encoding="utf-8") as fh:
            fh.write("x")
    if with_nm:
        nm = os.path.join(d, "node_modules", "pkg")
        os.makedirs(nm)
        with open(os.path.join(nm, "index.js"), "w", encoding="utf-8") as fh:
            fh.write("x")
    return d


def _capture():
    # events 回调收集器: 返回 (回调, 列表)
    events = []

    def cb(kind, payload):
        events.append((kind, payload))

    return cb, events


class TestCopyProfile:
    # service._run_result_op 以 func(ev, src, new) 位置参数调用; 测试保持同一调用形态。
    def test_success_excludes_node_modules(self, prof_root):
        _mk_profile(prof_root, "web", with_nm=True)
        payload = dsh_profiles.copy_profile(None, "web", "dev")
        assert payload == {"msg": "已复制 web → dev", "err": ""}
        dst = os.path.join(prof_root, "dev")
        assert os.path.isfile(os.path.join(dst, "cordis.yml"))
        assert os.path.isfile(os.path.join(dst, "sub", "x.yml"))   # 子目录一并拷贝
        assert not os.path.exists(os.path.join(dst, "node_modules"))
        assert os.path.exists(os.path.join(prof_root, "web", "node_modules"))  # 源不动

    def test_success_emits_ok_log(self, prof_root):
        _mk_profile(prof_root, "web")
        cb, events = _capture()
        dsh_profiles.copy_profile(cb, "web", "dev")
        assert events == [("log", ("[Profile管理] 已复制 web → dev", "ok"))]

    def test_bad_names_rejected_without_side_effect(self, prof_root):
        _mk_profile(prof_root, "web")
        for bad in ("", "   ", ".", "..", "a/b", "a" + os.sep + "b", "C:x",
                    "a:b", "a*b", "a?b", 'a"b', "a<b", "a>b", "a|b", "a\\b"):
            payload = dsh_profiles.copy_profile(None, "web", bad)
            assert payload["err"], bad
            assert payload["msg"] == ""
        # 源名不合法同样拒绝
        payload = dsh_profiles.copy_profile(None, "a/b", "dev")
        assert payload["err"] and payload["msg"] == ""
        assert os.listdir(prof_root) == ["web"]   # 非法输入零文件系统副作用

    def test_same_name_rejected(self, prof_root):
        _mk_profile(prof_root, "web")
        payload = dsh_profiles.copy_profile(None, "web", "web")
        assert payload["err"] and "相同" in payload["err"]
        assert payload["msg"] == ""

    def test_existing_target_rejected(self, prof_root):
        _mk_profile(prof_root, "web")
        _mk_profile(prof_root, "dev")
        payload = dsh_profiles.copy_profile(None, "web", "dev")
        assert payload["err"] and "已存在" in payload["err"]
        # 目标旧内容不被破坏
        assert os.path.isfile(os.path.join(prof_root, "dev", "sub", "x.yml"))

    def test_missing_src_rejected(self, prof_root):
        payload = dsh_profiles.copy_profile(None, "ghost", "dev")
        assert payload["err"] and "不存在" in payload["err"]
        assert payload["msg"] == ""
        assert os.listdir(prof_root) == []   # 未创建任何目录

    def test_copytree_failure_becomes_chinese_err(self, prof_root, monkeypatch):
        _mk_profile(prof_root, "web")

        def boom(src, dst, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(dsh_profiles.shutil, "copytree", boom)
        payload = dsh_profiles.copy_profile(None, "web", "dev")
        assert payload["msg"] == ""
        assert payload["err"] == "复制失败: disk full"

    def test_failure_emits_err_log(self, prof_root):
        cb, events = _capture()
        dsh_profiles.copy_profile(cb, "ghost", "dev")
        assert events and events[0][0] == "log" and "不存在" in events[0][1][0]
        assert events[0][1][1] == "err"


class TestDeleteProfile:
    def test_success_removes_directory(self, prof_root):
        _mk_profile(prof_root, "dev")
        payload = dsh_profiles.delete_profile(None, "dev")
        assert payload == {"msg": "已删除 dev", "err": ""}
        assert not os.path.exists(os.path.join(prof_root, "dev"))

    def test_web_rejected_even_if_missing(self, prof_root):
        # web 拒删先于目录存在性: 目录不存在时文案仍是"默认 Profile"
        payload = dsh_profiles.delete_profile(None, "web")
        assert payload["err"] == "web 是默认 Profile，不可删除"
        assert payload["msg"] == ""
        _mk_profile(prof_root, "web")
        payload = dsh_profiles.delete_profile(None, "web")
        assert payload["err"] == "web 是默认 Profile，不可删除"
        assert os.path.exists(os.path.join(prof_root, "web"))   # 目录原样保留

    def test_path_traversal_rejected(self, prof_root):
        # profiles 同级放一个"邻居"目录, 穿越名不得伤到它
        neighbor = os.path.join(os.path.dirname(prof_root), "neighbor")
        os.makedirs(neighbor)
        _mk_profile(prof_root, "dev")
        for bad in ("../dev", ".." + os.sep + "dev", "a/b", "..", ".", "a\\b",
                    os.path.join("..", "neighbor")):
            payload = dsh_profiles.delete_profile(None, bad)
            assert payload["err"], bad
            assert payload["msg"] == ""
        assert os.path.exists(neighbor)
        assert os.path.exists(os.path.join(prof_root, "dev"))

    def test_missing_dir_rejected(self, prof_root):
        payload = dsh_profiles.delete_profile(None, "ghost")
        assert payload["err"] and "不存在" in payload["err"]
        assert payload["msg"] == ""

    def test_rmtree_failure_becomes_chinese_err(self, prof_root, monkeypatch):
        _mk_profile(prof_root, "dev")

        def boom(path):
            raise OSError("file in use")

        monkeypatch.setattr(dsh_profiles.shutil, "rmtree", boom)
        cb, events = _capture()
        payload = dsh_profiles.delete_profile(cb, "dev")
        assert payload["msg"] == ""
        assert payload["err"] == "删除失败: file in use"
        assert events and events[0][0] == "log" and events[0][1][1] == "err"
        assert os.path.exists(os.path.join(prof_root, "dev"))   # 失败不删

    def test_success_emits_ok_log(self, prof_root):
        _mk_profile(prof_root, "dev")
        cb, events = _capture()
        dsh_profiles.delete_profile(cb, "dev")
        assert events == [("log", ("[Profile管理] 已删除 dev", "ok"))]


class TestErrContract:
    # payload 契约: 两个写操作的返回 dict 恒含 "msg" 与 "err"(对称取值, 一空一非空)。
    def test_payload_always_has_both_keys(self, prof_root):
        _mk_profile(prof_root, "web")
        for payload in (dsh_profiles.copy_profile(None, "web", "dev"),
                        dsh_profiles.delete_profile(None, "dev"),
                        dsh_profiles.copy_profile(None, "web", "dev"),
                        dsh_profiles.delete_profile(None, "ghost")):
            assert set(payload.keys()) == {"msg", "err"}
            assert (payload["msg"] == "") != (payload["err"] == "")
