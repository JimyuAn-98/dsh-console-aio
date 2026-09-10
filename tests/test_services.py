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

    def test_service_start_stop_restart_dsh(self, qapp_mod, tmp_path, monkeypatch):
        # 验证 service 的 start_dsh / stop_dsh / restart_dsh 能够调用 ctl 并 emit finished
        from app.services import DshService
        svc = DshService(str(tmp_path))
        calls = []
        monkeypatch.setattr(svc.ctl, "run_dsh", lambda mode, ev: calls.append(mode) or True)

        finished = []
        svc.finished.connect(lambda op, ok: finished.append((op, ok)))

        svc.start_dsh("start")
        for _ in range(50):
            qapp_mod.processEvents()
            if len(calls) == 1:
                break
            time.sleep(0.02)
        assert calls == ["start"]
        assert ("dsh", True) in finished

        calls.clear()
        finished.clear()
        svc.stop_dsh()
        for _ in range(50):
            qapp_mod.processEvents()
            if len(calls) == 1:
                break
            time.sleep(0.02)
        assert calls == ["stop"]
        assert ("dsh-stop", True) in finished

        calls.clear()
        finished.clear()
        svc.restart_dsh()
        for _ in range(50):
            qapp_mod.processEvents()
            if len(calls) == 1:
                break
            time.sleep(0.02)
        assert calls == ["restart"]
        assert ("dsh-restart", True) in finished

    def test_plugin_page_apply_profiles_unsets_busy(self, qapp_mod, tmp_path, monkeypatch):
        # 验证 PluginPage._apply_profiles 收到非空 profile 列表后立即解除 busy 并不死锁
        from app.services import DshService
        from ui.pages_plugins import PluginPage
        svc = DshService(str(tmp_path))

        class FakeApp:
            service = svc
            def loge(self, *a, **k): pass
            def set_status(self, *a, **k): pass

        # 拦截后台 list_profiles 避免真跑
        monkeypatch.setattr(svc, "list_profiles", lambda *a, **k: None)
        page = PluginPage(FakeApp())
        # 初始处于 busy 状态等待 profiles
        assert page._busy is True
        assert page._pending == "plugins-profiles-list"

        # 拦截 refresh 验证调用
        refresh_called = []
        monkeypatch.setattr(page, "_refresh", lambda force=False: refresh_called.append(force))

        # 模拟 service 结果到达
        profiles = [{"name": "web", "cordis": True, "patch": True, "pkg": True}]
        page._apply_profiles(profiles, "")

        # 验证 busy 状态被正确解除且不再卡住
        assert page._busy is False
        assert page._pending is None
        assert page._profile_cb.count() == 1
        assert page._profile_cb.currentText() == "web"
        assert refresh_called == [False]

    def test_plugin_page_update_and_update_all(self, qapp_mod, tmp_path, monkeypatch):
        # 验证 PluginPage 的更新按钮、更新全部与安装新插件命令组装
        from app.services import DshService
        from ui.pages_plugins import PluginPage
        svc = DshService(str(tmp_path))

        class FakeApp:
            service = svc
            def loge(self, *a, **k): pass
            def set_status(self, *a, **k): pass

        monkeypatch.setattr(svc, "list_profiles", lambda *a, **k: None)
        page = PluginPage(FakeApp())
        profiles = [{"name": "web", "cordis": True, "patch": True, "pkg": True}]
        monkeypatch.setattr(page, "_refresh", lambda force=False: None)
        page._apply_profiles(profiles, "")

        stream_calls = []
        monkeypatch.setattr(page, "_run_stream", lambda cmd, desc: stream_calls.append((cmd, desc)))

        # 1. 模拟在未选中时点击更新全部
        page._update_all()
        page._confirm._on_ok()
        assert len(stream_calls) == 1
        cmd, desc = stream_calls[0]
        assert "update" in cmd
        assert "--profile" in cmd
        assert "web" in cmd

        # 2. 模拟选中插件点击更新
        stream_calls.clear()
        monkeypatch.setattr(page, "_selected_entry", lambda: {"id": "my-plugin", "name": "my-plugin"})
        page._update()
        page._confirm._on_ok()
        assert len(stream_calls) == 1
        cmd, desc = stream_calls[0]
        assert cmd[-2:] == ["update", "my-plugin"]

        # 3. 模拟未选中条目点击安装，输入包名
        stream_calls.clear()
        monkeypatch.setattr(page, "_selected_entry", lambda: None)
        from PySide6.QtWidgets import QInputDialog
        monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("awesome-plugin", True))
        page._install()
        page._confirm._on_ok()
        assert len(stream_calls) == 1
        cmd, desc = stream_calls[0]
        assert cmd[-2:] == ["add", "awesome-plugin"]

    def test_service_download_console_installer(self, qapp_mod, tmp_path, monkeypatch):
        # 验证 service.download_console_installer 起线程跑 core 并回 result("version-installer")
        from app.services import DshService
        from core import version as vmod
        svc = DshService(str(tmp_path))
        seen = []
        monkeypatch.setattr(vmod, "download_installer",
                            lambda ev, version: seen.append(version) or
                            {"path": "C:/tmp/setup.exe", "err": ""})
        got = []
        svc.result.connect(lambda op, p: got.append((op, p)))
        svc.download_console_installer("0.8.0")
        for _ in range(50):
            qapp_mod.processEvents()
            if got:
                break
            time.sleep(0.02)
        assert seen == ["0.8.0"]
        assert got and got[0][0] == "version-installer"
        assert got[0][1]["path"] == "C:/tmp/setup.exe"

    def test_service_deploy_dsh_version(self, qapp_mod, tmp_path, monkeypatch):
        # 验证 service.deploy_dsh_version 起线程跑 ctl 并回 result("dsh-deploy-version")
        from app.services import DshService
        svc = DshService(str(tmp_path))
        seen = []
        monkeypatch.setattr(svc.ctl, "deploy_dsh_version",
                            lambda ev, tag, allow_dirty=False: seen.append((tag, allow_dirty)) or
                            {"err": "", "dirty": False, "msg": "ok", "tag": tag})
        got = []
        svc.result.connect(lambda op, p: got.append((op, p)))
        svc.deploy_dsh_version("dsh-v1.0.0")
        for _ in range(50):
            qapp_mod.processEvents()
            if got:
                break
            time.sleep(0.02)
        assert seen == [("dsh-v1.0.0", False)]
        assert got and got[0][0] == "dsh-deploy-version"
        assert got[0][1]["tag"] == "dsh-v1.0.0"
