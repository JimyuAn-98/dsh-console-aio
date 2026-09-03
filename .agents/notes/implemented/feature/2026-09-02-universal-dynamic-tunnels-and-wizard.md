# Agent Note: 通用动态 SSH 隧道管理架构与向导助手设计

- **日期**: 2026-09-02
- **状态**: Implemented
- **分类**: Architecture & UX

## 1. 为什么做这次重构 (Context & Rationale)

现有的三卡片（dsh-tunnel, connect-lab-dsh, dsh-tunnel-reverse）和固定标量配置将网络拓扑写死，导致无法支撑多机器、多端口、灵活跳板与直连场景。通过引入通用声明式 TunnelItem 数据模型、向导助手与动态监控联动，将隧道能力真正解耦为通用的基础设施。

## 2. 核心决策 (Decisions)

1. **统一声明式模型**: 隧道以 id,
ame, mode (forward/reverse), host, user, ssh_port, orwards: [{local_port, remote_host, remote_port, desc}], uto_restart, enabled 结构化表达；
2. **零破坏向后兼容**: core/config.py 在遇到旧配置时自动无缝合成默认 	unnels 规则列表；
3. **向导与模板驱动**: 提供典型场景问答模板（在家中继/内网反向/局域网直连/从已有部署生成）降低小白用户心智门槛，内置端口冲突检测；
4. **全链路动态监控**: 右侧监控栏（RightSidebar）与后台探活自动从 	unnels 汇聚监听端口并在配置热重载时即时重建。
