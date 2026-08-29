# -*- coding: utf-8 -*-
# ui/theme.py - 主题引擎: 设计 token -> QSS 生成 + 平台窗口效果(Mica/暗色标题栏)。
#
# 跨平台策略(见 docs/VISION_部署子工具组.md 第十一章): 一套设计系统 + 平台适配层。
# 本模块顶层不 import PySide(纯 Python), 便于纯单元测试; 窗口效果函数以窗口对象为参数。
#
# 主题优先级(见 dsh-console-aio.MainWindow._load_theme):
#   Mica 可用(Win11 22H2+) -> 生成半透明 QSS(让 DWM 背景透出), 外部 theme.qss 不参与;
#   否则 -> 外部 ui/theme.qss 优先(手动微调), 缺失则用生成的不透明 QSS。

import ctypes
import sys


# ── 设计 token(主题唯一真源; 手动微调改这里, 重开即生效) ──
TOKENS = {
    # 背景(不透明 / Mica 半透明两套, 由 build_qss(mica=...) 选用)
    # ⚠ Mica 模式的 alpha 不能太高: 0.86+ 在深色背景下与实心几乎无差别(实测教训)。
    "bg": "#1e1e2e",
    "bg_rgba": "rgba(30, 30, 46, 0.55)",
    "bg_elevated": "#252535",
    "bg_elevated_rgba": "rgba(37, 37, 53, 0.65)",
    "bg_log": "#16161f",
    "bg_log_rgba": "rgba(22, 22, 31, 0.80)",
    "bg_hover": "#2e2e44",
    "bg_active": "#2f3353",
    # 边框 / 强调
    "border": "#33334a",
    "border_strong": "#3d3d5c",
    "border_hover": "#5858a0",
    "accent": "#4f6ef7",
    "accent_hover": "#6179ff",
    # 文本
    "text": "#e6e6e6",
    "text_dim": "#9a9ab0",
    "text_bright": "#ffffff",
    # 状态色
    "ok": "#7ecb6a",
    "warn": "#e5c07b",
    "err": "#e07a7a",
    "mon_ok": "#43d17f",
    "mon_bad": "#e5574d",
    # 字体(跨平台栈: Win -> mac -> Linux)
    "font": '"Microsoft YaHei UI", "PingFang SC", "Noto Sans CJK SC", sans-serif',
    "mono": "Consolas, 'Cascadia Mono', monospace",
    # 圆角
    "radius": "10px",
    "radius_sm": "6px",
    # 滚动条
    "scroll_bg": "#1a1a28",
    "scroll_handle": "#3d3d5c",
    "scroll_handle_hover": "#4f5674",
}


def build_qss(t=None, mica=False):
    """由 token 生成完整 QSS。mica=True 时主要表面用半透明背景(DWM Mica 透出)。"""
    t = t or TOKENS
    bg_main = t["bg_rgba"] if mica else t["bg"]
    bg_panel = t["bg_elevated_rgba"] if mica else t["bg_elevated"]
    bg_log = t["bg_log_rgba"] if mica else t["bg_log"]
    return f"""
* {{
    font-family: {t["font"]};
    font-size: 13px;
    color: {t["text"]};
}}
QMainWindow, QWidget#central, QWidget#body {{ background: {bg_main}; }}

/* 顶部栏 */
QFrame#topbar {{ background: {bg_panel}; border-bottom: 1px solid {t["border"]}; }}
QLabel#titleLbl {{ font-size: 17px; font-weight: bold; color: {t["text_bright"]}; }}
QLabel#verLbl {{ color: {t["text_dim"]}; font-size: 12px; }}
QFrame#vsep {{ background: {t["border_strong"]}; border: none; width: 1px; }}
QComboBox#deploy {{
    background: #2f2f45; border: 1px solid {t["border_strong"]}; border-radius: {t["radius_sm"]};
    padding: 4px 10px; min-width: 130px; color: {t["text"]};
}}
QComboBox#deploy::drop-down {{ border: none; width: 22px; }}
QComboBox#deploy QAbstractItemView {{
    background: #2f2f45; border: 1px solid {t["border_strong"]};
    selection-background-color: {t["accent"]};
    selection-color: #ffffff; color: {t["text"]}; outline: 0; padding: 4px;
}}

QPushButton {{
    background: #2f2f45; border: 1px solid {t["border_strong"]}; border-radius: {t["radius_sm"]};
    padding: 5px 14px; color: {t["text"]};
}}
QPushButton:hover {{ background: #3a3a58; border-color: {t["border_hover"]}; }}
QPushButton:pressed {{ background: #26263a; }}
QPushButton:disabled {{ color: #6a6a80; background: #2a2a3c; }}
QPushButton#primary {{ background: {t["accent"]}; border-color: {t["accent"]}; color: #fff; font-weight: bold; }}
QPushButton#primary:hover {{ background: {t["accent_hover"]}; border-color: {t["accent_hover"]}; }}

/* 左导航 */
QListWidget#nav {{
    background: {bg_panel}; border: none; border-right: 1px solid {t["border"]};
    outline: 0; padding-top: 6px;
}}
QListWidget#nav::item {{ padding: 9px 16px; border-left: 3px solid transparent; color: #b8b8cf; }}
QListWidget#nav::item:hover {{ background: {t["bg_hover"]}; color: #fff; }}
QListWidget#nav::item:selected {{
    background: {t["bg_active"]}; color: {t["text_bright"]};
    border-left: 3px solid {t["accent"]}; font-weight: bold;
}}

/* 右状态栏 */
QFrame#rightBar {{ background: {bg_panel}; border-left: 1px solid {t["border"]}; }}
QLabel#rightTitle {{ color: {t["text_dim"]}; font-size: 12px; padding: 2px 4px; font-weight: bold; }}
QLabel#monDot {{ font-size: 15px; }}
QLabel#monName {{ color: {t["text"]}; font-size: 12px; }}
QLabel#monNote {{ color: {t["text_dim"]}; font-size: 11px; }}
QLabel#monVal {{ color: {t["text"]}; font-size: 12px; font-weight: bold; }}

/* 页面卡片 */
QFrame#card {{
    background: {bg_panel}; border: 1px solid {t["border"]}; border-radius: {t["radius"]};
}}
QFrame#card:hover {{ border-color: {t["border_hover"]}; }}
QLabel#cardTitle {{ font-size: 15px; font-weight: bold; color: {t["text_bright"]}; }}
QLabel#cardHint {{ color: {t["text_dim"]}; font-size: 12px; }}
QFrame#pageHostBg {{ background: {bg_main}; }}

/* 日志区 */
QFrame#logWrap {{ background: {bg_panel}; border-top: 1px solid {t["border"]}; }}
QLabel#logTitle {{ color: {t["text_dim"]}; font-size: 12px; padding: 2px 4px; }}
QTextEdit#log {{
    background: {bg_log}; border: 1px solid #2c2c40; border-radius: {t["radius_sm"]};
    padding: 6px; font-family: {t["mono"]}; font-size: 12px; color: {t["text"]};
    selection-background-color: {t["accent"]};
}}

/* 底部状态栏 */
QLabel#statusBar {{
    background: {bg_panel}; border-top: 1px solid {t["border"]};
    padding: 5px 12px; color: {t["text_dim"]}; font-size: 12px;
}}

/* 全局滚动条(修掉白色拖拽条) */
QScrollBar:vertical {{
    background: {t["scroll_bg"]}; width: 12px; margin: 0; border: none;
}}
QScrollBar::handle:vertical {{
    background: {t["scroll_handle"]}; min-height: 30px; border-radius: {t["radius_sm"]}; margin: 2px;
}}
QScrollBar::handle:vertical:hover {{ background: {t["scroll_handle_hover"]}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; background: none; border: none; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
QScrollBar:horizontal {{
    background: {t["scroll_bg"]}; height: 12px; margin: 0; border: none;
}}
QScrollBar::handle:horizontal {{
    background: {t["scroll_handle"]}; min-width: 30px; border-radius: {t["radius_sm"]}; margin: 2px;
}}
QScrollBar::handle:horizontal:hover {{ background: {t["scroll_handle_hover"]}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; background: none; border: none; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; }}

/* 工具提示/下拉菜单也覆盖掉系统色 */
QToolTip {{ background: #2f2f45; color: {t["text"]}; border: 1px solid #4f5674; padding: 4px 8px; }}
QMenu {{ background: #2f2f45; border: 1px solid {t["border_strong"]}; }}
QMenu::item {{ padding: 6px 22px; }}
QMenu::item:selected {{ background: {t["accent"]}; }}
QScrollArea {{ border: none; }}
"""


# ── 平台能力探测与窗口效果(Win11 Mica / 暗色标题栏) ──

def is_windows_11_22h2():
    """Windows 11 22H2+(build >= 22621)才支持 DWM Mica 背景。"""
    if sys.platform != "win32":
        return False
    try:
        v = sys.getwindowsversion()
        return v.major >= 10 and v.build >= 22621
    except Exception:
        return False


def apply_window_effects(window):
    """对顶层窗口应用平台效果: Win11 22H2+ 启用暗色标题栏 + Mica 背景。

    返回 True 表示 Mica 已启用(调用方应使用 build_qss(mica=True) 的半透明主题)。
    失败(旧系统/非 Windows/offscreen)静默回退, 不抛异常。
    """
    if not is_windows_11_22h2():
        return False
    try:
        from PySide6.QtCore import Qt  # 惰性导入: 本模块顶层保持纯 Python
        window.setAttribute(Qt.WA_TranslucentBackground, True)
        hwnd = int(window.winId())
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        DWMWA_SYSTEMBACKDROP_TYPE = 38
        DWMSBT_MAINWINDOW = 2
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(ctypes.c_int(1)), ctypes.sizeof(ctypes.c_int))
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_SYSTEMBACKDROP_TYPE,
            ctypes.byref(ctypes.c_int(DWMSBT_MAINWINDOW)), ctypes.sizeof(ctypes.c_int))
        return True
    except Exception:
        return False
