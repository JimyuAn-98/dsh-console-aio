# 架构（dsh 控制台 v2：管理功能扩展）

> 2026-08-25 定稿。原则：零依赖（仅 Python stdlib）、数据层与 UI 分离、
> 所有写操作先备份、只读功能优先、管理窗口独立文件（不膨胀主程序）。

## 分层

```
dsh-console-aio.py   主程序：现有功能 + 顶部"dsh 管理"菜单（导航到各管理窗口）
dsh_data.py             数据层：~/.dsh 各数据域读取/写入/备份（纯函数，无 GUI）
mgmt_*.py               管理窗口模块：每个提供一个 Toplevel 类（或 open(app) 函数）
  mgmt_sessions.py        会话 / 工作区 / 归档
  mgmt_agents.py          Agent 模式管理
  mgmt_profiles.py        Profile 管理
  mgmt_plugins.py         插件管理（参考 dsh-market：dsh plugin 命令 + disabled 补丁）
  mgmt_taskboard.py       任务看板（ledger + scheduler）
  mgmt_usage.py           模型用量/价格统计（解压 sessions 聚合）
  mgmt_llm.py             LLM/模型配置（settings.yaml agent-default-model + providers）
  mgmt_theme.py           主题/皮肤（settings.yaml UI 配置）
  mgmt_ops.py             备份迁移 / 日志 / 凭据提示 / 统计 / pet
```

## 数据层接口约定（dsh_data.py）

所有函数纯数据、无 tkinter 依赖；返回 dict/list；失败抛异常由 UI 捕获并中文提示。
写入函数一律先对目标文件做 .bak 备份（`backup_file(path)`）。

| 函数 | 作用 |
|------|------|
| dsh_home() | ~/.dsh 定位（DSH_HOME 环境变量优先） |
| read_yaml(path) / write_yaml(path, data) | 最小 YAML 子集解析/序列化（缩进 dict + "- " list + 标量 + 注释忽略） |
| read_workspace() | workspace.json（workspaceIds / archivedSessionIds） |
| list_sessions() | sessions 目录按工作目录分组（名称/数量/大小） |
| list_profiles() | profiles 目录列表（名称/含 cordis.yml 与否） |
| read_cordis(profile) | 解析 profile 的 cordis.yml（list of entries: id/name/config/insert/disabled） |
| write_cordis(profile, entries) | 写回（备份后） |
| plugin_cmd(profile, args) | 组装 dsh plugin --profile X ... 命令（由 UI 层用 _stream_cmd 执行） |
| read_settings() | settings.yaml dict |
| write_settings(data) | 写回（备份后） |
| read_taskboard() | ledger-v2.json + scheduler-v2.json |
| usage_stats(sessions=None) | 解压 session jsonl.zstd 聚合 token（按模型/天/会话）；依赖 zstandard，缺失则返回错误标记 |
| backup_dsh_home(out_zip) | 备份整个 ~/.dsh（排除凭据/密钥文件），返回文件清单 |

## UI 集成方式

主程序顶部加 **"dsh 管理"** Menubutton，菜单项打开对应 mgmt_*.py 的 Toplevel 窗口
（模式同 EnvDialog：transient + grab_set + 中文界面 + 危险操作确认 + 流式日志复用 _stream_cmd）。

管理窗口统一风格：ttk.Frame + F_BOLD 标题 + 表格（grid）+ 刷新按钮 + 关闭按钮；
只读操作即时刷新；写操作确认框（askyesno）+ 结果提示。

## 安全约束

- 凭据文件（.credentials.yaml、含 apiKeyEnv 的环境变量名）只显示"存在/最后修改"，不明文展示值。
- 写 settings.yaml / cordis.yml 前备份 .bak；导出备份 zip 排除凭据。
- 插件安装只接受用户显式输入的 npm 包名 + 确认；不自动执行未知构建脚本（提示）。
- 一切真实 IP/用户名不出现在任何提交文件（AGENTS.md 安全章节）。

## 参考实现

- dsh-market（https://github.com/dsh-market/dsh-market）：插件安装走官方 `dsh plugin --profile <name> add <pkg>`；
  热启停写 cordis.patch.yml 的 `- id: … disabled: true|false`；更新逐插件对比 npm 版本；
  备份/恢复用合并方式；写入前校验、失败自动回滚。
