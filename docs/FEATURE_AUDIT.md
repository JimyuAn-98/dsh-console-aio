# 功能校验矩阵（FEATURE_AUDIT）

> **P5 阶段工作底稿**：17 个页面逐页核实 + 打磨，收敛"文档宣称"与"代码实际"的偏差。
> 规则：**一次只动一页**；核对完把状态改为 ✅ 并在「发现/修复」记录；
> 修复项同步 `docs/ROADMAP.md` / `RELEASE_NOTES.md` 与测试。
> 页面 key 与顺序以 `dsh-console-aio.py::NAV_ITEMS` 为准。

## 一、校验维度

| 代号 | 维度 | 核对要点 |
|---|---|---|
| D1 | 数据正确性 | 与 dsh 真实数据/行为一致（对照 `~/.dsh` 与 `dsh` CLI / D:\Applications\deepseek-harness） |
| D2 | 状态完备 | 空态 / 加载态 / 错误态都有明确中文提示，不空白、不卡死 |
| D3 | 确认与安全 | 危险操作走 `ConfirmBanner`；凭据/私钥只做存在性；远程写只读 |
| D4 | 缓存与刷新 | 进页按需刷新、`RefreshIndicator` 语义正确、无重复扫描 |
| D5 | 并发与 busy | 防重入、按钮态联动、页面销毁不崩（`safe_emit`） |
| D6 | 观感与主题 | 布局不挤压/可滚动、无硬编码色值、明暗自适应 |

## 二、进度表

| # | 页面 | key | 状态 | 发现/修复 |
|---|------|-----|------|-----------|
| 1 | 总览 | overview | ✅ 已核对 | 修 5 项：主题色 token 化、缓存失效纳入 config/价格、右栏日志色、命中缓存补实时探活、busy 防重入加严 |
| 2 | DSH 管理 | dsh | ✅ 已核对 | 批1 版本发布日志查看(含状态色 token 化); 批2 部署指定版本/固定/回退 + 更新/部署进度条; 批3 长操作完整输出日志(「打开操作日志」按钮, 落盘前 Token 脱敏) + 卸载删除加固 |
| 3 | SSH隧道管理 | tunnels | ⬜ 待做 | |
| 4 | 会话与工作区 | sessions | ⬜ 待做 | |
| 5 | Agent 模式 | agents | ⬜ 待做 | |
| 6 | Profile 管理 | profiles | ⬜ 待做 | |
| 7 | 插件管理 | plugins | ⬜ 待做 | |
| 8 | 任务看板 | taskboard | ⬜ 待做 | |
| 9 | 模型用量 | usage | ⬜ 待做 | |
| 10 | LLM 配置 | llm | ⬜ 待做 | |
| 11 | 备份与凭据 | ops | ⬜ 待做 | |
| 12 | SSH 密钥 | keys | ⬜ 待做 | |
| 13 | 部署管理 | deployments | ⬜ 待做 | |
| 14 | 日志管理 | logs | ⬜ 待做 | |
| 15 | 设置 | settings | ⬜ 待做 | |
| 16 | 主题 | theme | ⬜ 待做 | |
| 17 | 关于与更新 | version | ⬜ 待做 | |

## 三、总览页核对结论（2026-09-10）

**已修：**

- D6 富文本状态色硬编码：`ui/pages_overview.py` 的 `#7ecb6a/#e07a7a/#9a9ab0/#e0a050` 全部改为 `ui.theme.TOKENS`
  （新增 `_c()` 助手，口径同 `widgets._badge_color`），浅色主题下不再低对比。
- D6 右栏日志色硬编码（顺带全局）：`ui/monitor.py::_append` 的 `#e6e6e6` 等改为 TOKENS，修复浅色主题下右栏日志几乎不可见。
- D4 缓存失效缺口：`core/data.py::overview_source_mtime` 未纳入 `config.json` / `model_prices.json` 的 mtime，
  改端口/命名或价格后总览缓存不失效。已补齐，并在 `tests/test_core_cache.py` 增加
  `test_overview_source_mtime_tracks_config`。

**待决项已落地（2026-09-10）：**

- D1/D4 实时探针被缓存 → 采用"命中缓存补轻量探活"：新增 `core/data.py::probe_local_web`（纯 socket 0.8s + 运行时 token）
  与 `app/services.py::probe_overview_local`；`ui/pages_overview.py` 命中缓存时渲染后异步补探活，只刷新运行状态卡/本地徽章
  （不写缓存，`--smoke` 跳过）。
- D5 force 绕过 busy → 改为 `if self._busy: return`（force 仅绕缓存，不绕防重入）；总览「刷新」按钮读取中置灰。
  同一模式在 `ui/pages_plugins.py` 一并加严。

**节点访问规划·阶段 1（2026-09-11）：**

- 删除总览底部「隧道状态」卡（与右栏重复；其 `probe/remote_probe` 数据源在 `collect_overview_data` 中从未赋值，实为死卡）；
- 「部署」区改名「节点」、标题改「节点总览」；
- 远程节点在线改为"经隧道/直连访问端口探活"（`collect_overview_data` 写 `web_ok/web_ms`，`--smoke` 跳过）；
- 新增「在浏览器打开」。阶段 2/3（配置显式化、节点码/信箱/发现）见 `docs/plans/20260911-节点访问规划-v1.md`。

**节点访问规划·阶段 2（2026-09-11）：**

- `deployments[]` 显式化 `node_key/web_port/tunnel_id/access_port` + 节点添加/编辑对话框（含正向隧道下拉与端口校验）；
- 访问端口推导收口为 `core/data.py::deployment_access_port`（唯一实现，概览页/部署页共用）；
- 部署页新增「编辑节点」「在浏览器打开」，详情卡新增「访问端口」；
- **命名去冗余**：设置页移除 `lab_name` 入口；命名单一来源见 `docs/ARCHITECTURE.md` §3.1。

**节点访问规划·阶段 3（2026-09-11）：**

- `core/nodeid.py`（节点码 MAC→短哈希，持久化可改）+ `core/runtime.py`（`runtime.json` 落盘、公网信箱 JSON 发布/拉取/列举/删除、远端直读、`resolve_node_token` 三级解析）；
- 捕获即投递：`DshCtl._capture_local_token`；`_sync_push_token` 改用 `node_id`；
- 设置页「本机节点」卡（节点码 / 重新生成 / 立即同步 Token）+ 部署页「从公网信箱发现」（绑定 / 删除条目）。

**转为跨页技术债：**

- 7 个数据页（overview/agents/profiles/sessions/plugins/taskboard/usage）各自复制同一段缓存编排
  （`read_cache → needs_refresh → 拉取 → data_changed/write_cache → spinner 状态机 → busy 防重入`），
  存储层 `core/cache.py` 已集中，缺的是**编排层**收口（见 §四）。

## 四、跨页已确认待修点

- [x] **缓存编排收口**（2026-09-10 完成）：`core/cache.py` 加种类注册表与管理 API（`list_cached/clear_cache/clear_all_cache`）；
  新增 `ui/cacheable.py::CacheableMixin`，总览/Agent/Profile/任务看板/用量/会话 6 页已迁移；插件页因双 op/profile 维度暂留。
- [ ] 4 处遗留 `QMessageBox.question`（`ui/dialog_tunnel_wizard.py`、`ui/pages_tunnels.py`×2、`ui/pages_ops.py`）→ `ConfirmBanner`。
- [ ] 布局记忆：主分栏 `setSizes([172,700])` 写死，无 `saveState/restoreState`。
- [ ] `run_dsh("restart")` 忽略 `stop_dsh` 返回值 + 固定 `sleep(1)`。
- [ ] 启动观测 15s + 监视 15s 对 `update_dsh` 的耗时叠加。
- [ ] 主题文件跨机导出/导入。
- [ ] 硬编码状态色清扫（总览页与右栏 `_append` 已修）：`ui/dialog_tunnel_wizard.py`、
  `ui/pages_deployments.py`、`ui/pages_logs.py`、`ui/pages_plugins.py`、
  `ui/pages_settings.py`；另 `ui/monitor.py` 齿轮 SVG 填充色 `#e6e6e6`（静态、浅色下偏淡）。
