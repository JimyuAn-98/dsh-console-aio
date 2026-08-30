# 提案: 隧道规划器(可视化映射编辑 + 冲突检测 + 启动自检)

- Status: implemented(2026-08-30 落地, 用户拍板 T1+T2 一起; 落地形态见「决策」)
- Date: 2026-08-30

## 背景

现状: 拓扑散落在 config.json 的 remote_tunnels/forward_ports/local_ports/reverse_port
等字段里, 编辑靠设置页的表格式端口表(盲编), 场景模板只覆盖三种固定场景。痛点:
- 改端口/加映射时**冲突不可见**(本机端口已被占用、两条映射撞本机端口、与 dsh web
  端口撞车), 只有启动失败后才知道;
- 启动后"通没通"要自己开命令行探测;
- 愿景 §二.2 的"连线式规划、冲突检测、连通性自检、隧道组"均未落地。

基建已就绪: tunnel_mgr(Tunnel 引擎 + pid 持久化记录 sig/mode/forwards/watch)、
tcp_ok 探测、diagnostics.py(诊断报告)、monitor 体系。

## 决策(落地形态; 与原提案的差异见「拒绝的替代方案」)

1. **方案 = 拓扑字段的命名快照**(T2 多拓扑的核心模型): config.json 新增
   `tunnel_plans: [{name, forward_ports, reverse_port, lab_port, local_ports}]` 与
   `tunnel_plans_active`。「应用方案」= 把快照字段写回 config 顶层 + 热重载 ——
   引擎(TunnelManager)/卡片/监控继续读标准字段, **单一代码事实源**, 零引擎改动。
2. **校验**(core/tunnel_planner.validate_plan, 纯函数 + 本机 bind 探测):
   本机端口重复/范围非法、转发端口撞 dsh web 与实验室映射本机端、反向端口与转发
   端口在中转主机上撞车、特权端口(<1024)警告、监测端口重复警告、本机端口占用实测
   (tunnel_mgr 新增 `port_free`, SO_REUSEADDR 区分 TIME_WAIT 与活监听)。
3. **启动自检**(self_check): 逐隧道探测本机绑定端口(tcp_ok) + 进程存活
   (tunnels_snapshot); 反向隧道本机不监听, 只查进程。结果内联展示。
4. **UI**: 隧道页顶部「隧道方案」卡——方案下拉 + 应用/存当前为方案/重命名/删除 +
   校验 + 启动自检, 结果内联; 全部写操作有确认, save_config 自动 .bak。
5. **拓扑字段编辑仍走设置页端口表**(唯一编辑器, 规划器不重复造表), 规划器负责
   快照/校验/切换/自检。

## 拒绝的替代方案(含与原提案的差异)

- **规划器内重建映射表编辑器**(原提案 T1 内容): 设置页端口表已是这些字段的编辑器,
  造第二张表 = 双编辑器漂移; 实际价值集中在 校验/快照/切换/自检, 据此收窄。
- **plans 独立数据模型重定义三条隧道参数(host/mode/forwards 任意组合)**: 三条标准
  隧道的 key/卡片/监控全部要动态化, 改动面与风险远大于收益; 快照-写回模型零引擎
  改动且语义即"多套拓扑切换"。
- **连线画布式 UI**: 视觉炫但实现重、表格+即时校验对小白更高效。
- **让用户直接编辑 JSON**: 违背"小白用户"定位。

## 影响

- core/tunnel_planner.py(新) + core/tunnel_mgr.py(port_free) +
  dsh-console-aio.py(TunnelsPage 规划卡) + tests/test_tunnel_planner.py(6 组)。
- 362 例纯单元全过; 隧道页端到端离屏冒烟(存方案→校验→自检走真实 UI 链路)。
- 多套拓扑切换的语义边界: 方案只覆盖端口拓扑四字段; 三处机器地址(ssh/lab)是全局
  配置不随方案切换——跨机器的拓扑差异属于部署清单(deployments)域。

## 开放问题(遗留)

- 无(用户已拍板 T1+T2 一起; 编辑收窄为沿用设置页)。
