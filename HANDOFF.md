# 交接文档（HANDOFF）

> **维护约定：本文件只在用户明确要求交接时更新**，平时不随每次改动刷新。
> 当前快照：**2026-09-12 01:35（+08:00）**。**v0.8.1 已发布**（本地 dsh 管理里程碑，CI success）。
> 下一阶段已定 = **v0.9.0：逐页完善其余功能页，把本地 dsh 控制台全做好**；远程/Linux 部署（P6）留到 0.9.0 之后。
> 路线总览 `docs/ROADMAP.md`；逐页校验底稿 `docs/FEATURE_AUDIT.md`；架构唯一权威 `docs/ARCHITECTURE.md`；已知问题 `docs/BUGS.md`。

---

## 一、当前状态（一句话）

PySide6 控制台 **17 页**（暗/浅主题 + 现代列表/卡片 + 系统托盘 + 内联确认条）。
**v0.8.1（tag `v0.8.1`，提交 `f5a6c54`）已发布**，CI 构建成功；本版内容：dsh **双安装模式**（源码 / npm 全局包）+ 自动检测、长操作**完整输出日志**（落盘前 Token 脱敏）+ **失败摘要/心跳**、卸载**删除加固**、节点访问规划（阶段 1-3）。
测试口径：**`pytest tests/` = 550 passed**（纯单元；GUI 冒烟须 `-m gui` 人工）。本机沙箱现在**能跑 pytest**（策略 danger-full-access），旧的 `.pytest-tmp` 权限限制已不再复现。

## 二、最近一批做了什么（2026-09-11 ~ 09-12）

- **双安装模式 + 自动检测**：新增 `core/pkgmgr.py`（`detect_mode` 判 source/package/none；`npm_env`/`npm_cwd`/`npm_version`；命令拼装）。启动/更新/卸载/部署/版本全部按模式分流。见 `docs/ARCHITECTURE.md` §3.2。
- **长操作完整输出日志**：`app/services.py` 的 `_begin_op/_op_log_write/_op_log_close/latest_op_log`，写 `<TEMP>/dsh-console-ops/<op>-<时间戳>.log`；DSH 管理页「打开操作日志」。
- **stream_cmd 健壮性**：改「独立读线程 + 队列 + 每 0.5s 主循环」，长命令静默时每 15s 心跳、超时真正生效；失败时打 `[失败摘要]` + ETARGET 中文提示。
- **卸载删除加固**：`_rmtree_force` = 原生 `cmd rmdir /s /q` 快删 → Python 后序精修（清只读、跳过 junction、每 2000 项进度）→ 残留清单。实测 75541 项 / 31.1s。
- **节点访问规划（阶段 1-3）**：`core/nodeid.py`（节点码）、`core/runtime.py`（runtime.json + 公网信箱）、总览「节点」区、部署配置显式化（`node_key/web_port/tunnel_id/access_port`）。
- **BUG-013 ~ BUG-020 全部修复**（见 `docs/BUGS.md`）；0.8.1 发版 + 打包加固（`release.yml` 改 `--collect-submodules core/app/ui`）。

## 三、目录结构（相对上一版的变化）

```
dsh-console-aio.py   主窗口骨架(顶栏/左导航/系统托盘/底部日志 + --smoke/--diag-config); APP_VERSION='0.8.1'
core/                后端业务(纯 Python 零 Qt): config / data / dshctl / pkgmgr(安装方式+npm命令) /
                     tunnels / tunnel_mgr / tunnel_planner / version / keys / env / ops / profiles /
                     sessions / plugins / deployments / logs / cache / diagnostics / nodeid / runtime
ui/                  前端: pages_*.py(17 个) + widgets/base/theme/monitor/chart/palette/win32_frame/
                     dialog_tunnel_wizard + cacheable.py(CacheableMixin); 旧 dialogs.py 已退役
app/services.py      信号桥(DshService, 唯一"起后台线程+转信号"处; _run_result_op/_run_core_op 模板;
                     长操作日志 _begin_op 等)
docs/                ARCHITECTURE / ROADMAP / TESTING / BUGS / FEATURE_AUDIT / VISION / plans/(+索引) / archive/
.github/workflows/release.yml   发版: 推 v* tag → PyInstaller(collect-submodules) + Inno → 上传安装包
RELEASE_BODY.md      CI 发布 Release 的正文(body_path)
```

## 四、铁律（必须遵守）

1. **绝不自动跑会构造 MainWindow / 触碰 3080 的测试**。默认 `pytest tests/` 只跑纯单元；GUI 冒烟 `-m gui` 人工。应用自带 `--smoke` 可离屏验证。
2. 后端(core)与 UI 之间一律 Qt 信号-槽；**`app/services.py` 是唯一"起后台线程 + 转信号"处**；新页面禁止自起线程。
3. 机器特定绝对路径、真实 IP/用户名不入库（`config.json` gitignored）。
4. 写配置前 `.bak` 备份；凭据只做存在性提示，绝不读写明文。
5. **每次改动必跑**：`python -m compileall -q dsh-console-aio.py core ui app tests` + 相关纯单元；改 UI 做一次离屏 17 页导航冒烟。
6. **Windows 严禁 `os.kill(pid, 0)`**（== CTRL_C_EVENT，杀宿主；BUG-002）。
7. **打包(frozen) 下 `__file__` 指向临时解压目录**——持久化路径一律走 `core/config.default_config_path()`（BUG-009 教训）。
8. 三引号 docstring 禁令：新代码一律 `#` 注释；必须用时只写英文纯 ASCII。
9. **dsh 包模式用 npm（不是 pnpm）**：pnpm 隔离布局满足不了 dsh 插件的动态 import（BUG-016）。
10. **安装/卸载/部署/更新成功后必须 `app.reload_config()`**，否则 `DshService._cfg` 是旧值、模式判定失效（BUG-018）。

## 五、环境信息

- **Python**：conda env `console` = `C:/Users/1/.conda/envs/console/python.exe`（PySide6/pytest 齐备）。
- 端口 3080 = 正在运行的 dsh web，**千万别碰**。
- **测试机用户 `JimyuAn`（家里那台），本沙箱用户 `1`**：用户机器上的路径/日志与沙箱不同，别把沙箱路径当用户路径。
- npm registry = `registry.npmmirror.com`（国内镜像，偶有同步延迟）；全局前缀 `C:/Users/<user>/AppData/Roaming/npm`。
- pnpm 坑：pnpm(corepack) 在全局 bin 目录不在 PATH 时会直接报错；`pkgmgr.pnpm_env()` 只服务环境检查卡的 pnpm 工具命令，**绝不设 `PNPM_HOME`**（BUG-013）。
- **版本号落点（发版四处→现在 6 处）**：`dsh-console-aio.py::APP_VERSION`、`version.json`、`installer/installer.iss::MyAppVersion`、`README.md`（中英各 1 处安装包名）、`RELEASE_BODY.md`（标题 + 安装包名）。
- **CI 发版**：改版本 → 提交推送 → `git tag vX.Y.Z && git push origin vX.Y.Z` → Action 自动构建并挂 Release。
- 本地打包：`build_win.bat`（conda 打包须把 `%CONDA_PREFIX%/Library/bin` 加进 PATH，否则 ffi.dll 缺失闪退）。
- 沙箱注意：**审批提示已禁用，绝不设 `sandbox_permissions`**；`git push` 正常可用。

## 六、下一步（v0.9.0：逐页完善）

按 `docs/FEATURE_AUDIT.md` 的 **17 页 × 6 维**（D1 数据 / D2 状态 / D3 确认与安全 / D4 缓存刷新 / D5 并发 busy / D6 观感主题）逐页过，**一次只动一页**，每页产出：核对结论 + 修复项 + 测试，并同步 `docs/ROADMAP.md`/`RELEASE_NOTES.md`。

- 已完成：**总览**、**DSH 管理**（FEATURE_AUDIT 第 1、2 行）。
- **下一个 = SSH 隧道管理**（第 3 行，`ui/pages_tunnels.py`）。

**已确认待修点（可直接做）：**
- 4 处遗留 `QMessageBox.question`：`ui/dialog_tunnel_wizard.py`、`ui/pages_tunnels.py`(2)、`ui/pages_ops.py`。
- 布局记忆缺失（主分栏 `setSizes([172,700])` 写死，无 `saveState/restoreState`）。
- `run_dsh("restart")` 忽略 `stop_dsh` 返回值且固定 `sleep(1)`。
- 启动观测 15s + 监视 15s 对 `update_dsh` 的耗时叠加（`core/dshctl.py`）。
- 4 分钟 npm 安装期间的进度体验（心跳已加，可再优化为分段提示）。

0.9.0 完成后 → **P6 远程部署（SSH 驱动）/ Linux 部署**（`docs/plans/` 待立，参考 `.agents/notes/proposed/feature/2026-08-30-remote-deploy.md`）。

## 七、协作提醒（用户偏好）

- 用户**人工验收 GUI**：外观/交互类改动由用户重启控制台拍板，不要自行判定完成。
- **一件一件来**；中文 UI；**少弹窗**（优先页内 `ConfirmBanner`）；文档做全（ROADMAP/RELEASE_NOTES/README 中英/notes/plans 同步）。
- 用户常要求「先不 push，功能 OK 再 push」；本次为发版已 push。
- 提交优先用**明确路径** add（用户曾提醒避免 `git add -A`）；文件结尾**恰好一个换行**（`git diff --cached --check` 门禁）。

## 八、本批踩过的坑（写代码前先扫一眼）

1. **pnpm 全局包 → dsh 启动即 100+ 条 `ERR_MODULE_NOT_FOUND`**：dsh 的 cordis-plugin-loader 运行时动态 `import()` 插件，pnpm 隔离布局不在 loader 祖先链上。→ 包模式用 npm（BUG-016）。
2. **`--prefer-offline` 复用过期 packument** → 明明已发布的版本报 `ETARGET`。→ npm 命令用 `--prefer-online`（BUG-020）。
3. **大目录删除像卡死**：旧实现走两遍 Python 全树。→ 原生 `rmdir` 快删 + 后序精修 + 进度（BUG-011）。
4. **静默命令超时失效**：直接在 `stdout.readline()` 阻塞。→ 读线程 + 队列 + 心跳（BUG-017）。
5. **安装/卸载后配置 stale** → 必须 `app.reload_config()`（BUG-018）。
6. **进度条按源码 7 步设范围、包模式只发 3 步 → 停在 42%** → 范围随模式 + 完成置满。
7. **经 JSON/补丁链路写多行字符串时 `\n` 会变成真换行**（会破坏 Python 源码）；写文件用「数组 join 换行」而不是字面量 `\n`。
