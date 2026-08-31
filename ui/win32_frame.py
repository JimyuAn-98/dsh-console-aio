# -*- coding: utf-8 -*-
"""Windows 原生窗口机制封装(ctypes, 零第三方依赖)。

目标: 在保留 WS_CAPTION | WS_THICKFRAME(标准非分层窗口)的前提下, 达成
  - 无边框外观(WM_NCCALCSIZE 藏原生标题栏)
  - 原生贴靠/多屏拖拽(WM_NCHITTEST 用 ScreenToClient 让 Windows 换算多屏 DPI 坐标)
  - 亚克力/Mica(DWM backdrop, 不设 WA_TranslucentBackground, 非分层)

背景: 手动用 geometry()+GetDpiForWindow 做命中在跨屏(负坐标/不同尺寸显示器)时
会差一个约等于两屏宽度差的常量偏移(便携屏实测 ~853 逻辑px)。正确做法是
ScreenToClient + GetClientRect, 由 Windows 完成多屏 DPI 坐标换算(qframelesswindow
内部正是这么写的, 此处为自研等价移植, 不引 PyQt5/GPL 库)。

只在本模块顶部有英文 ASCII docstring; 其余一律 # 注释(遵循项目三引号禁令)。
"""
import ctypes
from ctypes import wintypes

# ---- Win32 常量 ----
GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_EX_LAYERED = 0x00080000

WM_NCCALCSIZE = 0x0083
WM_NCHITTEST = 0x0084
WM_SYSCOMMAND = 0x0112
SC_MOVE = 0xF010
WM_ERASEBKGND = 0x0014

# WM_NCHITTEST 返回值
HTCLIENT = 1
HTCAPTION = 2
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17

# DWM system backdrop (Win11 22H2+)
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMSBT_AUTO = 0
DWMSBT_NONE = 1
DWMSBT_MAINWINDOW = 2      # Mica
DWMSBT_TRANSIENTWINDOW = 3 # Acrylic

# 自绘标题栏高度(逻辑 px), 与 _TopBar.setFixedHeight 对齐
TITLE_BAR_HEIGHT = 52
# 可拉伸边缘宽度(逻辑 px)
RESIZE_EDGE = 6

_user32 = ctypes.windll.user32
_dwmapi = ctypes.windll.dwmapi


class _MARGINS(ctypes.Structure):
    _fields_ = [("cxLeftWidth", ctypes.c_int), ("cxRightWidth", ctypes.c_int),
                ("cyTopHeight", ctypes.c_int), ("cyBottomHeight", ctypes.c_int)]


def _get_style(hwnd, index):
    return _user32.GetWindowLongPtrW(hwnd, index) & 0xFFFFFFFF


def has_caption(hwnd):
    return bool(_get_style(hwnd, GWL_STYLE) & WS_CAPTION)


def has_thickframe(hwnd):
    return bool(_get_style(hwnd, GWL_STYLE) & WS_THICKFRAME)


def is_layered(hwnd):
    """是否分层窗口(WS_EX_LAYERED)。分层提供逐像素 alpha(亚克力可透出)。
    分层不一定破坏贴靠/拉伸: 只要同时保留 WS_CAPTION|WS_THICKFRAME, 原生边框就在
    (参考用户本科项目 areo.h + SetWindowLong 配方)。真正破坏贴靠的是 FramelessWindowHint。"""
    return bool(_get_style(hwnd, GWL_EXSTYLE) & WS_EX_LAYERED)


def set_layered(hwnd, on=True):
    """强制在 GWL_EXSTYLE 上加/去 WS_EX_LAYERED。

    有些 Qt 版本 WA_TranslucentBackground 未必转换成 WS_EX_LAYERED; 这里显式控制。
    注意: Qt 若不知道自己分层, 渲染可能不写 alpha(黑窗), 需配合实测确认。
    返回 True 表示设置成功。
    """
    ex = _get_style(hwnd, GWL_EXSTYLE)
    ex = (ex | WS_EX_LAYERED) if on else (ex & ~WS_EX_LAYERED)
    try:
        _user32.SetWindowLongPtrW(int(hwnd), GWL_EXSTYLE, ex)
        return is_layered(hwnd) == on
    except Exception:
        return False


def ensure_native_frame(hwnd):
    """确保窗口保留 WS_CAPTION|WS_THICKFRAME|WS_MAXIMIZEBOX(原生贴靠/拉伸所需非客户区)。

    ❗不得调用 setWindowFlags(FramelessWindowHint) —— 那会删掉这些标志。
    与分层(WS_EX_LAYERED)并存即可同时获得"亚克力 + 原生贴靠"(用户项目实证)。
    """
    style = _get_style(hwnd, GWL_STYLE)
    new_style = style | WS_CAPTION | WS_THICKFRAME | 0x00030000  # WS_MAXIMIZEBOX|WS_MINIMIZEBOX
    try:
        _user32.SetWindowLongPtrW(int(hwnd), GWL_STYLE, new_style)
        return True
    except Exception:
        return False


def set_accent_blur(hwnd, gradient_color=0, accent_state=3):
    """SetWindowCompositionAttribute ACCENT_ENABLE_BLURBEHIND(3) / ACRYLICBLURBEHIND 亚克力。

    用户本科项目(areo.h)实证: 分层窗口 + 该调用 -> 亚克力/模糊实打实透出。
    返回 True 表示调用成功。
    """
    try:
        class ACCENT_POLICY(ctypes.Structure):
            _fields_ = [("AccentState", ctypes.c_uint), ("AccentFlags", ctypes.c_uint),
                        ("GradientColor", ctypes.c_uint), ("AnimationId", ctypes.c_uint)]

        class WCADATA(ctypes.Structure):
            _fields_ = [("Attrib", ctypes.c_int), ("Data", ctypes.c_void_p),
                        ("SizeOfData", ctypes.c_size_t)]

        accent = ACCENT_POLICY(int(accent_state), 0, int(gradient_color), 0)
        data = WCADATA(19, ctypes.addressof(accent), ctypes.sizeof(accent))  # 19=WCA_ACCENT_POLICY
        fn = _user32.SetWindowCompositionAttribute
        fn.argtypes = [wintypes.HWND, ctypes.POINTER(WCADATA)]
        fn.restype = ctypes.c_bool
        return bool(fn(int(hwnd), ctypes.byref(data)))
    except Exception:
        return False


def set_immersive_dark(hwnd, dark=True):
    on = ctypes.c_int(1 if dark else 0)
    return _dwmapi.DwmSetWindowAttribute(
        int(hwnd), DWMWA_USE_IMMERSIVE_DARK_MODE,
        ctypes.byref(on), ctypes.sizeof(on))


def set_system_backdrop(hwnd, kind=DWMSBT_TRANSIENTWINDOW):
    """设置 DWM 系统背景材质(亚克力/Mica/无)。不依赖分层窗口。

    kind: DWMSBT_TRANSIENTWINDOW(亚克力, 透出窗外模糊) / DWMSBT_MAINWINDOW(Mica, 静态纹理)
          / DWMSBT_NONE(关)。
    返回 True 表示调用成功。
    """
    try:
        val = ctypes.c_int(int(kind))
        r = _dwmapi.DwmSetWindowAttribute(
            int(hwnd), DWMWA_SYSTEMBACKDROP_TYPE,
            ctypes.byref(val), ctypes.sizeof(val))
        return r == 0
    except Exception:
        return False


def query_backdrop(hwnd):
    """返回当前 DWM backdrop 类型(DWMSBT_*), 失败返回 -1。"""
    try:
        v = ctypes.c_int(0)
        r = _dwmapi.DwmGetWindowAttribute(
            int(hwnd), DWMWA_SYSTEMBACKDROP_TYPE,
            ctypes.byref(v), ctypes.sizeof(v))
        return v.value if r == 0 else -1
    except Exception:
        return -1


def extend_frame(hwnd, margins=None):
    """DwmExtendFrameIntoClientArea; None 表示 {0,0,0,0}(不动原生边框)。
    传 (-1,-1,-1,-1) 让 DWM 玻璃覆盖整个客户区(透出材质的补丁手段)。
    返回 True 表示调用成功(HRESULT==0)。
    """
    if margins is None:
        m = _MARGINS()
    else:
        m = _MARGINS(*margins)
    try:
        return _dwmapi.DwmExtendFrameIntoClientArea(int(hwnd), ctypes.byref(m)) == 0
    except Exception:
        return False


def apply_native_look(hwnd, dark=True, backdrop=DWMSBT_TRANSIENTWINDOW):
    """组合应用: 暗色标题 + DWM 背景 + (保留原生 caption/thickframe 不删)。

    注意: 不改窗口样式(保留 WS_CAPTION|WS_THICKFRAME), 只在原生 look 层面做调整。
    """
    extend_frame(hwnd)                # 不收缩客户区(保持原生边框可用)
    set_immersive_dark(hwnd, dark)
    ok = set_system_backdrop(hwnd, backdrop)
    return ok


def client_rect(hwnd):
    """返回 (left, top, right, bottom) 客户区坐标(屏坐标系)。"""
    r = wintypes.RECT()
    _user32.GetClientRect(int(hwnd), ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def screen_to_client(hwnd, x, y):
    """把屏幕坐标转换为客户区坐标(由 Windows 处理多屏 DPI 换算)。"""
    pt = wintypes.POINT(int(x), int(y))
    _user32.ScreenToClient(int(hwnd), ctypes.byref(pt))
    return pt.x, pt.y


def hit_test(hwnd, maxed=False, title_bar_height=TITLE_BAR_HEIGHT,
             edge=RESIZE_EDGE):
    """在 WM_NCHITTEST 里计算命中类型, 与坐标空间无关(用当前光标屏幕坐标)。

    使用 ScreenToClient 把屏幕坐标转客户区坐标, 再对客户区宽高做命中判定。
    返回 HT* 常量; 需由调用方以 (True, hit) 形式返回给 nativeEvent。
    """
    # 用真实当前光标位置(WM_NCHITTEST lParam 的坐标在跨屏时可能不可靠,
    # 直接让 Windows 以光标屏幕坐标换客户区坐标, 天然适配多屏 DPI)。
    pos = wintypes.POINT()
    _user32.GetCursorPos(ctypes.byref(pos))
    return hit_test_at(hwnd, pos.x, pos.y, maxed=maxed,
                       title_bar_height=title_bar_height, edge=edge)


def hit_test_at(hwnd, screen_x, screen_y, maxed=False,
                title_bar_height=TITLE_BAR_HEIGHT, edge=RESIZE_EDGE):
    l, t, r, b = client_rect(hwnd)
    w = r - l
    h = b - t
    cx, cy = screen_to_client(hwnd, screen_x, screen_y)

    if maxed:
        # 最大化: 禁用侧边/底部拉伸; 顶部留一小条 HTCAPTION 便于移动(否则贴靠后挪不动)
        if cy < 8:
            return HTCAPTION
        return HTCLIENT

    left = cx < edge
    right = cx >= w - edge
    top = cy < edge
    bottom = cy >= h - edge

    if left and top:
        return HTTOPLEFT
    if right and top:
        return HTTOPRIGHT
    if left and bottom:
        return HTBOTTOMLEFT
    if right and bottom:
        return HTBOTTOMRIGHT
    if left:
        return HTLEFT
    if right:
        return HTRIGHT
    if top:
        return HTTOP
    if bottom:
        return HTBOTTOM
    if cy < title_bar_height:
        # 自绘标题栏区域 -> HTCAPTION: 触发原生拖拽 + Win+箭头边缘贴靠
        return HTCAPTION
    return HTCLIENT


def start_system_move(hwnd):
    """让 Windows 进入原生移动循环(SC_MOVE|HTCAPTION), 拖动到屏幕边缘触发 Aero 贴靠。

    标题栏拖拽走这条路而不是返回 HTCAPTION —— HTCAPTION 会让标题栏内的按钮失去
    点击(整块都变原生 caption); 用 Qt mouse 事件触发本函数 + canDrag 限制区域,
    按钮仍可正常点击。需先 ReleaseCapture(否则 SendMessage 无效)。
    """
    try:
        _user32.ReleaseCapture()
        _user32.SendMessageW(int(hwnd), WM_SYSCOMMAND, SC_MOVE | 0x0002, 0)  # 0x0002=HTCAPTION
        return True
    except Exception:
        return False


def on_nccalcsize_maximized(hwnd):
    """WM_NCCALCSIZE 在最大化时对任务栏留白(处理自动隐藏任务栏等)。"""
    return True, 0
