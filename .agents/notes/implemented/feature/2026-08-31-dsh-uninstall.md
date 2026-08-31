# DSH 卸载（保留 ~/.dsh / 彻底含数据）+ 环境检查卡修正

- Status: implemented
- Date: 2026-08-31

## 背景

DSH 管理页弹窗收敛（小菜②）后，安装了 dsh 却没有对等卸载能力。用户反馈三小点：
①环境检查「当前版本」文字用 `Qt.black`，暗色背景下看不清；②环境表内按钮太矮、字显不全；
③缺「保留/不保留数据的卸载」。本篇覆盖 ③（新功能）与 ①/②（小修）。

## 决策

1. **卸载语义（用户已确认）**：两种模式都先停 dsh web → 删源码目录（config.dash_repo）→
   清空 `config.json["dash_repo"]`（写前 .bak）；二选一决定是否再删 `~/.dsh` 数据目录。
   - 保留数据卸载：只删源码 + 清配置；`~/.dsh`（对话/会话/工作区/配置）保留。
   - 彻底卸载（含数据）：额外删除 `~/.dsh`，二次确认（防手滑、不可恢复）。
2. **业务下沉 core.env::uninstall_dsh, 零 Qt**：与 `install_dsh` 对称的纯业务；事件回调
   `events("step"/"log")` 同构；UI 层 background 线程 + 类级 Signal + safe_emit 更新
   页内进度条/日志（沿用弹窗收敛的页级范式, 不在此引入技术债）。
3. **防误删守卫**: 仅当路径 `isabs` 且确实存在才 rmtree；数据目录守卫 `abspath(data_dir)
   != abspath(expanduser("~"))`——dsh_home() 恰好等于用户主目录时绝不删主目录。
4. **危险确认双保险**: 删除前 QMessageBox.question 逐条列出将删的具体路径; 「彻底卸载」
   额外一道二次 warning 确认(默认 No)。与 AGENTS"危险操作先确认"一致。
5. **环境检查卡修正**: ① `_apply_env` 版本/状态前景色由 `Qt.black`/`Qt.darkGreen`/`Qt.red`
   改为**逐帧读主题 TOKENS**（`text`/`ok`/`err`）——暗色不再黑字、明/暗变体实时自适应；
   ② 表内 更新/安装/卸载 按钮 `setMinimumHeight(28)` + 行高 `34`, 防被行高裁切。
6. **新增危险按钮样式**: `QPushButton#danger`（err 红底白字）+ `err_hover` base token
   （两变体各给 hover 值）——危险操作在 UI 上有明确红色语义。

## 拒绝的替代方案

- **只在"更新 dsh 本体"卡里加卸载按钮**: 卸载是独立的危险生命周期操作, 与安装对等,
   单独卸载卡 + 二选一模式更清晰。
- **卸载走 service.run_cmd 子进程删目录**: 目录删除是本机纯文件操作, 无子进程必要;
   放 core.env 纯函数 + 事件回调即可, 不绕子进程层。
- **文字颜色仍用 Qt.black 但切浅色**: 治标不治本; 直接用主题 token 才随明/暗变体自适应。
- **提供"仅删源码不动配置"独立模式**: 与确认过的两种模式重复, 增加界面复杂度。

## 影响

- `core/env.py`（+uninstall_dsh 与守卫）、`ui/pages_dsh.py`（卸载卡 + 双确认 + 环境表
  色/按钮修正）、`ui/theme.py`（#danger QSS + err_hover token 两变体）、
  `tests/test_core_env.py`（TestUninstallDsh 5 例）。
- 功能验证: 离屏冒烟通过（卸载卡在、环境行色=TOKENS(text/err)、取消确认不执行卸载）;
  手动功能校验 4 场景全过（保留删源/含数据删 ~/.dsh/无仓库 graceful/主目录守卫）;
  新增 5 例单测中 4 例在沙箱内因 tmp 写盘被拒(PermissionError, 环境限制, 与既有
  TestInstallDsh 一致; 真环境可过)。
- 已知边界: 卸载会先停 web; 若 dsh 源代码目录被其他进程占用, rmtree 可能失败并返回
  中文错误; 沙箱内 tmp 写测试为环境限制非回归。
