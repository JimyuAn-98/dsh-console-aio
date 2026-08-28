# 交接文档（HANDOFF）

> **维护约定：本文件只在用户明确要求交接时更新**，平时不随每次改动刷新。
> 当前状态快照：2026-08-29，UI 前后端分层重构（阶段 0–4）已全部完成并收尾。

## 一、当前状态（一句话）

PySide6 控制台已完成分层重构：业务全部在 `core/`（纯 Python 零 Qt），信号桥在 `app/services.py`，
UI 在 `ui/` + 主程序 `dsh-console-aio.py`，全部经 Qt 信号-槽通讯。纯单元 299 例通过，工作树干净。

## 二、目录结构（2026-08-29 整理后）

```
dsh-console-aio.py   入口（主窗口壳 + 总览页 + 隧道页 + 日志桥）
core/                后端业务（纯 Python 零 Qt）: config / data / dshctl / tunnels /
                     tunnel_mgr / version / keys / env / ops / profiles / sessions /
                     plugins / deployments
ui/                  前端: pages_*.py 11 个管理页 + dialogs.py + base.py + theme.qss
app/                 信号桥: services.py(DshService)
tools/               工具: dump_ui.py(离屏渲染 dump)
tests/               pytest（纯单元默认跑; 构造 MainWindow 的测试须 -m gui 人工）
docs/                文档（ARCHITECTURE / UI_LAYERING / TESTING / PLANS / 个人使用指南）
installer/           Inno Setup 脚本 + 语言文件
legacy/              旧 tkinter / .ps1 归档（不再调用）
config.json          gitignored（真实配置）; config.example.json 模板; version.json 发版源
```

## 三、铁律（必须遵守）

1. **绝不自动跑会构造 MainWindow / 触碰 3080 的测试**（历史事故：dsh 被干死过）。默认
   `pytest tests/` 只跑纯单元层；`test_gui_ui.py`/`test_gui_smoke.py` 已标 `gui`，仅人工 `-m gui`。
2. 后端（core）与 UI 之间**一律 Qt 信号-槽**；services.py 是唯一"起后台线程 + 转信号"的地方。
3. 机器特定绝对路径、真实 IP/用户名不入库（config.json / 个人使用指南均 gitignored）。
4. 所有写操作前先 .bak 备份；凭据只做存在性提示，绝不读写明文。
5. 每次改动必跑：`py_compile` 全量 + 默认 pytest 纯单元层。

## 四、环境信息

- Python/PySide6：console env `C:\Users\1\.conda\envs\console\python.exe`（3.12.9, PySide6 6.11.2）
- 端口 3080 = 正在运行的 dsh web GUI，千万别碰
- 构建：`build_win.bat`（PyInstaller onefile + Inno Setup；spec 为 gitignored 本地文件）
- 控件指认：运行中按 F12 或启动加 `--inspect`，悬停显示控件身份、点击打印路径（向开发者指认界面用）

## 五、待办 / 已知事项

- 用户即将进行**功能与布局大更新**（下一步主任务）。
- GUI 验收项（分层重构遗留，用户已基本验过）：各管理页功能路径走查。
- OverviewPage.refresh 仍直连 core.data + 裸线程（未走 service，已知例外，可选后续收敛）。
- version.json 已同步 0.5.0；RELEASE_NOTES.md 中 v0.5.0 仍标"未发布"，发版时统一。
- 检查模式（--inspect）与隧道卡片圆点状态绑定（监控驱动）为最近新增，改动记录见 git log。
