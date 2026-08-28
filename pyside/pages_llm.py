# -*- coding: utf-8 -*-
# LLM / 模型配置页(UI 层)。
# 数据: ~/.dsh/settings.yaml 的 agent-default-model(读写) 与 llm-pi-ai.providers(只读)。
# 读取走 service.read_settings(remote)、保存走 service.write_settings(写前 .bak)
# —— result("llm-read"/"llm-save") 回包, 接收者是页面自身, 页面销毁 Qt 自动断开;
# log/status 不在页面 connect(主窗口级已接一次)。
# 密钥安全: apiKeyEnv 只引用环境变量名, 本页不读取/不写入/不展示密钥明文(仅 os.environ 存在性判断)。
# 部署联动: 当前部署(host 非空)构造 DshRemote, 读操作走远程; 写配置仍写本机(与旧版一致)。

import os

from PySide6.QtCore import Qt

from dsh_core import data as core_data
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QFrame, QComboBox,
    QTableWidget, QTableWidgetItem, QPushButton, QHeaderView, QMessageBox)

from pyside.base import BasePage

# 内置官方 provider 不在 settings.yaml 里, 模型 id 与数据层单价表保持一致
BUILTIN_PROVIDER = "deepseek-official"
# 官方模型名(与定价表对齐); 自定义 provider 模型会动态合并进下拉
BUILTIN_MODELS = ["deepseek-v4-flash", "deepseek-v4-pro", "deepseek-v4-flash-vision-exp"]
REASONING_LEVELS = ["off", "min", "medium", "max"]


def _providers_map(settings):
    # 自定义 providers 必须是 dict{名称: 配置}, 否则按空处理
    llm = settings.get("llm-pi-ai")
    p = llm.get("providers") if isinstance(llm, dict) else None
    return p if isinstance(p, dict) else {}


def _provider_options(settings):
    # 下拉顺序: 内置官方 provider 在前, 其余为 settings 里的自定义 provider 名
    names = [k for k in _providers_map(settings) if k != BUILTIN_PROVIDER]
    return [BUILTIN_PROVIDER] + names


def _models_for(settings, provider):
    # 返回该 provider 的模型 id 列表; 内置 provider 合并内置模型与同名自定义项
    ids = []
    if provider == BUILTIN_PROVIDER:
        ids = list(BUILTIN_MODELS)
    p = _providers_map(settings).get(provider)
    if isinstance(p, dict):
        mlist = p.get("models")
        if isinstance(mlist, list):
            for m in mlist:
                mid = m.get("id") if isinstance(m, dict) else m
                mid = str(mid) if mid else ""
                if mid and mid not in ids:
                    ids.append(mid)
    return ids


def _env_txt(env):
    # apiKeyEnv 只显示环境变量名与是否已设置, 绝不读值更不展示明文
    env = str(env or "")
    if not env:
        return ""
    return env + ("（已设置）" if os.environ.get(env) else "（未设置）")


class LlmPage(BasePage):
    # LLM / 模型配置: BasePage 范式, app 为 MainWindow。

    def __init__(self, app, parent=None):
        self._remote = None
        _dep = getattr(app, "_current_deploy", None)
        if _dep and _dep.get("host"):
            self._remote = core_data.DshRemote(_dep)
        self._settings = {}
        self._pending = None
        self._pending_settings = None
        super().__init__(app, parent)
        self.app.service.result.connect(self._on_result)
        self.app.service.finished.connect(self._on_finished)
        self._reload()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 12)
        root.setSpacing(8)

        title = QLabel("LLM / 模型配置", objectName="cardTitle")
        root.addWidget(title)
        hint = QLabel("查看/切换 agent-default-model，只读展示自定义 providers。",
                      objectName="cardHint")
        root.addWidget(hint)

        form = QFrame(objectName="card")
        fl = QFormLayout(form)
        fl.setContentsMargins(12, 8, 12, 8)
        fl.setSpacing(6)
        self._provider_cb = QComboBox()
        self._model_cb = QComboBox()
        self._effort_cb = QComboBox()
        fl.addRow("provider:", self._provider_cb)
        fl.addRow("model:", self._model_cb)
        fl.addRow("reasoningEffort:", self._effort_cb)
        root.addWidget(form)

        self._provider_cb.activated.connect(self._on_provider_changed)

        btns = QHBoxLayout()
        self._btn_save = QPushButton("保存默认模型")
        self._btn_save.clicked.connect(self._on_save)
        self._btn_reload = QPushButton("重新读取")
        self._btn_reload.clicked.connect(self._reload)
        btns.addWidget(self._btn_save)
        btns.addWidget(self._btn_reload)
        btns.addStretch(1)
        root.addLayout(btns)

        note = QLabel("密钥安全：密钥只保存在系统环境变量中（apiKeyEnv 只引用环境变量名）。\n"
                      "控制台不读取、不写入、不展示密钥明文。", objectName="cardHint")
        root.addWidget(note)

        self._table = self._make_table(
            ["provider", "api", "baseURL", "模型名称", "apiKeyEnv（环境变量）"],
            ["w", "w", "w", "w", "w"],
            [110, 120, 220, 200, 200], stretch_col=2)
        card = QFrame(objectName="card")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(10, 8, 10, 8)
        cap = QLabel("自定义 Providers（只读）", objectName="rightTitle")
        cv.addWidget(cap)
        cv.addWidget(self._table)
        root.addWidget(card, 1)

        foot = QLabel("修改写入 settings.yaml（自动备份 .bak），重启 dsh web 生效。",
                      objectName="cardHint")
        root.addWidget(foot)

        self._status_lbl = QLabel("就绪", objectName="statusBar")
        root.addWidget(self._status_lbl)

    def _make_table(self, headers, anchors, widths, stretch_col):
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.verticalHeader().setVisible(False)
        t.setSelectionBehavior(QTableWidget.SelectRows)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        hh = t.horizontalHeader()
        for i, (a, wd) in enumerate(zip(anchors, widths)):
            hh.setSectionResizeMode(i, QHeaderView.ResizeToContents if i != stretch_col
                                    else QHeaderView.Stretch)
            t.setColumnWidth(i, wd)
            if a == "e":
                t.horizontalHeaderItem(i).setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            elif a == "center":
                t.horizontalHeaderItem(i).setTextAlignment(Qt.AlignCenter)
        t.setSelectionMode(QTableWidget.SingleSelection)
        return t

    def _reload(self):
        # 重新读取 settings.yaml(可能被外部修改)并刷新界面; 业务在 dsh_core.data
        self._set_btns(False)
        self._set_status("正在读取配置...")
        self._pending = "llm-read"
        self.app.service.read_settings(self._remote)

    def _on_result(self, op, payload):
        if op == "llm-read":
            self._pending = None
            settings = payload.get("data")
            self._apply_data(settings if isinstance(settings, dict) else {},
                             payload.get("err", ""))
        elif op == "llm-save":
            self._pending = None
            self._after_save(self._pending_settings or {}, payload.get("err", ""))

    def _on_finished(self, op, ok):
        # 兜底: result 槽漏执行导致 busy 悬挂时解除
        if op == self._pending:
            self._pending = None
            self._set_btns(True)

    def _apply_data(self, settings, err):
        self._settings = settings
        self._set_btns(True)
        self._load_current()
        self._fill_providers()
        if err:
            self._set_status("读取失败: " + err)
            self.app.loge("[LLM] 读取失败: " + err, "err")
        else:
            self._set_status("已加载配置")

    def _load_current(self):
        # 把 settings 当前值填进三个下拉框, 未知取值保留显示而非静默改值
        adm = self._settings.get("agent-default-model")
        cur = adm if isinstance(adm, dict) else {}
        cur_provider = str(cur.get("provider") or BUILTIN_PROVIDER)
        cur_model = str(cur.get("model") or "")
        cur_effort = str(cur.get("reasoningEffort") or "medium")

        opts = _provider_options(self._settings)
        self._provider_cb.clear()
        self._provider_cb.addItems(opts)
        if cur_provider in opts:
            self._provider_cb.setCurrentText(cur_provider)
        elif opts:
            self._provider_cb.setCurrentIndex(0)
        else:
            self._provider_cb.setCurrentIndex(-1)

        self._apply_models(cur_model)

        efforts = list(REASONING_LEVELS)
        if cur_effort not in efforts:
            efforts.insert(0, cur_effort)
        self._effort_cb.clear()
        self._effort_cb.addItems(efforts)
        self._effort_cb.setCurrentText(cur_effort)

    def _apply_models(self, keep_model):
        # 刷新 model 下拉选项, 尽量保留当前选中
        provider = self._provider_cb.currentText()
        models = _models_for(self._settings, provider)
        self._model_cb.clear()
        self._model_cb.addItems(models)
        if keep_model in models:
            self._model_cb.setCurrentText(keep_model)
        elif models:
            self._model_cb.setCurrentIndex(0)
        else:
            self._model_cb.setCurrentIndex(-1)

    def _on_provider_changed(self, _index=None):
        self._apply_models(self._model_cb.currentText())

    def _fill_providers(self):
        # 刷新只读 providers 表格: 补全 baseURL/模型名称列表; apiKeyEnv 只显示环境变量名与是否已设置
        rows = []
        for name, p in _providers_map(self._settings).items():
            if not isinstance(p, dict):
                continue
            api = str(p.get("api") or "")
            base = str(p.get("baseURL") or "")
            mlist = p.get("models")
            mnames = []
            if isinstance(mlist, list):
                for m in mlist:
                    if isinstance(m, dict):
                        mnames.append(str(m.get("name") or m.get("id") or ""))
                    else:
                        mnames.append(str(m))
            models_txt = ", ".join(x for x in mnames if x) or "-"
            rows.append([name, api, base, models_txt, _env_txt(p.get("apiKeyEnv"))])
        self._table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                self._table.setItem(r, c, QTableWidgetItem(val))

    def _on_save(self):
        provider = self._provider_cb.currentText()
        model = self._model_cb.currentText()
        effort = self._effort_cb.currentText()
        if not provider or not model:
            QMessageBox.warning(self, "请选择", "请先选择 provider 与 model。")
            return
        if model not in _models_for(self._settings, provider):
            QMessageBox.warning(self, "模型无效", "所选模型不在该 provider 的模型列表中。")
            return
        desc = ("将默认模型改为：\n"
                "  provider: %s\n  model: %s\n  reasoningEffort: %s\n\n"
                "写入 settings.yaml（自动备份 .bak），重启 dsh web 生效。\n是否继续？"
                % (provider, model, effort))
        if QMessageBox.question(self, "确认修改默认模型", desc) != QMessageBox.Yes:
            return
        self._set_btns(False)
        self._set_status("正在保存配置...")
        # 组装完整 settings(页面持有当前副本), 写盘业务在 dsh_core.data(写前 .bak)
        new_settings = dict(self._settings)
        new_settings["agent-default-model"] = {
            "provider": provider, "model": model, "reasoningEffort": effort}
        self._pending_settings = new_settings
        self._pending = "llm-save"
        self.app.service.write_settings(new_settings)

    def _after_save(self, settings, err):
        self._set_btns(True)
        if err:
            self._set_status("保存失败: " + err)
            self.app.loge("[LLM] 保存失败: " + err, "err")
            QMessageBox.critical(self, "保存失败", "写入 settings.yaml 失败：%s" % err)
            return
        msg = self._pending_msg()
        self._settings = settings
        self._load_current()
        self._fill_providers()
        self.app.loge("[LLM] " + msg, "ok")
        self._set_status(msg + "（已保存，重启 dsh web 生效）")
        QMessageBox.information(
            self, "已保存",
            "默认模型已写入 settings.yaml（已自动备份 .bak）。\n重启 dsh web 生效。")

    def _pending_msg(self):
        adm = (self._pending_settings or {}).get("agent-default-model") or {}
        return "默认模型已改为 %s / %s" % (adm.get("provider") or "?", adm.get("model") or "?")

    def _set_btns(self, on):
        for b in (self._btn_save, self._btn_reload):
            b.setEnabled(on)

    def _set_status(self, text):
        self._status_lbl.setText(text)
