# SSH 隧道管理生命周期管理缺失与动态监控缓存脱节治理

- Status: implemented
- Date: 2026-09-03
- Related: `docs/plans/20260903-tunnel-system-remediation-v1.md`, `core/config.py`, `core/tunnel_planner.py`, `core/tunnels.py`, `ui/pages_tunnels.py`

## 背景

通用动态 SSH 隧道向导和卡片落地后，实测暴露出四大核心缺陷：
1. 切换方案后右侧健康监控不生效，仍固定在旧端口或变空白；
2. 切换并应用方案不会停止上一方案启动的隧道，产生后台孤儿进程和端口占用冲突；
3. 向导添加隧道在管理页面不显示，切换方案因下拉框读取内存陈旧对象无法反映新拓扑；
4. 启动自检逻辑混乱，写死旧时代三件套且将未启动隧道误标为红色异常。

## 根因剖析

- **单一事实源被历史静态覆盖**：`core/config.py` 的 `derived()` 原逻辑若发现 `local_ports` / `remote_tunnels` 字段存在便直接使用，方案快照与新建方案中固化了老端口或空列表，覆盖了由 `tunnels` 动态计算的监控点。
- **生命周期调度缺失**：方案切换只写盘配置，未协调 `TunnelManager` 停机。导致旧隧道长连接与端口监听持续存在，新方案启动报端口冲突。
- **下拉框内存缓存陈旧（Stale Cache）**：`_plan_combo` 将启动时的方案 dict 存入 `itemData`，CRUD 未重新调用 `_plan_refresh()`，方案切换直接读 `currentData()` 导致新配置不可见，再次保存甚至抹除新加隧道。
- **自检逻辑遗留硬编码**：`self_check` 硬编码前置探测 `dsh-tunnel`、`connect-lab-dsh`、`dsh-tunnel-reverse`，且未启动状态被标记为 `False` 误导用户。

## 修复决策

1. **确立单一事实源**：`derived()` 始终由 `dash_port` + 当前方案 `tunnels` 启用的端口动态合成 `local_ports` 与 `remote_tunnels`，并在应用方案时清空顶层静态字段。
2. **闭环生命周期管理**：
   - 切换方案应用时自动安全停止上一方案所有运行中的隧道，并在控制台打出中文日志；
   - `stop_all()` 增强为遍历 `tunnel-pids.json`，清理任意方案遗留的存活隧道进程。
3. **消除方案下拉框陈旧缓存**：
   - 方案获取一律通过方案名称实时查询最新配置；
   - 所有 CRUD 完成后立即重新刷新下拉框、热重载配置并触发即时监控探测（`monitor_once`）。
4. **重构启动自检**：
   - 移除硬编码三件套，完全按目标方案的 `tunnels` 动态探活；
   - 规范化三态：🟢 在线(`True`) / ⚪ 未启动(`None`) / 🔴 异常(`False`)；
   - 在主日志打出详细逐项探活记录，单行展示紧凑统计摘要。

## 影响

- 自动化测试用例通过数由 421 升至 425，无任何历史回归。
- 方案切换实现零冲突无缝切换，右侧监控栏与卡片指示灯秒级联动。
