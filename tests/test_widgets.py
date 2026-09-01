# -*- coding: utf-8 -*-
# test_widgets.py - ui/widgets.py 自定义组件单元测试（含 ConfirmBanner 等）。

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def test_confirm_banner_initial_state(qapp):
    from ui.widgets import ConfirmBanner

    parent = QWidget()
    banner = ConfirmBanner(parent)

    # 初始状态默认隐藏
    assert banner.isHidden()
    assert banner._callback is None
    parent.close()


def test_confirm_banner_ask_and_dismiss(qapp):
    from ui.widgets import ConfirmBanner

    parent = QWidget()
    banner = ConfirmBanner(parent)

    called = []

    def on_confirm():
        called.append(True)

    banner.ask("危险操作", "确定删除该项目吗？", on_confirm, level="danger", confirm_text="确认删除")

    assert not banner.isHidden()
    assert banner._callback is not None
    assert "危险操作" in banner._title_lbl.text()
    assert "确定删除该项目吗？" in banner._msg_lbl.text()
    assert banner._ok_btn.text() == "确认删除"
    assert banner.property("level") == "danger"

    # 点击取消
    banner.dismiss()
    assert banner.isHidden()
    assert banner._callback is None
    assert len(called) == 0

    parent.close()


def test_confirm_banner_confirm_action(qapp):
    from ui.widgets import ConfirmBanner

    parent = QWidget()
    banner = ConfirmBanner(parent)

    called = []

    def on_confirm():
        called.append(True)

    banner.ask("警告操作", "是否执行该变更？", on_confirm, level="warn", confirm_text="确认执行")

    assert not banner.isHidden()
    assert banner.property("level") == "warn"

    # 触发确认
    banner._on_ok()

    # 回调执行且 banner 自动隐藏
    assert len(called) == 1
    assert called[0] is True
    assert banner.isHidden()
    assert banner._callback is None

    parent.close()


def test_confirm_banner_key_press_escape(qapp):
    from ui.widgets import ConfirmBanner
    from PySide6.QtGui import QKeyEvent

    parent = QWidget()
    banner = ConfirmBanner(parent)

    called = []
    banner.ask("测试", "按 Esc 取消", lambda: called.append(True))
    assert not banner.isHidden()

    # 模拟 Esc 键
    event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
    banner.keyPressEvent(event)

    assert banner.isHidden()
    assert banner._callback is None
    assert len(called) == 0

    parent.close()
