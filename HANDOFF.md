# 交接文档（HANDOFF）

> **维护约定：本文件只在用户明确要求交接时更新**，平时不随每次改动刷新。
> 当前快照：2026-08-29 深夜，**交接给 zcode 继续开发**（用户将人工验收 GUI）。

## 一、当前状态（一句话）

PySide6 控制台，分层架构完成（core 纯 Python 零 Qt / app 信号桥 / ui 前端），
**P0 配置驱动 ✅ + P1 外观 ✅** 刚收官：深色亚克力（系统级模糊）、无边框自绘标题栏、
分栏拖拽、右栏双态收起（100px 动画）、三处机器命名/监测端口可自定义（⚙ 监控设置 + 热重载）。
纯单元 **307 例**全过，工作树干净。

## 二、目录结构

```
dsh-console-aio.py   入口（主窗口壳 + 总览/隧道页 + 日志桥 + 自绘标题栏）
core/                后端业务（纯 Python 零 Qt）: config/data/dshctl/tunnels/tunnel_mgr/
                     version/keys/env/ops/profiles/sessions/plugins/deployments
ui/                  前端: pages_*.py 11 页 + dialogs.py + theme.py(主题引擎) + base.py
app/                 信号桥: services.py(DshService, 含 reload_config)
tests/               pytest（纯单元默认跑; 构造 MainWindow 的测试须 -m gui 人工）
docs/                路线:ROADMAP.md / 问题:BUGS.md / 架构:ARCHITECTURE.md /
                     契约:UI_LAYERING.md / 测试:TESTING.md / 历史:PLANS.md / 愿景:VISION
installer/           Inno Setup 脚本;  config.json gitignored(真实配置)
```

## 三、铁律（必须遵守）

1. **绝不自动跑会构造 MainWindow / 触碰 3080 的测试**。默认 `pytest tests/` 只跑纯单元层
   （307 例）；`test_gui_ui.py`/`test_gui_smoke.py` 已标 `gui`，仅人工 `-m gui`。
2. 后端（core）与 UI 之间**一律 Qt 信号-槽**；services.py 是唯一"起后台线程 + 转信号"处。
3. 机器特定绝对路径、真实 IP/用户名不入库（config.json / 个人使用指南 gitignored）。
4. 写操作前 .bak 备份；凭据只做存在性提示，绝不读写明文。
5. 每次改动必跑：`py_compile` 全量 + 默认 pytest 纯单元层。
6. **Windows 上严禁 `os.kill(pid, 0)`**（== CTRL_C_EVENT，向共享控制台广播 Ctrl+C，
   会 SIGINT 掉宿主；详见 BUGS-002 / .agents/notes/2026-08-29-os-kill-ctrlc-harness.md）。

## 四、环境信息

- Python/PySide6：console env `C:\Users\1\.conda\envs\console\python.exe`（3.12.9, PySide6 6.11.2）
- 端口 3080 = 正在运行的 dsh web GUI，千万别碰
- 构建：`build_win.bat`（PyInstaller onefile + Inno Setup；spec 为 gitignored 本地文件）
- 控件指认：运行中 F12 切换检查模式（悬停显示身份、点击打印路径）

## 五、下一步（见 docs/ROADMAP.md）

- **P2 功能对齐**：插件管理对齐 dsh web（配置状态 + cordis 状态徽章）；日志查看器
- **P1 遗留**：表格页多栏展开（列表-详情-配置）
- **BUG-001 待修**：插件停用/启用不生效（bundle名 vs entry id 映射）
- 技术债：OverviewPage.refresh 未走 service；core 内部 `import dsh_data` 可迁 `from core import data`

## 六、协作提醒

- 用户将**人工验收 GUI**：外观类改动（布局/字体/动效）由用户重启控制台拍板，不要自行判定完成。
- 用户近期关注：少弹窗、现代简约（Mica/亚克力、分栏动画、SVG 图标），命名/端口可自定义。
- 上游：os.kill 同一 bug 已由他人报 deepseek-ai/deepseek-harness Discussion #4713，
  我方补充证据回复已备好（在 #4713 回复即可，勿另开帖）。
