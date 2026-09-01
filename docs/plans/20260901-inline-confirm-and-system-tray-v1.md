# 实施计划: 页内内联确认条（弹窗收敛）与系统托盘后台常驻

本文档规划了控制台两大体验升级：
1. **弹窗收敛最后一步（路线 B）**：封装通用现代 `ConfirmBanner`（页内内联确认条）组件，替代全项目约 20 处传统的 `QMessageBox.question` 模态弹窗，实现无中断、现代化的交互体验；
2. **系统托盘与常驻（路线 C）**：支持最小化到 Windows 托盘、后台维持隧道与健康监测、托盘快捷右键菜单（显示窗口/立即刷新/重启dsh/真正退出）与托盘通知气泡。

---

## 方案设计

### 一、内联确认条组件 `ConfirmBanner`（`ui/widgets.py`）

#### 1. 组件外观与行为
- 继承 `QFrame(objectName="confirmBanner")`，默认折叠隐藏（`hide()`）；
- 支持两种危险级别：
  - `level="warn"`（警告级：黄色/橙色强调，主确认按钮为 `primary`）；
  - `level="danger"`（高危级：红色强调，主确认按钮为 `danger`）；
- 布局组成：
  - **左侧**：状态图符 + 标题（粗体） + 详细说明文案（支持多行/换行展示具体将要执行的操作/删除的路径）；
  - **右侧**：【取消】按钮（次要按钮） + 【确认执行】按钮（高亮/红色按钮）；
- 支持快捷键响应（按 `Esc` 自动取消收起，避免鼠标必须精准点击）。

#### 2. API 设计
```python
banner = ConfirmBanner(parent=self)

# 发起确认请求
banner.ask(
    title="确认删除 Profile",
    msg="将删除 ~/.dsh/profiles/test 及其配置文件，此操作不可撤销。",
    on_confirm=self._do_real_delete,
    level="danger",
    confirm_text="确认删除",
    cancel_text="取消"
)

# 取消/收起
banner.dismiss()
```

#### 3. 覆盖替换的页面清单
- `ui/pages_sessions.py`（删除会话、删除会话分组、归档/恢复会话）；
- `ui/pages_profiles.py`（删除 Profile、复制 Profile）；
- `ui/pages_plugins.py`（安装插件、卸载插件、禁用/启用插件）；
- `ui/pages_deployments.py`（删除部署节点）；
- `ui/pages_llm.py`（修改默认模型）；
- `ui/pages_keys.py`（删除 Key / 清空预设）；
- `ui/pages_dsh.py`（更新 dsh、卸载 dsh）；
- `ui/pages_settings.py`（导入配置覆盖）；
- `ui/pages_theme.py`（重置变体、删除主题文件）；
- `ui/pages_version.py`（版本更新确认）；
- `dsh-console-aio.py`（隧道方案应用、删除方案）。

---

## 二、系统托盘与常驻（`dsh-console-aio.py`）

#### 1. 托盘初始化与生命周期
- 实例化 `QSystemTrayIcon(QIcon(LOGO_ICO_PATH), self)`；
- 托盘气泡提示：首次最小化到托盘时提示“dsh 控制台已最小化到托盘，后台持续监控与隧道运行中”；
- 托盘双击/单击：激活前台显示主窗口（`showNormal()` + `activateWindow()` + `raise_()`）。

#### 2. 托盘右键上下文菜单（`QMenu`）
- 🐳 **显示主窗口**（加粗默认项）
- 🔄 **立即刷新**（触发全量监控与总览刷新）
- ⚡ **重启本机 dsh**（经 service 触发重启）
- —— 分隔线 ——
- ❌ **退出控制台**（执行完整资源释放并真正退出）

#### 3. 窗口关闭拦截（`closeEvent`）
- 用户点击窗口右上角 `X` 时：`event.ignore()` + `self.hide()`，转入托盘后台运行；
- 仅当用户在托盘菜单点击“退出控制台”或通过菜单栏“退出”时，才设置 `self._quitting = True` 并执行 `QApplication.quit()`。

---

## 三、实施步骤

1. **步骤 1：组件层与样式扩展**
   - 在 `ui/widgets.py` 中实现 `ConfirmBanner`；
   - 在 `ui/theme.py` 中补充 `QFrame#confirmBanner` 与确认条子控件的 QSS 样式（深/浅变体适配）。
2. **步骤 2：全页面危险操作弹窗替换**
   - 逐个页面引入 `ConfirmBanner`，将存量 `QMessageBox.question` 替换为 `self._confirm_banner.ask(...)`；
   - 保持危险操作先确认后执行的安全原则不变。
3. **步骤 3：主窗口系统托盘与常驻逻辑接入**
   - 在 `dsh-console-aio.py` 中添加 `QSystemTrayIcon`、右键菜单与 `closeEvent` 托盘拦截逻辑；
   - 确保 `--smoke` 模式与无头单测下安全绕过托盘初始化。
4. **步骤 4：测试验证与文档沉淀**
   - 运行全量 400+ 个单元测试与 GUI 冒烟测试；
   - 补充 `ConfirmBanner` 与托盘菜单单测；
   - 更新 `docs/ROADMAP.md`、`RELEASE_NOTES.md`，沉淀 note 记录。

---

## 四、验证计划

### 自动化测试
```bash
python -m compileall -q dsh-console-aio.py core ui app tests
python -m pytest tests/ -q
python -m pytest tests/ -m gui -q
python dsh-console-aio.py --smoke
```

### 手动验收
- 启动 GUI，测试各页面删除/卸载/归档操作，验证内联确认条展开、取消与确认执行流程；
- 点击右上角关闭按钮，验证窗口平滑最小化到托盘，托盘菜单各动作（显示、启动/关闭/重启 DSH、启动/关闭隧道、真正退出）响应正常；鼠标悬停可秒级查看 DSH 与隧道健康状态。

---

## 五、实施与验证结论（2026-09-01）

- ✅ **内联确认条（`ConfirmBanner`）**：组件在 `ui/widgets.py` 中落地，全项目约 20 处 `QMessageBox.question` 模态弹窗全部迁移收敛为页内内联确认条；
- ✅ **系统托盘（`QSystemTrayIcon`）**：在 `dsh-console-aio.py` 中落地，支持秒级动态 Tooltip 状态、右键快捷运维菜单、关窗最小化常驻与平滑退出；
- ✅ **测试全过**：
  - `python -m compileall` 零报错；
  - `tests/test_widgets.py` 4 例单测全部通过；
  - `pytest tests/ -q` 404 例单元测试全部通过；
  - `pytest tests/ -m gui -q` 83 例 GUI 冒烟测试全部通过；
  - `python dsh-console-aio.py --smoke` 返回 `SMOKE_OK pages= 1 deploys= 1`。

