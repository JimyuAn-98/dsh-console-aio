# 多部署管理：DshRemote 远程抽象

- Status: implemented
- Date: 2026-08-25

## 背景

用户愿景（参考 anywhere-labs/dsh-desktop 后提出）：在隧道基础上，成为"对所有部署的 dsh 的管理"控制台——统一查看/管理分布在各机器（家里/公司/实验室/云主机）的 dsh 实例。差异化：dsh-desktop 是"跑 dsh 的桌面端"（单机），我们是"管 dsh 的控制台"（多机）。

## 决策

dsh_data.py 新增 DshRemote 抽象：
- 本地模式：直接文件系统（现状逻辑）
- 远程模式：ssh（BatchMode + ConnectTimeout）执行只读命令 + cat 拉取小文件
- 数据域函数可传 remote 参数统一取值

部署清单存 config.json 的 deployments 数组（gitignored，含主机信息）；新增 load_deployments/save_deployments（写前 .bak 备份）。

阶段 A（本次）：部署管理窗口 mgmt_deployments.py——CRUD + 连接测试 + deployment_snapshot() 只读状态总览（版本/会话/插件/profiles/presets/在线离线）。

## 拒绝的替代方案

- 远程部署 agent（每台机器装客户端）：运维成本高，破坏"零依赖单文件"卖点；SSH 免密已够用。
- 远程 zstd 解压统计用量：远程未必有 python/zstandard，阶段 A 只做 ls/du 轻量统计。
- 阶段 B 再考虑：各管理窗口部署选择器 + 远程写操作（dsh plugin 经 SSH）+ 远程用量。

## 影响

- dsh_data.py 增 DshRemote/deployment_snapshot/load_deployments/save_deployments。
- 主程序菜单加"部署管理"。
- 安全原则：远程默认只读；写操作确认 + 流式日志；部署信息只存 gitignored 配置。
