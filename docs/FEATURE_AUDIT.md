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
| 1 | 总览 | overview | ✅ 已核对 | 修 3 项(主题色/缓存失效/右栏日志色), 留 2 项待决(见下) |
| 2 | DSH 管理 | dsh | ⬜ 待做 | |
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

**待决：**

- D1/D4 实时探针被缓存：`collect_overview_data` 的 `web_ok/web_ms/local_token` 是实时值，却被写入总览缓存；
  服务启停不改变任何源文件 mtime，命中缓存时会长期显示过期的在线/离线状态。
  建议：命中缓存时仍做一次廉价本机 socket 探活刷新状态卡，或把实时字段排除出缓存。
- D5 force 绕过 busy：`refresh(force=True)` 在 `_busy` 时仍会发起第二次后台读取，两次结果都会 `_apply_data`。
  建议 busy 时忽略 force 或做结果合并。

## 四、跨页已确认待修点

- [ ] 4 处遗留 `QMessageBox.question`（`ui/dialog_tunnel_wizard.py`、`ui/pages_tunnels.py`×2、`ui/pages_ops.py`）→ `ConfirmBanner`。
- [ ] 布局记忆：主分栏 `setSizes([172,700])` 写死，无 `saveState/restoreState`。
- [ ] `run_dsh("restart")` 忽略 `stop_dsh` 返回值 + 固定 `sleep(1)`。
- [ ] 启动观测 15s + 监视 15s 对 `update_dsh` 的耗时叠加。
- [ ] 主题文件跨机导出/导入。
- [ ] 硬编码状态色清扫（总览页与右栏 `_append` 已修）：`ui/dialog_tunnel_wizard.py`、
  `ui/pages_deployments.py`、`ui/pages_dsh.py`、`ui/pages_logs.py`、`ui/pages_plugins.py`、
  `ui/pages_settings.py`；另 `ui/monitor.py` 齿轮 SVG 填充色 `#e6e6e6`（静态、浅色下偏淡）。
