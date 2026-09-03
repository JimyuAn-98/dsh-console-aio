# -*- coding: utf-8 -*-
# ui/monitor.py - 右侧折叠健康监控栏 (RightBar/StatusPanel) 与线程安全日志桥 (LogBridge)。

from PySide6.QtCore import Qt, Signal, QObject, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QTextCursor, QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QFrame)

# 白色齿轮 SVG(内嵌, 无需打包资源文件; QSvgRenderer 渲染为 QIcon)
_GEAR_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#e6e6e6">'
             '<path d="M19.14,12.94c0.04,-0.3 0.06,-0.61 0.06,-0.94c0,-0.32 -0.02,-0.64 '
             '-0.07,-0.94l2.03,-1.58c0.18,-0.14 0.23,-0.41 0.12,-0.61l-1.92,-3.32c-0.12,-0.22 '
             '-0.37,-0.29 -0.59,-0.22l-2.39,0.96c-0.5,-0.38 -1.03,-0.7 -1.62,-0.94L14.4,2.81'
             'c-0.04,-0.24 -0.24,-0.41 -0.48,-0.41h-3.84c-0.24,0 -0.43,0.17 -0.47,0.41L9.25,5.35'
             'C8.66,5.59 8.12,5.92 7.63,6.29L5.24,5.33c-0.22,-0.08 -0.47,0 -0.59,0.22L2.74,8.87'
             'C2.62,9.08 2.66,9.34 2.86,9.48l2.03,1.58C4.84,11.36 4.8,11.69 4.8,12s0.02,0.64 '
             '0.07,0.94l-2.03,1.58c-0.18,0.14 -0.23,0.41 -0.12,0.61l1.92,3.32c0.12,0.22 0.37,0.29 '
             '0.59,0.22l2.39,-0.96c0.5,0.38 1.03,0.7 1.62,0.94l0.36,2.54c0.05,0.24 0.24,0.41 '
             '0.48,0.41h3.84c0.24,0 0.44,-0.17 0.47,-0.41l0.36,-2.54c0.59,-0.24 1.13,-0.56 '
             '1.62,-0.94l2.39,0.96c0.22,0.08 0.47,0 0.59,-0.22l1.92,-3.32c0.12,-0.22 0.07,-0.47 '
             '-0.12,-0.61L19.14,12.94zM12,15.6c-1.98,0 -3.6,-1.62 -3.6,-3.6s1.62,-3.6 3.6,-3.6'
             's3.6,1.62 3.6,3.6S13.98,15.6 12,15.6z"/></svg>')


def svg_icon(svg_text, size):
    # SVG 字符串 -> QIcon(内嵌图标, 免资源文件; QtSvg 缺失时返回 None 由调用方兜底)
    try:
        from PySide6.QtCore import QByteArray
        from PySide6.QtGui import QPainter
        from PySide6.QtSvg import QSvgRenderer
        r = QSvgRenderer(QByteArray(svg_text.encode("utf-8")))
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        r.render(p)
        p.end()
        return QIcon(pm)
    except Exception:
        return None


# ---------------- 线程安全日志桥: 后台线程 -> Qt 主线程 ----------------
class LogBridge(QObject):
    _sig = Signal(str, str)          # (text, tag)
    _status = Signal(str)            # 状态栏文本(跨线程安全)

    def __init__(self):
        super().__init__()
        self._view = None
        self._status_cb = None
        self._sig.connect(self._append)
        self._status.connect(self._apply_status)

    def attach(self, view):
        self._view = view

    def on_status(self, cb):
        self._status_cb = cb

    def emit(self, text, tag=""):
        self._sig.emit(text, tag)

    def emit_status(self, text):
        self._status.emit(text)

    def _apply_status(self, text):
        if self._status_cb is not None:
            self._status_cb(text)

    def _append(self, text, tag):
        if self._view is None:
            return
        color = "#e6e6e6"
        if tag == "err":
            color = "#e07a7a"
        elif tag == "warn":
            color = "#e5c07b"
        elif tag == "ok":
            color = "#7ecb6a"
        self._view.setTextColor(QColor(color))
        self._view.append(text)
        self._view.setTextColor(QColor("#e6e6e6"))
        self._view.moveCursor(QTextCursor.End)


# ---------------- 右状态栏(监控点) ----------------
class RightBar(QFrame):
    # 展开/收起共用同一控件: 收起态仅隐藏 备注/延迟/设置, 布局与字体天然一致。
    ROW_H = 36   # 单元格行高固定: 收起态隐藏子标签后高度不变

    def __init__(self, cfg, on_toggle=None, on_settings=None, parent=None):
        super().__init__(parent)
        self.setObjectName("rightBar")
        self.setMinimumWidth(210)
        self.setMaximumWidth(280)
        self._compact = False
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)

        head = QHBoxLayout()
        t = QLabel("监控", objectName="rightTitle")
        self._btn_toggle = QPushButton("»", objectName="collapseBtn")
        self._btn_toggle.setFixedSize(24, 22)
        self._btn_toggle.setToolTip("收起为窄条")
        if on_toggle:
            self._btn_toggle.clicked.connect(on_toggle)
        head.addWidget(t)
        head.addStretch(1)
        self._btn_settings = QPushButton(objectName="collapseBtn")
        icon = svg_icon(_GEAR_SVG, 16)
        if icon is not None:
            self._btn_settings.setIcon(icon)
        else:
            self._btn_settings.setText("⚙")
        self._btn_settings.setFixedSize(24, 22)
        self._btn_settings.setToolTip("监控设置(端口/命名)")
        if on_settings:
            self._btn_settings.clicked.connect(on_settings)
        head.addWidget(self._btn_settings)
        head.addWidget(self._btn_toggle)
        v.addLayout(head)

        # 内容区独立容器: 热重载时整体清空重建(命名/端口跟随配置)
        self._content = QVBoxLayout()
        self._content.setSpacing(8)
        v.addLayout(self._content)
        self._build_content(cfg or {})

    def _clear_layout(self, lay):
        while lay.count():
            item = lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _build_content(self, cfg):
        self._clear_layout(self._content)
        self._cells = {}
        self._sections = []
        local = (cfg or {}).get("local_name") or "本机"
        dash_p = (cfg or {}).get("dash_port") or 0

        # 1. 本机服务端口 (固定分组)
        self._add_section(local + "服务端口")
        if dash_p and dash_p > 0:
            self._add_cell("L%d" % dash_p, local + " dsh", "GUI", dash_p)

        # 2. 拓扑方案动态隧道卡片分组 (复用卡片名称作为分类标题)
        from core.config import normalize_tunnels
        tunnels = normalize_tunnels(cfg, allow_empty_ports=True)

        if tunnels:
            for tun in tunnels:
                tname = tun.get("name") or tun.get("id") or "未命名隧道"
                mode = tun.get("mode") or "forward"
                mode_tag = " (正向)" if mode == "forward" else " (反向)"
                self._content.addSpacing(6)
                self._add_section(tname + mode_tag)
                forwards = tun.get("forwards") or []
                if not forwards:
                    hint = QLabel("（未配置端口规则）", objectName="cardHint")
                    self._content.addWidget(hint)
                    self._sections.append(hint)
                for fw in forwards:
                    lp = fw.get("local_port") if isinstance(fw, dict) else (fw[0] if len(fw) >= 1 else None)
                    rp = fw.get("remote_port") if isinstance(fw, dict) else (fw[2] if len(fw) >= 3 else None)
                    desc = fw.get("desc") if isinstance(fw, dict) else (fw[3] if len(fw) >= 4 else "")
                    if not lp:
                        continue
                    if mode == "forward":
                        note = desc or ("→ :%s" % (rp or lp))
                        self._add_cell("L%d" % lp, "本机 %d" % lp, note, lp)
                    else:  # mode == "reverse"
                        note = desc or ("← 本机:%s" % (rp or dash_p or 3080))
                        self._add_cell("R%d" % lp, "公网 :%d" % lp, note, lp)
        elif not (dash_p and dash_p > 0):
            hint = QLabel("（暂无监控项）", objectName="cardHint")
            self._content.addWidget(hint)
            self._sections.append(hint)

        self._content.addStretch(1)

    def reload(self, cfg):
        self._build_content(cfg or {})

    def _add_section(self, text):
        lbl = QLabel(text, objectName="rightTitle")
        lbl.setWordWrap(True)
        self._content.addWidget(lbl)
        self._sections.append(lbl)

    def _add_cell(self, key, name, note, port):
        wrap = QWidget()
        wrap.setFixedHeight(self.ROW_H)   # 行高固定(收起态隐藏标签后布局不变)
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        dot = QLabel("●", objectName="monDot")
        dot.setStyleSheet("color:#999;")
        nm = QLabel(name, objectName="monName")
        detail = QLabel("%s" % note, objectName="monNote")
        val = QLabel("--", objectName="monVal")
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(nm)
        col.addWidget(detail)
        row.addWidget(dot)
        row.addLayout(col, 1)
        row.addWidget(val, 0, Qt.AlignRight)
        self._content.addWidget(wrap)
        self._cells[key] = (dot, nm, detail, val)

    def set_state(self, key, ok, ms=-1):
        # 实时更新单元格状态: 圆点与数值配色(绿=在线/红=不可达)。
        # ms=None 表示只有 on/off 信息(如远程隧道), 显示 在线/不可达; ms>=0 显示延迟。
        cell = self._cells.get(key)
        if cell is None:
            return
        dot, nm, detail, val = cell
        color = "#43d17f" if ok else "#e5574d"
        dot.setStyleSheet("color:%s;" % color)
        if ms is None:
            val.setText("在线" if ok else "不可达")
        elif ok and ms >= 0:
            val.setText("%dms" % ms)
        else:
            val.setText("未就绪")
        val.setStyleSheet("color:%s;" % color)

    def set_compact(self, on):
        # 收起态 = 同一控件隐藏 备注/延迟/设置按钮; 切换按钮语义; 行高/字体不变。
        self._compact = on
        self._btn_settings.setVisible(not on)
        self._btn_toggle.setText("«" if on else "»")
        self._btn_toggle.setToolTip("展开状态栏" if on else "收起为窄条")
        self.setMinimumWidth(0 if on else 210)
        for sec in getattr(self, "_sections", []):
            sec.setVisible(not on)
        for dot, nm, detail, val in self._cells.values():
            detail.setVisible(not on)
            val.setVisible(not on)


class StatusPanel(QFrame):
    # 右栏容器: RightBar 双态(展开/收起), 宽度动画; 收起 = 同一控件隐藏备注/延迟/设置
    def __init__(self, cfg=None, on_settings=None, parent=None):
        super().__init__(parent)
        self.setObjectName("statusPanel")
        self.setMinimumWidth(210)
        self.setMaximumWidth(280)
        self._collapsed = False
        self.right = RightBar(cfg, on_toggle=self._on_toggle, on_settings=on_settings)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.right)
        # min/max 同步动画: 布局按约束强制给宽, 动画期间宽度严格跟随(右锚定顺滑)
        self._anim_max = QPropertyAnimation(self, b"maximumWidth", self)
        self._anim_min = QPropertyAnimation(self, b"minimumWidth", self)
        for a in (self._anim_max, self._anim_min):
            a.setDuration(180)
            a.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_max.finished.connect(self._on_anim_done)
        self._target = None

    def _on_toggle(self):
        if self._collapsed:
            self.expand()
        else:
            self.collapse()

    def collapse(self):
        # 同一控件双态: 收起 = 隐藏元素 + 压缩宽度(动画全程无空白)
        self._target = "collapsed"
        self.right.set_compact(True)
        self._start_anim(100)

    def expand(self):
        self._target = "expanded"
        self.right.set_compact(False)
        self._start_anim(240)

    def _start_anim(self, end):
        w = self.width()
        self._anim_max.stop()
        self._anim_min.stop()
        self._anim_max.setStartValue(w)
        self._anim_max.setEndValue(end)
        self._anim_min.setStartValue(w)
        self._anim_min.setEndValue(end)
        self._anim_max.start()
        self._anim_min.start()

    def _on_anim_done(self):
        if self._target == "collapsed":
            self.setMinimumWidth(100)
            self.setMaximumWidth(100)     # 钉死收起宽度
            self._collapsed = True
        elif self._target == "expanded":
            self.setMinimumWidth(210)
            self.setMaximumWidth(280)
            self._collapsed = False
        self._target = None

    def reload(self, cfg):
        # 热重载: 右栏按新配置重建(端口/命名)
        self.right.reload(cfg)

