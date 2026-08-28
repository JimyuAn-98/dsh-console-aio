# 测试套件安全边界（GUI/真实资源默认跳过）

- Status: implemented
- Date: 2026-08-28

## 背景

新增的 pytest 测试套件 `tests/`（test_dsh_data / test_tunnel_mgr / test_version_page /
test_dialogs / test_gui_smoke）中，`test_gui_smoke.py` 会在进程内构造真实 `dsh-console-aio` 的
`MainWindow`：它延迟加载真实 `config.json`（含真实 `dash_repo=D:\Applications\deepseek-harness`、
端口 3080、真实公网/实验室 SSH 服务器），并触发 `_start_monitor()` 的健康监控线程与
各页面构造器 `daemon=True` 起的真实后台线程（探测本地 3080/8090/3090、SSH 到公网与实验室服务器等）。

多次运行整套 `pytest` 后，端口 3080 正在运行的 dsh 进程（`node ... apps/cli/src/bin.ts "web"`）
的 PID 发生变化——实测确认跑测试会干扰/导致其重启。AGENTS.md 本就有"不真跑"冒烟约定，但套件
未落实，且当时运行 pytest 会直接触碰真实资源。

## 决策

1. 新增 `pytest.ini`（仓库根），默认 `addopts = -m "not gui"` + `testpaths = tests`：
   - 普通 `python -m pytest tests/` 只收集/运行纯单元测试（142 个），绝不构造 MainWindow、
     不读真实 config.json、不连 SSH/端口/进程。
2. `tests/test_gui_smoke.py` 顶部加 `pytestmark = pytest.mark.gui`（40 个用例默认被剔除，仅 `-m gui` 手动执行）。
3. 即便 `-m gui` 手动执行，`main_win` fixture 也隔离：DSH_HOME 指向临时假目录、拦截 `_start_monitor`
   与 `_stream_cmd`，避免触碰真实端口/SSH/进程。
4. `tests/conftest.py` 模块级 `QT_QPA_PLATFORM=offscreen` 兜底无头。
5. `.gitignore` 增补 pytest 临时产物（`.pytest-tmp/`、`pytest-cache-files-*/`、`.pytest_cache/`、`tmp/`）。

## 拒绝的替代方案

- **直接删掉 GUI 冒烟**：丧失对 MainWindow 构造/导航的回归价值；改为默认跳过 + 隔离更合适。
- **让 GUI 冒烟用假 config 完全重写主程序**：改主程序为可注入成本高、侵入大；隔离 fixture + `-m gui` 更轻。
- **跑测试时临时停止 dsh（3080）**：与使用者正在用的 GUI 冲突，不可接受。

## 影响

- 默认 pytest 与运行中的 dsh（端口 3080）完全隔离，不再互相干扰。
- 真实资源（GUI/SSH/端口/进程）测试交给人工 `-m gui` 把关执行。
- 涉及真实路由的运维类测试（部署页 SSH 快照等）仍属人工范围，代码层未替代。

## 迭代 2（2026-08-28 补充）: 纯 UI 自动测试层 + 空端口假数据

- 新增 automated 纯 UI 层 tests/test_gui_ui.py: 在离屏(offscreen)下**真实构造** MainWindow,
  自动断言"GUI 元素是否正确响应后端函数"——页面构造/导航/按钮接线/日志桥/右栏状态/对话框。
- **假 config 所有端口留空**(dash_port=0, local_ports/forward_ports/remote_tunnels 为 []),
  服务器用占位, dash_repo 为空 -> 任何离屏构造都不会以真实 3080/8090/8022/8091/3090 或真实服务器为目标。
- 新增"事实布局"断言(tests/test_gui_ui.py::TestLayoutFacts): 顶部栏按钮/左导航文案/右栏分区/隧道卡片按钮/窗口尺寸
  等真实控件存在性与层级(离屏下控件是真实构造的, 可读几何与属性)。
- **业务代码小改动**: 主程序 dsh-console-aio.py 与 dsh_data._config_path() 支持环境变量
  DSH_AIO_CONFIG(指向 config.json)优先读取, 用于测试隔离; 未设置时行为不变。
  build_win.bat 移除硬编码 Python 绝对路径(改用 PATH python + 环境变量 PYTHON_EXE 覆盖), 并补回末尾换行。
- 纯 UI 层(41 例)默认运行且已验证: 运行前后端口 3080 的 dsh PID 不变(完全隔离)。
