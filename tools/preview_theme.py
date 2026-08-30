# -*- coding: utf-8 -*-
# tools/preview_theme.py - 主题配色预览: 离屏渲染 MainWindow, 输出多方案并排对比图。
#
# 用途: 换主题色/调 token 前先看效果, 不用真开 GUI。每个页面按 VARIANTS 渲染各方案
#       截图 + 一张带标签的并排对比图, 落盘 preview/(*_preview.png, gitignore)。
#       试新方案 = 在 VARIANTS 加一行 (名称, 标签, token覆盖dict) —— build_qss 支持
#       部分覆盖, 未给的 key 落回 TOKENS 默认; 全部配色均 token 驱动, 无字面量替换。
#
# 安全性: 与 tools/dump_ui.py 同一套隔离(import dump_ui 即生效): 后台线程 no-op +
#       假 config/假 DSH_HOME + 拦截 service 子进程通道, 绝不触碰真实 config.json /
#       SSH / 端口 / 进程。渲染用 windows 平台 + WA_DontShowOnScreen(不出屏)并强制
#       非 Mica(保证渲染为不透明纯 QSS, 字体与真实运行一致)。
#
# 运行:  python tools/preview_theme.py [页面key...]   (默认 overview/tunnels/settings)

import os
import sys
import shutil
import tempfile

# 必须 dump_ui 之前设置: offscreen 平台缺 CJK 字体(中文渲染成方块), 用 windows 平台
# + WA_DontShowOnScreen 渲染(不出现在屏幕/任务栏, 字体渲染与真实运行一致)。
os.environ["QT_QPA_PLATFORM"] = "windows"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR := os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import dump_ui  # noqa: F401  # import 副作用即完成线程屏蔽隔离

from ui.theme import build_qss

OUT_DIR = os.path.join(ROOT_DIR, "preview")

# 旧配色(2026-08-30 换版前, accent #4f6ef7 + 240° 蓝紫中性色)完整覆盖表:
# 留作新旧对比与回滚参照; 文字灰两版相同(色相差异不可感知)故不含 text 类 token。
_OLD_PALETTE = {
    "bg": "#1e1e2e", "bg_rgba": "rgba(30, 30, 46, 0.55)",
    "bg_elevated": "#252535", "bg_elevated_rgba": "rgba(37, 37, 53, 0.55)",
    "bg_log": "#16161f", "bg_log_rgba": "rgba(22, 22, 31, 0.75)",
    "bg_page_rgba": "rgba(30, 30, 46, 0.42)",
    "bg_hover": "#2e2e44", "bg_active": "#2f3353",
    "border": "#33334a", "border_strong": "#3d3d5c", "border_hover": "#5858a0",
    "accent": "#4f6ef7", "accent_hover": "#6179ff",
    "accent_soft": "rgba(79, 110, 247, 70)", "accent_glow": "rgba(79, 110, 247, 0.35)",
    "btn_bg": "#2f2f45", "btn_hover": "#3a3a58", "btn_pressed": "#26263a",
    "btn_disabled_bg": "#2a2a3c", "input_disabled_bg": "#24243a",
    "inset_border": "#2c2c40", "table_alt": "#232338",
    "text_disabled": "#6a6a80", "tooltip_border": "#4f5674",
    "scroll_bg": "#1a1a28", "scroll_handle": "#3d3d5c", "scroll_handle_hover": "#4f5674",
}

VARIANTS = [
    ("old", "旧主题 4f6ef7(蓝紫)", _OLD_PALETTE),
    ("current", "当前主题 5686FE(纯蓝)", None),
]


def _compose(images, labels):
    # 对比图: 顶部 30px 标签条 + 各方案截图横向拼接(2px 分隔线)
    from PySide6.QtGui import QImage, QPainter, QColor, QFont
    head = 30
    width = sum(i.width() for i in images) + 2 * (len(images) - 1)
    height = head + max(i.height() for i in images)
    img = QImage(width, height, QImage.Format.Format_RGB32)
    img.fill(QColor("#101018"))
    p = QPainter(img)
    x = 0
    for pm, lbl in zip(images, labels):
        p.setPen(QColor("#e6e6e6"))
        p.setFont(QFont("Microsoft YaHei UI", 10))
        p.drawText(x + 12, 20, lbl)
        p.drawImage(x, head, pm)
        x += pm.width() + 2
    p.end()
    return img


def main():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    tmp = tempfile.mkdtemp(prefix="dsh-preview-theme-")
    cfg_file, fake_home, restore = dump_ui._make_fake_env(tmp)
    console = dump_ui._import_console()
    # 强制非 Mica: 离屏无 DWM, 保证预览为不透明纯 QSS 渲染(与实际回退模式一致)
    console.apply_window_effects = lambda w: False
    console.try_system_blur = lambda w: False
    from app import services as _services
    console.MainWindow._start_monitor = lambda self: None
    _services.DshService.run_cmd = lambda self, cmd, cwd=None, env=None, op="run-cmd": None
    _services.DshService._run_result_op = lambda self, *a, **k: None
    _services.DshService._run_core_op = lambda self, *a, **k: None

    app = QApplication.instance() or QApplication([])
    pages = sys.argv[1:] or ["overview", "tunnels", "settings"]
    win = None
    try:
        os.makedirs(OUT_DIR, exist_ok=True)
        win = console.MainWindow(smoke=True)
        win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        win.show()   # 不上屏, 仅触发真实布局/字体渲染
        app.processEvents()
        for key in pages:
            shots = []
            for name, label, overrides in VARIANTS:
                win.setStyleSheet(build_qss(overrides, mica=False))
                win._show_page(key)
                app.processEvents()
                pm = win.grab().toImage()
                path = os.path.join(OUT_DIR, "theme_%s_%s_preview.png" % (name, key))
                assert pm.save(path, "PNG"), "save failed: " + path
                shots.append(pm)
            cmp_path = os.path.join(OUT_DIR, "theme_cmp_%s_preview.png" % key)
            assert _compose(shots, [lbl for _, lbl, _ in VARIANTS]).save(cmp_path, "PNG")
            print("WROTE", cmp_path)
        print("fake config:", cfg_file)
        print("background threads BLOCKED (no real resources touched)")
        return 0
    finally:
        if win is not None:
            win.close()
        restore()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
