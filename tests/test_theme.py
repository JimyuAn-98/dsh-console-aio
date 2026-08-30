# -*- coding: utf-8 -*-
# test_theme.py - ui/theme.py 主题引擎纯单元测试(顶层零 Qt 依赖, 不构造窗口/不碰资源)。


def test_tokens_have_required_keys():
    from ui.theme import TOKENS
    for key in ("bg", "bg_rgba", "bg_elevated", "text", "text_dim", "accent",
                "accent_hover", "ok", "warn", "err", "font", "mono",
                "radius", "radius_sm", "border", "border_hover"):
        assert key in TOKENS, key


def test_build_qss_contains_key_selectors():
    from ui.theme import TOKENS, build_qss
    qss = build_qss(mica=False)
    for sel in ("QMainWindow", "QPushButton:hover", "QListWidget#nav::item:selected",
                "QTextEdit#log", "QFrame#card", "QToolTip"):
        assert sel in qss, sel
    # token 生效: 主背景取自 TOKENS(换配色无需改本测试)
    assert TOKENS["bg"] in qss


def test_build_qss_mica_variant_uses_rgba_panels():
    from ui.theme import TOKENS, build_qss
    qss = build_qss(mica=True)
    # Mica(分层)模式: 主背景(bg_rgba 染色层)/面板 rgba 半透明, 不再是全透明
    assert TOKENS["bg_rgba"] in qss
    assert TOKENS["bg_elevated_rgba"] in qss


def test_bg_rgba_follows_bg_hex():
    # 主背景联动: 改 bg 本色时 bg_rgba 的 rgb 跟随、alpha(染色深度)保留;
    # set_active({}) 重派生也不动滑杆调过的 alpha
    from ui.theme import TOKENS, get_alpha, reset_default, set_active, set_alpha
    try:
        a0 = get_alpha("bg_rgba")
        set_active({"bg": "#ff0000"})
        assert TOKENS["bg_rgba"] == "rgba(255, 0, 0, %.2f)" % a0
        set_alpha("bg_rgba", 0.7)
        set_active({})
        assert get_alpha("bg_rgba") == 0.7
        assert TOKENS["bg_rgba"].startswith("rgba(255, 0, 0, ")
    finally:
        reset_default()


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


def test_build_qss_partial_tokens_merge_defaults():
    # 部分覆盖: 只给 accent 也能生成完整 QSS(其余 key 落回 TOKENS 默认), 不 KeyError
    from ui.theme import build_qss
    qss = build_qss({"accent": "#123456"}, mica=False)
    assert "#123456" in qss
    assert "QToolTip" in qss


def test_set_active_updates_and_derives():
    # 激活主题: accent 更新且低透明派生色自动重算; 测试间恢复出厂防串扰
    from ui.theme import TOKENS, reset_default, set_active
    try:
        set_active({"accent": "#ff0000"})
        assert TOKENS["accent"] == "#ff0000"
        assert TOKENS["accent_soft"] == "rgba(255, 0, 0, 70)"
        assert TOKENS["accent_glow"] == "rgba(255, 0, 0, 0.35)"
    finally:
        reset_default()


def test_set_active_ignores_unknown_and_invalid():
    # 白名单外(非颜色 token)/非法值一律忽略, 脏配置不致命
    from ui.theme import TOKENS, reset_default, set_active
    try:
        before = dict(TOKENS)
        set_active({"accent": "not-a-color", "bogus_key": "#123456",
                    "radius": "#123456"})
        assert TOKENS == before
    finally:
        reset_default()


def test_alpha_roundtrip():
    # set_alpha 只改 alpha 保留 rgb, 并裁剪到 0.05-1.0
    from ui.theme import TOKENS, get_alpha, reset_default, set_alpha
    try:
        set_alpha("bg_elevated_rgba", 0.8)
        assert get_alpha("bg_elevated_rgba") == 0.8
        assert TOKENS["bg_elevated_rgba"].startswith("rgba(34, 39, 53, ")
        set_alpha("bg_elevated_rgba", 5)   # 越界(过大) -> 裁到上限
        assert get_alpha("bg_elevated_rgba") == 1.0
        set_alpha("bg_elevated_rgba", 0)   # 越界(过小) -> 裁到下限
        assert get_alpha("bg_elevated_rgba") == 0.05
    finally:
        reset_default()


def test_current_overrides_diff():
    # 覆盖集 = 与出厂的差异(含调过的透明度, 不含派生色); 恢复默认后为空
    from ui.theme import current_overrides, reset_default, set_active
    reset_default()
    assert current_overrides() == {}
    try:
        set_active({"accent": "#22c55e",
                    "bg_elevated_rgba": "rgba(34, 39, 53, 0.3)"})
        ov = current_overrides()
        assert ov["accent"] == "#22c55e"
        assert ov["bg_elevated_rgba"] == "rgba(34, 39, 53, 0.3)"
        assert "accent_soft" not in ov
    finally:
        reset_default()


def test_theme_file_roundtrip(tmp_path):
    # 具名主题文件的 存/列/载/删; 非法名字拒绝; 不存在返回 None
    from ui import theme as dsh_theme
    saved = dsh_theme.themes_dir
    dsh_theme.themes_dir = lambda: str(tmp_path)
    try:
        assert dsh_theme.list_themes() == []
        assert dsh_theme.save_theme_file("我的主题", {"accent": "#22c55e"})
        assert dsh_theme.save_theme_file("../evil", {}) is False
        assert dsh_theme.list_themes()[0][0] == "我的主题"
        assert dsh_theme.load_theme_file("我的主题") == {"accent": "#22c55e"}
        assert dsh_theme.load_theme_file("不存在") is None
        assert dsh_theme.delete_theme_file("我的主题")
        assert dsh_theme.list_themes() == []
    finally:
        dsh_theme.themes_dir = saved


def test_mica_probe_returns_bool():
    from ui.theme import is_windows_11_22h2
    assert isinstance(is_windows_11_22h2(), bool)
