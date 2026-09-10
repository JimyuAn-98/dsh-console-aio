# 路线图历史（ROADMAP_HISTORY）

> 本文件承载从 `docs/ROADMAP.md`「当前状态」中拆出的历史完成项（2026-08-29 ~ 2026-08-31 及更早批次），供追溯。
> **当前路线与状态**见 `docs/ROADMAP.md`；**发版详细叙述**见 `RELEASE_NOTES.md`；
> **早期方案归档**见 `docs/archive/PLANS.md`；**已知问题**见 `docs/BUGS.md`。
> 2026-09-01 起的批次仍保留在 ROADMAP「当前状态（近况）」，待其沉淀后再迁入本文件。

## 一、阶段里程碑

- ✅ **P0 配置驱动完成**：三处机器命名可自定义、监测端口 GUI 编辑、保存即热重载
- ✅ **P1 外观全部完成**：深色亚克力（`set_accent_blur` blurbehind）、保留原生标题栏、分栏拖拽、右栏收起动画、DSH 品牌 +
  **表格页多栏展开**（插件/会话/用量/部署四页「列表-详情-配置」三栏现代列表）+
  **主题美化**（表格/输入框/标签页/复选框/下拉框 QSS 现代化）+
  **三栏横向可扩展**（视口不足出横向滚动条，每栏固定最小宽度互不挤压、变宽向右吸收）+
  **状态文字上移标题右侧 + 设置页纵向滚动**
- ✅ **BUG-001 已修**：插件启用不生效——根因是启用删空禁用行后写出空 patch 文件，`write_yaml` 空容器写 `[]`/`{}` + 强启用行兜底
- ✅ **P2 全部完成**：插件管理对齐 dsh web（cordis 状态徽章 + 合成配置原文）+ 日志管理页（tail/过滤/着色/混合编码解码）
- ✅ **弹窗收敛第一步（设置页）**：ConfigDialog/MonitorSettingsDialog 退役 → 「设置」页标签页（隧道与部署/监控与命名），顶栏「配置」与右栏 ⚙ 导航直达，保存即热重载
- ✅ **概览页重设计 + 两个数据 bug 修复**（BUG-007/008）：运行状态卡 + 数据速览（会话/用量/任务板/插件）+ 部署列表 + 隧道速览，数据走页面级 Signal；会话大小不再恒 0
- ✅ **v0.6.0 发布**（2026-08-30, tag→Action 自动出安装包）+ 发版工程修复：CI 打包链（运行依赖/hidden-import/theme.qss/产物路径）+ 打包运行路径（BUG-009）+ 隧道 PID 持久化
- ✅ **品牌 Logo 接入**：顶栏 whale logo + 任务栏/exe/安装包图标（logo.ico 多尺寸）
- ✅ **主题色换版**：accent #4f6ef7 → #5686fe + 结构中性色相 240°→224° 对齐（纯蓝夜）；QSS 散落色值全部收编 TOKENS；新增主题预览工具 `tools/preview_theme.py` 与 `python -m ui.theme` 主题产物再生成
- ✅ **实时主题定制（主题页, 16 页导航）**：TOKENS=当前生效色板（QSS/画家层同源），全部界面颜色即时可调即时生效；透明度滑杆（主背景/面板/日志区/页面宿主, 亚克力模式下主背景=模糊材质上的染色层）；主题文件保存/加载/删除（themes/*.json）+「保存为启动默认」（config.json["theme"]）；模糊开关刻意不做（窗口材质需重建整窗, 风险大于收益）
- ✅ **v0.7.0 发布**（2026-08-30, tag→Action 自动出安装包）+ CI 打包链补齐（pages_theme hidden-import / logo 资源 / exe 图标）+ Release 资产附 SHA256SUMS
- ✅ **执行顺序 ② 完成**：设置页新增「诊断与配置」标签——一键诊断报告（工具链/端口/隧道进程/配置概览, 敏感打码可外发, 不发起远程连接）+ 配置导出/导入（GUI↔CLI 信封格式, 导入 .bak+热重载）
- ✅ **执行顺序 ③ 完成**：用量页新增每日 token 趋势卡（按模型堆叠自绘柱状图, 7/14/30 天窗口, 悬停明细; core 补 days_models 维度）+ 三栏最低高度修复纵向滚动
- ✅ **执行顺序 ④ 完成**：全局命令面板 Ctrl+K（页面/部署/动作 搜索直达）
- ✅ **安装包发布者改为 JimyuAn**（Windows 设置→应用; README 版权行同步）
- ✅ **用量页数据缓存 + 进页按需刷新**（2026-08-31）：进页先读本地缓存直接呈现(绿)，数据源时间戳(最新 session 文件 mtime)变了才后台重扫，标题右侧转圈 + 绿/黄/红状态点（通用缓存层 `core/cache.py` + `RefreshIndicator` 控件，本期先接入用量页验证，其他数据页后续迭代接入）
- ✅ **模型价格持久化 + 弹窗重做**（2026-08-31）：价格写回软件路径 `model_prices.json`（`core.data` `load/save/effective_prices`），下次启动自动带入；每模型新增计费模式（按量 token / 订阅 token-plan，token-plan 不走按量估算）；价格弹窗改表格（模型列拉满不压缩 + 计费模式下拉 + 空闲/高峰双档）
- ✅ 纯单元测试 357 例全过，3080 宿主无恙
- ✅ **浅色主题 + 明/暗变体切换**（2026-08-31）：新增浅色 LIGHT_TOKENS 全套变体（背景/文字/边框/控件/滚动条全面反色，QSS 中散落 #fff 选中/强调文字收编为可换的 on_accent/on_selection token，画家层 hover/选中/spinner 改读 token），主题页新增「明/暗变体」卡一键切换，切变体即丢弃旧变体覆盖、持久化 config.json["theme_variant"]、原生标题栏跟随（set_immersive_dark），深色仍为启动默认；浅色在非 Mica 模式下走实时生成 QSS（不读深色出厂 theme.qss）
- ✅ **弹窗收敛第二步：环境检查 + 安装向导 → 页面内分步**（2026-08-31, 小菜②）：退役 EnvDialog/InstallDialog 两个模态弹窗（`ui/dialogs.py` 整体删除），改为 DSH 管理页「开发环境检查」内联表 + 「安装 dsh」页内分步卡（URL/目录 + 进度条 + 流式日志），业务仍在 core/env.py；打包 hidden-import `ui.dialogs` 移除；README 改述为页面内分步
- ✅ **卸载 dsh（保留/含数据）+ 环境检查卡修正**（2026-08-31）：DSH 管理页新增卸载卡——保留数据卸载（停 web + 删源码 dash_repo + 清 config、保留 ~/.dsh）/ 彻底卸载含数据（额外删 ~/.dsh）；删除前逐条列路径、「彻底卸载」二次确认、防误删守卫（不删主目录）；业务在 core/env.py::uninstall_dsh。顺带修正环境检查卡：版本/状态文字改主题 token（QSS 硬编码 Qt.black/绿 → text/ok/err, 明暗自适应）+ 表内按钮最小高度防裁切；新增 danger 红色按钮样式与 err_hover token
- ✅ **P4 远程部署子工具组改为延后/独立试验**（2026-08-31 拍板）：不进当前主分支、不占主线，用独立分支 + WSL 做远程部署原型，验证可行后再合并——详见 `.agents/notes/proposed/feature/2026-08-30-remote-deploy.md` 与同目录 API 状态标注
- ✅ **通用缓存层全面推广 + 技术债统一收口**（2026-09-01）：
  - **缓存推广与指示灯**：总览（Overview）、会话（Sessions）、Profile、插件（Plugins）、任务看板（Taskboard）、Agent 模式 全面接入 `core/cache.py` 与 `RefreshIndicator` 状态灯（绿=无变化/命中缓存、黄=数据有变化已刷新、红=获取错误）；
  - **核心纯数据层扩展**（`core/data.py`）：新增各数据域源时间戳探测（`sessions_source_mtime`、`plugins_source_mtime`、`taskboard_source_mtime`、`agent_presets_source_mtime`、`profiles_source_mtime`、`overview_source_mtime`）与纯数据聚合函数（`read_sessions_data`、`collect_overview_data`）；
  - **Service 信号桥收口与裸线程清理**（`app/services.py`）：`DshService` 统一调度出口，新增 `step` 进度信号与 9 个业务方法；彻底清理 `ui/pages_dsh.py`、`ui/pages_settings.py`、`ui/pages_sessions.py`、`ui/pages_profiles.py`、`ui/pages_plugins.py`、`ui/pages_taskboard.py`、`ui/pages_agents.py`、`dsh-console-aio.py` 中的所有裸线程（`threading.Thread`）与私有 `Signal`；
  - **测试完备**：400 个纯单元测试 + 83 个 GUI 冒烟测试全部通过。
- ✅ **全页内联确认条（`ConfirmBanner`）收敛全部危险操作弹窗**（2026-09-01, 路线 B）：新增 `ConfirmBanner` 内联确认组件（`ui/widgets.py` + `ui/theme.py`），支持 `level="danger"|"warn"` 语义色、动态操作文案与 `Esc` 键快捷取消；全面替代存量全部 `QMessageBox.question` 模态弹窗（包含隧道方案应用/删除、会话归档/恢复/删除分组、Profile 复制/删除、插件安装/卸载/停用/启用、部署删除、默认模型修改、SSH 密钥生成、配置导入覆盖、主题删除/重置、版本更新、DSH 更新/环境工具操作/彻底卸载等约 20 处操作），实现交互完全页面内嵌闭环。
- ✅ **系统托盘与常驻快捷运维**（2026-09-01, 路线 C）：支持 Windows 系统托盘图标（关闭窗口最小化到托盘不中断隧道），双击/左键恢复窗口；**动态 Tooltip 悬停监控**秒级同步展示本机 DSH 运行状态与 SSH 隧道联通状态；**快捷右键运维菜单**免开主窗口执行「启动/关闭/重启 DSH」「启动/关闭隧道」与真正「退出控制台」。

## 二、历史执行顺序记录（原 ROADMAP 编号清单）

1. **发版 v0.7.0**：提交当前批次（logo 全链路 + 主题色换版 + 实时主题页）→ CI 打包链补齐（pages_theme hidden-import / logo 资源 / exe 图标）→ 本地 build_win.bat 实测安装包 → tag 发版。✅ 已完成
2. ✅ **P3 切入：诊断报告 + 配置导出/导入**（2026-08-30 完成, 设置页「诊断与配置」标签）
3. ✅ **用量图表**（2026-08-30 完成, 用量页趋势卡）
4. ✅ **命令面板 Ctrl+K**（2026-08-30 完成）
5. **P4 两大件**：✅ 隧道规划器 T1+T2 完成（2026-08-30, 隧道页「隧道方案」卡；多拓扑快照切换/校验/自检）; 远程部署提案已获批 L1 受控写, R1 只读增强与 R2 排后续（提案见 `.agents/notes/proposed/feature/2026-08-30-remote-deploy.md`）
6. **小菜（穿插做）**：✅ 浅色主题；✅ 弹窗收敛第二步·环境检查+安装向导 → 页面内分步
7. ✅ **用量页数据缓存 + 进页按需刷新 + 模型价格持久化**（2026-08-31 完成）
