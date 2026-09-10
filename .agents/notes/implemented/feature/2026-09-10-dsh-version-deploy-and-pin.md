# DSH 管理页：部署指定版本与版本固定

- Status: implemented
- Date: 2026-09-10
- Related: `core/dshctl.py`, `core/env.py`, `app/services.py`, `ui/pages_dsh.py`, `tests/test_core_dsh_deploy.py`

## 背景

DSH 管理页此前只能"更新到最新"（`git pull --ff-only`），无法安装/回退到某个确定版本。用户明确需要"部署指定版本"能力（上游几乎全是 `-rc`/`-alpha` 预发布，需要按 tag 精确选择）。

## 决策

- 新增 `DshCtl.deploy_dsh_version`：停 web -> `git fetch --tags --prune` -> 校验 tag（`rev-parse --verify <tag>^{commit}`）-> `git checkout <tag>` -> `pnpm install` -> clean + build -> 重启；成功后写 `config.dsh_version_pin`。
- **工作区脏 -> 二次确认**：core 先只回 `{"dirty": True}` 哨兵（不改动任何东西），页面 ConfirmBanner 确认后再以 `allow_dirty=True` 重发。选择"询问"而非"自动 stash"，因为静默 stash 会让用户丢失对改动去向的预期。
- **回退旧版本提示**：按 Releases 列表（新->旧）判断选中项是否排在本机版本之后，是则在确认框提示"可能与 ~/.dsh 数据不兼容，建议先备份"（只提示，不强制）。
- **版本固定与更新联动**：`config.dsh_version_pin`；固定状态下点更新先弹窗确认是否切回默认分支（`update_dsh(to_main=True)` 先 `git checkout <默认分支>` 再拉取），成功后清除固定。默认分支优先 `origin/HEAD`，缺失回退 `main`。
- **安装也支持指定版本**：`install_dsh(..., version=...)` 在 clone 后 checkout 目标 tag；安装卡下拉与版本卡共用同一份 Releases 数据。
- **进度条**：`update_dsh`/`deploy_dsh_version` 发 `step` 事件（1..7），页面据此驱动进度条——此前 update 只有流水日志没有 step。

## 拒绝的替代方案

- **静默 stash 本地改动**：用户看不到改动去了哪里，风险更高；改为显式确认。
- **强制 `git checkout -f` 丢弃改动**：会不可逆丢数据，绝不可接受。
- **只允许源码模式/只允许安装包**：两条路径都要支持，但实现复用同一套 core 编排。
- **把"回退旧版"直接禁止**：上游以预发布为主，回退是正当需求；用提示而非阻止。
- **用任意 commit SHA/分支名部署**：只允许 Releases 列表里的 tag，降低误操作面。

## 影响

- DSH 管理页具备"查看日志 -> 选版本 -> 部署/回退/固定 -> 更新联动"的完整闭环。
- 新增 `config.dsh_version_pin`（README 配置表已登记）。
- 新增 `tests/test_core_dsh_deploy.py`（repo 状态/默认分支/部署编排/脏哨兵/to_main）与 service 测试。
