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
import json
import os
import re
import sys


# ── 设计 token(主题唯一真源; 手动微调改这里, 重开即生效) ──
# 色相基准(2026-08-30 换版): accent #5686fe(纯蓝 223°), 结构中性色(背景/边框/面板)
# 统一对齐到 ~224° 蓝相(旧版为 240° 蓝紫); 文字灰(text/text_dim/nav_text)饱和度低、
# 色相差异不可感知, 维持原值不跟转。
TOKENS = {
    # 背景(不透明; Mica 模式下顶层走 bg_rgba 半透明层, 由 DWM 模糊材质透出)
    "bg": "#1b202e",
    # 主背景的 rgba 形式: rgb 与 bg 联动(改 bg 本色自动跟随), alpha 是"模糊上的染色深度"
    # (主题页「主背景」透明度滑杆; 1.0=等同纯 QSS 不透明, 越低透出越多系统模糊)
    "bg_rgba": "rgba(27, 32, 46, 0.42)",
    "bg_elevated": "#222735",
    "bg_elevated_rgba": "rgba(34, 39, 53, 0.55)",
    "bg_log": "#14181f",
    "bg_log_rgba": "rgba(20, 24, 31, 0.75)",
    # 页面宿主底色(Mica/亚克力模式): 比面板更透一层, 保持层级一致(OverviewPage 等
    # 空白页不再显得"更透明")
    "bg_page_rgba": "rgba(27, 32, 46, 0.42)",
    "bg_hover": "#2b3144",
    "bg_active": "#2c3453",
    # 边框 / 强调
    "border": "#2f364a",
    "border_strong": "#39425c",
    "border_hover": "#5264a0",
    "accent": "#5686fe",
    "accent_hover": "#7aa3ff",
    # accent 的低透明派生(表格选中软色块 / 分栏手柄 hover 辉光; 与 accent 同步换)
    "accent_soft": "rgba(86, 134, 254, 70)",
    "accent_glow": "rgba(86, 134, 254, 0.35)",
    # 控件底色(按钮/下拉/菜单/工具提示共用的凸起面板) + 内嵌控件描边
    "btn_bg": "#2c3345",
    "btn_hover": "#363f58",
    "btn_pressed": "#232a3a",
    "btn_disabled_bg": "#272d3c",
    "input_disabled_bg": "#242a3a",
    "inset_border": "#292f40",
    "table_alt": "#202638",
    # 文本
    "text": "#e6e6e6",
    "text_dim": "#9a9ab0",
    "text_bright": "#ffffff",
    "nav_text": "#b8b8cf",
    "text_disabled": "#6a6a80",
    "tooltip_border": "#4b5878",
    # 强调/选中底上的文字色(浅色主题反转为深色; 与 accent 同源配色, 不入可编辑白名单)
    "on_accent": "#ffffff",
    "on_selection": "#ffffff",
    # 状态色
    "ok": "#7ecb6a",
    "warn": "#e5c07b",
    "err": "#e07a7a",
    "err_hover": "#eb9c9c",
    "mon_ok": "#43d17f",
    "mon_bad": "#e5574d",
    # 字体(跨平台栈: Win -> mac -> Linux)
    "font": '"Microsoft YaHei UI", "PingFang SC", "Noto Sans CJK SC", sans-serif',
    "mono": "Consolas, 'Cascadia Mono', monospace",
    # 圆角
    "radius": "10px",
    "radius_sm": "6px",
    # 滚动条
    "scroll_bg": "#181d28",
    "scroll_handle": "#39425c",
    "scroll_handle_hover": "#4b5878",
}


# ── 实时换肤/主题管理(纯 Python; 调用链: 主题页 -> MainWindow.apply_theme -> set_active) ──
# 激活模型: TOKENS 即"当前生效色板"—— QSS 由它生成, 画家层(ui/widgets)逐帧读它;
# DEFAULT_TOKENS 是模块加载时冻结的出厂预设。config.json["theme"] 存启动默认覆盖,
# themes/*.json 是具名主题文件(两者格式相同: {token: 颜色值} 最小覆盖集)。

DEFAULT_TOKENS = dict(TOKENS)   # 深色出厂预设快照(恢复默认 = 从当前变体的 base 拷回)

# ── 浅色主题变体(LIGHT_TOKENS): 与深色同一套 token 键, 值全为浅色。
# 由主题页「明/暗」切换启用, config.json["theme_variant"] 持久化(深色仍为启动默认)。
# rgba 半透明层在亚克力模式下把浅色托在 DWM 模糊之上; 文字/边框/控件全面反转为浅色系。
LIGHT_TOKENS = {
    # 背景
    "bg": "#eef1f6",
    "bg_rgba": "rgba(238, 241, 246, 0.42)",
    "bg_elevated": "#f7f9fc",
    "bg_elevated_rgba": "rgba(247, 249, 252, 0.55)",
    "bg_log": "#ffffff",
    "bg_log_rgba": "rgba(255, 255, 255, 0.75)",
    "bg_page_rgba": "rgba(238, 241, 246, 0.42)",
    "bg_hover": "#dde3ee",
    "bg_active": "#d3ddf5",
    # 边框 / 强调
    "border": "#d5dbe6",
    "border_strong": "#c3cbd9",
    "border_hover": "#9fb0d8",
    "accent": "#5686fe",
    "accent_hover": "#3068f0",
    "accent_soft": "rgba(86, 134, 254, 40)",   # _derive_tokens 会按 accent 重算
    "accent_glow": "rgba(86, 134, 254, 0.22)",
    # 控件
    "btn_bg": "#ffffff",
    "btn_hover": "#e7edf7",
    "btn_pressed": "#d9e1ef",
    "btn_disabled_bg": "#eef1f6",
    "input_disabled_bg": "#eef1f6",
    "inset_border": "#cdd5e2",
    "table_alt": "#f2f5fa",
    # 文字
    "text": "#23262e",
    "text_dim": "#6b7280",
    "text_bright": "#14171d",
    "nav_text": "#4b5160",
    "text_disabled": "#9aa1af",
    "tooltip_border": "#c3cbd9",
    "on_accent": "#ffffff",
    "on_selection": "#23262e",
    # 状态色(浅色底上加深保证对比度)
    "ok": "#2f9e44",
    "warn": "#b7791f",
    "err": "#d64545",
    "err_hover": "#e55a5a",
    "mon_ok": "#1f9d63",
    "mon_bad": "#e03e2f",
    # 字体 / 圆角 / 滚动条(与深色一致; 滚动条底色转浅)
    "font": '"Microsoft YaHei UI", "PingFang SC", "Noto Sans CJK SC", sans-serif',
    "mono": "Consolas, 'Cascadia Mono', monospace",
    "radius": "10px",
    "radius_sm": "6px",
    "scroll_bg": "#e2e6ee",
    "scroll_handle": "#c3cbd9",
    "scroll_handle_hover": "#9fb0d8",
}


# 主题页可编辑的 hex 颜色 token(按分组展示)。不在白名单的: accent_soft/accent_glow
# (accent 派生色, 自动重算)、bg_rgba(未使用的预留 token)、font/mono/radius(非颜色)。
COLOR_GROUPS = (
    ("背景", ("bg", "bg_elevated", "bg_log", "bg_hover", "bg_active")),
    ("边框", ("border", "border_strong", "border_hover", "inset_border", "tooltip_border")),
    ("强调", ("accent", "accent_hover")),
    ("控件", ("btn_bg", "btn_hover", "btn_pressed", "btn_disabled_bg",
             "input_disabled_bg", "table_alt")),
    ("滚动条", ("scroll_bg", "scroll_handle", "scroll_handle_hover")),
    ("文字", ("text", "text_bright", "text_dim", "nav_text", "text_disabled")),
    ("状态", ("ok", "warn", "err", "mon_ok", "mon_bad")),
)
# 可调透明度的 rgba token(仅亚克力/Mica 半透明模式下有可见效果); bg_rgba = 主背景
# 在模糊材质上的染色层(rgb 随 bg 联动)
ALPHA_KEYS = (
    ("bg_rgba", "主背景"),
    ("bg_elevated_rgba", "面板/卡片"),
    ("bg_log_rgba", "日志/输入区"),
    ("bg_page_rgba", "页面宿主"),
)
# 可持久化 key = 可编辑 hex 色 + 透明度 token(派生色不入覆盖集)
PERSIST_KEYS = tuple(k for _, ks in COLOR_GROUPS for k in ks) \
    + tuple(t for t, _ in ALPHA_KEYS)

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_RGBA_RE = re.compile(r"^rgba\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*[\d.]+\s*\)$")
_RGBA_ALPHA_RE = re.compile(r"^(rgba\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*)([\d.]+)(\s*\))$")


def valid_color(v):
    # 合法颜色值: #rrggbb 或 rgba(r, g, b, a) 字符串(主题页/配置校验共用)
    return isinstance(v, str) and bool(_HEX_RE.match(v) or _RGBA_RE.match(v))


def _hex_rgb(v):
    v = v.lstrip("#")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def _derive_tokens():
    # 联动派生: accent 的低透明派生色自动重算(用户只调本色);
    # bg_rgba 的 rgb 随 bg 本色联动(alpha 保留 —— 它是「主背景」滑杆的独立自由度)
    r, g, b = _hex_rgb(TOKENS["accent"])
    TOKENS["accent_soft"] = "rgba(%d, %d, %d, 70)" % (r, g, b)
    TOKENS["accent_glow"] = "rgba(%d, %d, %d, 0.35)" % (r, g, b)
    r, g, b = _hex_rgb(TOKENS["bg"])
    TOKENS["bg_rgba"] = "rgba(%d, %d, %d, %.2f)" % (r, g, b, get_alpha("bg_rgba"))


def set_active(overrides):
    # 激活主题: 原地更新 TOKENS。只接受白名单内(PERSIST_KEYS)的合法颜色值, 其余一律
    # 忽略不抛错 —— 脏 config/脏主题文件不能致命。accent/bg_rgba 派生随之重算。
    for k, v in (overrides or {}).items():
        if k in PERSIST_KEYS and valid_color(v):
            TOKENS[k] = v
    try:
        _derive_tokens()
    except Exception:
        pass  # accent/bg 非 hex 时保持旧派生色(上游 valid_color 已拦, 双保险不致命)


def reset_default():
    # 恢复出厂 = 恢复当前变体的 base 色板(深色/浅色各自出厂), 派生随之重算
    TOKENS.clear()
    TOKENS.update(VARIANTS[ACTIVE_VARIANT])
    _derive_tokens()


# ── 明/暗变体 ──
VARIANTS = {"dark": DEFAULT_TOKENS, "light": LIGHT_TOKENS}
ACTIVE_VARIANT = "dark"        # 模块级当前变体(启动默认深色; 由 config["theme_variant"] 覆盖)


def get_variant():
    return ACTIVE_VARIANT


def set_variant(variant):
    # 切换明/暗: 把 TOKENS 重置为该变体的 base 色板(覆盖仅对本变体生效, 切换即丢弃,
    # 避免把另一套配色的覆盖叠到新底上)。返回是否成功。
    global ACTIVE_VARIANT
    if variant not in VARIANTS:
        return False
    ACTIVE_VARIANT = variant
    TOKENS.clear()
    TOKENS.update(VARIANTS[variant])
    _derive_tokens()
    return True


def get_alpha(token):
    m = _RGBA_ALPHA_RE.match(TOKENS[token])
    return float(m.group(2)) if m else 1.0


def set_alpha(token, alpha):
    # 只改 rgba 的 alpha 保留 rgb; 裁剪到 0.05-1.0(全透明面板会不可见)
    m = _RGBA_ALPHA_RE.match(TOKENS[token])
    if not m:
        return
    a = max(0.05, min(1.0, float(alpha)))
    TOKENS[token] = m.group(1) + ("%.2f" % a) + m.group(3)


def current_overrides():
    # 当前生效值与"当前变体出厂"的差异集 = 写 config["theme"] / 主题文件的最小覆盖集
    return {k: TOKENS[k] for k in PERSIST_KEYS if TOKENS[k] != VARIANTS[ACTIVE_VARIANT][k]}


def themes_dir():
    # 主题文件目录: 源码运行=仓库根/themes; 打包=exe 所在安装目录/themes(用户可写,
    # 与 config.json 同规则, 不能用 onefile 临时解压目录)。
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "themes")


def list_themes():
    # themes/*.json -> [(名字, 覆盖dict)] 按名字排序; 目录不存在/坏文件跳过不致命
    try:
        names = sorted(os.listdir(themes_dir()))
    except OSError:
        return []
    out = []
    for n in names:
        if not n.endswith(".json"):
            continue
        try:
            with open(os.path.join(themes_dir(), n), encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                out.append((n[:-5], data))
        except Exception:
            pass  # 单个损坏的主题文件跳过, 不拖垮整个列表
    return out


def save_theme_file(name, overrides):
    # 保存具名主题; 成功 True。名字做路径安全校验(拒绝分隔符/通配符)。
    if not isinstance(name, str) or not name.strip() \
            or any(c in name for c in '\\/:*?"<>|'):
        return False
    try:
        os.makedirs(themes_dir(), exist_ok=True)
        with open(os.path.join(themes_dir(), name + ".json"), "w", encoding="utf-8") as f:
            json.dump(overrides or {}, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


def load_theme_file(name):
    try:
        with open(os.path.join(themes_dir(), name + ".json"), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None  # 不存在/损坏/非 dict


def delete_theme_file(name):
    try:
        os.remove(os.path.join(themes_dir(), name + ".json"))
        return True
    except OSError:
        return False


def build_qss(t=None, mica=False):
    """由 token 生成完整 QSS。

    亚克力方案(2026-08-29 定稿): 无边框 + WA_TranslucentBackground(分层) + 系统级模糊
    (SetWindowCompositionAttribute ACCENT_ENABLE_BLURBEHIND, try_system_blur 启用,
    参考用户本科项目 areo.h 的经典方案; 实测 Win11 22H2+ 可用)。
    mica=True 时顶层背景 = bg_rgba 半透明染色层(rgb 随 bg 联动, alpha 可调)、面板 rgba
    半透明, 透出系统模糊; 系统模糊失败时保持半透明(无模糊)。非 Windows/旧系统走纯
    QSS 不透明主题。
    """
    t = {**TOKENS, **t} if t else TOKENS   # 允许传部分覆盖 dict, 未给的 key 落回默认
    if mica:
        # 亚克力模式: 主窗口背景 = bg_rgba(主背景色的半透明层, 叠在系统模糊材质上;
        # alpha 由主题页「主背景」滑杆控制, 全透明则纯透出模糊), 面板 rgba 半透明
        bg_main = t["bg_rgba"]
        bg_panel = t["bg_elevated_rgba"]
        bg_log = t["bg_log_rgba"]
        bg_page = t["bg_page_rgba"]
    else:
        bg_main = t["bg"]
        bg_panel = t["bg_elevated"]
        bg_log = t["bg_log"]
        bg_page = t["bg"]
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

/* 无边框窗口控制按钮(自绘标题栏) */
QPushButton#winBtn {{
    background: transparent; border: 1px solid transparent; border-radius: {t["radius_sm"]};
    padding: 6px 12px; color: {t["text_dim"]}; font-size: 13px;
}}
QPushButton#winBtn:hover {{ background: rgba(255, 255, 255, 0.12); color: {t["text"]}; border-color: transparent; }}
QPushButton#winBtnClose:hover {{ background: #e81123; color: #ffffff; border-color: #e81123; }}

/* 分栏(可拖拽); 手柄必须有非零 alpha(分层窗口按 alpha 命中测试, 透明处鼠标会穿透) */
QSplitter::handle {{ background: {bg_panel}; }}
QSplitter::handle:hover {{ background: {t["accent_glow"]}; }}
QSplitter::handle:horizontal {{ width: 3px; }}
QFrame#statusPanel {{ border: none; }}

/* 右栏(展开/收起同一控件; 收起态隐藏元素, 布局字体不变) */
QPushButton#collapseBtn {{
    background: transparent; border: 1px solid transparent; border-radius: {t["radius_sm"]};
    padding: 0; color: {t["text_dim"]}; font-size: 13px;
}}
QPushButton#collapseBtn:hover {{ background: rgba(255, 255, 255, 0.12); color: {t["text"]}; border-color: transparent; }}
QComboBox#deploy {{
    background: {t["btn_bg"]}; border: 1px solid {t["border_strong"]}; border-radius: {t["radius_sm"]};
    padding: 4px 10px; min-width: 130px; color: {t["text"]};
}}
QComboBox#deploy::drop-down {{ border: none; width: 22px; }}
QComboBox#deploy QAbstractItemView {{
    background: {t["btn_bg"]}; border: 1px solid {t["border_strong"]};
    selection-background-color: {t["accent"]};
    selection-color: {t["on_selection"]}; color: {t["text"]}; outline: 0; padding: 4px;
}}

QPushButton {{
    background: {t["btn_bg"]}; border: 1px solid {t["border_strong"]}; border-radius: {t["radius_sm"]};
    padding: 5px 14px; color: {t["text"]};
}}
QPushButton:hover {{ background: {t["btn_hover"]}; border-color: {t["border_hover"]}; }}
QPushButton:pressed {{ background: {t["btn_pressed"]}; }}
QPushButton:disabled {{ color: {t["text_disabled"]}; background: {t["btn_disabled_bg"]}; }}
QPushButton#primary {{ background: {t["accent"]}; border-color: {t["accent"]}; color: {t["on_accent"]}; font-weight: bold; }}
QPushButton#primary:hover {{ background: {t["accent_hover"]}; border-color: {t["accent_hover"]}; }}
QPushButton#danger {{ background: {t["err"]}; border-color: {t["err"]}; color: #ffffff; }}
QPushButton#danger:hover {{ background: {t["err_hover"]}; border-color: {t["err_hover"]}; }}

/* 左导航 */
QListWidget#nav {{
    background: {bg_panel}; border: none; border-right: 1px solid {t["border"]};
    outline: 0; padding-top: 6px;
}}
QListWidget#nav::item {{ padding: 9px 16px; border-left: 3px solid transparent; color: {t["nav_text"]}; }}
QListWidget#nav::item:hover {{ background: {t["bg_hover"]}; color: {t["text_bright"]}; }}
QListWidget#nav::item:selected {{
    background: {t["bg_active"]}; color: {t["text_bright"]};
    border-left: 3px solid {t["accent"]}; font-weight: bold;
}}

/* 现代列表(P1 多栏展开): 行渲染全在自绘 delegate, QSS 只关掉默认选择块 */
QListWidget#modernList {{
    background: transparent; border: none; outline: 0;
}}
QListWidget#modernList::item {{ border: none; }}
QListWidget#modernList::item:selected {{ background: transparent; color: {t["on_selection"]}; }}

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
QFrame#pageHostBg {{ background: {bg_page}; }}

/* 输入框(单行): 圆角 + 聚焦 accent 描边 */
QLineEdit {{
    background: {bg_log}; border: 1px solid {t["border_strong"]}; border-radius: {t["radius_sm"]};
    padding: 5px 10px; color: {t["text"]}; selection-background-color: {t["accent"]};
}}
QLineEdit:hover {{ border-color: {t["border_hover"]}; }}
QLineEdit:focus {{ border-color: {t["accent"]}; background: {bg_panel}; }}
QLineEdit:disabled {{ color: {t["text_disabled"]}; background: {t["input_disabled_bg"]}; }}

/* 多行文本(只读详情/日志类控件代码里自设等宽字体, 此处不覆盖 font-family) */
QTextEdit, QPlainTextEdit {{
    background: {bg_log}; border: 1px solid {t["inset_border"]}; border-radius: {t["radius"]};
    padding: 6px; color: {t["text"]}; selection-background-color: {t["accent"]};
}}
QTextEdit:focus, QPlainTextEdit:focus {{ border-color: {t["accent"]}; }}

/* 表格(设置端口表/环境检查等仍用表格处): 无网格 + 扁平表头 + accent 选中 */
QTableWidget {{
    background: transparent; border: 1px solid {t["inset_border"]}; border-radius: {t["radius"]};
    gridline-color: transparent; alternate-background-color: {t["table_alt"]};
    selection-background-color: {t["accent_soft"]};
    selection-color: {t["on_selection"]}; outline: 0;
}}
QTableWidget::item {{ padding: 4px 8px; border: none; }}
QTableWidget::item:selected {{ background: {t["accent_soft"]}; }}
QHeaderView::section {{
    background: transparent; color: {t["text_dim"]}; border: none;
    border-bottom: 1px solid {t["border"]}; padding: 6px 8px;
    font-size: 12px; font-weight: bold;
}}
QTableCornerButton::section {{ background: transparent; border: none; }}

/* 标签页: 下划线式选中 */
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background: transparent; color: {t["text_dim"]}; padding: 6px 14px;
    border: none; border-bottom: 2px solid transparent; margin-right: 2px;
}}
QTabBar::tab:hover {{ color: {t["text"]}; }}
QTabBar::tab:selected {{ color: {t["text_bright"]}; border-bottom: 2px solid {t["accent"]}; }}

/* 复选框: 圆角方块指示器, 选中=accent 实心 */
QCheckBox {{ spacing: 6px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border: 1px solid {t["border_strong"]};
    border-radius: 4px; background: {bg_log};
}}
QCheckBox::indicator:hover {{ border-color: {t["border_hover"]}; }}
QCheckBox::indicator:checked {{ background: {t["accent"]}; border-color: {t["accent"]}; }}
QCheckBox::indicator:disabled {{ background: {t["btn_disabled_bg"]}; border-color: {t["border"]}; }}

/* 下拉框(通用; #deploy 专属规则更具体不受影响) */
QComboBox {{
    background: {t["btn_bg"]}; border: 1px solid {t["border_strong"]}; border-radius: {t["radius_sm"]};
    padding: 4px 10px; color: {t["text"]};
}}
QComboBox:hover {{ border-color: {t["border_hover"]}; }}
QComboBox:focus {{ border-color: {t["accent"]}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {t["btn_bg"]}; border: 1px solid {t["border_strong"]};
    selection-background-color: {t["accent"]}; selection-color: {t["on_selection"]};
    color: {t["text"]}; outline: 0; padding: 4px;
}}

/* 滚动区容器: 透明融入页面/卡片(内容自身带卡片底) */
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

/* 日志区 */
QFrame#logWrap {{ background: {bg_panel}; border-top: 1px solid {t["border"]}; }}
QLabel#logTitle {{ color: {t["text_dim"]}; font-size: 12px; padding: 2px 4px; }}
QTextEdit#log {{
    background: {bg_log}; border: 1px solid {t["inset_border"]}; border-radius: {t["radius_sm"]};
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

/* 滑杆(主题页透明度): accent 圆点手柄 + 细槽, 已选段 accent */
QSlider::groove:horizontal {{ height: 4px; background: {t["border_strong"]}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {t["accent"]}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; background: {t["accent"]}; }}
QSlider::handle:horizontal:hover {{ background: {t["accent_hover"]}; }}

/* 主题页文件列表(objectName=themeList; 不影响 #nav / #modernList 专属规则) */
QListWidget#themeList {{
    background: {t["bg_log"]}; border: 1px solid {t["inset_border"]};
    border-radius: {t["radius_sm"]}; color: {t["text"]}; outline: 0;
}}
QListWidget#themeList::item {{ padding: 5px 8px; }}
QListWidget#themeList::item:selected {{ background: {t["accent_soft"]}; color: {t["on_selection"]}; }}

/* 工具提示/下拉菜单也覆盖掉系统色 */
QToolTip {{ background: {t["btn_bg"]}; color: {t["text"]}; border: 1px solid {t["tooltip_border"]}; padding: 4px 8px; }}
QMenu {{ background: {t["btn_bg"]}; border: 1px solid {t["border_strong"]}; }}
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


def try_system_blur(window):
    """尝试系统级模糊: SetWindowCompositionAttribute ACCENT_ENABLE_BLURBEHIND(3)。
    参考: 用户本科项目(Qt5, areo.h)验证过的经典方案; Win11 22H2+ 需实测。
    成功返回 True(调用方可跳过自绘 AcrylicBackdrop); 失败返回 False。
    """
    if sys.platform != "win32":
        return False
    try:
        class ACCENT_POLICY(ctypes.Structure):
            _fields_ = [("AccentState", ctypes.c_uint), ("AccentFlags", ctypes.c_uint),
                        ("GradientColor", ctypes.c_uint), ("AnimationId", ctypes.c_uint)]

        class WCADATA(ctypes.Structure):
            _fields_ = [("Attrib", ctypes.c_int), ("Data", ctypes.c_void_p),
                        ("SizeOfData", ctypes.c_size_t)]

        accent = ACCENT_POLICY(3, 0, 0, 0)   # ACCENT_ENABLE_BLURBEHIND
        data = WCADATA(19, ctypes.addressof(accent), ctypes.sizeof(accent))
        fn = ctypes.windll.user32.SetWindowCompositionAttribute
        hwnd = int(window.winId())
        return bool(fn(hwnd, ctypes.byref(data)))
    except Exception:
        return False


def apply_window_effects(window):
    """对顶层窗口应用平台效果(须配合无边框窗口, 见 build_qss 注释):
    Win11 22H2+ 启用 WA_TranslucentBackground(分层); DWM backdrop 显式置 0——
    分层窗口上 Mica/丙烯酸材质不渲染且会盖住透明(实测), 模糊由 try_system_blur 提供。

    返回 True 表示亚克力模式已启用(调用方应使用 build_qss(mica=True))。
    非 Windows/旧系统返回 False(纯 QSS 回退)。
    """
    if not is_windows_11_22h2():
        return False
    try:
        from PySide6.QtCore import Qt  # 惰性导入: 本模块顶层保持纯 Python
        window.setAttribute(Qt.WA_TranslucentBackground, True)
        window.setAttribute(Qt.WA_NoSystemBackground, True)
    except Exception:
        return False
    try:
        hwnd = int(window.winId())
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        DWMWA_SYSTEMBACKDROP_TYPE = 38
        DWMSBT_NONE = 0
        try:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
                ctypes.byref(ctypes.c_int(1)), ctypes.sizeof(ctypes.c_int))
        except Exception:
            pass
        try:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_SYSTEMBACKDROP_TYPE,
                ctypes.byref(ctypes.c_int(DWMSBT_NONE)), ctypes.sizeof(ctypes.c_int))
        except Exception:
            pass
    except Exception:
        pass
    return True


if __name__ == "__main__":
    # 重新生成 ui/theme.qss(非 Mica 模式的外部覆盖层, _load_theme 优先读取它):
    #   python -m ui.theme
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "theme.qss")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("# 由 ui/theme.py build_qss(mica=False) 生成(含 winBtn 样式)\n")
        f.write(build_qss(mica=False))
    print("WROTE", out)
