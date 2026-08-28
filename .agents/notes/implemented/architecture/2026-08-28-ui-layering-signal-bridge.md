# UI 分层重构: 业务层 dsh_core + DshService 信号桥(阶段0)

Status: implemented
Date: 2026-08-28

## 背景

PySide6 迁移完成后, 业务逻辑散在 UI 类里(主程序内联 dsh 启停/隧道启停/常驻重连/监控探测,
pages_* 直接 import subprocess 干业务), 业务不可独立测试、与 UI 强耦合。历史上纯 UI 测试
曾两次因"假配置端口被 or 兜底回真实端口 + 页面后台线程未拦截"干掉运行中的 dsh(端口 3080)。
用户拍板: 前后端分离 = 逻辑分层解耦(不要 C/S 网络服务化, 不要 web 前端套壳),
后端 <-> UI 一律 Qt 信号-槽(硬约束)。设计见 docs/UI_LAYERING.md, 操作交接见 HANDOFF.md。

## 决策

1. **三层结构**: dsh_core/(纯 Python, 严禁 import PySide) + app/services.DshService(QObject
   信号桥, 唯一起后端线程并转结果的地方) + UI 层(只展示/订阅/调触发方法)。
   业务函数用 events(kind, payload) 纯数据回调向外报告, service 转发到 Signal.emit,
   Qt 排队回接收者线程 —— 后端线程绝不直接碰 UI。
2. **connect 层级**: log/status -> MainWindow 的槽只在窗口构造时接一次; card -> 页面槽在
   页面里接(接收者销毁 Qt 自动断开)。拒绝在页面里 connect 到 app 的槽: 页面随导航反复
   销毁重建而接收者(MainWindow)长命, 连接会叠加导致日志重复。
3. **config.derived(cfg, allow_empty_ports=False)**: 默认 False 与主程序 or 兜底行为完全
   一致; True 时端口空/0 原样保留, 供测试假配置与真实端口(3080 等)隔离。
   拒绝直接改默认行为: 真实 GUI 主链路行为不能变。
4. **monitor 信号 None 哨兵**: service.monitor_once 的探测线程任何异常都以恰好一次信号
   收场(正常结果或 None), 否则 UI 的 busy 标志永真、监控永久停摆。
5. **隧道 persist 停止标志归 service 持有**(TunnelManager 随窗口生命周期): 原实现在页面
   实例上, 页面切换重建后旧重连循环失控, "停止"无法取消常驻 -> 会再次拉起隧道。
6. **隧道页"运行更新"恢复(2026-08-28 用户反馈修正)**: 该卡片引用的 _run_update 自 PySide6
   迁移起就未定义(点击抛 AttributeError)。最初误将提示指向「关于与更新」页 —— 但该页更新
   的是**控制台自身**, 与卡片承诺的**更新 dsh 本体**(git 拉取->依赖->构建->重启)是两回事,
   用户指出后改为从 tkinter 旧主程序恢复完整流程: dshctl.update_dsh(停 web -> git fetch/pull
   -> pnpm install/build -> 重启), 经 service.update_dsh 后台执行, 点击先 QMessageBox 确认
   (危险操作约定)。顺带修正旧版 git fetch cwd 缺失(原会在控制台目录执行 git)。
   **追加(同日实测事故)**: 用户首跑更新, build 报 7 个 MISSING_EXPORT —— 根因是 dsh 仓库
   的 lib/ 构建产物被 gitignore, git pull 不清; 上游 0.1.2-alpha.1 大改名删掉
   resolveSessionPreset 等导出, 过期生成物(packages/host/apiproxy/lib)毒化增量构建
   (上游 CI 干净 checkout 不受影响)。修复: 更新流程固定加入 `pnpm run clean`(dsh 仓库
   自带 scripts/clean.ts, 只删 tsconfig 项目图声明的构建产物, 保留 node_modules,
   遇未知文件拒绝删除, 已审读确认安全), 位于 git pull 之后 install 之前。
7. **验证边界**: dsh_core 纯单元测试(tests/test_dsh_core.py, 端口全 0/空)可自动跑;
   构造 MainWindow 的交互验证一律用户人工在 GUI 做, 绝不自动跑(HANDOFF 铁律)。

## 拒绝的替代方案

- **页面级 connect service.log/status**: 见决策 2, 连接叠加 bug。
- **主窗口监控保留独立 _probe/_ssh_proc_count/_probe_remote_tunnels 副本**: 与 dshctl 重复,
  两处漂移; 已删并统一走 service.monitor_once。
- ~~**把 update-dsh 流程补进 dshctl**: 超出阶段0 最小闭环~~(2026-08-28 推翻: 用户指出
  更新指向错误后, 已按 tkinter 历史实现恢复进 dshctl.update_dsh, 见决策 6)。
- **自动跑 test_gui_ui 回归**: 它构造 MainWindow, 违反铁律; 只跑纯单元层
  (159 例通过) + py_compile + 模块级 import 符号残留检查。

## 影响

- 主程序 dsh-console-aio.py 不再含隧道/监控/启停业务, 体积下降 ~200 行; 页面动作只分派。
- dsh_core 可被单测/CLI 复用; 后续阶段2(pages_*)、阶段4(dsh_data 归并)沿用同一信号桥模式。
- spec hiddenimports 补 app.services/dsh_core.*; 打包前需真机验证 exe(未自动跑 build)。
- 未决: 阶段0 改动未经用户 GUI 人工验证前不提交(交接文档要求先提交骨架, 一并待验)。
