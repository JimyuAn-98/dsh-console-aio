# 实施方案与计划: 通用动态 SSH 隧道管理架构与向导助手 (v1)

> 状态: 🚀 实施中
> 日期: 2026-09-02
> 责任: Antigravity

---

## 一、背景与目标

原控制台的隧道实现存在三大核心局限：
1. **硬编码写死三卡片**：dsh-tunnel（正向中继）、connect-lab-dsh（直连实验室）、dsh-tunnel-reverse（本机反向），严重限制了网络拓扑结构与隧道数量；
2. **字段散落且概念割裂**：config.json 中散落着 ssh_server / lab_server / forward_ports / reverse_port，与多部署（Deployments）系统割裂，方案规划器也只能存数字端口而非拓扑；
3. **缺少小白友好的配置向导**：用户容易混淆正向（-L）与反向（-R）概念，需要场景向导辅助配置。

**本次重构目标**：
1. 建立声明式通用 TunnelItem 数据模型，支持任意数量、任意正向/反向模式、多端口映射规则、独立常驻守护；
2. 100% 保持老配置平滑向后兼容（自动无感迁移）；
3. 实现「隧道创建助手（Tunnel Wizard）」：包含场景模板（在家中继/内网穿透/局域网直连/从部署生成）与高级自定义，带端口占用检测；
4. 重构 ui/pages_tunnels.py（动态卡片流 + 批量启停 + 方案快照管理）；
5. 精简 ui/pages_settings.py，收敛配置职责；
6. 右侧健康监控栏与系统托盘与动态隧道配置实时联动。

---

## 二、分步推进清单

- [x] Phase 0: 方案归档与决策文档
- [ ] Phase 1: 核心配置与向后兼容转换 (core/config.py)
- [ ] Phase 2: 动态隧道管理与方案规划重构 (core/tunnels.py, core/tunnel_planner.py)
- [ ] Phase 3: 服务与信号桥调度接口 (app/services.py)
- [ ] Phase 4: 隧道创建助手向导 (ui/dialog_tunnel_wizard.py)
- [ ] Phase 5: 隧道管理页面动态卡片重构 (ui/pages_tunnels.py)
- [ ] Phase 6: 设置页精简与右侧监控/托盘联动 (ui/pages_settings.py, dsh-console-aio.py)
- [ ] Phase 7: 自动化测试编写与全量验证 (tests/test_tunnels_dynamic.py)
- [ ] Phase 8: 文档更新 (ROADMAP.md, ARCHITECTURE.md, RELEASE_NOTES.md, README.md)
