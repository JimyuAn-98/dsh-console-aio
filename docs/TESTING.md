# 自动化测试（pytest）说明

本仓库用 pytest 做自动化测试, 分两个边界清晰的层次。**默认只跑「纯单元 / 纯 UI」层, 绝不触碰正在运行的 dsh(端口 3080)。**

## 一、两层测试

| 层次 | 文件 | 测什么 | 默认是否运行 | 触碰真实资源? |
|------|------|--------|------------|--------------|
| 纯单元 | tests/test_dsh_data.py | 数据层纯函数(YAML/路径/备份/会话/Profile/用量/部署/SSH命令等) | 是 | 否(用临时 tmp 数据) |
| 纯单元 | tests/test_tunnel_mgr.py | 隧道管理器纯逻辑(tcp_ok/PID文件/Tunnel命令组装) | 是 | 否(临时目录) |
| 纯单元 | tests/test_version_page.py | 版本号比较 / 路径定位 | 是 | 否 |
| 纯单元 | tests/test_dialogs.py | 对话框构造 + 字段/保存逻辑 | 是 | 否(不写真实 config) |
| 纯单元 | tests/test_dsh_core.py | 业务层: config 派生兜底规则(默认/allow_empty_ports)/TunnelManager 组装/DshService 信号桥契约 | 是 | 否(端口全 0/空, 不起线程) |
| 纯 UI  | tests/test_gui_ui.py | 离屏构造真实 MainWindow, 测页面/导航/按钮接线/日志桥/右栏状态 | 是 | 否(假 config+假 DSH_HOME+拦截线程) |
| 真实资源(人工) | tests/test_gui_smoke.py | 真实 MainWindow 监控/SSH/端口/启停 dsh 的冒烟 | 否, 需 -m gui | **是, 必须人工执行** |

## 二、怎么运行

```bash
# 1) 只跑安全的纯单元 + 纯 UI 测试(推荐, 默认)
python -m pytest tests/

# 2) 只看收集到的用例数(不执行, 不碰真实资源)
python -m pytest tests/ --collect-only -q

# 3) 手动执行真实资源 GUI 冒烟(人工把关, 见下)
python -m pytest tests/test_gui_smoke.py -m gui
```

> 关键: 默认 -m "not gui"(见 pytest.ini), 所以 test_gui_smoke.py 的 40 个用例默认被跳过,
> 只有显式 -m gui 才执行。**切勿在 dsh(端口 3080)正在运行时自动跑真实资源测试。**

## 三、不打开真实 GUI 也能测 GUI 元素——原理(纯 UI 层)

PySide6 支持离屏(offscreen)运行: 不弹真实窗口, 也能在内存里实例化真实的 MainWindow 和页面控件。
test_gui_ui.py 就这么做, 并通过 5 道隔离保证不碰真实资源:

1. 假 config: 设 DSH_AIO_CONFIG 指向一个假 config.json(占位符 YOUR_*, 无真实服务器/IP),
   于是主程序 CONFIG 与 dsh_data.load_deployments() 全读假配置。
2. 假 DSH_HOME: 设 DSH_HOME 指向临时假目录, 数据页(session/profile/用量等)读假数据。
3. 拦截真实副作用: 把 MainWindow._start_monitor(真实健康监控线程)与 _stream_cmd(真实子进程)
   替换为空实现, 避免探测端口 / 跑真实命令。
4. --smoke 模式: OverviewPage 等在 smoke 下不做真联网/真操作。
5. 线程硬拦截: 构造 MainWindow 前把 threading.Thread.start 替换为空实现(只登记线程对象
   到 _BLOCKED_THREADS), main_win 存续期间任何后台线程都不真正运行 —— 即使第 3 道拦截
   有遗漏, 页面构造器起的 daemon 线程也探测不到真实端口(如 3080);
   TestThreadInterception 用哨兵线程断言该拦截生效。

这样能自动断言并验证的「功能是否生效」:
- 窗口能否构造、导航项数量、部署下拉默认「本机」。
- 每个导航 key 都能 _show_page 出页面且类型正确。
- 日志桥 bridge.emit 是否真的出现在日志区(线程安全回主线程)。
- 右栏 set_state 是否更新单元格、对不存在 key 是否安全。
- 隧道页是否按 ITEMS 生成全部卡片、动作按钮接线到 _on_action 并经 main_win.service 信号桥分派
  (分层后内联 _run_python_tunnel/_stop_py_tunnel 已删除, 断言其不存在)。
- 总览页在 smoke 下是否显示演示/未配置文案、refresh 是否不崩溃。
- **事实布局**(TestLayoutFacts): 顶部栏 配置/环境/安装/立即刷新 按钮存在; 左导航文案与 NAV_ITEMS 一致;
  右栏分区标题存在(端口空=>无单元格); 每张隧道卡片含 ITEMS 声明的动作按钮; 窗口 resize 后几何反映尺寸。
- 部署切换是否重建页面、窗口最小尺寸约束。

## 四、假数据(fake_env.py)

tests/fake_env.py 提供假环境构造器, 供纯 UI 测试与 -m gui 人工测试使用:

- make_fake_config_dict(): 假配置字典(占位符, 无真实信息), 字段与真实 config 一致。
- make_fake_config_file(tmp): 把假 config.json 写到临时目录, 返回路径。
- make_fake_home(tmp): 构造模拟 ~/.dsh 目录(profiles/sessions/storages/task-board/.agent-presets/settings.yaml)。
- default_env(tmp): 一键完成「假 config + 假 DSH_HOME + 设好 DSH_AIO_CONFIG/DSH_HOME」, 返回 (cfg, home, restore)。

> DSH_AIO_CONFIG 是新增的环境变量开关: 主程序 dsh-console-aio.py 与 dsh_data._config_path() 在设置时
> 优先读它指向的 config.json(测试隔离用), 未设置时不改变原行为(仍读 exe/源码目录下的 config.json)。
> 这属于**业务代码的小改动**, 需随本次收尾一并 review/提交。

## 五、安全边界与约定(务必遵守)

1. 默认 pytest 绝不碰真实资源: 纯单元/纯 UI 用假数据 + 拦截, 与 3080 的 dsh 完全隔离(已验证)。
2. 涉及真实资源的测试交人工: 真实 dsh 启停、SSH 到真实服务器、端口连通、隧道建立/断开——
   这些必须由人工在可控环境 -m gui 执行并观察, 自动化不代跑。
3. 新增测试: 若你写会触碰真实资源(网络/进程/端口/真实 config)的用例, 务必加 @pytest.mark.gui,
   并写到 test_gui_smoke.py(或单独 -m gui 文件), 不要混进默认运行的纯测试。
4. 改动后必做: python -m py_compile dsh_data.py tunnel_mgr.py dsh-console-aio.py + 一次 pytest tests/(安全层)
   + --collect-only 确认方向, AGENTS.md 的冒烟约定不变。
