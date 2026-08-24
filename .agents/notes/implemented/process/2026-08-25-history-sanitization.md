# 历史脱敏（filter-repo 重写 git 历史）

- Status: implemented
- Date: 2026-08-25

## 背景

早期 3 个 commit（初版、脱敏 legacy、配置向导）在 README、主程序 DEFAULTS、legacy ps1 中含真实公网 IP、实验室 IP 与用户名。开源仓库必须从历史中抹除。

## 决策

用 git-filter-repo 2.47（pip 安装）的 --replace-text 规则重写全部 7 个 commit：
- 公网 IP → YOUR_PUBLIC_IP；实验室 IP → YOUR_LAB_IP；用户名 → YOUR_USER / YOUR_NAME
- force push 覆盖远程 main（83c483d → 7e4d209）

## 为什么不用 git filter-branch

本机 Git for Windows 2.53 的 filter-branch 在此环境对任何 --tree-filter 参数都报 usage（rev-parse --parseopt 的 premature end of input），无法使用。filter-repo 一次成功。

## 拒绝的替代方案

- **物理删除早期 commit（孤儿重建）**：会丢失全部提交历史；filter-repo 保留历史且达到同等安全效果，故选之。
- **手动 rebase 逐 commit 修改**：7 个 commit 易错且 filter-repo 更可靠。

## 影响

- 所有 commit hash 改变；本地备份在 dsh-backup-history/.git-*（工作区外）。
- 曾 clone 旧仓库的人本地仍有旧副本，无法远程抹除；GitHub 侧旧对象在 GC 后移除。
- 规则：任何新提交不得再引入真实 IP/用户名（AGENTS.md 安全章节）。
