# -*- coding: utf-8 -*-
# test_core_logs.py - core/logs.py 纯单元测试(零 Qt)。
# 日志文件用 tmp_path 造假, 不读真实 %TEMP%/dsh-dash, 不触发任何子进程。

import os

from core import logs


class TestPaths:
    def test_log_dir_under_temp(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TEMP", str(tmp_path))
        assert logs.log_dir() == os.path.join(str(tmp_path), "dsh-dash")
        assert logs.log_path("out") == os.path.join(str(tmp_path), "dsh-dash", "dsh-web.out.log")
        assert logs.log_path("err").endswith("dsh-web.err.log")


class TestMaskTokens:
    def test_masks_token_value_keeps_url(self):
        url = "dsh web: http://127.0.0.1:3080/?token=Abc123_-xyz&foo=1"
        masked = logs.mask_tokens(url)
        assert "token=***&foo=1" in masked
        assert "Abc123" not in masked

    def test_plain_line_untouched(self):
        assert logs.mask_tokens("[ELIFECYCLE] Command failed with exit code 1.") == \
            "[ELIFECYCLE] Command failed with exit code 1."


class TestClassify:
    def test_err_keywords_case_insensitive(self):
        assert logs.classify_line("[ELIFECYCLE] Command failed with exit code 1.") == "err"
        assert logs.classify_line("Error: cannot find module") == "err"
        assert logs.classify_line("FATAL something") == "err"

    def test_warn_keywords(self):
        assert logs.classify_line("(node:123) Warning: deprecated") == "warn"

    def test_ok_startup_lines(self):
        assert logs.classify_line("dsh web: http://127.0.0.1:3080/?token=x") == "ok"
        assert logs.classify_line("server ready on port 3080") == "ok"

    def test_plain_line(self):
        assert logs.classify_line("$ node --import tsx/esm apps/cli/src/bin.ts") == ""

    def test_err_stream_all_red(self):
        # err 流整文件按错误显示, 即使行内容像普通命令回显
        assert logs.classify_stream("err", "$ node apps/cli/src/bin.ts") == "err"
        assert logs.classify_stream("out", "$ node apps/cli/src/bin.ts") == ""


class TestReadTail:
    def test_missing_file_yields_empty(self, tmp_path):
        assert logs.read_tail(str(tmp_path / "nope.log")) == []

    def test_returns_last_n_lines(self, tmp_path):
        p = tmp_path / "a.log"
        p.write_text("".join("line%d\n" % i for i in range(3000)), encoding="utf-8")
        rows = logs.read_tail(str(p), max_lines=2000)
        assert len(rows) == 2000
        assert rows[0] == "line1000" and rows[-1] == "line2999"

    def test_small_file_fully(self, tmp_path):
        p = tmp_path / "b.log"
        p.write_text("a\n\nc\n", encoding="utf-8")
        assert logs.read_tail(str(p)) == ["a", "", "c"]

    def test_byte_cap_drops_partial_head_line(self, tmp_path):
        p = tmp_path / "c.log"
        p.write_text("head-partial\n" + "x" * 100 + "\n" + "tail\n", encoding="utf-8")
        rows = logs.read_tail(str(p), max_bytes=64)
        # 窗口落在 x 行中间: 该残行整行丢弃, 不出现半行
        assert rows == ["tail"]


class TestTailer:
    def test_incremental_and_partial_hold(self, tmp_path):
        p = tmp_path / "t.log"
        t = logs.Tailer(str(p))
        p.write_text("one\ntwo\n", encoding="utf-8")
        lines, reset = t.read_new()
        assert (lines, reset) == (["one", "two"], False)
        # 半行(无换行)不消费, 下次补齐
        with open(p, "a", encoding="utf-8") as fh:
            fh.write("thr")
        assert t.read_new() == ([], False)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write("ee\nfour\n")
        lines, reset = t.read_new()
        assert (lines, reset) == (["three", "four"], False)
        assert t.read_new() == ([], False)

    def test_truncation_resets(self, tmp_path):
        p = tmp_path / "r.log"
        p.write_text("old-1\nold-2\n", encoding="utf-8")
        t = logs.Tailer(str(p))
        assert t.read_new() == (["old-1", "old-2"], False)
        p.write_text("new\n", encoding="utf-8")
        lines, reset = t.read_new()
        assert reset is True and lines == ["new"]

    def test_missing_file(self, tmp_path):
        t = logs.Tailer(str(tmp_path / "gone.log"))
        assert t.read_new() == ([], False)
        # 先有数据后文件消失 -> reset 通知清屏
        p = tmp_path / "g2.log"
        p.write_text("x\n", encoding="utf-8")
        t2 = logs.Tailer(str(p))
        t2.read_new()
        p.unlink()
        lines, reset = t2.read_new()
        assert reset is True and lines == []

    def test_crlf(self, tmp_path):
        p = tmp_path / "crlf.log"
        with open(p, "wb") as fh:
            fh.write(b"a\r\nb\r\n")
        t = logs.Tailer(str(p))
        assert t.read_new() == (["a", "b"], False)

    def test_mixed_encoding_gbk_line(self, tmp_path):
        # 真实场景回归: out.log 里 node/pnpm 行是 UTF-8, cmd.exe 批处理提示按 GBK 写入,
        # 逐行探测解码后中文必须正常(UTF-8 严格解码失败才回退 GBK)
        gbk_line = "终止批处理操作吗(Y/N)?".encode("gbk")
        p = tmp_path / "mixed.log"
        with open(p, "wb") as fh:
            fh.write(b"utf8: ok\n" + gbk_line + b"\r\n")
        assert logs.read_tail(str(p)) == ["utf8: ok", "终止批处理操作吗(Y/N)?"]
        t = logs.Tailer(str(p))
        assert t.read_new() == (["utf8: ok", "终止批处理操作吗(Y/N)?"], False)

    def test_read_tail_empty_file(self, tmp_path):
        p = tmp_path / "empty.log"
        p.write_bytes(b"")
        assert logs.read_tail(str(p)) == []


class TestFilterRows:
    ROWS = [("dsh web: http://x", "ok"), ("Error: boom", "err"), ("plain line", "")]

    def test_include(self):
        out = logs.filter_rows(self.ROWS, include="error")
        assert out == [("Error: boom", "err")]

    def test_exclude(self):
        out = logs.filter_rows(self.ROWS, exclude="http")
        assert ("dsh web: http://x", "ok") not in out and len(out) == 2

    def test_combined_and_empty_conditions(self):
        assert logs.filter_rows(self.ROWS, include="", exclude="") == self.ROWS
        assert logs.filter_rows(self.ROWS, include="err", exclude="boom") == []
