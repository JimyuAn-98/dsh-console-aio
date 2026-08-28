# UI 前后端分层重构：设计蓝图与迁移计划

> 2026-08-28 加入。目标: 把当前"UI 层揉业务"的 PySide6 桌面应用, 重构为经典 Qt 分层:
> 纯 Python 业务层(core) + Qt 信号桥接口层(services) + 只做展示/订阅的 UI 层。
> 关键约定: 后端与 UI 之间**一律通过 Qt 信号-槽**通讯, 禁止危险的跨线程/跨进程直接调用。

## 0. 为什么要重构(当前耦合现状, 已静态审计)

- 业务/数据根(core/data.py, core/tunnel_mgr.py)已较干净: **不 import PySide**, 纯 Python。
- 但大量业务逻辑仍**散在 UI 类里**:
  - dsh-console-aio.py 主窗口/页面里内联了 dsh 启停(_run_dsh/_dsh_start/_dsh_stop)、
    更新(_run_update)、隧道常驻重连(_start_persist)、监控探测(_probe/_ssh_proc_count/
    _probe_remote_tunnels)、命令流(_stream_cmd) —— 全是纯 Python 业务, 却绑在 Qt 类里。
  - ui/pages_*.py 里直接 import subprocess/shutil/zipfile 干业务(keys/version/ops 等)。
  - UI 到处 import core.data, 没有统一业务接口层 / 状态订阅机制。
- 结果: 业务不可独立测试、与 UI 强耦合、UI 与后端混在一起难维护。

## 1. 目标分层

```
┌─ 后端层 core/  (纯 Python, 严禁 import PySide) ──────────────┐
│  dshctl.py    dsh 启停/更新/监控探测(由主程序抽出)                │
│  tunnels.py   隧道启停/常驻重连(由 core.tunnel_mgr + 主程序抽出)        │
│  (后续: config.py / ssh.py / data.py / stats.py 从 core.data 归并) │
└───────────────────────────────────────────────────────────────┘
┌─ 接口层 app/services.py  (可 import PySide) ────────────────────┐
│  DshService(QObject): 持有 Signal, 起后台线程跑 core, emit 回 UI │
└───────────────────────────────────────────────────────────────┘
┌─ UI 层  ui/ + 主窗口  (只展示 + 订阅信号 + 调 service) ───────┐
└───────────────────────────────────────────────────────────────┘
```

## 2. 信号-槽通讯契约(硬约束, 全员遵守)

- 业务层(core) **不 import PySide**; 它只向调用方抛"纯数据事件"或回调接口参数。
- services.py 是唯一起后端线程并转结果的地方: 定义 `QObject` 子类 + Signal:
  ```
  class DshService(QObject):
      status   = Signal(str)                  # 一条状态文案
      log      = Signal(str, str)             # (text, tag)
      card     = Signal(str, bool)            # (隧道key, 是否在线)
      monitor  = Signal(object)               # (local, ssh_count, remote) 探测结果;
                                              # None 哨兵 = 本轮探测线程异常(UI 只解除 busy)
      finished = Signal(str, bool)            # (操作key, ok)
  ```
- 后端线程**只 emit 这些信号**(Qt 自动排队到接收者线程), **绝不**直接调 UI 方法、
  **绝不**共享可变 list/dict 无锁跨线程写。这是唯一通讯通道。
- UI 层只 `connect` 信号 + 调 service 的触发方法(触发方法内部起线程, 不阻塞 UI)。
- **connect 层级约定**: 生命周期长的接收者(MainWindow 的 loge/set_status)只在 MainWindow
  构造时 connect 一次 —— 页面随导航反复销毁重建, 若在页面里 connect 到 app 的槽会叠加连接
  重复输出; 接收者是页面自身槽的(card -> 页面 _apply_card)在页面里 connect, 页面销毁时 Qt 自动断开。

## 3. 迁移计划(分阶段, 每个页面独立验收, 可单独回退)

- 阶段0: 搭 core/ + app/services.py 骨架, 抽 dshctl(启停/探测) + tunnels(隧道) 最小闭环。
        跑通 "UI -> service(Signal) -> core(后台线程) -> emit 回 UI"。人工在 GUI 验证。
        **[已完成 2026-08-28]**: 骨架 + 隧道页/主窗口监控接线(dsh 分支/隧道分支走 service,
        右栏探测走 service.monitor_once); 内联实现全部删除; config.derived 增加
        allow_empty_ports 隔离分支(默认 False 与主程序行为一致, 测试用 True 与真实端口隔离);
        tests/test_core.py 纯单元覆盖。待用户 GUI 人工验证(隧道启停/监控/3080 无恙)。
- 阶段1: 把主窗口/隧道页从"内联业务"改为走 service; 原 _run_dsh/_dsh_stop/隧道逻辑删除。
        **[更新流已提前完成 2026-08-28]**: 隧道页"运行更新"按钮从 tkinter 旧主程序恢复
        (dshctl.update_dsh: 停 web -> git 拉取 -> pnpm run clean 清理旧构建 -> pnpm
        install/build -> 重启), 经 service.update_dsh 后台执行, 点击先 QMessageBox 确认;
        注意它更新的是 dsh 本体, 与「关于与更新」页的控制台自更新是两回事。
        clean 步骤不可省: dsh 的 lib/ 构建产物被 gitignore, git pull 不清, 上游改导出后
        过期产物会让 build 报 MISSING_EXPORT(2026-08-28 实测)。余下: _stream_cmd 收敛。
- 阶段2: pages_* 逐个改走 service: version/keys/ops(直接 subprocess 的页面优先)。
        **[波0+波1 已完成 2026-08-28]**: 波0 前置 —— DshService 增第六信号
        result = Signal(str, object) + _run_result_op 通用模板(core 函数契约:
        func(events=None,...) -> dict payload, payload 至少含 "err"); 波1 ——
        version 页(core/version.py, 顺带修复源码模式更新后不重启的存量 bug)与
        keys 页(core/keys.py, 私钥安全红线成文)迁移完成, 页面零
        subprocess/urllib/zipfile/shutil/threading。GUI 人工验收待用户执行。
        余下波次: **[波2 已完成 2026-08-29]**: ops(profiles 备份页)/profiles/sessions
        三页写盘类迁移完成, service 触发方法 backup_dsh_home/copy_profile/delete_profile/
        set_sessions_archived/delete_session_group; 统一"远程只读红线"(远程部署下写操作
        拒绝并中文提示); 修复两个存量 bug: sessions 归档调用不存在的 core.data.write_workspace
        (归档/恢复自迁移起失效, core 信封直写修复)、profiles 线程未用 safe_emit。
        纯读仍留页面直连(线程+safe_emit), 阶段4 收敛。
        **[波3 已完成 2026-08-29]**: plugins(core/plugins.py: 列表汇总/宿主防线/patch 写;
        service.load_plugins/toggle_plugin + 通用 run_cmd)与 deployments(core/
        deployments.py: N 线程编排收进单线程串行快照, result("deploy-snap") 逐行回包)。
        页面全面解除对 app._stream_cmd / app.DASH_REPO 的依赖(service.run_cmd/ctl.d)。
        **[阶段3/波4 已完成 2026-08-29]**: dialogs 子进程业务下沉 core/env.py
        (SSH 测试/版本探测/安装流/工具命令)与 core/config.save_config; 三份
        _stream_cmd 归一为 dshctl.stream_cmd; InstallDialog 线程只转 events->信号,
        EnvDialog 有主窗口走 service.run_cmd, 无主窗口保留 run_capture 兜底。
        ui/ 页面与对话框层已无任何 subprocess/urllib/zipfile/shutil/threading 直接
        子进程业务(纯读线程与对话框 events 转发线程除外, 阶段4 收敛)。
        **[剩余 = 阶段4]**: core/data.py 归并进 core(config/ssh/data/stats),
        页面纯读统一经 service; 波5 纯读页(agents/taskboard/usage/llm)随阶段4。
        **[阶段4 已完成 2026-08-29 — 分层重构全部完成]**:
        - 原根级 dsh_data.py 整体归并 core/data.py(git mv 保历史); 2026-08-29 目录整理时
          兼容 shim 已删除, 所有引用统一为 `from core import data`。
        - services 新增 _run_core_op(纯数据函数包装 {"data","err"}; 与 _run_result_op 的
          events 域函数约定不同, 曾因此产生 TypeError 被纯单测拦截) + 五个纯读/轻写方法
          (list_agent_presets/read_taskboard/read_usage_stats/read_settings/write_settings)。
        - agents/taskboard/usage/llm 四页读取与 llm 保存全部走 service; 页面零自起线程、
          零 core.data 引用(agents 详情为本机小文件同步直读)。
        最终形态: core 12 个模块(含 data/tunnel_mgr)纯 Python 零 Qt; ui/ UI 层零子进程业务;
        后端->UI 全部 Qt 信号-槽; 纯单元 299 例(2026-08-29)。
- 阶段3: dialogs.py 评估是否抽业务(动态表单类可能保留一部分)
- 阶段4(已完成): dsh_data.py 归并进 core/data.py(config/ssh/data/stats), 页面统一经 service 访问。
- 每阶段: 业务层可加纯单元测试(不构造 MainWindow, 安全); GUI 交互验证由人工执行。

## 4. 验收清单(每阶段)

- [ ] 业务层(core) 不 import PySide, 可独立 python -c 调用/单测。
- [ ] UI 不直接 import subprocess/socket(zipfile 等业务应移走)。
- [ ] 后端 -> UI 全部经 Signal emit, 无跨线程直接改 UI。
- [ ] 各页面在任意窗口尺寸下功能与布局行为与重构前一致。
