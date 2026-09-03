# 设置页废弃旧隧道配置与手工端口表格，彻底清除老旧 Config 字段

- Status: implemented
- Date: 2026-09-03
- Related: `ui/pages_settings.py`, `core/tunnel_planner.py`, `core/diagnostics.py`, `config.example.json`, `config.json`

## 背景

在通用动态 SSH 隧道向导和卡片流架构落地后，所有隧道规则和监控点已完全由「隧道」页面及拓扑方案驱动。但设置页（`ui/pages_settings.py`）中仍保留了：
1. 历史遗留的手工编辑监测端口表格（`local_ports` / `remote_tunnels`）；
2. 历史遗留的场景模板（`TEMPLATES`，向配置注入 `forward_ports` / `reverse_port` / `lab_port` 等）；
3. `config.json` 和 `config.example.json` 中遗留的大量标量隧道字段（`forward_ports`, `reverse_port`, `lab_port`, `lab_server`, `lab_user` 等）。

用户在设置页点击保存设置时，手动端口表格会强行将陈旧的静态端口列表写回 `config.json`，破坏单一事实源，造成右侧健康监控与动态隧道再次脱节。

## 决策

1. **精简设置页标签与逻辑（`ui/pages_settings.py`）**：
   - 移除 `_local_tbl`、`_remote_tbl` 手动端口增删表格；
   - 移除 `TEMPLATES` 及对老旧标量字段的映射；
   - Tab 1 重命名为「基础与服务」，聚焦默认中转服务器、本机 dsh 服务参数和健康检查间隔；
   - Tab 2 重命名为「监控与命名」，聚焦机器命名（本机/实验室/公网中转），并以说明卡片明确监控点已由动态隧道系统自动派生；
   - `_on_save` 仅收集保存基础字段与机器命名，并在保存时主动从 `config.json` 中剔除 `local_ports`, `remote_tunnels`, `forward_ports`, `reverse_port`, `lab_port`, `lab_server`, `lab_user` 历史字段。
2. **清除配置文件历史冗余**：
   - `config.json`：物理删除遗留的老旧隧道标量字段；
   - `config.example.json`：移除旧端口表，补齐规范的 `tunnels` 与 `tunnel_plans` 模板。
3. **收敛下游模块引用**：
   - `core/tunnel_planner.py`：`PLAN_FIELDS` 收敛为仅 `("tunnels",)`，快照仅抓取 `name` 与 `tunnels`，应用方案时自动清理旧字段；
   - `core/diagnostics.py`：诊断端口探测直接取自动态 `local_ports`，脱钩 `forward_ports` / `lab_port`；
   - `core/data.py` 与 `ui/pages_deployments.py`：部署端口匹配优先查找动态 `tunnels` 中的对应映射。

## 影响

- 彻底根除了设置页保存对动态隧道健康监控的污染；
- 代码精简约 100 行，设置页体验更清晰清爽；
- 全量自动化测试（424 例单元测试 + 离屏 GUI 冒烟测试）全数通过。
