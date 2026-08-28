# -*- coding: utf-8 -*-
# test_gui_ui.py - 纯 GUI 元素/事件/数据流测试(完全离屏, 零真实资源)。
#
# 目标: 不打开真实 GUI、不连真实 SSH/端口/进程、不启停 dsh, 就能验证 GUI 元素及其
#       对应功能(页面构造/导航/按钮接线/日志桥/右栏状态/对话框字段)是否生效。
#
# 隔离手段:
#   - DSH_AIO_CONFIG 指向假 config.json(占位符, 无真实服务器/IP);
#     主程序 CONFIG 与 dsh_data.load_deployments 全部读假配置。
#   - DSH_HOME 指向假目录, 数据页读假数据。
#   - 拦截 MainWindow._start_monitor(真实健康监控线程)与 _stream_cmd(真实子进程)。
#   - --smoke 模式: OverviewPage/总览等不做真联网/真操作。
#   - 硬拦截 threading.Thread.start(main_win 存续期间): 任何后台线程都不真正运行,
#     线程对象只被登记进 _BLOCKED_THREADS, 目标函数绝不执行 —— 即使上述拦截有遗漏,
#     页面构造器起的 daemon 线程也探测不到真实端口(如 3080)。
#
# 关于模块引用: 真实源文件是 dsh-console-aio.py(文件名带连字符, 不能直接 import),
# 因此本文件用 console fixture(在假环境下通过 importlib 动态加载)拿主程序模块对象,
# 并用 console.NAV_ITEMS / console.OverviewPage 等访问其符号(不再 import dsh_console_aio,
# 以避免 Pylance 的 reportMissingImports)。
#
# 注意: 本文件构造真实 MainWindow 与各页面, 页面构造器会起 daemon 后台线程。这些测试
#       由人工执行; 自动运行的风险边界与拦截说明见 docs/TESTING.md。

import os
import sys
import importlib
import threading

import pytest

from fake_env import default_env

pytest.importorskip("PySide6")

# 本文件构造真实 MainWindow 与全部页面 —— 按铁律(HANDOFF.md)不得默认自动运行,
# 仅 `-m gui` 人工执行(与 test_gui_smoke.py 同等待遇)。
pytestmark = pytest.mark.gui

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 被拦截(未真正启动)的线程对象登记处: 哨兵测试据此断言线程拦截生效
_BLOCKED_THREADS = []


def _import_console():
    # 动态导入 dsh-console-aio.py(文件名含连字符, 不能直接 import)
    # 需在 DSH_AIO_CONFIG/DSH_HOME 设好后调用, 否则主程序会读真实 config.json。
    main_path = os.path.join(ROOT_DIR, "dsh-console-aio.py")
    name = "dsh_console_aio"
    spec = importlib.util.spec_from_file_location(name, main_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def qapp_mod():
    # module-scoped QApplication(离屏)
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(scope="module")
def ui_env(tmp_path_factory):
    # 构造假 config + 假 DSH_HOME, 设好 DSH_AIO_CONFIG/DSH_HOME
    root = tmp_path_factory.mktemp("gui-ui")
    cfg_file, fake_home, restore = default_env(root)
    yield cfg_file, fake_home
    restore()


@pytest.fixture(scope="module")
def console(ui_env, qapp_mod):
    # 在假环境下导入主程序(仅一次)
    return _import_console()


@pytest.fixture(scope="module")
def main_win(qapp_mod, console):
    # 离屏构造 MainWindow(smoke=True), 拦截真实副作用
    _orig_monitor = console.MainWindow._start_monitor
    _orig_stream = console.MainWindow._stream_cmd
    console.MainWindow._start_monitor = lambda self: None
    console.MainWindow._stream_cmd = lambda self, cmd, cwd=None, env=None: True
    # 第 5 道隔离: 硬拦截 Thread.start 作为兜底 —— 即使上面两处拦截漏了某个入口,
    # 页面构造器起的 daemon 线程也只是被登记, 线程目标函数绝不执行, 不可能探测真实端口。
    _orig_thread_start = threading.Thread.start

    def _blocked_start(self, *args, **kwargs):
        # 只登记线程对象即返回, 不真正创建 OS 线程
        _BLOCKED_THREADS.append(self)

    threading.Thread.start = _blocked_start
    try:
        win = console.MainWindow(smoke=True)
        yield win
        win.close()
        qapp_mod.processEvents()
    finally:
        # 三道拦截全部恢复, 缺一个都会把假环境泄漏到 fixture 之外的代码
        threading.Thread.start = _orig_thread_start
        console.MainWindow._start_monitor = _orig_monitor
        console.MainWindow._stream_cmd = _orig_stream


class TestWindowConstruction:
    # 窗口基础构造(假配置)
    def test_title(self, main_win):
        assert main_win.windowTitle().startswith("dsh 控制台")

    def test_nav_count(self, main_win, console):
        assert main_win.nav.count() == len(console.NAV_ITEMS) > 0

    def test_deploy_combo_default_local(self, main_win):
        assert main_win.deploy.currentText() == "本机"
        assert main_win._current_deploy is None

    def test_stack_initial_overview(self, main_win, console):
        assert isinstance(main_win.stack.currentWidget(), console.OverviewPage)

    def test_bridge_attached(self, main_win):
        assert main_win.bridge._view is not None

    def test_smoke_flag(self, main_win):
        assert main_win.smoke is True


class TestNavToPages:
    # 每个导航项都能映射到页面(不崩溃)
    PAGES = ["overview", "tunnels", "sessions", "agents", "profiles",
             "plugins", "taskboard", "usage", "llm", "ops",
             "keys", "version", "deployments"]

    @pytest.mark.parametrize("key", PAGES)
    def test_show_page(self, main_win, qapp_mod, key):
        main_win._show_page(key)
        qapp_mod.processEvents()
        assert main_win.stack.currentWidget() is not None

    def test_page_types(self, main_win, qapp_mod, console):
        from pyside.pages_sessions import SessionPage
        from pyside.pages_deployments import DeploymentPage
        from pyside.pages_version import VersionPage
        expect = {"overview": console.OverviewPage, "tunnels": console.TunnelsPage,
                  "sessions": SessionPage, "deployments": DeploymentPage,
                  "version": VersionPage}
        for key, cls in expect.items():
            main_win._show_page(key)
            qapp_mod.processEvents()
            assert isinstance(main_win.stack.currentWidget(), cls), key


class TestNavMappingAll:
    # NAV_ITEMS 全部 key 都能生成页面
    def test_all_keys(self, main_win, qapp_mod, console):
        for label, key in console.NAV_ITEMS:
            main_win._show_page(key)
            qapp_mod.processEvents()
            assert main_win.stack.currentWidget() is not None, "%s(%s)" % (label, key)


class TestLogBridge:
    # 线程安全日志桥: emit 应出现在日志区
    def test_emit_ok(self, main_win, qapp_mod):
        main_win.bridge.emit("ui unit log", "ok")
        qapp_mod.processEvents()
        assert "ui unit log" in main_win.log_view.toPlainText()

    def test_emit_err(self, main_win, qapp_mod):
        main_win.bridge.emit("ui err log", "err")
        qapp_mod.processEvents()
        assert "ui err log" in main_win.log_view.toPlainText()

    def test_loge_status(self, main_win, qapp_mod):
        main_win.loge("ui status")
        qapp_mod.processEvents()
        assert main_win.status.text() == "ui status"


class TestRightBar:
    # 右栏状态单元格更新(仅 UI 状态, 不真探测端口)
    def test_right_bar_exists(self, main_win):
        assert main_win.right is not None

    def test_set_state_existing(self, main_win, qapp_mod):
        if main_win.right._cells:
            key = list(main_win.right._cells.keys())[0]
            main_win.right.set_state(key, True, 42)
            qapp_mod.processEvents()
            main_win.right.set_state(key, False, -1)
            qapp_mod.processEvents()

    def test_set_state_missing(self, main_win, qapp_mod):
        main_win.right.set_state("NONEXISTENT", True, 100)
        qapp_mod.processEvents()


class TestTunnelsPage:
    # 隧道页卡片构造 + 动作按钮接线(不点真实启停)
    def test_cards_built(self, main_win, qapp_mod, console):
        main_win._show_page("tunnels")
        qapp_mod.processEvents()
        page = main_win.stack.currentWidget()
        assert isinstance(page, console.TunnelsPage)
        cards = set(page._cards.keys())
        items = set(i["key"] for i in console.ITEMS)
        assert cards == items

    def test_action_buttons_wired(self, main_win, qapp_mod):
        # 每个 ITEM 的动作按钮都存在且 wired 到处理函数(不点击 -> 不触发真实操作)。
        # 分层后: 页面只分派, 业务经 main_win.service 信号桥执行; 内联隧道实现已删除。
        main_win._show_page("tunnels")
        qapp_mod.processEvents()
        page = main_win.stack.currentWidget()
        assert page._on_action is not None
        assert main_win.service is not None
        assert not hasattr(page, "_run_python_tunnel")
        assert not hasattr(page, "_stop_py_tunnel")

    def test_service_card_connected_to_page(self, main_win, qapp_mod):
        # service.card -> 当前隧道页 _apply_card: 信号桥接通后卡片圆点随信号更新。
        main_win._show_page("tunnels")
        qapp_mod.processEvents()
        page = main_win.stack.currentWidget()
        main_win.service.card.emit("dsh-tunnel", True)
        qapp_mod.processEvents()
        page._apply_card("dsh-tunnel", False)
        qapp_mod.processEvents()


class TestOverviewPage:
    # 总览页在 smoke 模式显示演示/未配置文案
    def test_smoke_shows_demo(self, main_win, qapp_mod, console):
        main_win._show_page("overview")
        qapp_mod.processEvents()
        page = main_win.stack.currentWidget()
        assert isinstance(page, console.OverviewPage)
        text = page.dep_status.text()
        assert ("演示" in text) or ("未配置" in text)

    def test_refresh_smoke_noop(self, main_win, qapp_mod):
        main_win._show_page("overview")
        main_win.stack.currentWidget().refresh()
        qapp_mod.processEvents()


class TestForceRefresh:
    # 立即刷新(overview)不崩溃
    def test_force_refresh(self, main_win, qapp_mod):
        main_win._force_refresh()
        qapp_mod.processEvents()


class TestDeploySwitch:
    # 部署切换不崩溃
    def test_switch_local(self, main_win, qapp_mod):
        main_win._on_deploy_changed(0)
        qapp_mod.processEvents()
        assert main_win._current_deploy is None

    def test_deploy_rebuilds_page(self, main_win, qapp_mod):
        main_win._show_page("sessions")
        qapp_mod.processEvents()
        main_win._on_deploy_changed(0)
        qapp_mod.processEvents()
        assert main_win.stack.currentWidget() is not None


class TestLayoutFacts:
    # GUI 事实布局断言: 真实控件是否存在/层级/文字/尺寸(离屏下控件是真实构造的)。
    def _topbar(self, main_win):
        from PySide6.QtWidgets import QFrame
        bar = main_win.findChild(QFrame, "topbar")
        assert bar is not None, "topbar frame missing"
        return bar

    def test_topbar_buttons_exist(self, main_win):
        # 顶部栏应含 标题/版本/部署下拉 + 配置/环境/安装/立即刷新 4 个入口按钮
        from PySide6.QtWidgets import QPushButton
        bar = self._topbar(main_win)
        btns = [b.text() for b in bar.findChildren(QPushButton)]
        assert set(btns) >= {"配置", "环境", "安装", "立即刷新"}, btns
        # 部署下拉存在且默认"本机"
        assert main_win.deploy.objectName() == "deploy"

    def test_nav_labels_match_constants(self, main_win, console):
        # 左导航每一项的文字应与 NAV_ITEMS 一致(事实层级/文案)
        labels = [main_win.nav.item(i).text() for i in range(main_win.nav.count())]
        assert labels == [l for l, _ in console.NAV_ITEMS]

    def test_right_bar_sections_with_empty_ports(self, main_win):
        # 假 config 端口全空 => 右栏不应有本地端口/远程隧道单元格
        assert main_win.right._cells == {}, main_win.right._cells
        # 但分区标题应仍存在
        from PySide6.QtWidgets import QLabel
        texts = [l.text() for l in main_win.right.findChildren(QLabel)]
        assert "本机端口" in texts
        assert "公网服务器 反向隧道" in texts

    def test_log_area_present(self, main_win):
        assert main_win.log_view is not None
        # 日志区固定高度
        assert main_win.log_view.height() > 40

    def test_tunnels_cards_have_action_buttons(self, main_win, qapp_mod, console):
        # 每张隧道卡片应含其 ITEMS 声明的动作按钮(事实层级)
        from PySide6.QtWidgets import QFrame, QPushButton
        main_win._show_page("tunnels")
        qapp_mod.processEvents()
        page = main_win.stack.currentWidget()
        for item in console.ITEMS:
            expected = [console.BTN_TEXT[a] for a in item["actions"]]
            card_btns = []
            for card in page.findChildren(QFrame, "card"):
                card_btns.append([b.text() for b in card.findChildren(QPushButton)])
            flat = [t for grp in card_btns for t in grp]
            for t in expected:
                assert t in flat, "按钮缺失: %s 的 %s" % (item["key"], t)

    def test_window_resize_reflects(self, main_win, qapp_mod):
        # resize 后实际几何应反映请求尺寸
        main_win.resize(1280, 900)
        qapp_mod.processEvents()
        assert main_win.width() >= 1280
        assert main_win.height() >= 900


class TestWindowSize:
    # 窗口尺寸约束
    def test_minimum(self, main_win):
        assert main_win.minimumWidth() >= 960
        assert main_win.minimumHeight() >= 620


class TestThreadInterception:
    # 第 5 道隔离的哨兵: main_win 存续期间 threading.Thread.start 被硬拦截
    def test_thread_start_blocked(self, main_win):
        # 确定性断言: start() 只登记不调度, 目标函数绝不执行, 不依赖线程时序。
        # 依赖 main_win 是刻意的 —— 拦截窗口随该 fixture 装卸, 不请求它则哨兵无效。
        hit = []
        before = len(_BLOCKED_THREADS)
        t = threading.Thread(target=lambda: hit.append(1), daemon=True)
        t.start()
        assert hit == []
        assert len(_BLOCKED_THREADS) == before + 1
