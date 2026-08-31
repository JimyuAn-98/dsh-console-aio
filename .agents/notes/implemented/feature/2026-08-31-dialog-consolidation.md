# 弹窗收敛第二步：环境检查 + 安装向导 → 页面内分步（小菜②）

- Status: implemented
- Date: 2026-08-31

## 背景

ROADMAP「未做/候选」的弹窗收敛（愿景 §二.5）：向导类（配置/安装/环境）→ 页面内分步
（step in place）。第一步（设置页 ConfigDialog/MonitorSettingsDialog 退役）已在前批完成。
第二步聚焦用户确认的「先做环境检查/安装向导两块，危险确认 QMessageBox 暂不动」——
这俩是面向小白价值最高、也最重的模态弹窗。

## 决策

1. **退役 EnvDialog / InstallDialog, `ui/dialogs.py` 整体删除**: 这两个模态弹窗在 DSH
   管理页（ui/pages_dsh.py）改为「页面内分步」——开发环境检查 = 页内 QTableWidget 内联表
   （版本 + 推荐基准 + OK/缺失状态 + 更新/安装/卸载动作）；安装 dsh = 页内卡（URL + 目录
   可浏览 + 开始安装 + 进度条 + 流式日志）。`dialogs.py` 全文件在应用内已无其他 import
   （页面已只被 pages_dsh 引用; 设置页 SSH 测试已下沉 core.env），按「弹窗收敛第一步」
   退役删除先例整文件删除。业务不动, 仍在 `core/env.py`（纯 Python）。
2. **页面内分步的线程范式沿用页级安全线程**: 后台线程只调 core 纯函数, 经**类级 Signal +
   BasePage.safe_emit** 回主线程更新控件（AGENTS 约定; pages_dsh 已有 tags 拉取同范式）。
   安装事件流经 `core_env.install_dsh(events)` → events("step"/"log") → 信号转进度条/日志。
   这是文档化的「过渡态范式」, 统一收口 DshService 已列入大菜第一阶段技术债, 不在本小菜
   范围内引入新债。
3. **危险确认保留 QMessageBox.question**: 用户明确「危险确认 QMessageBox 暂不动」, 所以
   更新/安装/卸载动作与「运行更新」仍先 QMessageBox.question 说明将执行什么、点是才执行;
   空 URL 校验用 QMessageBox.critical 提示。确认条组件/按页分批替换留待后续批次。
4. **打包清理**: `build_win.bat` 与两个 spec 移除 `ui.dialogs` hidden-import（pages_dsh
   保留）。legacy/tkinter 的旧 EnvDialog/InstallDialog 为只读历史, 不动。
5. **安装成功联动保留**: 安装完成仍 `_refresh_deploy_list()`（新仓库可被部署联动）, 与旧
   InstallDialog 回调一致。

## 拒绝的替代方案

- **保留 dialogs.py 仅删两对话框类**: 应用内无其他 import, 留着是死代码; 按先例整文件退役
  更干净（`_DialogBase`/`_load_config` 仅被旧测试引用, 随文件删除）。
- **环境/安装做成独立新弹窗页或向导 overlay**: 与「页面内分步 step in place」目标相悖;
  直接内联进 DSH 管理页最贴愿景（配置/安装/环境都用页面承载），且复用页级 safe_emit 范式。
- **把环境版本探测/安装迁进 service 再收口**: 属大菜第一阶段「各页裸线程统一收口到
  DshService」的技术债范围; 本小菜只做「弹窗→页面」形态迁移, 保住 HTTP 语义单一职责,
  不混入技术债清理（避免一次改两层）。

## 影响

- `ui/pages_dsh.py`（重写: 页面内环境检查表 + 安装分步卡 + 旧入口逻辑; 整页包进 QScrollArea）、
  `ui/dialogs.py`（删除）、`build_win.bat` + 两 spec（隐式引入移除）、`core/env.py`（仅顶部
  注释更新）、`tests/test_dialogs.py`（移除旧对话框测试, 新增 TestDshManagePage 构造冒烟 +
  空 URL 安装校验）。
- 渲染验证: 离屏 17 页导航冒烟通过（DSH 页 = DshManagePage, 4 环境行 + 安装卡 + 空 URL
  拦截不挂起, 无真安装/真网络）; 新测试 12 例过。
- 已知边界: 环境/安装仍走 page 自有线程（未收口 service, 属大菜技术债）; tags 拉取需网络;
  沙箱内 tmp 写测试（test_read_tail/log_entries）为环境限制非回归。
