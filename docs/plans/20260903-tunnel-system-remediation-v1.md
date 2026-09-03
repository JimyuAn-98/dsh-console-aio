# 实施方案: SSH 隧道管理全面缺陷修复与生命周期治理 (v1)

> 状态: 🚀 实施中
> 日期: 2026-09-03
> 责任: Antigravity

解决用户在实测中发现的四大核心缺陷（右侧监控不联动、切方案未停止旧隧道、添加隧道不显示且缓存陈旧、拓扑自检逻辑混乱与硬编码），并全面修复按钮级与生命周期级的潜在 Bug。

---

## 一、用户关注的核心问题与修复决策

1. **方案切换与运行中隧道的生命周期**：
   - 切换并「应用」新方案时，自动终止旧方案中正在运行的隧道，在控制台打出明确中文提示 `[隧道方案] 切换生效方案，已安全停止旧方案运行中的 X 条隧道`，根除端口冲突和后台僵尸进程。
2. **右侧监控栏与静态端口解绑**：
   - 彻底废除 `config.json` 与 `tunnel_plans` 中历史残留的手工 `local_ports` / `remote_tunnels` 覆盖。右侧监控栏和后台探测点一律**根据当前激活方案中的 `tunnels` 动态实时生成**。

---

## 二、模块修改规划

### 1. 核心配置与动态派生层 (core/config.py)
- 修改 `derived(cfg)`：不再被静态残留的 `local_ports` 覆盖，始终由 `dash_port` + `tunnels` 启用的端口动态合成；
- 提供清洗逻辑，清理历史脏数据。

### 2. 隧道规划器与自检层 (core/tunnel_planner.py)
- 更新 `PLAN_FIELDS`：方案快照聚焦于 `tunnels`，不再持久化静态端口表；
- 重构 `self_check`（启动自检）：
  - 移除硬编码的旧三件套（`dsh-tunnel`、`connect-lab-dsh`、`dsh-tunnel-reverse`）；
  - 动态按目标方案的 `tunnels` 真实探测；
  - 区分三种状态：🟢 `在线` / ⚪ `未启动` / 🔴 `异常`；
- 改进 `validate_plan`：排除自身进程的占用警告。

### 3. 隧道运行时管理器与进程杀除 (core/tunnels.py & core/tunnel_mgr.py)
- 强化 `stop_all()`：直接读取 `tunnel-pids.json`，一次性全部安全终止所有活跃隧道进程；
- 新增方案切换时的停机协调方法。

### 4. 隧道向导对话框修复 (ui/dialog_tunnel_wizard.py)
- 编辑态自身端口占用放行；
- 场景 ④「从已有部署生成」显式隐藏普通服务器输入框。

### 5. 隧道管理页面重构与联动 (ui/pages_tunnels.py)
- 彻底根治方案缓存陈旧问题：方案下拉框切换与读取时，一律通过方案名称实时从最新 `config.json` 获取；
- CRUD 操作完成后立即刷新下拉框与卡片，并热重载配置；
- 应用方案时协调停机并触发即时监控探测（`monitor_once`）；
- 修复 `_render_cards` 布局清理泄漏；
- 边界防呆（新建重名校验、删除当前方案安全处理）。

---

## 三、验证计划

1. 单元测试：`tests/test_tunnels_dynamic.py`、`tests/test_tunnel_planner.py` 及新增的 `tests/test_tunnel_lifecycle.py`；
2. 页面构造冒烟测试：`python dsh-console-aio.py --smoke`；
3. 模拟完整交互场景：新建隧道、切换方案、应用生效、启动自检、全部停止。
