# -*- coding: utf-8 -*-
# app/services.py DshService 信号桥测试。
# 验证: 新增的 service 方法(read_overview, read_sessions, list_profiles, check_tool_versions 等)
# 能够正确调度线程、捕获异常并经 result / finished / step 信号回传。

import time
import pytest

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp_mod():
    import os
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class TestDshService:
    def test_service_read_overview(self, qapp_mod, tmp_path, monkeypatch):
        from app.services import DshService
        import core.data as d
        monkeypatch.setattr(d, "collect_overview_data",
                            lambda cfg, deps, smoke: {"dash_port": 3080, "ok": True})
        svc = DshService(str(tmp_path))
        results = []
        svc.result.connect(lambda op, payload: results.append((op, payload)))

        svc.read_overview({}, [], smoke=True)
        # 等待后台线程发出信号
        for _ in range(50):
            qapp_mod.processEvents()
            if results:
                break
            time.sleep(0.02)

        assert len(results) == 1
        op, payload = results[0]
        assert op == "overview-read"
        assert payload.get("data") == {"dash_port": 3080, "ok": True}
        assert payload.get("err") == ""

    def test_service_read_sessions(self, qapp_mod, tmp_path, monkeypatch):
        from app.services import DshService
        import core.data as d
        monkeypatch.setattr(d, "read_sessions_data",
                            lambda remote=None: {"ws": {}, "groups": [{"name": "g1"}]})
        svc = DshService(str(tmp_path))
        results = []
        svc.result.connect(lambda op, payload: results.append((op, payload)))

        svc.read_sessions()
        for _ in range(50):
            qapp_mod.processEvents()
            if results:
                break
            time.sleep(0.02)

        assert len(results) == 1
        op, payload = results[0]
        assert op == "sessions-read"
        assert payload.get("data") == {"ws": {}, "groups": [{"name": "g1"}]}

    def test_service_step_and_log_events(self, qapp_mod, tmp_path):
        from app.services import DshService
        svc = DshService(str(tmp_path))
        steps = []
        logs = []
        svc.step.connect(lambda idx, text: steps.append((idx, text)))
        svc.log.connect(lambda text, tag: logs.append((text, tag)))

        ev = svc._events()
        ev("step", (1, "步骤 1"))
        ev("log", ("这是一条日志", "ok"))
        ev("log", "纯文本日志")

        qapp_mod.processEvents()
        assert steps == [(1, "步骤 1")]
        assert logs == [("这是一条日志", "ok"), ("纯文本日志", "")]
