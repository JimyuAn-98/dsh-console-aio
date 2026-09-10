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
| 1 | 总览 | overview | ⏳ 进行中 | 见下 |
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

## 三、跨页已确认待修点

- [ ] 4 处遗留 `QMessageBox.question`（`ui/dialog_tunnel_wizard.py`、`ui/pages_tunnels.py`×2、`ui/pages_ops.py`）→ `ConfirmBanner`。
- [ ] 布局记忆：主分栏 `setSizes([172,700])` 写死，无 `saveState/restoreState`。
- [ ] `run_dsh("restart")` 忽略 `stop_dsh` 返回值 + 固定 `sleep(1)`。
- [ ] 启动观测 15s + 监视 15s 对 `update_dsh` 的耗时叠加。
- [ ] 主题文件跨机导出/导入。
