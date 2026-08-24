# pnpm 更新 PATH 注入（新版 pnpm 检查）

- Status: implemented
- Date: 2026-08-25

## 背景

新版 pnpm（v10+）执行 add -g / bin -g 时硬性检查全局 bin 目录（%LOCALAPPDATA%/pnpm/bin）是否在 PATH，不在则报错退出。用户机器与开发机均复现；且 pnpm 禁止用 add -g 更新自身（ERR_PNPM_GLOBAL_PNPM_INSTALL），要求 pnpm self-update。

## 决策

- _stream_cmd 增加 env 参数（默认 None 向后兼容）。
- EnvDialog._run_cmd 对 pnpm 命令自动把 %LOCALAPPDATA%/pnpm/bin 注入子进程 PATH。
- pnpm 更新命令改用 pnpm.cmd self-update。

## 影响

- 环境检查的 pnpm 更新/安装不再报 PATH 错；实测注入后 pnpm bin -g 通过。
- 长期修复是用户跑 pnpm setup + 重启；GUI 注入是每次执行自动处理。
