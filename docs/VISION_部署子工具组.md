# 愿景：OTP 式部署子工具组（探索笔记，2026-08-29 夜）

> 用户睡前随口一提的长期方向，先记下来、探索清楚，供后续会话展开。
> 参照物：**Office Tool Plus (OTP)** —— https://github.com/YerongAI/Office-Tool
> （UI 设计参考：https://deepwiki.com/YerongAI/Office-Tool/9-user-interface-reference ）

## 一、OTP 是什么、为什么值得参照

OTP 是 Windows 上部署/激活/管理 Microsoft Office 的第三方工具，单窗口、便携、绿色。
它的三个关键特征正是我们想要的"部署子工具组"形态：

| OTP 特征 | 说明 | 对我们意味着什么 |
|---|---|---|
| **页面化工作流，无向导弹窗** | 部署/激活/工具箱/设置全是**页面**，配置在页面内完成，不层层弹窗 | 我们的"配置向导/安装向导/环境检查"应从弹窗改为**页面内分步** |
| **GUI ↔ CLI 双模，共享配置** | GUI 生成的配置 XML 可被 `deploy.exe /xml xxx.xml` 命令行复用 | 我们的部署/隧道/远程配置应可导出为 JSON/脚本，GUI 与命令行同一份配置 |
| **状态即界面** | 进度、日志、结果都内嵌在页面（进度条/日志区/状态栏），极少模态框 | 我们的操作反馈应从"结果弹窗"改为"页面内状态" |

## 二、愿景蓝图（对齐用户原话）

### 1. 部署子工具组（Deploy 域）—— 本机 + 远程
- **本机部署**（已有雏形，深化）：环境预检 → 安装 dsh → 构建 → 启动，做成页面内分步（替代 InstallDialog 弹窗）
- **远程部署（隧道之上，重点探索）**：
  - 现有基建已就绪：SSH 隧道（tunnel_mgr）+ DshRemote（远程只读抽象）+ deployments 页
  - 想象：在隧道连通的基础上，对远程主机做「一键安装/更新 dsh、版本对比、web 健康探测（经隧道端口）、日志拉取、配置比对」
  - 红线不变：远程**写操作显式确认 + 只读优先**；凭据仍走 ssh 免密，不明文；操作前备份

### 2. 隧道构建辅助（Tunnel 规划器）
- 现有"场景模板"升级为可视化**隧道规划器**：
  - 本地端口 ↔ 远程端口映射的"连线式"编辑
  - 冲突检测（端口占用）、连通性自检（复用 probe 体系）、一键诊断报告
  - 隧道组：一次规划多条、批量启停、常驻编排

### 3. 更全面的 dsh 管理（13 页深化）
- web 日志实时 tail 进页面（替代打开日志文件）
- 进程/端口/版本实时面板
- 本机 vs 远程配置比对

### 4. 更细致的数据查看
- 统一「对象详情面板」：选中会话/插件/profile/部署 → 右侧面板直接看详情（**不弹窗**）
- 表格增强：排序/过滤/导出 CSV

### 5. GUI 现代化：简约、优雅、少弹窗
- **弹窗收敛策略**：
  - 向导类（配置/安装/环境）→ 页面内分步（step in place）
  - 危险操作确认 → 页面内确认条/滑出条（保留确认强度，去掉模态）
  - 结果提示 → 状态栏/日志区/页面内 toast
  - 保留弹窗的场景：确实需要阻塞聚焦的极少数
- **视觉**：暗色、清晰的层级与留白、统一组件（表格/卡片/标签/详情面板）、图标化导航
- 顺带：F12 检查模式 + 离屏渲染（screenshot_ui.py）正好是 GUI 迭代的验证工具

## 三、与现有架构的映射

```
core/                          → 新增
  deployments.py (已有, 深化)    remote_deploy.py(远程安装/更新编排)
  tunnels.py (已有, 深化)        tunnel_planner.py(映射/冲突/诊断)
  data.py (已有)                导出配置/portability.py
ui/                            → 新增 ui/widgets/（表格、详情面板、命令条、步骤页）
  pages_deployments.py 深化      部署工具组页面
  现有 13 页 → 统一视觉 + 详情面板
app/services.py                → 新操作走 _run_result_op/_run_core_op（信号-槽不变）
tools/screenshot_ui.py         → 每轮 GUI 改动的验证工具（渲染 PNG 对比）
```

## 四、分期建议（供明天讨论）

- **P0 GUI 现代化**（风险低、见效快）：先收敛弹窗 + 统一组件 + 页面内分步；验证工具：离屏渲染对比
- **P1 隧道规划器**：在现有 tunnels 上做映射编辑/自检/隧道组（纯增量）
- **P2 远程部署子工具组**：隧道之上，先只读（远程面板/版本/日志），再写（安装/更新，确认+备份）
- **P3 数据可视化深化**：用量图表、会话详情、导出

## 五、开放问题（明天聊）

1. 远程部署的执行方式：scp 文件？管道脚本？远程 dsh 的安装源（git clone vs npm 包）？
2. 隧道规划器与 config.json 拓扑的关系（多套拓扑切换要不要一起做）
3. GUI 现代化是否引入图标资源/字体（零依赖 vs 打包体积）
4. "远程写操作"与现有红线（远程拒写）的关系——是放开一部分受控写，还是保持只读？

---

# 第二轮：用户新想法（2026-08-29 夜-晨）

## 六、配置驱动的 UI（自定义监测端口 + 三处机器命名）

**现状痛点**：config.json 的 local_ports/remote_tunnels 端口能改，但 GUI（右栏监控点、隧道卡片、
部署下拉）是**启动时读 CONFIG 构建**的——改完必须重启才生效；"本机/实验室/远程服务器"名字是
硬编码/半硬编码（ITEMS desc、RightBar label、部署列表），GUI 不跟随。

**方向**：
- **前提工程 = 配置热重载**（docs/PLANS.md 已有 [规划] 项）：CONFIG 从"模块级常量"变为"事件源"，
  `configChanged` 信号 → 重建右栏监控点 / 隧道卡片 / 部署列表 / 监控探测点。这是"自定义一切"的地基。
- **监测端口可自定义**：local_ports / remote_tunnels 在 GUI 内**增删改**（不只改端口号），
  右侧栏、卡片圆点、监控探测全部跟随。
- **三处机器命名进配置**：
  - 本机：deployments[0].name（已有"本机"默认值）
  - 实验室：lab_server/lab_user 增加 name 字段（如"实验室 204"）
  - 中转服务器：ssh_server 增加 name 字段（如"公网中转"）
  - ITEMS 卡片/右栏/日志里的硬编码"实验室/公网"字样全部改为取配置名。

## 七、GUI 现代化（Mica / 光效 / 分栏 / 表格展开 / 品牌）

### 7.1 深色亚克力 / Windows 11 深色 Mica
- **Mica**：Win11 22H2+，经 ctypes 调 `DwmSetWindowAttribute(DWMWA_SYSTEMBACKDROP_TYPE)`，
  或直接用 [win32mica](https://github.com/marticliment/win32mica)（PyPI，已验证可用）。
- **Acrylic**：`SetWindowCompositionAttribute`（Win10 1809+，注意性能开销）。
- **回退策略**：旧系统/不可用 → 纯色深色 QSS（现有主题兜底），不崩不卡。
- **主题引擎**：QSS 参数化（Python 生成），支持 Mica 深色 / 纯色深色 / 浅色切换。

### 7.2 hover 光效
- 方案 A（推荐主力）：QSS `::hover` 状态（边框渐变、光晕感渐变底色）——零成本、可批量。
- 方案 B（点缀）：重点控件挂 `QGraphicsDropShadowEffect`（如主按钮/卡片选中态）——
  ⚠️ 已知性能坑（Qt 论坛多次报告全控件滥用会卡），**只用于少量控件**。
- 方案 C：自绘 paintEvent（最可控，成本最高）。

### 7.3 可拖拽分栏 + 展开/收起动画
- **QSplitter 原生支持拖拽**（现有布局可改造成 splitter 分栏：左导航 | 中栏 | 右栏，可拖拽调宽）。
- 展开/收起：`QPropertyAnimation` 控制 splitter sizes 或控件尺寸，配快捷键（如 Ctrl+B 收左栏）。
- **布局记忆**：分栏尺寸/展开状态持久化到 settings.yaml。

### 7.4 表格页多栏展开风格
- 方案：列表-详情-配置 **三栏**（QSplitter），或 QTreeView 可展开行（master-detail）。
- 适用页面：插件（列表 → 配置详情）、会话（分组 → 会话 → 详情）、用量（模型 → 日期 → 明细）、
  部署（清单 → 单机状态 → 日志）。

### 7.5 插件管理对齐 dsh web
- 现状：我们 plugins 页已有列表/启停/安装卸载（cordis insert/patch 视角）。
- **补齐**：每个插件的**配置状态**（组合后 config 内容，只读展示）、**cordis 状态徽章**
  （insert / patch / disabled / 缺失 / 异常）、与 dsh web 插件管理页逐项对齐
  （实现时对照 D:\Applications\deepseek-harness 的 web 插件管理实现取数）。

### 7.6 品牌：DSH 大写
- 大标题 "**DSH Console / DSH 控制台**"，全 UI 文案统一大写 DSH（与 dsh web 一致），
  标题栏/关于页/日志起始行同步。

## 八、功能补充（我帮补的横向清单）

1. **全局命令面板 Ctrl+K**：搜索页面/操作/隧道，键盘直达（OTP 式高效操作）。
2. **配置导出/导入**：当前 config.json / 隧道拓扑 / 部署清单可导出为一份 JSON，GUI↔CLI 共享
   （OTP 的 deploy.xml 思想；未来 CLI 模式 `dsh-console deploy --config xxx.json`）。
3. **日志查看器**：web/隧道/控制台日志 tail + 过滤 + 着色（替代"打开文件"）。
4. **数据可视化**：用量按模型/日期的图表（QtCharts 或自绘），会话明细钻取。
5. **诊断报告一键生成**：环境 + 隧道连通性 + 远程部署状态 → 汇总报告（可复制/导出）。
6. **托盘常驻 + 全局快捷键**：最小化到托盘，隧道状态托盘提示。
7. **多主题切换**（Mica/纯色/浅色）+ 布局记忆（见上）。
8. **远程部署子工具组**（第一轮愿景，不变）。

## 九、技术可行性注记

- Mica：win32mica（PyPI）/ DWM 属性，Win11 22H2+；回退方案必须有。
- 动画：QPropertyAnimation（PySide6 官方支持）。
- hover 光效：QSS ::hover 为主，QGraphicsDropShadowEffect 少量使用（性能教训：全控件滥用卡顿）。
- 热重载：CONFIG 事件化（configChanged 信号 → 重建视图），中等重构，是 P0 前提。

## 十、建议实施顺序（修订）

- **P0（地基）**：配置热重载 + 三处命名进配置 + 监测点 GUI 编辑 —— 为"自定义一切"打底
- **P1（外观）**：Mica/主题引擎 + hover 光效 + 分栏拖拽/动画 + 表格多栏展开 + DSH 品牌 —— 离屏渲染验证
- **P2（功能对齐）**：插件管理增强（配置/cordis 状态）+ 日志查看器
- **P3（进阶）**：命令面板 + 配置导出导入 + 诊断报告 + 图表
- **P4（愿景主线）**：隧道规划器 + 远程部署子工具组

## 十一、跨平台 GUI 策略（2026-08-29 决定：一套自适应套件）

**结论：一套设计系统（token + 组件库）+ 平台效果适配层；不做三套独立 UI。**

- 单一 PySide6 代码库，UI 逻辑约 80% 平台无关；多套套件 = 三倍维护成本，小项目不可承受。
- 拆分维度是"设计 token（颜色/圆角/间距/字体栈）"与"平台效果适配器"：

| 层 | Windows 11 | macOS | Linux |
|---|---|---|---|
| 背景效果 | Mica（DWM, 22H2+） | vibrancy（原生集成成本高 → 先半透明近似或纯色） | 纯 QSS 深色（尊重系统暗色） |
| 字体栈 | Microsoft YaHei UI | PingFang SC | Noto Sans CJK（QSS 多字体回退） |
| 标题栏 | 无边框自绘（配 Mica） | **原生标题栏**（红绿灯） | 原生 |
| 动效/组件 | QPropertyAnimation + 同一组件库 | 同左 | 同左 |

- **真正拦路虎在 core 层**：powershell/tasklist/taskkill/ssh.exe/pnpm.cmd 全为 Windows 专属；
  GUI 跨平台需要 core 平台抽象（进程/隧道/路径）。
- **渐进路线**：UI 层现在就跨平台就绪（平台探测 + 适配器接口，P1 主题引擎内建）；
  core 层 Windows 优先，等真有 Linux/macOS 用户再抽平台层。P1 阶段 Linux/macOS 即可走纯 QSS 回退运行。


