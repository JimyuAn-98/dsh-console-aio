# 交接文档（HANDOFF）

> **维护约定：本文件只在用户明确要求交接时更新**，平时不随每次改动刷新。
> 当前快照：2026-08-30，**v0.6.0 已发布**（tag 触发 GitHub Action 自动出安装包）。

## 一、当前状态（一句话）

PySide6 控制台 15 页导航（暗色亚克力 + 现代列表/卡片组件），**P0/P1/P2 三阶段全部完成 +
弹窗收敛第一步（设置页）+ 概览页重设计 + 主题美化 + 三栏横向可扩展**；纯单元 **342 例**
全过；BUG-001~009 全部关闭；本地 `build_win.bat` 同参数构建与 CI 发版链路均已验证。

## 二、目录结构

```
dsh-console-aio.py   入口(主窗口壳 + 总览/隧道页 + 日志桥 + 自绘标题栏 + --smoke/--diag-config)
core/                后端业务(纯 Python 零 Qt): config/data/dshctl/tunnels/tunnel_mgr/
                     version/keys/env/ops/profiles/sessions/plugins/deployments/logs
ui/                  前端: 15 个 pages_*.py + dialogs.py(仅 Install/Env) + widgets.py
                     (ModernList/three_split/card_wrap) + base.py + theme.py(QSS 引擎, theme.qss 为其产物)
app/services.py      信号桥(DshService, 唯一起后台线程处; from_env 的 base_dir 打包=exe 目录)
tools/dump_ui.py     离屏控件树 dump(假环境自包含, 不碰真实资源)
docs/screenshots/    README 截图(用户自行维护, 提交前与其确认 git add 范围)
installer/           Inno Setup 脚本(OutputBaseFilename 已带版本号, PrivilegesRequired=lowest,
                     默认装 {localappdata}\Programs —— 用户可写目录, config.json 就地保存)
.github/workflows/release.yml  发版: 推 v* tag → PyInstaller + Inno → 上传安装包(仅安装包, 免安装版停发)
```

## 三、铁律（必须遵守）

1. **绝不自动跑会构造 MainWindow / 触碰 3080 的测试**。默认 `pytest tests/` 只跑纯单元层；
   应用自带 `--smoke`（假隔离：跳过特效/监控线程、构造即返回）是文档明示的离屏验证方式。
2. 后端（core）与 UI 之间一律 Qt 信号-槽；services.py 是唯一"起后台线程 + 转信号"处
   （纯本地小 IO 的 QTimer 轮询不在此列，如日志管理页）。
3. 机器特定绝对路径、真实 IP/用户名不入库（config.json / 个人指南 gitignored）。
4. 写操作前 .bak 备份；凭据只做存在性提示，绝不读写明文。
5. 每次改动必跑：`py_compile` 全量 + 默认 pytest 纯单元层。
6. **Windows 上严禁 `os.kill(pid, 0)`**（== CTRL_C_EVENT，广播 Ctrl+C 会杀宿主；BUGS-002）。
7. **打包(frozen)运行时 `__file__` 指向临时解压目录（_MEIPASS，每次启动重建）**——config、
   隧道 PID 文件等一切持久化路径必须用 **exe 所在目录**：统一走
   `core/config.default_config_path()` 与 `services.from_env`（均已封装 frozen 分支），
   **禁止新增 `__file__` 推导的落盘路径**；同文件内同名函数禁止重复定义（后置覆盖前置，
   源码运行恰好正确、只有打包才发作——BUG-009 的教训）。
8. 改动 UI 布局后用离屏渲染 + 编程断言自查（学 logs/三栏轮做法），观感由用户真机拍板。

## 四、环境信息

- Python/PySide6：conda env `C:\Users\1\.conda\envs\console\python.exe`（3.12.9, PySide6 6.11.2）
- 端口 3080 = 正在运行的 dsh web，千万别碰
- **本地打包**：`build_win.bat`（PyInstaller onefile + Inno Setup）；**用 conda python 打包时
  必须把 `%CONDA_PREFIX%\Library\bin` 加进 PATH**，否则 ffi.dll 不入包（_ctypes 闪退）；
  Inno 本机路径 `C:\Users\1\AppData\Local\Programs\Inno Setup 6\ISCC.exe`
- **CI 发版**：改版本四处（version.json / APP_VERSION / installer.iss 默认值 / RELEASE_NOTES
  定稿+开下一段）→ 提交 → `git tag vX.Y.Z && git push origin vX.Y.Z` → Action 自动构建
  `dsh-console-aio-setup-<版本>.exe` 并挂到 Release（RELEASE_BODY.md 为发布正文）
- **CI 打包清单（新增动态导入的页面必加）**：release.yml 的 `--hidden-import ui.pages_X`
  （页面在 _show_page 内懒加载，PyInstaller 分析不到）；`--add-data ui/theme.qss`；
  `pip install -r requirements.txt`（PySide6+zstandard，缺了静默不打进包）
- 诊断工具：运行中 F12 控件指认；**`--diag-config` 打印打包运行的配置解析链路**
  （frozen/exe/环境变量/路径/键数/派生端口，只出键名不出值）；诊断用 console 打包
  （去 --windowed）可抓 stderr——注意要用修复后的打包方式（见铁律 7/本地打包注意）

## 五、下一步（候选，见 docs/ROADMAP.md）

- **A2 弹窗收敛第二步**：危险操作确认 → 页面内确认条组件（存量 QMessageBox.question 约 20 处，按页分批）
- **A3 弹窗收敛第三步**：环境检查/安装向导 → 页面内分步
- **P3**：全局命令面板（Ctrl+K）/ 配置导出导入 / 诊断报告一键生成 / 用量图表
- **P4 愿景主线**：隧道规划器（映射编辑/冲突检测/隧道组）、远程部署子工具组
- **技术债**：仓库根 `dsh_data.py` 等 shim 迁移到 `core.*` 直连；多主题切换（Mica/纯色/浅色）+ 布局记忆

## 六、协作提醒

- 用户**人工验收 GUI**：外观/交互类改动由用户重启控制台拍板，不要自行判定完成；
  用户会在仓库里自行维护 README 截图（docs/screenshots）——提交时用明确路径 add，
  **避免 `git add -A` 扫进用户进行中的文件**。
- 用户偏好：现代简约观感（无网格表格/徽章/卡片）、少弹窗、固定栏宽不互相挤压、
  状态文字在标题右侧。
- 上游：os.kill 同一 bug 已报 deepseek-ai/deepseek-harness Discussion #4713，回复即可勿另开帖。
- 发版流程与打包清单见本文件"四、环境信息"；发版前跑 `pytest tests/` 全绿。
