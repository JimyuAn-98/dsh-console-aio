
# Release Notes

## v0.8.0 (未发布)

### 用量趋势图表（执行顺序 ③, 模型用量页）

- **每日 token 趋势图**：用量页新增趋势卡——按模型堆叠的每日柱状图（输入+输出,
  不含缓存命中避免大数吃掉趋势）, 7/14/30 天窗口切换, 悬停显示当日分模型明细,
  模型按窗口内总量取前 8、其余并入「其他」
- **自绘图表控件** `ui/chart.py`：零新依赖(不引 QtCharts 控包体), 主题 token 驱动
  (文字/网格), 模型配色为与暗色主题同族的固定 8 色板(首色=accent)
- **core**：`usage_stats` 新增 `days_models` 维度(天×模型, 与 days 同源累加, 向后兼容)
- 切换时间窗口只重排缓存数据不重扫; 远程部署(统计不支持)时显示占位

### 诊断报告 + 配置导出/导入（执行顺序 ②, 设置页新标签「诊断与配置」）

- **一键诊断报告**：工具链版本(git/node/npm/pnpm) + 本机 dsh/端口探测 + 隧道常驻进程
  存活 + 配置概览, 一键生成/复制/保存; 地址与用户名自动打码(IPv4 保前两段、用户名留
  首字符), 诊断不发起任何远程连接, 报告可安全外发求助/贴 issue
- **配置导出/导入**：导出完整 config.json 为带信封的 JSON(`_type`/`_version`/
  `_exported_at`, GUI↔CLI 共享格式, OTP deploy.xml 思想); 导入校验信封 + 确认覆盖
  (自动 .bak) + 热重载
- core 新增 `diagnostics.py`(collect/render/脱敏纯函数) 与 `config.export_envelope/
  parse_import`; `tunnel_mgr.tunnels_snapshot` 只取 pid/alive(记录里的明文主机/用户
  不入报告); Release 资产新增 SHA256SUMS.txt(下载校验)
- 修复 tunnels_snapshot 首版假设 pid 记录为裸 int 的数据形状 bug(实测记录为 dict);
  新增 4 组单测, 353 例全过
- **安装包发布者改为 JimyuAn**：Windows「设置→应用」的发布者字段与 README 版权行
  同步; AppId 不变, 升级安装仍识别为同一应用(装完 v0.8.0 后生效)

## v0.7.0 (2026-08-30)

### 实时主题定制（新增「主题」页, 16 页导航）

- **全部界面颜色实时可调**：主题页按 背景/边框/强调/控件/滚动条/文字/状态 分组展示
  全部颜色 token, 色块按钮（QColorDialog）+ hex 直填, 改动即时生效无需重启
  （`MainWindow.apply_theme` -> TOKENS 原地更新 -> 重新生成 QSS setStyleSheet,
  Qt 立即重抛光; 自绘 delegate 逐帧读 TOKENS 随重绘跟随）
- **透明度滑杆**：主背景/面板/日志区/页面宿主四个 rgba token 的 alpha 实时调节
  （80ms 节流防连续 repolish; 仅亚克力模糊模式有可见效果; 裁剪 5%-100% 防全透明）。
  亚克力模式主窗口背景从"全透明"改为 **bg_rgba 染色层**（rgb 随「主背景」联动,
  alpha=染色深度）—— 修复亚克力模式下改「主背景」颜色无效果的盲区
- **强调色派生自动化**：改 accent 时表格选中软色块/分栏高亮辉光自动重算,
  派生色不进覆盖集（用户只管本色）
- **主题持久化**：「保存为启动默认」写 config.json["theme"]（core save_config 自动
  .bak, 重启仍生效）; 「保存当前为主题文件」/加载/删除走 themes/*.json（打包运行在
  exe 目录, 与 config.json 同规则）; 「恢复默认」即时回到出厂配色
- **架构去双源**：`ui/widgets.py` 画家侧配色从常量改为逐帧读 TOKENS（QSS/自绘同源）;
  theme.py 新增 DEFAULT_TOKENS 快照、COLOR_GROUPS/ALPHA_KEYS 白名单（脏配置不致命,
  非法值忽略）、`valid_color`/`set_alpha`/`current_overrides`/主题文件 IO 纯函数;
  新增滑杆/主题列表 QSS; 启动时激活 config["theme"] 后再生成样式表
- 模糊/亚克力开关刻意不做：窗口材质须在显示前设置, 运行中切换需重建整窗
- 测试：theme 管理纯函数 5 组新用例（激活派生/白名单忽略/alpha 往返裁剪/覆盖集/
  主题文件往返）, 348 例全过; 16 页构造冒烟 + apply_theme 实时换肤离屏验证

### 主题色换版: #5686fe + 中性色相 240°→224° 对齐

- **accent 换纯蓝 `#5686fe`**（hover `#7aa3ff`），配套派生值同步：表格选中软色块、
  分栏手柄 hover 辉光、导航选中底 `bg_active`；`ui/widgets.py` 画家侧 ACCENT 同步
- **结构中性色（背景/边框/面板/按钮底/滚动条）色相 240°→~224°**：整体从"蓝紫夜"
  转为"纯蓝夜"，与新品牌 logo 同族；文字灰维持原值（色相差异不可感知）
- **硬编码色值全部提升为 token**：build_qss 模板内 btn_bg/btn_hover/inset_border/
  accent_soft 等散落字面量收编进 TOKENS（"主题唯一真源"契约恢复）；`build_qss`
  支持部分覆盖 dict；pages_plugins 徽章底、pages_version 详情框改读 token
- 新增 `python -m ui.theme` 一键重新生成 `ui/theme.qss`（非 Mica 外部覆盖层产物）；
  `tests/test_theme.py` 主背景断言改 token 驱动 + 部分覆盖用例（343 例全过）
- 决策记录：`.agents/notes/implemented/feature/2026-08-30-theme-accent-5686fe.md`

### 品牌 Logo / 图标接入

- **Logo 全链路接入**：根目录 `logo.png`（蓝鲸）→ 顶栏标题左侧 logo（DPI 自适应缩放，
  资源缺失自动隐藏降级为纯文字）+ 任务栏/Alt-Tab 窗口图标（`setWindowIcon`）+
  exe 图标（PyInstaller `--icon logo.ico`）+ 安装包/卸载项图标（Inno `SetupIconFile`）
- 新增 `logo.ico`（由 logo.png 透明补方正方形后生成的 16-256px 多尺寸图标）；
  logo.png 经 `--add-data` 进包，运行时 frozen 走 `_MEIPASS` 定位（与 theme.qss 同套路）
- 新增 **主题预览工具** `tools/preview_theme.py`：离屏（WA_DontShowOnScreen）渲染
  MainWindow，按 VARIANTS 输出新旧配色并排对比图到 `preview/`（`*_preview.png` 已
  gitignore）；旧配色以完整覆盖表保留在工具内供对比/回滚参照

## v0.6.0 (2026-08-30)

### 发版工程修复（首次 CI 全流程跑通暴露, 已全部修复并真机验证）

- **CI 打包链**：补装运行依赖（PySide6/zstandard, 缺失被 PyInstaller 静默跳过→exe 启动
  即 ModuleNotFoundError）；补 `pages_logs/pages_settings` hidden-import（懒加载页面分析
  不到）；补 `ui/theme.qss` 资源；exe 落到 iss 期望的 installer/dist、产物上传路径同步；
  免安装版停发, 安装包文件名带版本号
- **打包运行路径**（BUG-009）：config.json/隧道 PID 文件在 onefile 下写进临时解压目录
  （退出即失）；统一改为 exe 所在安装目录（安装到用户可写目录, 就地保存）
- 新增 `--diag-config` 配置解析诊断开关；conda 环境本地打包需把 `Library\bin` 加 PATH
  （ffi.dll 入包）已写入打包注意事项

### Agent 模式页对齐部署管理风格 + 备份运维页去重

- **Agent 模式页**：旧双表格布局改为与部署管理页同款——左栏窄列表（ModernList，按名字
  选，固定 260px）+ 右栏模式详情（信息行 + preset.yml 只读 Consolas）；去表格化
- **「备份与运维」更名「备份与凭据」**：移除日志分区（文件列表/查看尾部弹窗）——与
  「日志管理」页完全重复且是弱化版（无过滤/着色/实时跟随），日志需求归口日志管理页；
  保留独有的一键备份 ~/.dsh 与凭据存在性提示；core.ops 的日志纯读函数保留（测试覆盖）
- README 导航表与清单、页面截图同步；341 例全绿

## v0.5.0 (2026-08-30)

### UI 迁移到 PySide6（现代暗色主题, 可打包 exe 分发）

- **UI 框架从 tkinter 迁移到 PySide6**：现代暗色主题（QSS 独立 `ui/theme.qss`，可用 QssStylesheetEditor 编辑）、线程安全（后台线程 + Qt Signal 回主线程）、支持 PyInstaller 打包分发给小白
- **全部 13 个导航页完成 PySide6 迁移**：总览/隧道/会话/Agent/Profile/插件/任务看板/模型用量/LLM 配置/备份运维/SSH 密钥/版本管理/部署管理；管理逻辑照搬原 `mgmt_*.py`，业务行为不变
- **部署联动保留**：各管理页数据源随顶部部署选择器按 `DshRemote` 切换（本机 / 远程只读）
- **右侧栏实时健康监控**：本机端口 / 公网服务器 / 反向隧道 / ssh 进程，后台每 3s 探测，绿(在线)/红(不可达)实时状态 + 底部状态栏汇总
- **对话框迁移**：配置向导 `ConfigDialog` / 安装向导 `InstallDialog` / 环境检查 `EnvDialog` 迁为 PySide6 QDialog，后台执行子进程 + `safe_emit`
- **整合**：PySide6 主框架成为正式 `dsh-console-aio.py`（文件名不变，内容替换）；旧 tkinter 主程序归档 `legacy/`
- **打包适配**：`dsh-console-aio.spec` / `build_win.bat` 适配 PySide6（含 `ui/theme.qss` add-data），支持 PyInstaller onefile + Inno Setup 安装包
- **安全红线**：SSH 私钥 / API key 等凭据绝不读写明文；部署管理页不加密码字段（`DshRemote` 固定 `BatchMode` 免密）

### UI 前后端分层重构（阶段0，详见 docs/UI_LAYERING.md）

- **新增纯 Python 业务层 `dsh_core/`**（config / dshctl / tunnels，严禁 import PySide）+ **信号桥 `app/services.DshService`**：后端与 UI 之间一律 Qt 信号-槽（status/log/card/monitor/finished 五信号），禁止跨线程直接改 UI
- **隧道页与本机 dsh 启停/停止、右侧健康监控探测改走 service**：主程序中的内联业务实现（_run_dsh/_dsh_start/_dsh_stop/_run_python_tunnel/_start_persist/_stop_py_tunnel/_build_tunnel_obj/_probe 等）全部删除；隧道"常驻重连"状态改由 service 持有（窗口生命周期），修复页面切换重建后"停止隧道又自动重连"的隐患
- **config.derived 新增 allow_empty_ports 隔离分支**：测试用假配置的空端口不再被兜底回真实端口（3080 事故根因封堵）；默认行为与主程序完全一致
- **业务层可独立单测**：新增 tests/test_dsh_core.py（config 派生契约/隧道组装/信号桥转发），零真实资源
- **恢复隧道页"运行更新"（更新 dsh 本体，非控制台）**：该按钮自 PySide6 迁移后引用了未定义的 `_run_update`（点击静默报错）；现从 tkinter 旧主程序恢复完整流程并改进：停止 dsh web → git 拉取 → **清理旧构建产物（`pnpm run clean`，dsh 仓库自带安全清理）** → pnpm install → pnpm run build → 重启，落入 `dsh_core.dshctl.update_dsh` 并经 service 信号桥后台执行，点击先弹确认框列出各步骤；顺带修正旧版 `git fetch` 未在 dsh 仓库内执行的问题。清理一步是 2026-08-28 实测事故的修复：dsh 的 `lib/` 构建产物被 gitignore、git pull 不清，上游大版本改名删导出后，过期产物导致 `tsdown` 报 MISSING_EXPORT 构建失败（上游 CI 干净 checkout 不受影响，本地增量构建必踩）

### UI 前后端分层阶段2（波0+波1，详见 docs/UI_LAYERING.md）

- **DshService 新增 `result` 信号与通用结果模板**：带数据的操作结果统一通道（payload 至少含 `err`），core 异常也以恰好一次信号收场、不卡 UI busy
- **版本管理页业务下沉 `dsh_core/version.py`**：检查更新/一键更新走 service，页面不再 import subprocess/urllib/zipfile/shutil/threading；**修复存量 bug——源码模式更新后重启指向不存在的 app_pyside.py（FileNotFoundError 被吞，表现为更新完成后不重启）**
- **SSH 密钥页业务下沉 `dsh_core/keys.py`**：列表/生成走 service，ssh-keygen 全在 core；私钥安全红线成文（内容绝不读取/进日志/进返回值，仅存在性+指纹）；生成密钥增加重名预检与文件名校验（防路径穿越），失败文案中文化

### UI 前后端分层阶段2 波2（备份/Profile/会话页，详见 docs/UI_LAYERING.md）

- **三个写盘页业务下沉**：备份与运维（`dsh_core/ops.py`，一键备份 ~/.dsh 走 service，日志列表/尾部本地小 IO 同步直调）、Profile 管理（`dsh_core/profiles.py`，复制/删除走 service，core 防线重做校验：名称合法性/重名/web 拒删/commonpath 防路径穿越）、会话与工作区（`dsh_core/sessions.py`，归档/删除分组走 service，路径越界校验从 UI 下沉 core）
- **统一"远程只读红线"**：远程部署下三页的写操作（复制/删除/归档/备份）一律拒绝并中文提示——修复远程读却写本机目录的语义错误
- **修复存量 bug**：会话页"归档/恢复"调用不存在的 `dsh_data.write_workspace`（AttributeError，该功能自 PySide6 迁移起即失效），core 改为信封直写并保留 workspace.json 未知顶层字段、写前 .bak；Profile 页列表线程未用 safe_emit（页面销毁竞态 RuntimeError）
- 页面层不再 import shutil；新增三页纯单元测试（含越界拒绝零副作用断言）

### UI 前后端分层阶段2 波3 + 阶段3（插件/部署/对话框，详见 docs/UI_LAYERING.md）

- **插件管理页下沉 `dsh_core/plugins.py`**：列表汇总（bundle 基线 + cordis.patch.yml 叠加）、宿主基础设施防线（core 不信任 UI 预检）、patch 层停用/启用走 service；安装/卸载走通用 `service.run_cmd` 流式通道
- **部署管理页下沉 `dsh_core/deployments.py`**：刷新总览的"每部署一线程 + 代数/计数丢弃过期回调"编排收进 core 单线程串行，逐行经 `result("deploy-snap")` 回包；测试连接/保存走 service
- **页面全面解除对 `app._stream_cmd` / `app.DASH_REPO` 的依赖**（新增 `service.run_cmd` 通用流式命令通道，dash_repo 取 service 配置派生）
- **阶段3：对话框子进程业务下沉 `dsh_core/env.py`**：SSH 免密测试、工具版本探测、dsh 一键安装流（预检→clone→install→build→写 config）、pnpm PATH 注入；**三份重复的 `_stream_cmd` 实现归一为 `dshctl.stream_cmd` 一份**；`dsh_core/config` 新增 `save_config`（DSH_AIO_CONFIG 感知 + 写前 .bak）；无主窗口的独立对话框场景保留捕获式兜底
- 新增 44 例纯单元（plugins 13 / deployments 9 / env 22），业务层累计 290 例全绿

### UI 前后端分层阶段4（数据层归并 + 纯读页统一，重构全部完成）

- **数据层归并**：`dsh_data.py` 整体并入 `dsh_core/data.py`（git mv 保历史），仓库根保留兼容 shim（旧 import 路径不变，`DEFAULT_PRICES` 原地修改跨命名空间等价）
- **services 新增 `_run_core_op` 通用模板**：纯数据函数统一包装为 `result(op, {"data", "err"})`；新增 list_agent_presets / read_taskboard / read_usage_stats / read_settings / write_settings 五个触发方法
- **四个纯读页统一走 service**：Agent 模式 / 任务看板 / 模型用量 / LLM 配置的读取与 LLM 保存全部经信号桥；页面不再自起读取线程、不再直接引用数据层
- **分层重构主体完成**：dsh_core 12 个模块纯 Python 零 Qt、UI 层零子进程业务、后端→UI 全部 Qt 信号-槽，纯单元 294 例全绿

### 修复：插件启用不生效（BUG-001，根因是空 patch 文件）

- **现象**：插件停用正常、启用不生效（dsh web 侧仍是停用态），控制台列表却显示已启用
- **真实根因**（原记录的 bundle名→entry id 映射此前已实现，非本次根因）：启用删除禁用行后
  `write_yaml([])` 把 cordis.patch.yml 写成**空文件**；空文档 YAML 解析为 null 而非空数组，
  dsh 的 patch 层解析直接抛错——运行中的 web HMR 重载失败（旧树保留，启用不生效），
  且该 profile **重启即启动失败**（dshmarket patch.js 中 "profile is bricked" 警告的场景）
- **修复**：`core/data.py write_yaml` 空容器写 `[]`/`{}` 合法文档（保护全部 YAML 写路径）；
  `core/plugins.py` 启用未命中禁用行时追加 `disabled: false` 强启用行（对齐 dshmarket enableRow 语义）
- **查证结论**：dsh 启停链路无需 build——`dsh plugin` 是纯 pnpm 转发器（apps/cli/src/plugin.ts），
  dshmarket 自身启停也是纯 patch 文件操作（lib/patch.js）；纯单元 311 例全绿

### 插件管理对齐 dsh web：cordis 生效状态徽章（P2 第一步）

- **插件页新增「cordis」列**：显示每个条目在 cordis 合成层的生效状态（启用/停用/—未知），
  与「配置」列（cordis.patch.yml 本地视图，原「状态」列更名）并列，两列不一致即"配置改了但
  生效层没跟上/被更低层压住"，一眼可辨
- **`core/data.py dump_entry_states` 替代 `load_entry_id_map`**：同一次 `dsh --dump-config`
  子进程（零新增开销）同时产出 bundle名→entry id 映射与每条 entry 的 disabled 状态；
  逐行缩进栈解析而非完整 YAML（输出可含 `!!js` 表达式），config 里恰好叫 disabled 的键、
  嵌套 group 子条目、group 尾部字段均正确归属；dump 失败徽章退化为"—"不阻断列表
- **真机验证**：web profile 实测 293 条 id 映射 / 147 条生效状态；纯单元 316 例全绿

### 日志管理（P2 完成）

- **新「日志管理」导航页**（与底部控制台输出区分）：双 tab（dsh-web.out.log / dsh-web.err.log）
  tail 查看控制台拉起的 dsh web 落盘输出（`%TEMP%\dsh-dash`，start_dsh 既有重定向，此前无
  任何界面可见）——cordis loader 警告、Node 堆栈、启动 URL 等首次有了查看入口
- **混合编码逐行探测解码**：node/pnpm 行是 UTF-8，cmd.exe 批处理提示（如"终止批处理操作吗"）
  按控制台代码页 GBK 写入同一文件；UTF-8 严格解码失败逐行回退 GBK，中文不再乱码
- **增量 tail**：2 秒 QTimer 只读新增字节（半行回退、截断自动重置、2MB/2000 行防线），
  UI 线程纯本地小 IO，不起后台线程
- **过滤与着色**：包含/排除关键字即时过滤；行级着色复用主日志区配色（err 红/warn 黄/ok 绿），
  err 流整文件按错误色；`token=***` 展示层脱敏（web 登录 token 不外显，文件不动）
- **边界**：只覆盖控制台启动的实例（自行终端启动的 dsh 不落盘，页面有提示）；跟随滚动/
  清屏/打开日志目录；数据逻辑全在 `core/logs.py` 纯 Python 可单测
- 纯单元 337 例全绿（+21 例）；离屏单页构造冒烟真机日志通过（含 GBK 中文行）

### 表格页多栏展开（P1 遗留收官，P0-P2 主体全完成）

- **新通用组件 `ui/widgets.py`**：ModernList（QListView 自绘 delegate：标题 + meta 弱化行 +
  状态点 + 右侧圆角徽章 chips，无网格、行高加大、圆角选中块/hover 高亮）、`three_split`
  三栏可拖拽 QSplitter、`card_wrap` 标题卡片 —— 四页共用一套现代观感，替代复古网格表格
- **插件页**：列表 | 详情（徽章 chips + 描述/来源/patch 键值）| **配置**（cordis 合成 entry
  原文只读，来自 `dsh --dump-config`，core 新增 entry 原始 YAML 块抓取）；配置态与 cordis
  生效态一致时列表不显示第二徽章，**只提示分歧**（例外才可见）
- **会话页**：分组 | 会话 | 会话详情（选中单个会话的完整信息 + 原始数据 JSON，此前无法查看）
- **用量页**：按模型 | 按天 | 明细卡（选中行完整字段与折算说明，数字右对齐排版）
- **部署页**：部署（状态点 + 在线/离线徽章）| 详情 grid | **操作日志**（测试连接/刷新总览/
  保存结果就地显示带时间戳着色，不再只进主日志）
- **坑与修复**：PySide6 把扁平 dict 存入 `setData(Qt.UserRole)` 会 QVariantMap 深拷贝，
  对象身份断裂 —— ModernList 改为 Python 侧自持行数据（浅拷贝保身份），Qt 侧副本仅供绘制
- 纯单元 338 例全绿（+1 例 yaml 块抓取）；四页离屏构造冒烟（FakeApp 注入假数据全路径）通过

### 设置页（弹窗收敛第一步，配置弹窗 → 标签页）

- **新「设置」导航页**（QTabWidget 两标签）：「隧道与部署」（场景模板 + SSH 测试 + ①-④
  全部配置字段，原 ConfigDialog）+「监控与命名」（三处机器命名 + 本机端口/公网隧道
  增删改表，原 MonitorSettingsDialog）——愿景 §二.5"配置在页面内完成，不层层弹窗"落地
- **入口整合**：顶栏「配置」按钮与右栏 ⚙ 监控设置改为**导航到设置页**（⚙ 预选监控标签），
  ConfigDialog / MonitorSettingsDialog 退役删除
- **保存即热重载**：以磁盘 config.json 为基准合并两页字段 → core save_config(自动 .bak)
  → `reload_config()`（原 `_reload_config` 公开化）——端口/命名/监控点即时生效，不再
  "完整生效需重启"；隧道 SSH 参数下次启动隧道生效（状态栏明示）
- 测试：ConfigDialog 三个用例迁为 SettingsPage 等价用例（构造回填/模板填充/保存合并+
  热重载/非法整数拒绝），配置读写 monkeypatch 拦截绝不写真实 config.json；339 例全绿

### 概览页重设计 + 数据修复（BUG-007/008）

- **修复"数据看不到"**：概览页快照结果原先经 bridge 发进底部日志区，状态标签永远停在
  "读取中…"；现改页面级 Signal + safe_emit 回 UI，数据获取走 service.ctl 探测（技术债
  "概览页裸线程未走 service"一并清偿）
- **修复"会话大小恒 0"**（BUG-007）：`DshRemote.dir_stats` 本地分支只数子目录直接文件，
  而会话目录是 组/会话/文件 三层——改为有界递归 `_tree_size`，概览页与部署页快照同源修复
- **重设计**（现代卡片语言）：运行状态卡（dsh web 探测圆点 + 本体版本，仓库 package.json）
  + 数据速览四卡（会话/模型用量含累计费用/任务板/插件与预设）+ 部署列表（ModernList：
  在线徽章 + 本体/市场双版本 + 插件/profile/预设/大小）+ 隧道速览（本机端口本机探、
  反向隧道经 ssh 查公网监听，与右栏监控同口径）；远程快照纯读，未配置/演示模式明示
- 真机离屏冒烟：3080 在线、会话 59/21 归档/70.4MB（修复前恒 0）、6 模型累计费用、
  隧道圆点全部正确；纯单元 341 例全绿

### 主题美化：表格/输入框/标签页/复选框/下拉框现代化

- **全局 QSS 升级**（theme.py 模板 + theme.qss 双路径同步）：QLineEdit 圆角+聚焦 accent
  描边；QTextEdit/QPlainTextEdit 圆角暗底（不覆盖代码自设的等宽字体）；QTableWidget
  无网格+扁平表头+accent 选中+交替行底色；QTabBar 下划线式选中；QCheckBox 圆角方块
  指示器（选中=accent 实心）；QComboBox 通用暗色下拉（#deploy 专属规则不受影响）
- **设置页微调**：端口表隐藏行号列 + 交替行底色（离屏渲染自查时抓到未设
  alternate-background-color 掉回浅色调色板的问题）
- 覆盖范围：设置/日志页标签、密钥/Profile/LLM/Agent/运维页与 EnvDialog 的表格、
  全部输入框与下拉框；离屏渲染 PNG 自查布局与配色（中文字体在 offscreen 平台不可见，
  以真机验收为准）；341 例全绿

### 布局：三栏页横向可扩展 + 全页状态文字上移 + 设置页纵向滚动

- **三栏页（插件/会话/部署）横向可扩展**：三栏 + 操作行装进 QScrollArea（透明融入背景，
  `mid.setMinimumWidth(1020)`）——视口不足时出**横向滚动条**，宽窗口自动铺满，未来加栏
  不挤压；底部位置让给滚动条
- **状态文字统一上移**：全部 15 个页面的底部状态条取消，状态文字移到**页面标题右侧**
  （monVal 样式）；概览页状态在刷新按钮左侧、设置页在标题右侧
- **设置页纵向滚动**：标签页 + 保存条装进 QScrollArea，矮窗口出纵向滚动条
- **关键坑（离屏渲染验证发现）**：滚动区外的长提示 QLabel 未开 wordWrap 时最小宽度
  =整行文字宽，把页面 minimumSizeHint 撑到 1530px——页面自身缩不下去，滚动条永远不
  触发；滚动区外提示一律开 wordWrap（页面最小宽度降到 774px，900 宽窗口正确出现滚动条、
  1400 宽自动铺满）
- 341 例全绿

### 多部署管理（原 v0.4.0 规划, 未单独发版, 随本版一并发布）

- 架构：dsh_data.py 新增 DshRemote 抽象（本机直接文件系统 / 远程 SSH 只读命令 + 文件拉取），部署清单存 config.json 的 deployments（gitignored）
- 部署管理窗口（mgmt_deployments.py）：部署 CRUD、连接测试、只读状态总览（dsh 版本 / 会话数 / 大小 / 插件数 / profile 数 / agent 预设数 / 在线离线）
- **页面部署联动**：8 个管理页（会话/Agent/Profile/插件/看板/用量/LLM/主题）数据源随顶部部署选择器切换（DshRemote），远程不可达时优雅提示
- **总览部署状态卡片**：总览页汇总所有部署快照（版本/会话/插件/在线离线）
- **SSH 密钥管理**（mgmt_keys）：安全红线——私钥内容绝不读取/展示/复制，只显示文件名/时间/指纹（ssh-keygen -lf）；公钥可查看复制；生成 ed25519 密钥
- 移除顶部"dsh 管理"菜单（全页面化后左导航即入口）
- 安全：远程默认只读，ssh BatchMode + 超时；写操作留待阶段 B

## v0.3.0 (未发布)

### 新增：dsh 管理（v2 架构）

- 架构：数据层 dsh_data.py（~/.dsh 各数据域，零依赖最小 YAML 解析器）+ 管理窗口模块 mgmt_*.py + 主程序顶部“dsh 管理”菜单动态加载
- 会话与工作区管理：按工作目录分组浏览/归档/恢复/删除（二次确认）
- Agent 模式管理：浏览 preset 与说明
- Profile 管理：列出/复制/删除 profile
- 插件管理：浏览已装 bundle、dsh plugin 官方命令安装/卸载、patch 层停用/启用
- 任务看板：ledger + scheduler 只读展示
- 模型用量统计：解压 session 聚合 token（按模型/天），价格估算（内置单价可编辑）
- LLM 配置：默认模型切换 + 自定义 provider 浏览（密钥仅环境变量名提示）
- 主题外观：settings.yaml UI 开关切换
- 备份与运维：~/.dsh 一键备份（排除凭据）、日志浏览、凭据存在性提示
- 版本管理（关于与更新）：显示当前版本、检查更新（读远程 version.json）、更新日志、一键自动更新（源码版：下载→备份→替换→重启；安装版：引导下载新安装包）
- **打包发布**：PyInstaller 单文件 exe + Inno Setup 安装包（中文向导、开始菜单/桌面快捷方式、卸载、升级）；首次启动自动引导配置（可跳过）

## v0.2.1 (未发布)

### 新增
- **隧道配置向导（替代手改 config.json）**
  - 配置对话框升级为分组向导：① 公网中转服务器 ② 本机 dsh ③ 隧道参数 ④ 轮询
  - 内置 3 个场景模板（在家→中继 / 实验室→直连实验室dsh / 本机→中继反向），一键填充端口映射
  - 支持在界面里直接编辑 forward_ports / lab_server / lab_user / lab_port / reverse_port（原来只能手改 JSON）
  - 新增"测试 SSH 连接"按钮：填好服务器即可在线验证免密能否连通
  - 每个字段带灰色帮助文字，降低配置门槛（面向使用者）
- **一键安装 dsh（辅助全新环境）**
  - 顶部新增"安装 dsh"按钮，打开安装向导
  - 填 dsh 仓库地址（默认官方 deepseek-harness）与目标目录
  - 自动环境预检（git / node / npm / pnpm 是否可用，缺失会明确提示）
  - 后台流式执行 clone → pnpm install → pnpm build
  - 安装完成后自动把 dash_repo 写入 config.json（重启生效）
- **环境检查独立窗口（运维辅助）**
  - 顶部新增"环境"按钮，独立窗口查看 git/node/npm/pnpm 版本
  - 显示推荐基准版本（直接写版本号：git 2.53 / node v24.19 / npm 11.17 / pnpm 11.7）
  - 每个工具带 更新/安装/卸载 三按钮：点击先说明将执行什么，确认后才执行
  - 更新：git 自带升级器 / npm i -g npm@latest / pnpm add -g pnpm@latest；node 提示用 nvm 或官网
  - 更新/安装 pnpm 时自动把全局 bin 目录注入 PATH（解决新版 pnpm 的 PATH 检查报错）
  - 安装：git/node 打开官网下载页；pnpm 用 npm i -g pnpm；npm 随 Node.js
  - 卸载：git/node 引导到 Windows 设置-应用-安装的应用；npm/pnpm 用命令行卸载（npm uninstall -g）
  - 安装 dsh 的目标目录支持系统文件夹选择弹窗（浏览…）
  - 安全：早期含真实 IP 的历史提交已用 git-filter-repo 重写脱敏并 force push

## v0.1.0 (草案)

首个开源版本。把 dsh 日常的 SSH 隧道管理、本机 dsh 启停、服务健康监控封装成一个零依赖的 Windows GUI。

### 新增
- **隧道引擎全量 Python 化（v0.2）**
  - 新增 tunnel_mgr.py：纯 Python SSH 隧道管理器（forward/reverse、start/persist/stop、断线重连）
  - dsh-tunnel / connect-lab-dsh / dsh-tunnel-reverse 三张卡片全部改由 Python 建隧道
  - update-dsh 改为纯 Python：git fetch/pull + pnpm install/build + 重启 GUI（流式日志）
  - 旧的 4 个 .ps1 已收进 legacy/，不再被界面调用
- **操控区（5 张卡片）**
  - 本机 dsh：一键 启动 / 停止（后台 pnpm dsh web，匹配 dsh+web 进程精确停止）
  - 三条 SSH 隧道：启动 / 常驻 / 停止（调用对应 .ps1）
  - update-dsh：一键运行完整更新（git 拉取 → 构建 → 重启，实时滚动日志）
- **健康监控（两层）**
  - 本机端口行：探测本机监听端口（每 4s）
  - 公网服务器 反向隧道行：SSH 直查公网中转服务器上反向隧道监听状态（每 20s）——
    这才是"隧道是否配置成功"的真实指标
  - 窗口全程不弹控制台（CREATE_NO_WINDOW）
- **配置外置**
  - 所有可调项集中在 config.json（IP / 用户名 / 仓库路径 / 端口 / 轮询间隔）
  - GUI 右上角【配置】对话框可编辑常用项
  - 无 config.json 时自动回退内置默认值
- **零依赖**：仅 Python 标准库（tkinter）

### 修复
- 修复 bat 启动器闪退（UTF-8 中文被 cmd 按 GBK 解析 + if 块内括号干扰配对）
- 修复子进程输出 gbk 解码崩溃（errors=replace）
- 修复 update-dsh 被误当作可启停（它是一次性更新，只有一个运行按钮）
- 修复 pythonw 环境下监控子进程弹出控制台窗口

### 使用
见 README（中英双语）。