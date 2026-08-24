# v2 架构：数据层 + 管理窗口模块化

- Status: implemented
- Date: 2026-08-25

## 背景

宏大计划（dsh 控制台）涉及 9 个管理窗口（会话/工作区/Agent模式/Profile/插件/任务看板/用量/LLM/主题/运维）。
若全部塞进单文件 dsh-tunnel-console.py（~1100 行）会失控；5 个并行 subagent 协同也要求文件边界清晰。

## 决策

三层架构（docs/ARCHITECTURE.md）：
1. dsh_data.py — 数据层：~/.dsh 各数据域读取/写入/备份，纯函数零依赖（自写最小 YAML 子集解析器，不引 PyYAML 保零依赖）；写入一律先 .bak 备份。
2. mgmt_*.py — 每个管理窗口一个独立文件，提供 Toplevel 子类；master 兼容 Dashboard / Tk root。
3. 主程序 — 顶部"dsh 管理"Menubutton + _open_mgmt() 动态 importlib 加载，新增窗口 = 新文件 + 菜单注册一行。

## 拒绝的替代方案

- 全部写进主程序：文件爆炸、subagent 并行冲突。
- 引 PyYAML：破坏"零依赖"卖点；自写解析器覆盖真实数据域（settings.yaml / cordis.yml 均为简单嵌套）足够。
- Notebook 标签页集成：改动现有 UI 布局风险大；独立 Toplevel 与现有 EnvDialog 模式一致。

## 影响

- 新增 dsh_data.py + 9 个 mgmt_*.py；主程序只加菜单与 _open_mgmt（~40 行）。
- 插件管理用 dsh_data.read_profile_package() 读 package.json 的 dsh.profile.bundles（已装插件真实来源；cordis.yml 在 bundle 组合架构下为空）。
- 数据层 YAML 解析器不支持嵌套 list（真实数据用不到），文档已注明。
