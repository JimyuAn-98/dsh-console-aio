# -*- coding: utf-8 -*-
# DshService 长操作完整输出日志测试(QObject, 不开窗口/不起线程/不连网)。
# 覆盖: _begin_op 建文件并逐行写入 log/status/step; latest_op_log 返回路径;
#       _events()(无 op)不落盘。

from PySide6.QtCore import QCoreApplication

from app import services as services


def _qapp():
    return QCoreApplication.instance() or QCoreApplication([])


class TestOpLog:
    def test_full_output_written_and_closed(self, tmp_path, monkeypatch):
        _qapp()
        svc = services.DshService(str(tmp_path))
        logf = tmp_path / 'op.log'
        monkeypatch.setattr(svc, '_op_log_path', lambda op: str(logf))
        ev = svc._begin_op('dsh-install')
        ev('log', ('line one', 'ok'))
        ev('status', 'busy')
        ev('step', (2, '依赖'))
        svc._op_log_close('dsh-install')
        text = logf.read_text(encoding='utf-8')
        assert 'line one' in text
        assert 'busy' in text
        assert '依赖' in text
        assert svc.latest_op_log() == str(logf)

    def test_events_without_op_writes_nothing(self, tmp_path, monkeypatch):
        _qapp()
        svc = services.DshService(str(tmp_path))
        logf = tmp_path / 'op.log'
        monkeypatch.setattr(svc, '_op_log_path', lambda op: str(logf))
        ev = svc._events()   # op=None -> 只发信号, 不落盘
        ev('log', 'x')
        assert not logf.exists()

    def test_token_redacted_in_log(self, tmp_path, monkeypatch):
        # 落盘日志必须抹掉 Token(安全红线), 但控制台信号不受影响
        _qapp()
        svc = services.DshService(str(tmp_path))
        logf = tmp_path / 'op.log'
        monkeypatch.setattr(svc, '_op_log_path', lambda op: str(logf))
        seen = []
        svc.log.connect(lambda t, _tag: seen.append(t))
        ev = svc._begin_op('dsh')
        ev('log', '  http://127.0.0.1:3080/?token=abcDEF123456')
        ev('log', 'Authorization: Bearer xyz9876543210')
        svc._op_log_close('dsh')
        text = logf.read_text(encoding='utf-8')
        assert 'abcDEF123456' not in text
        assert 'xyz9876543210' not in text
        assert 'token=***' in text
        # 控制台(信号)保持原文
        assert any('abcDEF123456' in t for t in seen)
