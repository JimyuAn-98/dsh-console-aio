# 实施计划索引（docs/plans）

> **规则**：计划文件统一命名 `YYYYMMDD-主题-vN.md`；落地后在本索引标「已落地」；
> 被取代的标「已取代」并保留指向；**同一批次的重复计划应合并，不再并存**。
> 本目录是历史沉淀，**当前路线与状态以 `docs/ROADMAP.md` 为准**；决策"为什么"见 `.agents/notes/`。

## 索引

| 日期 | 计划 | 状态 |
|------|------|------|
| 2026-09-11 | [dsh 全局包安装模式（pnpm -g）](20260911-全局包安装模式-v1.md) | 已落地（方案 A 双模式 + 自动检测） |
| 2026-09-11 | [节点访问规划：本机/远程 dsh 节点、Token 获取与总览展示](20260911-节点访问规划-v1.md) | 已落地（阶段 1/2/3），待实机验收 |
| 2026-09-10 | [dsh 启动报错捕获、端口清理与插件管理更新能力](20260910-dsh-start-recovery-and-plugin-update-v1.md) | 已落地（2026-09-10） |
| 2026-09-03 | [隧道系统治理](20260903-tunnel-system-remediation-v1.md) | 已落地（2026-09-03） |
| 2026-09-02 | [通用动态 SSH 隧道与向导](20260902-universal-dynamic-tunnels-and-wizard-v1.md) | 已落地（2026-09-03） |
| 2026-09-02 | [鉴权 Token 捕获与 SSH 信箱](20260902-auth-token-capture-and-ssh-mailbox-v1.md) | 已落地（2026-09-02） |
| 2026-09-01 | [主入口拆分重构](20260901-refactor-split-main-window-v1.md) | 已落地（2026-09-01） |
| 2026-09-01 | [内联确认条与系统托盘](20260901-inline-confirm-and-system-tray-v1.md) | 已落地（2026-09-01） |
| 2026-09-01 | [缓存层与技术债收口](20260901-cache-and-tech-debt-v1.md) | 已落地（2026-09-01） |
| 2026-09-01 | [文档结构整理与历史归档](20260901-文档结构整理与历史归档-v1.md) | 已落地（2026-09-01） |

## 合并记录

- **2026-09-10**：原三份重复计划
  `20260910-dsh-start-error-capture-and-plugin-profile-hang-fix-v1.md`、
  `20260910-dsh-start-log-monitoring-and-port-cleanup-v1.md`、
  `20260910-plugin-update-and-log-wait-v1.md`
  已合并为 `20260910-dsh-start-recovery-and-plugin-update-v1.md`（早期 3-5s 轮询设计被 15s 定稿取代）。
