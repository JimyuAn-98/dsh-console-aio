# -*- coding: utf-8 -*-
# test_theme.py - ui/theme.py 主题引擎纯单元测试(顶层零 Qt 依赖, 不构造窗口/不碰资源)。


def test_tokens_have_required_keys():
    from ui.theme import TOKENS
    for key in ("bg", "bg_rgba", "bg_elevated", "text", "text_dim", "accent",
                "accent_hover", "ok", "warn", "err", "font", "mono",
                "radius", "radius_sm", "border", "border_hover"):
        assert key in TOKENS, key


def test_build_qss_contains_key_selectors():
    from ui.theme import build_qss
    qss = build_qss(mica=False)
    for sel in ("QMainWindow", "QPushButton:hover", "QListWidget#nav::item:selected",
                "QTextEdit#log", "QFrame#card", "QToolTip"):
        assert sel in qss, sel
    # token 生效: 主背景是 token 值而非默认值
    assert "#1e1e2e" in qss


def test_build_qss_mica_variant_uses_rgba():
    from ui.theme import TOKENS, build_qss
    qss = build_qss(mica=True)
    # 直接断言 token 值, 避免改 token 时测试不同步
    assert TOKENS["bg_rgba"] in qss
    assert TOKENS["bg_elevated_rgba"] in qss


def test_custom_tokens_override():
    from ui.theme import build_qss
    qss = build_qss({"bg": "#000000", "bg_rgba": "rgba(0,0,0,0.5)",
                     "bg_elevated": "#111111", "bg_elevated_rgba": "rgba(0,0,0,0.5)",
                     "bg_log": "#000000", "bg_log_rgba": "rgba(0,0,0,0.5)",
                     "bg_hover": "#1a1a1a", "bg_active": "#222222",
                     "text": "#fff", "text_dim": "#ccc", "text_bright": "#fff",
                     "accent": "#123456", "accent_hover": "#234567",
                     "border": "#222", "border_strong": "#333", "border_hover": "#444",
                     "font": "sans-serif", "mono": "monospace",
                     "radius": "4px", "radius_sm": "2px",
                     "scroll_bg": "#000", "scroll_handle": "#333", "scroll_handle_hover": "#444",
                     "ok": "#0f0", "warn": "#ff0", "err": "#f00",
                     "mon_ok": "#0f0", "mon_bad": "#f00"}, mica=False)
    assert "#000000" in qss
    assert "#123456" in qss


def test_mica_probe_returns_bool():
    from ui.theme import is_windows_11_22h2
    assert isinstance(is_windows_11_22h2(), bool)
