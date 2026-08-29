# 弹窗收敛第一步：配置弹窗 → 「设置」页标签页（A1）

- Status: implemented
- Date: 2026-08-29
- Related: docs/VISION_部署子工具组.md §一/§二.5（OTP"页面化工作流，无向导弹窗"）；
  docs/ROADMAP.md 弹窗收敛条目

## 背景

愿景 §二.5 弹窗收敛策略：向导类（配置/安装/环境）→ 页面内分步；危险确认 → 页面内确认条；
结果提示 → 页面内状态。用户点名先做"配置弹窗变标签页"。存量：ConfigDialog（顶栏入口，
保存后仅部分生效需重启）、MonitorSettingsDialog（右栏 ⚙，已带标签页与热重载）。

## 关键决策

- **两个弹窗合并为一个「设置」页两标签**：「隧道与部署」= ConfigDialog 全部字段 + 场景模板
  + SSH 测试（线程 + 内联结果，无弹窗）；「监控与命名」= MonitorSettingsDialog 的三处命名
  与端口表。交互逻辑原样平移，业务零改动（原则 3）。
- **入口导航化**：顶栏「配置」→ `_show_page("settings")`；右栏 ⚙ → 同页并预选监控标签
  （`app._pending_settings_tab` 一次性传参，页面构造时消费清零——页面随导航重建，无需
  长命状态）。
- **保存路径统一为"磁盘为基准合并"**：`load_config() → cfg.update(两页字段) → save_config`
  （core 自动 .bak）→ `reload_config()` 热重载。旧 ConfigDialog 的"手动写 + 需重启"路径
  退役；隧道 SSH 参数不能热生效的部分在状态栏明示（"下次启动隧道生效"）。
- **`_reload_config` 公开化为 `reload_config`**：设置页作为调用方，公开 API 不带下划线。
- **测试迁移**：ConfigDialog 3 个用例改为 SettingsPage 等价用例；load_config/save_config
  monkeypatch 拦截，绝不写真实 config.json。

## 放弃了什么

- 保留 ConfigDialog 作为兼容 shim：预发布阶段无外部消费者（AGENTS.md），直接删。
- 设置页做脏检查/未保存提示：v1 显式保存按钮已够，字段每次进页从磁盘回填。

## 剩余（后续轮次）

- 环境检查/安装向导 → 页面内分步（A3）；危险确认 QMessageBox.question 存量 20 处 →
  页面内确认条组件分批替换（A2）。

## 验证

- 纯单元 339 例全绿（设置页 4 例：构造回填/模板/保存合并+热重载记账/非法整数拒绝不落盘）。
- py_compile 全过；dialogs.py 精简约 300 行。
