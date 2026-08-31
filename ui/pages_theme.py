# -*- coding: utf-8 -*-
# 主题页: 全部界面颜色实时可调 + 主题保存/加载。
# 模型(见 ui/theme.py): TOKENS = 当前生效色板(QSS 与画家层同源); 页面上的改动即时预览
# (仅内存, 经 app.apply_theme 重建 QSS, 无需重启); "保存为启动默认"写 config.json["theme"]
# (core save_config 自动 .bak, 重启仍生效); "保存为主题文件"落 themes/<名>.json 供复用,
# 列表可加载/删除。模糊/亚克力开关刻意不做: 窗口材质须在显示前设置, 运行中切换需重建
# 整窗(挂着 service 桥/监控线程/全部页面), 风险大于收益 —— 透明度调 rgba token 即可。
# self._config_path 默认 None(走 DSH_AIO_CONFIG/默认路径), 测试可注入 tmp 路径。

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QGridLayout, QLineEdit,
    QPushButton, QListWidget, QSlider, QScrollArea, QWidget, QColorDialog,
    QInputDialog, QMessageBox)

from core import config as dsh_config
from ui import theme as dsh_theme
from ui.base import BasePage

# 颜色 token 中文标签(与 theme.COLOR_GROUPS 的 key 对应; 漏了就回退显示 key 本身)
LABELS = {
    "bg": "主背景", "bg_elevated": "面板/卡片", "bg_log": "日志/输入区底",
    "bg_hover": "悬停底色", "bg_active": "导航选中底",
    "border": "边框", "border_strong": "边框(强)", "border_hover": "边框(悬停)",
    "inset_border": "内嵌边框", "tooltip_border": "提示边框",
    "accent": "强调色", "accent_hover": "强调色(悬停)",
    "btn_bg": "按钮底色", "btn_hover": "按钮悬停", "btn_pressed": "按钮按下",
    "btn_disabled_bg": "按钮禁用底", "input_disabled_bg": "输入禁用底",
    "table_alt": "表格斑马纹",
    "scroll_bg": "滚动条槽", "scroll_handle": "滚动条", "scroll_handle_hover": "滚动条悬停",
    "text": "正文文字", "text_bright": "标题文字", "text_dim": "次要文字",
    "nav_text": "导航文字", "text_disabled": "禁用文字",
    "ok": "成功", "warn": "警告", "err": "错误",
    "mon_ok": "监控·在线", "mon_bad": "监控·离线",
}


class ThemePage(BasePage):
    # 主题: BasePage 范式, app 为 MainWindow。页面随导航重建, 控件每次从 TOKENS 回填
    # (TOKENS 是模块级活状态, 导航往返不丢)。
    def __init__(self, app, parent=None):
        self._config_path = None    # None = DSH_AIO_CONFIG/默认路径; 测试可注入 tmp 路径
        self._cells = {}            # token -> (色块按钮, hex 输入框)
        self._sliders = {}          # token -> (滑杆, 百分比标签)
        self._pending_alpha = None  # (token, 值) 拖动节流待应用项
        super().__init__(app, parent)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 12)
        root.setSpacing(8)

        self._status_lbl = QLabel("就绪", objectName="monVal")
        head = QHBoxLayout()
        head.addWidget(QLabel("主题", objectName="cardTitle"))
        head.addStretch(1)
        head.addWidget(self._status_lbl)
        root.addLayout(head)
        hint = QLabel(
            "改动即时预览(重启后回到启动默认), 要保留请点「保存为启动默认」; "
            "「强调色」变化时其低透明派生色(表格选中/分栏高亮)自动跟随。"
            "透明度仅在亚克力(模糊)模式下有可见效果。", objectName="cardHint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        # 拖动滑杆的节流定时器: 停止 80ms 后才重建 QSS(连续 valueChanged 不逐帧 repolish)
        self._alpha_timer = QTimer(self)
        self._alpha_timer.setSingleShot(True)
        self._alpha_timer.setInterval(80)
        self._alpha_timer.timeout.connect(self._apply_pending_alpha)

        content = QWidget()
        v = QVBoxLayout(content)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        v.addWidget(self._build_variant_card())
        v.addWidget(self._build_files_card())
        v.addWidget(self._build_colors_card())
        v.addWidget(self._build_alpha_card())
        v.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

    # ── 明/暗变体卡: 深色/浅色 一键切换(持久化 config["theme_variant"]; 深色为默认) ──
    def _build_variant_card(self):
        card = QFrame(objectName="card")
        v = QVBoxLayout(card)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(6)
        v.addWidget(QLabel("明/暗变体(切换即 discard 当前变体上未保存的覆盖; 保留请先「保存为启动默认」)",
                           objectName="rightTitle"))
        row = QHBoxLayout()
        self._dark_btn = QPushButton("深色")
        self._dark_btn.setCheckable(True)
        self._dark_btn.clicked.connect(lambda: self._on_toggle_variant("dark"))
        self._light_btn = QPushButton("浅色")
        self._light_btn.setCheckable(True)
        self._light_btn.clicked.connect(lambda: self._on_toggle_variant("light"))
        row.addWidget(self._dark_btn)
        row.addWidget(self._light_btn)
        row.addStretch(1)
        v.addLayout(row)
        self._sync_variant_btns()
        return card

    def _sync_variant_btns(self):
        # 变体按钮高亮与当前变体一致(blockSignals 防回填触发切换)
        cur = dsh_theme.get_variant()
        for btn in (self._dark_btn, self._light_btn):
            btn.blockSignals(True)
        self._dark_btn.setChecked(cur == "dark")
        self._light_btn.setChecked(cur == "light")
        self._dark_btn.setObjectName("primary" if cur == "dark" else "")
        self._light_btn.setObjectName("primary" if cur == "light" else "")
        # objectName 变化后需重新抛光才生效
        self._dark_btn.style().unpolish(self._dark_btn); self._dark_btn.style().polish(self._dark_btn)
        self._light_btn.style().unpolish(self._light_btn); self._light_btn.style().polish(self._light_btn)
        for btn in (self._dark_btn, self._light_btn):
            btn.blockSignals(False)

    def _on_toggle_variant(self, variant):
        if variant == dsh_theme.get_variant():
            self._sync_variant_btns()
            return
        if not self.app.set_theme_variant(variant):
            self._set("切换失败: 非法变体或 config.json 写入失败(可能被占用)", err=True)
            self._sync_variant_btns()
            return
        self._set("已切换为%s色主题(config.json theme_variant=%s)"
                  % ("浅" if variant == "light" else "深", variant))
        self._sync_variant_btns()
        self._refresh_all()

    # ── 主题文件卡: 具名主题的保存/加载/删除 ──
    def _build_files_card(self):
        card = QFrame(objectName="card")
        v = QVBoxLayout(card)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(6)
        v.addWidget(QLabel("主题文件(themes/ 目录; 加载仅即时预览, 不改启动默认)",
                           objectName="rightTitle"))
        row = QHBoxLayout()
        self._list = QListWidget(objectName="themeList")
        self._list.setMaximumHeight(118)
        row.addWidget(self._list, 1)
        side = QVBoxLayout()
        load = QPushButton("加载")
        load.clicked.connect(self._on_load)
        dele = QPushButton("删除")
        dele.clicked.connect(self._on_delete)
        side.addWidget(load)
        side.addWidget(dele)
        side.addStretch(1)
        row.addLayout(side)
        v.addLayout(row)
        act = QHBoxLayout()
        save_file = QPushButton("保存当前为主题文件...")
        save_file.clicked.connect(self._on_save_file)
        reset = QPushButton("恢复默认")
        reset.clicked.connect(self._on_reset)
        save_default = QPushButton("保存为启动默认", objectName="primary")
        save_default.clicked.connect(self._on_save_default)
        act.addWidget(save_file)
        act.addWidget(reset)
        act.addWidget(save_default)
        act.addStretch(1)
        v.addLayout(act)
        self._reload_themes()
        return card

    def _reload_themes(self):
        self._list.clear()
        for name, _ in dsh_theme.list_themes():
            self._list.addItem(name)

    # ── 颜色卡: 分组的色板编辑(色块按钮选色 + hex 直填) ──
    def _build_colors_card(self):
        card = QFrame(objectName="card")
        outer = QVBoxLayout(card)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(6)
        for gname, keys in dsh_theme.COLOR_GROUPS:
            outer.addWidget(QLabel(gname, objectName="rightTitle"))
            grid = QGridLayout()
            grid.setHorizontalSpacing(18)
            grid.setVerticalSpacing(4)
            for i, key in enumerate(keys):
                grid.addWidget(self._color_cell(key), i // 3, i % 3)
            outer.addLayout(grid)
        return card

    def _color_cell(self, key):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        sw = QPushButton()
        sw.setFixedSize(34, 20)
        sw.setCursor(Qt.CursorShape.PointingHandCursor)
        edit = QLineEdit(dsh_theme.TOKENS[key])
        edit.setFixedWidth(88)
        edit.setFont(QFont("Consolas", 9))
        edit.setToolTip(LABELS.get(key, key))
        self._sync_swatch(sw, dsh_theme.TOKENS[key])
        sw.clicked.connect(lambda _=False, k=key, e=edit, s=sw: self._pick(k, e, s))
        edit.editingFinished.connect(lambda k=key, e=edit, s=sw: self._on_hex(k, e, s))
        self._cells[key] = (sw, edit)
        h.addWidget(sw)
        h.addWidget(QLabel(LABELS.get(key, key)))
        h.addStretch(1)
        h.addWidget(edit)
        return w

    @staticmethod
    def _sync_swatch(sw, color):
        # 色块按钮即时反映当前值(inline 样式优先级高于全局 QSS 的 QPushButton 规则)
        sw.setStyleSheet("QPushButton { background: %s; border: 1px solid #3d3d5c; "
                         "border-radius: 4px; padding: 0; }" % color)

    def _pick(self, key, edit, sw):
        color = QColorDialog.getColor(QColor(dsh_theme.TOKENS[key]), self,
                                      LABELS.get(key, key))
        if not color.isValid():
            return
        self.app.apply_theme({key: color.name()}, note=None)
        self._refresh_cell(key)

    def _on_hex(self, key, edit, sw):
        text = edit.text().strip()
        if dsh_theme.valid_color(text):
            self.app.apply_theme({key: text}, note=None)
        self._refresh_cell(key)   # 非法输入回填当前生效值(不应用)

    def _refresh_cell(self, key):
        sw, edit = self._cells[key]
        sw.blockSignals(True)
        edit.blockSignals(True)
        edit.setText(dsh_theme.TOKENS[key])
        self._sync_swatch(sw, dsh_theme.TOKENS[key])
        edit.blockSignals(False)
        sw.blockSignals(False)

    # ── 透明度卡: rgba token 的 alpha 滑杆(仅亚克力模式可见) ──
    def _build_alpha_card(self):
        card = QFrame(objectName="card")
        v = QVBoxLayout(card)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(6)
        v.addWidget(QLabel("透明度(仅亚克力模糊模式可见; 「主背景」是模糊材质上的"
                           "染色层, 颜色在上方「背景·主背景」改)", objectName="rightTitle"))
        for token, label in dsh_theme.ALPHA_KEYS:
            h = QHBoxLayout()
            h.addWidget(QLabel(label))
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(5, 100)
            slider.setValue(int(round(dsh_theme.get_alpha(token) * 100)))
            pct = QLabel("%d%%" % slider.value())
            pct.setFixedWidth(40)
            slider.valueChanged.connect(
                lambda val, t=token, p=pct: self._on_alpha(t, val, p))
            self._sliders[token] = (slider, pct)
            h.addWidget(slider, 1)
            h.addWidget(pct)
            v.addLayout(h)
        return card

    def _on_alpha(self, token, val, pct_lbl):
        pct_lbl.setText("%d%%" % val)
        self._pending_alpha = (token, val / 100.0)
        self._alpha_timer.start()

    def _apply_pending_alpha(self):
        if self._pending_alpha is None:
            return
        token, alpha = self._pending_alpha
        self._pending_alpha = None
        dsh_theme.set_alpha(token, alpha)
        self.app.apply_theme(note=None)

    # ── 动作 ──
    def _on_save_file(self):
        name, ok = QInputDialog.getText(self, "保存主题", "主题名:")
        if not ok:
            return
        if not dsh_theme.save_theme_file(name.strip(), dsh_theme.current_overrides()):
            self._set("保存失败: 主题名为空或含非法字符(\\ / : * ? \" < > |), 或写入失败",
                      err=True)
            return
        self._reload_themes()
        self._set("已保存主题文件: themes/%s.json" % name.strip())

    def _on_load(self):
        item = self._list.currentItem()
        if item is None:
            self._set("先在列表中选择一个主题文件", err=True)
            return
        data = dsh_theme.load_theme_file(item.text())
        if data is None:
            self._set("加载失败: 主题文件损坏或不存在", err=True)
            return
        self.app.apply_theme(data, note="[主题] 已加载主题: " + item.text())
        self._refresh_all()
        self._set("已加载主题: %s(即时预览; 保留请「保存为启动默认」)" % item.text())

    def _on_delete(self):
        item = self._list.currentItem()
        if item is None:
            self._set("先在列表中选择要删除的主题文件", err=True)
            return
        ret = QMessageBox.question(
            self, "删除主题",
            "将删除主题文件 themes/%s.json, 删除后不可恢复。确定删除?" % item.text())
        if ret != QMessageBox.StandardButton.Yes:
            return
        if not dsh_theme.delete_theme_file(item.text()):
            self._set("删除失败: 文件可能被占用", err=True)
            return
        self._reload_themes()
        self._set("已删除主题: " + item.text())

    def _on_reset(self):
        if dsh_theme.current_overrides() \
                and QMessageBox.question(
                    self, "恢复默认",
                    "将恢复出厂配色(当前未保存的调整丢失, 启动默认不变)。继续?") \
                != QMessageBox.StandardButton.Yes:
            return
        dsh_theme.reset_default()
        self.app.apply_theme(note="[主题] 已恢复出厂配色(仅本次运行; 要保留请「保存为启动默认」)")
        self._refresh_all()
        self._set("已恢复出厂配色")

    def _on_save_default(self):
        # 以磁盘 config.json 为基准只改 theme 段(不碰其他字段); 恢复出厂后保存即清空覆盖
        cfg = dsh_config.load_config(self._config_path)
        ov = dsh_theme.current_overrides()
        if ov:
            cfg["theme"] = ov
        else:
            cfg.pop("theme", None)
        if not dsh_config.save_config(cfg, self._config_path):
            self._set("保存失败: config.json 写入失败(可能被占用), 请重试", err=True)
            return
        self.app._custom_theme = bool(ov)
        self._set("已保存为启动默认(config.json)%s" % ("" if ov else " —— 出厂配色"))

    # ── 状态/回填 ──
    def _refresh_all(self):
        # 色板/滑杆从 TOKENS 回填(加载/恢复默认/切变体后调用); blockSignals 防回填触发再应用
        self._sync_variant_btns()
        for key in self._cells:
            self._refresh_cell(key)
        for token, (slider, pct) in self._sliders.items():
            slider.blockSignals(True)
            val = int(round(dsh_theme.get_alpha(token) * 100))
            slider.setValue(val)
            pct.setText("%d%%" % val)
            slider.blockSignals(False)

    def _set(self, text, err=False):
        self._status_lbl.setText(text)
        self._set_status(text)
        if not err:
            self.app.loge("[主题] " + text, "ok")

    def _set_status(self, text):
        self._status_lbl.setText(text)
