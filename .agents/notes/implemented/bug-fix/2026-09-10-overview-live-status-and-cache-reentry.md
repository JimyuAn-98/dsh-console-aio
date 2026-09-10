# 总览实时状态缓存过期与缓存防重入治理

- Status: implemented
- Date: 2026-09-10
- Related: `core/data.py`, `app/services.py`, `ui/pages_overview.py`, `ui/pages_plugins.py`, `tests/test_core_cache.py`

## 背景

P5 逐功能校验总览页时发现两处缓存语义问题：

1. `collect_overview_data` 把实时探针结果（`web_ok/web_ms/local_token`）与快照一起写入总览缓存；而 `needs_refresh` 只比较数据源文件 mtime，dsh web 的启停不改任何源文件 mtime，命中缓存时会长期显示过期的在线/离线状态。
2. `refresh(force=True)` 写作 `if self._busy and not force: return`，使 force 同时绕过了"绕过缓存"和"正在读取中"的防重入，造成重复后台扫描/SSH 快照，结果还可能乱序覆盖。

## 决策

- **实时字段不进缓存语义**：保留整包缓存（改动最小），命中缓存时渲染后再异步补一次轻量本机探活。新增 `core/data.py::probe_local_web`（纯 socket 0.8s + `get_runtime_token`）与 `app/services.py::probe_overview_local`；`ui/pages_overview.py` 在 `overview-live` 回包时只把 `web_ok/web_ms/dash_port/local_token/local_auth_url` 合并进当前 payload 并重渲染，**不写缓存**；`--smoke` 模式跳过（不触碰 3080）。
- **force 语义收窄**：`force` 只用于绕过缓存，不绕过 busy；busy 时一律 return。总览「刷新」按钮读取中置灰，`ui/pages_plugins.py` 同款判断一并加严。
- 不采用"每次进页全量 force"（丢秒开 + 跑远程快照），也不采用"缓存前剔除实时字段"的较重改法（保留整包缓存 + 补探活已满足正确性）。

## 拒绝的替代方案

- **总览进页强制全量刷新**：牺牲缓存收益，且触发远程 SSH 快照。
- **把实时字段从缓存剔除**：语义更干净，但需拆分 collect/merge，改动面更大。

## 影响

- 总览运行状态卡（含本地节点徽章/免密链接）命中缓存时也能反映当前 web 状态。
- force 不再造成重复读取；7 个数据页重复的缓存编排已登记为跨页技术债（`docs/FEATURE_AUDIT.md` §四），建议后续抽共享 mixin 收口。
