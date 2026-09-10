# 交接文档（HANDOFF）

> **维护约定：本文件只在用户明确要求交接时更新**，平时不随每次改动刷新。
> 当前快照：**2026-09-10**。**下一阶段已定 = P5 逐功能校验与完善优化**（用户 2026-09-10 拍板）。
> 路线总览见 `docs/ROADMAP.md`，校验底稿见 `docs/FEATURE_AUDIT.md`。

---

## 一、当前状态（一句话）

PySide6 控制台 **17 页导航**（暗/浅亚克力 + 明暗变体 + 现代列表/卡片 + 系统托盘 + 内联确认条），
P0~P4 全部完成、P4 远程部署单独延后；2026-09-10 批次（dsh 启动报错流式捕获、端口清理、插件更新能力）
已提交 `ea1c673`；文档结构同日重排（ROADMAP 历史拆入 `docs/archive/ROADMAP_HISTORY.md`，
新增 `docs/plans/README.md` 索引）。纯单元 + GUI 冒烟口径 **435 + 86**；本机沙箱因 `.pytest-tmp`
写权限限制跑不绿（环境限制，非回归）。

## 二、目录结构

```
dsh-console-aio.py   主窗口骨架(顶栏/左导航/系统托盘/底部日志/自绘工具栏 + --smoke/--diag-config)
core/                后端业务(纯 Python 零 Qt): config/data/dshctl/tunnels/tunnel_mgr/
                     tunnel_planner/version/keys/env/ops/profiles/sessions/plugins/
                     deployments/logs/cache/diagnostics
ui/                  前端: pages_*.py(17 个, 全页面独立) + widgets/base/theme/monitor/
                     chart/palette/win32_frame/dialog_tunnel_wizard ; 旧 dialogs.py 已退役
app/services.py      信号桥(DshService, 唯一"起后台线程+转信号"处; _run_result_op/_run_core_op 模板)
tools/               dump_ui.py(离屏控件树 dump) / preview_theme.py(主题配色预览)
docs/                ARCHITECTURE(架构唯一权威)/ROADMAP/TESTING/BUGS/FEATURE_AUDIT/VISION/
                     plans/(+README 索引) / archive/(含 ROADMAP_HISTORY)
installer/           Inno Setup 脚本
.github/workflows/release.yml  发版: 推 v* tag → PyInstaller + Inno → 上传安装包
.agents/notes/       决策记录(implemented/proposed)
```

> 总览页与隧道页自 2026-09-01 起已是独立 `ui/pages_overview.py` / `ui/pages_tunnels.py`。

## 三、铁律（必须遵守）

1. **绝不自动跑会构造 MainWindow / 触碰 3080 的测试**。默认 `pytest tests/` 只跑纯单元层；
   GUI 冒烟须 `-m gui` 人工把关。应用自带 `--smoke`（构造即返回）是离屏验证手段。
2. 后端（core）与 UI 之间一律 Qt 信号-槽；**services.py 是唯一"起后台线程 + 转信号"处**。
   `_run_result_op`（带 events 的域函数）/ `_run_core_op`（纯数据函数）两道模板；
   新页面禁止自起线程。
3. 机器特定绝对路径、真实 IP/用户名不入库（config.json gitignored）。
4. 写操作前 `.bak` 备份；凭据只做存在性提示，绝不读写明文。
5. **每次改动必跑**：`compileall` 全量 + 相关纯单元；改 UI 做一次离屏 17 页导航冒烟。
6. **Windows 严禁 `os.kill(pid, 0)`**（== CTRL_C_EVENT，杀宿主；BUG-002）。
7. **打包(frozen) 下 `__file__` 指向临时解压目录**——持久化路径一律走
   `core/config.default_config_path()`；同文件内同名函数禁止重复定义（BUG-009 教训）。
8. 三引号 docstring 禁令：新代码一律 `#` 注释；必须用时只写英文纯 ASCII。

## 四、环境信息

- **Python**：conda env `console` = `C:\Users\1\.conda\envs\console\python.exe`（已装 PySide6/pytest，AGENTS.md 指定）；
  另有 `C:\ProgramData\miniconda3\python.exe`。
- 端口 3080 = 正在运行的 dsh web，千万别碰。
- 本地打包：`build_win.bat`（PyInstaller onefile + Inno）；用 conda python 打包须把
  `%CONDA_PREFIX%\Library\bin` 加进 PATH（否则 ffi.dll 不入包闪退）。
- CI 发版：改版本四处（`version.json` / `APP_VERSION` / `installer.iss` 默认值 / `RELEASE_NOTES.md`）→
  提交 → `git tag vX.Y.Z && git push origin vX.Y.Z` → Action 自动构建并挂 Release。
- CI 打包清单（新增懒加载页面必加）：`release.yml --hidden-import ui.pages_X` +
  `--add-data ui/theme.qss` + `pip install -r requirements.txt`。
- 当前版本：`version.json = 0.8.0`（v0.8.0 已发布 2026-09-10，累积 09-03 隧道治理与 09-10 启动/插件两批）。
- 诊断：运行中 F12 控件指认；`--diag-config` 打配置链路（出键名不出值）。

## 五、下一步：P5 逐功能校验与完善优化

目标：按 `docs/FEATURE_AUDIT.md` 的 **17 页 × 校验维度**矩阵逐页核实与打磨，收敛"文档宣称"与
"代码实际"的偏差，并补齐小功能。**一次只动一页**，每页产出：核对结论 + 修复项 + 对应测试，
同步 `docs/ROADMAP.md` 与 `RELEASE_NOTES.md`。

建议顺序：总览 → DSH 管理 → 隧道 → 插件 → 会话 → 用量 → 部署 → 日志 → 设置/主题 → 其余。

**已确认的待修点（可直接做）：**
- 4 处遗留 `QMessageBox.question`：`ui/dialog_tunnel_wizard.py`、`ui/pages_tunnels.py`(2)、`ui/pages_ops.py`。
- 布局记忆缺失：主分栏 `setSizes([172,700])` 写死，无 `saveState/restoreState`。
- `run_dsh("restart")` 忽略 `stop_dsh` 返回值且固定 `sleep(1)`。
- 启动观测 15s + 监视 15s 对 `update_dsh` 流程的耗时叠加（`core/dshctl.py`）。

发版留到功能更多时再做；届时按"四、环境信息"的四处版本号 + tag 流程执行。

## 六、协作提醒

- 用户**人工验收 GUI**：外观/交互类改动由用户重启控制台拍板，不要自行判定完成。
- 用户自行维护 README 截图（`docs/screenshots`）；提交用明确路径 add，**避免 `git add -A`**。
- 用户偏好：现代简约观感、少弹窗、固定栏宽不互相挤压、状态文字在标题右侧、"一件一件来"。
