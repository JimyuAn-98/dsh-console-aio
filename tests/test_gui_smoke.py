# -*- coding: utf-8 -*-
# PySide6 GUI 冒烟测试。
#
# 安全提醒(重要):
#   本文件会构造真实 dsh-console-aio 的 MainWindow, 并触发其内部真实的健康监控线程
#   与真实子进程。若与正在运行的 dsh(端口 3080)共用同一份真实 config.json, 存在
#   config.json 中真实服务器/端口被读取探测、以及监控/页面后台线程触碰真实资源的风险。
#   因此默认不执行: 由 pytest.ini 的 `-m "not gui"` 跳过, 仅 `-m gui` 显式手动执行。
#   手动执行时请确保不会干扰正在运行的 dsh(端口 3080)。
#
# 环境: QT_QPA_PLATFORM=offscreen (由 conftest qapp fixture 设置)。
# 不触发真实 SSH/子进程/启停: --smoke 模式 + 隔离 fixture(monkeypatch 拦截监控与 _stream_cmd)。

import os
import sys

import pytest

# GUI 测试需要 PySide6
pytest.importorskip("PySide6")

# 默认跳过: 仅 `-m gui` 手动执行(见 pytest.ini)。
pytestmark = pytest.mark.gui

# 项目根目录
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# 主程序文件名含连字符(dsh-console-aio.py), 用 importlib 动态导入
import importlib
import importlib.util

def _import_main():
    """dynamic import of dsh-console-aio.py"""
    main_path = os.path.join(ROOT_DIR, "dsh-console-aio.py")
    spec = importlib.util.spec_from_file_location("dsh_console_aio", main_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dsh_console_aio"] = mod
    spec.loader.exec_module(mod)
    return mod

# 延迟导入(避免模块加载时就触发 QApplication / 读真实 config.json)
_main_mod = None

def _get_main_mod():
    global _main_mod
    if _main_mod is None:
        _main_mod = _import_main()
    return _main_mod


@pytest.fixture(scope="module")
def qapp_mod():
    """module-scoped QApplication"""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(scope="module")
def main_win(qapp_mod, tmp_path):
    """MainWindow(smoke=True), isolated from real resources."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    # 隔离: DSH_HOME 指向临时假目录, 绝不读真实 ~/.dsh
    fake_home = str(tmp_path / "dsh-home")
    os.makedirs(fake_home, exist_ok=True)
    os.environ["DSH_HOME"] = fake_home
    mod = _get_main_mod()
    # 隔离: 拦截真实健康监控线程; 子进程通道下沉到 service 层(DshService)
    # —— 页面业务经 run_cmd/_run_result_op/_run_core_op 后台执行, 不再走主窗口 _stream_cmd。
    from app import services as _services
    _orig_monitor = mod.MainWindow._start_monitor
    _orig_run_cmd = _services.DshService.run_cmd
    _orig_run_result = _services.DshService._run_result_op
    _orig_run_core = _services.DshService._run_core_op
    mod.MainWindow._start_monitor = lambda self: None
    _services.DshService.run_cmd = lambda self, cmd, cwd=None, env=None, op="run-cmd": None
    _services.DshService._run_result_op = lambda self, *a, **k: None
    _services.DshService._run_core_op = lambda self, *a, **k: None
    try:
        win = mod.MainWindow(smoke=True)
        yield win
        win.close()
        qapp_mod.processEvents()
    finally:
        mod.MainWindow._start_monitor = _orig_monitor
        _services.DshService.run_cmd = _orig_run_cmd
        _services.DshService._run_result_op = _orig_run_result
        _services.DshService._run_core_op = _orig_run_core


class TestMainWindowConstruction:
    """MainWindow basic construction smoke."""

    def test_window_created(self, main_win):
        assert main_win is not None
        assert main_win.windowTitle().startswith("dsh 控制台")

    def test_nav_items_loaded(self, main_win):
        assert main_win.nav.count() > 0

    def test_stack_has_widget(self, main_win):
        assert main_win.stack.count() >= 1

    def test_log_view_exists(self, main_win):
        assert main_win.log_view is not None

    def test_status_exists(self, main_win):
        assert main_win.status is not None

    def test_deploy_combo_exists(self, main_win):
        assert main_win.deploy is not None

    def test_smoke_flag_set(self, main_win):
        assert main_win.smoke is True

    def test_bridge_attached(self, main_win):
        assert main_win.bridge._view is not None


class TestPageNavigation:
    """iterate nav items, switch pages, ensure no crash."""

    NAV_KEYS = ["overview", "tunnels", "sessions", "agents", "profiles",
                "plugins", "taskboard", "usage", "llm", "ops",
                "keys", "version", "deployments"]

    @pytest.mark.parametrize("key", NAV_KEYS)
    def test_show_page(self, main_win, qapp_mod, key):
        main_win._show_page(key)
        qapp_mod.processEvents()
        assert main_win.stack.count() >= 1, "page '%s' not loaded" % key
        widget = main_win.stack.currentWidget()
        assert widget is not None, "page '%s' widget None" % key

    def test_overview_page_type(self, main_win, qapp_mod):
        mod = _get_main_mod()
        main_win._show_page("overview")
        qapp_mod.processEvents()
        assert isinstance(main_win.stack.currentWidget(), mod.OverviewPage)

    def test_tunnels_page_type(self, main_win, qapp_mod):
        mod = _get_main_mod()
        main_win._show_page("tunnels")
        qapp_mod.processEvents()
        assert isinstance(main_win.stack.currentWidget(), mod.TunnelsPage)

    def test_sessions_page_type(self, main_win, qapp_mod):
        from ui.pages_sessions import SessionPage
        main_win._show_page("sessions")
        qapp_mod.processEvents()
        assert isinstance(main_win.stack.currentWidget(), SessionPage)

    def test_deployments_page_type(self, main_win, qapp_mod):
        from ui.pages_deployments import DeploymentPage
        main_win._show_page("deployments")
        qapp_mod.processEvents()
        assert isinstance(main_win.stack.currentWidget(), DeploymentPage)

    def test_version_page_type(self, main_win, qapp_mod):
        from ui.pages_version import VersionPage
        main_win._show_page("version")
        qapp_mod.processEvents()
        assert isinstance(main_win.stack.currentWidget(), VersionPage)


class TestNavToPageMapping:
    """every NAV key maps to a page."""

    def test_all_nav_keys_produce_pages(self, main_win, qapp_mod):
        mod = _get_main_mod()
        for label, key in mod.NAV_ITEMS:
            main_win._show_page(key)
            qapp_mod.processEvents()
            assert main_win.stack.count() >= 1, "NAV '%s'(%s) no page" % (label, key)


class TestDeploySwitching:
    """deploy switching no crash."""

    def test_switch_to_local(self, main_win, qapp_mod):
        main_win.deploy.setCurrentIndex(0)
        qapp_mod.processEvents()
        assert main_win._current_deploy is None

    def test_deploy_changed_refreshes_page(self, main_win, qapp_mod):
        main_win._show_page("sessions")
        qapp_mod.processEvents()
        w1 = main_win.stack.currentWidget()
        main_win._on_deploy_changed(0)
        qapp_mod.processEvents()
        w2 = main_win.stack.currentWidget()
        assert w2 is not None


class TestLogBridge:
    """LogBridge thread-safe logging."""

    def test_log_bridge_emit(self, main_win, qapp_mod):
        main_win.bridge.emit("test log message", "ok")
        qapp_mod.processEvents()
        assert "test log message" in main_win.log_view.toPlainText()

    def test_log_bridge_error_tag(self, main_win, qapp_mod):
        main_win.bridge.emit("error message", "err")
        qapp_mod.processEvents()
        assert "error message" in main_win.log_view.toPlainText()

    def test_loge_updates_status(self, main_win, qapp_mod):
        main_win.loge("status test")
        qapp_mod.processEvents()
        assert main_win.status.text() == "status test"


class TestRightBar:
    """right health bar."""

    def test_right_bar_exists(self, main_win):
        assert main_win.right is not None

    def test_set_state_on_existing_cell(self, main_win, qapp_mod):
        if main_win.right._cells:
            key = list(main_win.right._cells.keys())[0]
            main_win.right.set_state(key, True, 42)
            qapp_mod.processEvents()
            main_win.right.set_state(key, False, -1)
            qapp_mod.processEvents()

    def test_set_state_on_missing_cell(self, main_win, qapp_mod):
        main_win.right.set_state("NONEXISTENT", True, 100)
        qapp_mod.processEvents()


class TestOverviewPage:
    """overview page shows demo data in smoke mode."""

    def test_overview_smoke_shows_demo(self, main_win, qapp_mod):
        mod = _get_main_mod()
        main_win._show_page("overview")
        qapp_mod.processEvents()
        page = main_win.stack.currentWidget()
        assert isinstance(page, mod.OverviewPage)
        assert "演示" in page.dep_status.text() or "未配置" in page.dep_status.text()

    def test_overview_refresh_smoke(self, main_win, qapp_mod):
        mod = _get_main_mod()
        main_win._show_page("overview")
        qapp_mod.processEvents()
        page = main_win.stack.currentWidget()
        page.refresh()
        qapp_mod.processEvents()


class TestForceRefresh:
    def test_force_refresh_on_overview(self, main_win, qapp_mod):
        main_win._show_page("overview")
        qapp_mod.processEvents()
        main_win._force_refresh()
        qapp_mod.processEvents()


class TestWindowSize:
    def test_minimum_size(self, main_win):
        assert main_win.minimumWidth() >= 960
        assert main_win.minimumHeight() >= 620

    def test_resize(self, main_win, qapp_mod):
        main_win.resize(1200, 900)
        qapp_mod.processEvents()
        assert main_win.width() >= 1200
