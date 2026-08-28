# -*- coding: utf-8 -*-
# tools/dump_ui.py - 把 dsh-console-aio 的 GUI 渲染结果序列化为 JSON / XML(离屏)。
#
# 用途: 由人工运行, 用于"不打开真实 GUI 也能看到 GUI 呈现成什么样"。脚本会构造真实
#       MainWindow 与所有页面, 并把控件树(层级/objectName/类名/文字/几何)落盘到
#       dump_ui.json 与 dump_ui.xml, 供人工检查界面是否符合预期。后台线程被屏蔽,
#       因此只做"静态渲染", 不连真实 SSH/端口/进程。
#
# 安全性(重要): 本脚本构造真实 MainWindow/页面。页面构造器会启动 daemon 后台线程去读
#       SSH/端口/进程等真实资源 —— 本脚本在 import 主程序前, 把 threading.Thread.start
#       改成 no-op(所有后台线程不启动), 并拦截 MainWindow._start_monitor 与 service 子进程
#       通道(DshService.run_cmd/_run_result_op/_run_core_op, 原 MainWindow._stream_cmd
#       遗留已删除), 再用全占位/空端口的假 config(DSH_AIO_CONFIG) 与假 DSH_HOME 隔离,
#       因此绝不触碰真实 config.json / 3080 / SSH / 端口 / 进程。
#
# 运行:  python tools/dump_ui.py            (输出到仓库根 dump_ui.json / dump_ui.xml)
#        python tools/dump_ui.py out_dir    (指定输出目录)
#
# 说明: 由于实际源文件是 dsh-console-aio.py(带连字符), 本脚本用 importlib 动态加载。
#       本脚本自包含(fake env 内联), 不 import tests/fake_env, 避免 Pylance 解析不到。

import os
import sys
import json
import time
import shutil
import tempfile
import pathlib
import importlib
import importlib.util
import threading

# ---- 0) 环境隔离必须在 import 主程序之前 ----
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# ---- 假环境(内联自 tests/fake_env, 自包含) ----
def _make_fake_config_dict():
    # 全空端口/占位服务器, 与真实 3080/8090/8022/8091/3090 完全脱钩。
    return {
        "ssh_server": "YOUR_PUBLIC_IP",
        "ssh_user": "YOUR_USER",
        "dash_repo": "",
        "dash_port": 0,
        "dash_cmd": ["pnpm.cmd", "dsh", "web"],
        "poll_seconds": 4,
        "local_ports": [],
        "remote_tunnels": [],
        "forward_ports": [],
        "reverse_port": 0,
        "lab_port": 0,
    }


def _make_fake_home(tmp_root):
    home = pathlib.Path(str(tmp_root)) / ".dsh-fake"
    home.mkdir(parents=True, exist_ok=True)
    for sub in ("profiles", "sessions", "storages", "task-board", ".agent-presets"):
        (home / sub).mkdir(exist_ok=True)
    (home / "storages" / "workspace.json").write_text(
        json.dumps({"global": {"workspaceIds": [], "archivedSessionIds": []}}),
        encoding="utf-8")
    (home / "settings.yaml").write_text("{}\n", encoding="utf-8")
    return str(home)


def _make_fake_env(tmp_root):
    # 构造假 config + 假 DSH_HOME, 设好 DSH_AIO_CONFIG / DSH_HOME, 返回 (恢复函数)。
    cfg_dir = pathlib.Path(str(tmp_root)) / "cfg"
    cfg_dir.mkdir(exist_ok=True)
    cfg_file = cfg_dir / "config.json"
    cfg_file.write_text(json.dumps(_make_fake_config_dict(), ensure_ascii=False,
                                   indent=2), encoding="utf-8")
    fake_home = _make_fake_home(str(tmp_root))
    _old_cfg = os.environ.get("DSH_AIO_CONFIG")
    _old_home = os.environ.get("DSH_HOME")
    os.environ["DSH_AIO_CONFIG"] = str(cfg_file)
    os.environ["DSH_HOME"] = fake_home

    def _restore():
        if _old_cfg is None:
            os.environ.pop("DSH_AIO_CONFIG", None)
        else:
            os.environ["DSH_AIO_CONFIG"] = _old_cfg
        if _old_home is None:
            os.environ.pop("DSH_HOME", None)
        else:
            os.environ["DSH_HOME"] = _old_home

    return str(cfg_file), fake_home, _restore


# ---- 1) 禁止后台线程真正启动(阻止页面 worker 碰真实资源) ----
_ORIG_THREAD_START = threading.Thread.start
_ORIG_THREAD_INIT = threading.Thread.__init__


def _safe_thread_init(self, group=None, target=None, name=None, args=(),
                      kwargs=None, *, daemon=None):
    kwargs = kwargs if kwargs is not None else {}
    _ORIG_THREAD_INIT(self, group=group, target=target, name=name, args=args,
                      kwargs=kwargs, daemon=daemon)


def _safe_start(self):
    # 本脚本只做静态渲染: 一律不启动任何线程(dsh 页面 worker 全是 daemon 线程)。
    return


threading.Thread.__init__ = _safe_thread_init
threading.Thread.start = _safe_start


# ---- 2) 在假环境下动态加载主程序 ----
def _import_console():
    ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # 把仓库根加入 sys.path, 否则主程序里的 import core.data / core.tunnel_mgr / ui.*
    # 在 importlib 加载时解析不到(正常以 python 脚本启动会自动加脚本目录)。
    if ROOT_DIR not in sys.path:
        sys.path.insert(0, ROOT_DIR)
    spec = importlib.util.spec_from_file_location(
        "dsh_console_aio", os.path.join(ROOT_DIR, "dsh-console-aio.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dsh_console_aio"] = mod
    spec.loader.exec_module(mod)
    return mod


from PySide6.QtWidgets import QWidget, QLabel, QPushButton, QComboBox, \
        QListWidget, QTextEdit, QTableWidget  # noqa: E402


def _dump_widget(w):
    # 递归序列化一个 Qt 控件(规避无法序列化的属性)。
    # 只递归"直接子控件", 避免重复/爆炸式树。
    info = {
        "cls": w.__class__.__name__,
        "objectName": w.objectName() or "",
        "geometry": [w.x(), w.y(), w.width(), w.height()],
        "visible": w.isVisible(),
        "_text": "",
    }
    if isinstance(w, QLabel):
        info["_text"] = w.text() or ""
    elif isinstance(w, QPushButton):
        info["_text"] = w.text() or ""
    elif isinstance(w, QTextEdit):
        info["_text"] = w.toPlainText() or ""
    elif isinstance(w, QComboBox):
        info["_text"] = "|".join(w.itemText(i) for i in range(w.count()))
    elif isinstance(w, QListWidget):
        info["_text"] = "|".join(w.item(i).text() for i in range(w.count()))
    elif isinstance(w, QTableWidget):
        info["_text"] = "rows=%d cols=%d" % (w.rowCount(), w.columnCount())
    direct = []
    for c in w.children():
        if isinstance(c, QWidget):
            direct.append(c)
    info["children"] = [_dump_widget(cc) for cc in direct]
    return info


def main():
    ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # 参数: [--ui] [out_dir]
    want_ui = "--ui" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--ui"]
    out_dir = args[0] if args else ROOT_DIR
    os.makedirs(out_dir, exist_ok=True)
    ui_out = os.path.join(out_dir, "ui_dump")  # 与源码主题目录 ui/ 区分, 避免污染
    if want_ui:
        os.makedirs(ui_out, exist_ok=True)

    # 假环境(空端口 config + 假 DSH_HOME)
    tmp = tempfile.mkdtemp(prefix="dsh-dump-ui-")
    cfg_file, fake_home, restore = _make_fake_env(tmp)

    console = _import_console()
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    # 拦截监控与命令流(双保险): service 子进程通道(run_cmd/_run_result_op/_run_core_op)
    # 是页面业务统一出口(原 MainWindow._stream_cmd 遗留已删除)。
    from app import services as _services
    _orig_monitor = console.MainWindow._start_monitor
    _orig_run_cmd = _services.DshService.run_cmd
    _orig_run_result = _services.DshService._run_result_op
    _orig_run_core = _services.DshService._run_core_op
    console.MainWindow._start_monitor = lambda self: None
    _services.DshService.run_cmd = lambda self, cmd, cwd=None, env=None, op="run-cmd": None
    _services.DshService._run_result_op = lambda self, *a, **k: None
    _services.DshService._run_core_op = lambda self, *a, **k: None

    try:
        win = console.MainWindow(smoke=True)
        # 强制布局, 离屏才有确定几何
        win.show()
        app.processEvents()

        window_info = {
            "title": win.windowTitle(),
            "geometry": [win.x(), win.y(), win.width(), win.height()],
            "min": [win.minimumWidth(), win.minimumHeight()],
        }

        pages = {}
        for label, key in console.NAV_ITEMS:
            try:
                win._show_page(key)
                app.processEvents()
                page = win.stack.currentWidget()
                pages[key] = _dump_widget(page)
            except Exception as e:
                pages[key] = {"error": "%s: %s" % (type(e).__name__, e)}

        right_cells = {}
        for k, (dot, val) in getattr(win.right, "_cells", {}).items():
            right_cells[str(k)] = val.text() if val else None

        result = {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "app": "dsh-console-aio",
            "offscreen": True,
            "background_threads_blocked": True,
            "fake_config": _load_json(cfg_file),
            "fake_home": fake_home,
            "window": window_info,
            "nav_items": console.NAV_ITEMS,
            "right_bar_cells": right_cells,
            "pages": pages,
        }

        json_path = os.path.join(out_dir, "dump_ui.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        xml_path = os.path.join(out_dir, "dump_ui.xml")
        with open(xml_path, "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="utf-8"?>\n')
            f.write("<dump>\n")
            f.write(_to_xml(result, 1))
            f.write("</dump>\n")

        print("WROTE %s" % json_path)
        print("WROTE %s" % xml_path)

        if want_ui:
            written = []
            for key, tree in pages.items():
                if not isinstance(tree, dict) or tree.get("error"):
                    continue
                uipath = os.path.join(ui_out, key + ".ui")
                with open(uipath, "w", encoding="utf-8") as f:
                    f.write(_tree_to_ui(tree, _ui_classname(key)))
                written.append(uipath)
            _write_ui_readme(ui_out, written, console)
            print("WROTE %d .ui files to %s" % (len(written), ui_out))
            for p in written:
                print("  - %s" % p)
            print("用 pyside6-designer 打开即可可视化查看/编辑。")

        print("pages dumped:", ", ".join(pages.keys()))
        print("background threads BLOCKED (no real resources touched)")
        return 0
    finally:
        restore()
        console.MainWindow._start_monitor = _orig_monitor
        _services.DshService.run_cmd = _orig_run_cmd
        _services.DshService._run_result_op = _orig_run_result
        _services.DshService._run_core_op = _orig_run_core
        shutil.rmtree(tmp, ignore_errors=True)


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _to_xml(obj, indent=0):
    pad = "  " * indent
    out = []
    if isinstance(obj, dict):
        out.append("%s<dict>" % pad)
        for k, v in obj.items():
            out.append('%s  <item key="%s">' % (pad, _esc(str(k))))
            if isinstance(v, (dict, list)):
                out.append(_to_xml(v, indent + 2))
            else:
                out.append("%s    %s" % (pad, _esc(str(v))))
            out.append("%s  </item>" % pad)
        out.append("%s</dict>" % pad)
    elif isinstance(obj, list):
        out.append("%s<list>" % pad)
        for v in obj:
            if isinstance(v, (dict, list)):
                out.append(_to_xml(v, indent + 1))
            else:
                out.append("%s  <item>%s</item>" % (pad, _esc(str(v))))
        out.append("%s</list>" % pad)
    else:
        out.append("%s%s" % (pad, _esc(str(obj))))
    return "\n".join(out)


def _esc(s):
    s = str(s)
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


# ---- .ui 生成(Qt Designer 格式) ----
_QTMAP = {
    "QWidget": "QWidget", "QFrame": "QFrame", "QLabel": "QLabel",
    "QPushButton": "QPushButton", "QComboBox": "QComboBox",
    "QListWidget": "QListWidget", "QTextEdit": "QTextEdit",
    "QTableWidget": "QTableWidget", "QStackedWidget": "QStackedWidget",
    "QScrollArea": "QScrollArea", "QMainWindow": "QMainWindow",
    "QCheckBox": "QCheckBox", "QRadioButton": "QRadioButton",
    "QLineEdit": "QLineEdit", "QSpinBox": "QSpinBox",
}


def _ui_classname(key):
    # 页面关键字 -> 类名(首字母大写 + Page)
    base = key.replace("-", "_")
    return "".join(p.capitalize() for p in base.split("_")) + "Page"


def _ui_widget(tree, name_hint="widget"):
    cls = _QTMAP.get(tree.get("cls"), "QWidget")
    oname = _esc(tree.get("objectName") or name_hint)
    lines = ['<widget class="%s" name="%s">' % (cls, oname)]

    geo = tree.get("geometry")
    if isinstance(geo, list) and len(geo) == 4:
        lines.append('  <property name="geometry">')
        lines.append('   <rect><x>%d</x><y>%d</y><width>%d</width><height>%d</height></rect>'
                     % (int(geo[0]), int(geo[1]), int(geo[2]), int(geo[3])))
        lines.append('  </property>')

    txt = tree.get("_text")
    if cls in ("QLabel", "QPushButton") and txt:
        lines.append('  <property name="text">')
        lines.append('   <string>%s</string>' % _esc(txt))
        lines.append('  </property>')

    kids = [c for c in tree.get("children", []) if isinstance(c, dict)]
    if kids:
        lines.append('  <layout class="QVBoxLayout" name="layout_%s">' % oname)
        for k in kids:
            lines.append('   <item>')
            lines.extend("   " + ln for ln in _ui_widget(k))
            lines.append('   </item>')
        lines.append('  </layout>')

    lines.append('</widget>')
    return lines


def _tree_to_ui(tree, class_name):
    out = []
    out.append('<?xml version="1.0" encoding="UTF-8"?>')
    out.append('<ui version="4.0">')
    out.append(' <class>%s</class>' % class_name)
    out.extend(_ui_widget(tree, class_name))
    out.append(' <resources/>')
    out.append(' <connections/>')
    out.append('</ui>')
    return "\n".join(out) + "\n"


def _write_ui_readme(ui_out, written, console):
    with open(os.path.join(ui_out, "README.txt"), "w", encoding="utf-8") as f:
        f.write("dsh-console-aio 各页面的 Qt Designer 视图(.ui)。\n")
        f.write("用 pyside6-designer 打开单个 .ui 即可可视化查看/拖改。\n")
        f.write("(路径含空格, 用引号; 或 Web 版: 拖进 https://build-system.fman.io/qt-designer 查看)\n\n")
        f.write("页面列表:\n")
        for p in written:
            f.write("  - %s\n" % p)
        f.write("\n注意: 这些 .ui 由运行时控件树反向生成, 用于查看/手工微调原型;\n")
        f.write("改完的 .ui 需 pyside6-uic 转代码后再接入业务, 不会自动反映回源码。\n")


if __name__ == "__main__":
    sys.exit(main())
