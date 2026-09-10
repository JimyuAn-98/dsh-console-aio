# DSH 管理页：dsh 版本发布日志查看（GitHub Releases）

- Status: implemented
- Date: 2026-09-10
- Related: `core/dshctl.py`, `app/services.py`, `ui/pages_dsh.py`, `tests/test_core_dsh_releases.py`

## 背景

DSH 管理页「版本信息」卡此前只拉 GitHub `/tags`，显示 tag 列表 + 本机 `package.json` 版本；用户看不到"每个版本具体改了什么"，也无法判断该不该更新。上游 deepseek-harness 实际有完整的 GitHub Releases（tag `dsh-v<version>`，正文中英双语 Markdown，含发布日期与 prerelease 标记），这些信息此前完全没用上。

## 决策

- 数据源从 `/tags` 改为 `/releases?per_page=30`：一次请求同时拿到版本列表与更新日志正文；
- 归属仓库**固定官方** `deepseek-ai/deepseek-harness`（不随 `dash_repo` 的 git remote 推导，避免 fork/私有镜像场景的不确定性）；
- UI 用**单栏**（版本下拉 + 只读正文），不做左右双栏——卡片空间有限，单栏更紧凑；
- 正文**只显示中文段**：上游正文是"中文 + English"两段，纯展示没必要双语重复；
- 加**会话内 10 分钟 TTL 缓存**（`force` 绕过）：匿名 GitHub API 限流 60/h，进页复用避免浪费；
- 本机版本用 `package.json` 精确等于"tag 去掉 `dsh-v` 前缀"匹配，废弃原先脆弱的子串比较。

## 拒绝的替代方案

- **继续用 `/tags`**：拿不到发布日期、prerelease、正文，无法满足"看更新日志"。
- **从 git remote 推导 owner/repo**：项目定位是官方 dsh 控制台，固定官方更简单、可预期；fork 支持留待有真实需求再做。
- **双语都渲染 / 加语言切换**：单栏空间有限，中文用户看中文段即可；要英文可点「在浏览器打开」。
- **外部浏览器承载日志**：破坏页面内闭环；改为页内 Markdown 渲染 + 可选浏览器打开。

## 影响

- 版本卡信息量与可读性提升；新增 core 纯函数 `fetch_dsh_releases / dsh_local_version / cn_section / html_headings_to_md` 与对应单测。
- 本页状态圆点硬编码色改为主题 token，浅色主题自适应。
- 批 2（部署指定版本 / pin / 更新联动）待做，见 `docs/ROADMAP.md`。
