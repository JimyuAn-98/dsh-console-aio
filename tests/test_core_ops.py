# -*- coding: utf-8 -*-
# test_core_ops.py - core/ops.py 纯单元测试(零 Qt, 零子进程, 不真打备份 zip)。
#
# 安全边界: 不构造 MainWindow; backup_dsh_home 用 monkeypatch 拦截 dsh_data.backup_dsh_home,
# 绝不向真实 ~/.dsh 或用户目录写任何文件。

from core import data as dsh_data
import core.ops as ops


class TestLogEntries:
    def test_missing_dir_returns_empty(self, tmp_path):
        assert ops.log_entries(str(tmp_path / "nope")) == []

    def test_filters_logs_only(self, tmp_path):
        (tmp_path / "a.log").write_text("x", encoding="utf-8")
        (tmp_path / "b.txt").write_text("x", encoding="utf-8")
        (tmp_path / "C.LOG").write_text("x", encoding="utf-8")
        (tmp_path / "sub.dir.log").mkdir()   # 名字像 .log 的目录必须排除
        names = [e["name"] for e in ops.log_entries(str(tmp_path))]
        assert names == ["C.LOG", "a.log"]

    def test_entries_have_size_and_mtime(self, tmp_path):
        (tmp_path / "x.log").write_text("hello", encoding="utf-8")
        e = ops.log_entries(str(tmp_path))[0]
        assert e["size"] == 5
        assert e["mtime"] > 0

    def test_default_dir_is_temp_dsh_dash(self):
        # 缺省目录契约: %TEMP%/dsh-dash(与 dsh web 日志落点一致)
        assert ops.log_dir().endswith("dsh-dash")


class TestReadTail:
    def test_small_file_full_content(self, tmp_path):
        p = tmp_path / "a.log"
        p.write_text("line1\nline2\n", encoding="utf-8")
        assert ops.read_tail(str(p)) == "line1\nline2\n"

    def test_crlf_normalized(self, tmp_path):
        p = tmp_path / "a.log"
        p.write_bytes(b"l1\r\nl2\r\n")
        assert ops.read_tail(str(p)) == "l1\nl2\n"

    def test_limit_drops_partial_first_line(self, tmp_path):
        # 限读截断落在行中间时丢弃残余半行("e8\n"), 从下一个完整行起返回
        p = tmp_path / "a.log"
        body = "".join("line%d\n" % i for i in range(10))   # 每行 6 字节, 共 60
        p.write_text(body, encoding="utf-8")
        assert ops.read_tail(str(p), limit=8) == "line9\n"

    def test_missing_file_raises_oserror(self, tmp_path):
        import pytest
        with pytest.raises(OSError):
            ops.read_tail(str(tmp_path / "nope.log"))


class TestBackupDshHome:
    # backup_dsh_home 是 service 后台 op: 只验证 payload 组装与中文 err 分支,
    # dsh_data.backup_dsh_home 被拦截, 绝不真写 zip。
    def test_success_payload(self, tmp_path, monkeypatch):
        zpath = tmp_path / "b.zip"

        def fake_backup(target):
            # 写一个真实小文件, 让 os.path.getsize 走真路径(不 patch 全局)
            zpath.write_bytes(b"zipdata")
            return 7

        monkeypatch.setattr(dsh_data, "backup_dsh_home", fake_backup)
        got = []
        r = ops.backup_dsh_home(lambda kind, p: got.append((kind, p)), str(zpath))
        assert r["err"] == ""
        assert r["count"] == 7
        assert r["size"] == 7
        assert "已备份 7 个文件" in r["msg"]
        # events 日志契约: core 输出带 "[运维] " 前缀 + ok tag
        assert ("log", ("[运维] " + r["msg"], "ok")) in got

    def test_failure_chinese_err(self, tmp_path, monkeypatch):
        def boom(target):
            raise OSError("disk full")

        monkeypatch.setattr(dsh_data, "backup_dsh_home", boom)
        r = ops.backup_dsh_home(None, str(tmp_path / "x.zip"))
        assert r["msg"] == "" and r["count"] == 0 and r["size"] == 0
        assert "备份失败" in r["err"] and "disk full" in r["err"]

    def test_empty_target_refused(self):
        r = ops.backup_dsh_home(None, "   ")
        assert r["msg"] == "" and "备份路径不能为空" in r["err"]
