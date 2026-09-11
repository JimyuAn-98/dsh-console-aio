# dsh 双安装模式：源码 / 全局包（pnpm -g）与自动检测

- Status: implemented
- Date: 2026-09-11
- Related: `core/pkgmgr.py`, `core/dshctl.py`, `core/env.py`, `core/config.py`, `app/services.py`, `ui/pages_dsh.py`, `tests/test_core_pkgmgr.py`

## 背景

用户查到 dsh 的更新指令是 `pnpm update -g @deepseek-ai/dsh`。核实：dsh npm 官方包 `@deepseek-ai/dsh`（`apps/cli`，`bin=dsh`）存在且公开；CLI 本身只有 `web` / `plugin` 两个子命令（`apps/cli/src/args.ts`），**没有 update/uninstall**——更新/卸载确实是 pnpm 全局包的职责。控制台此前只有源码模式（git clone + build），安装/更新动辄数分钟，卸载还要删含只读 `.git` 的整棵树。

本机还有一个坑：pnpm（corepack）在全局 bin 目录 `%LOCALAPPDATA%\pnpm\bin` 不在 `PATH` 时，连 `pnpm list -g` 都直接报错退出。

## 决策

- **方案 A：双模式并存**（用户拍板）。新增 `config.dsh_install_mode`（`source` | `package`），保留源码模式给 DSH 开发（跑本地未发布代码），新增全局包模式给普通用户。两模式共用 `~/.dsh` 数据，切换不迁移。**不做**方案 B（全面改全局包，会断掉本地源码工作流），**不做**方案 C（只补文档）。
- **判定收口 `core/pkgmgr.py::detect_mode`**：显式配置优先；否则源码目录可用则 `source`（保持既有行为），再全局包 `package`，都没有 `none`。启动/更新/卸载/版本/部署全部调它，禁止各模块各猜。
- **pnpm 环境修正 `pnpm_env()`**：全局 bin 前置进 `PATH` + 补 `PNPM_HOME`；`core/env.py::pnpm_env` 改为委托，消除两份实现。
- **自动检测而非手动切换**（用户要求）：DSH 管理页页头异步探测并展示「模式: 源码模式（路径，版本）/ 全局包模式（版本）」；安装卡默认按检测结果预选安装方式。
- **全局包安装成功即写 `dsh_install_mode=package`**，卸载时清空，保证三处（启动/更新/卸载）判定一致。

## 拒绝的替代方案

- **全面改全局包（方案 B）**：代码更少，但用户本机跑的是未发布的 DSH 源码（`D:\Applications\deepseek-harness`），会断开发流。
- **`npx @deepseek-ai/dsh web` 零安装**：每次启动都解析/下载，慢且不可控；作为文档备选保留，未接入生命周期。
- **在 `dsh_local_version` 内部自行探测模式**：会给每个调用点（含单测）引入 pnpm 子进程；改为可选 `mode` 参数由调用方传入。

## 影响

- 普通用户可秒级安装/更新/卸载（`pnpm -g`），彻底绕开 BUG-011 的只读 `.git` 删除问题；开发用户继续用源码模式。
- DSH 管理页页头可见当前模式；更新/卸载卡文案随模式切换。
- 新增 `tests/test_core_pkgmgr.py`（15 例：PATH 修正 / 模式优先级 / 命令拼装 / 包模式生命周期路由）；`tests/test_dialogs.py` 的 `_FakeService` 补 `detect_dsh_mode`/`install_dsh_pkg`，并新增「全局包模式无需仓库地址」用例。

## 遗留

- `pnpm -g` 首次安装/更新的真实链路需用户实机验证（本机当前无全局包）。
- npm 上 `latest` 目前是预发布 `0.1.5-rc.1`，「更新」会拉到 rc，需与版本卡「预发布」标注保持一致。
