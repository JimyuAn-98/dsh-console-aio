# DSH 管理页(dsh 域操作集中: 操控/更新/环境/安装/版本信息)

- Status: implemented
- Date: 2026-08-30

## 背景

用户要求: 在总览与隧道之间新建独立「DSH 管理」页, 收拢 隧道页的"本机 dsh 操控/运行
更新"两卡与顶栏"环境/安装"入口, 并展示 dsh 本体的版本信息(取自 GitHub
deepseek-ai/deepseek-harness 的 tags)。

## 决策

1. **页面化收敛**: dsh 域(安装/更新/操控/环境)从隧道页与顶栏分散入口集中为一页;
   隧道页回归纯隧道(只剩 3 张隧道卡 + 方案卡), 顶栏只剩 搜索/立即刷新。
2. **ITEMS 保持不动**: dsh-web/update-dsh 两项仍留在 ITEMS——它们是探测与卡片状态
   的单一来源(概览页"本机 dsh"卡与监控依赖); 隧道页构建时按 type/key 过滤不渲染,
   新页面自建卡片并直连 service.card 信号。删 ITEMS 会连坐监控与概览, 过滤是零伤
   举动。
3. **版本信息走 GitHub API**: `api.github.com/repos/deepseek-ai/deepseek-harness/tags`
   (官方 JSON 接口), 不爬 tags HTML 页(脆弱); `core/dshctl.fetch_dsh_tags` 纯函数,
   UI 后台线程 + safe_emit(BUG-008 范式)。本机版本读 dash_repo/package.json(与概览
   页同源), 与最新 tag 做展示级比对(一致/可能落后), 不做版本号解析排序。
4. **环境/安装沿用现有对话框**: EnvDialog/InstallDialog 功能完整, v1 只迁入口不改
   造(安装完成回调 _refresh_deploy_list 保留); 页面内分步改造留给未来弹窗收敛批次。

## 拒绝的替代方案

- **从 ITEMS 删除 dsh 两卡**: 连坐监控探测与概览页状态, 为页面归属破坏单一来源。
- **爬 tags HTML**: GitHub 页面结构变化即碎; API 稳定且返回即数据。
- **版本号语义化比较(解析 alpha/rc)**: 展示级子串比对已够; dsh 的 tag 命名(dsh-v
  前缀)与 package.json version 弱相关, 解析规则易碎。
- **安装/环境改造为页面内分步**: 大工程, 与本需求(入口收敛)解耦。

## 影响

- ui/pages_dsh.py(新) + core/dshctl.py(fetch_dsh_tags) + dsh-console-aio.py
  (NAV 17 页/_show_page/隧道页过滤/顶栏精简) + 打包 hidden-import 四处
  (bat/两 spec/release.yml; 本地 bat 顺带补上一直缺失的 pages_logs/pages_settings)。
- 362 例纯单元全过; 离屏端到端验证(17 项导航/新页渲染/GitHub tags 真实拉取成功/
  隧道页仅剩 3 隧道卡)。
- 已知边界: tags 拉取需网络(失败显示重试提示); 版本比对为展示级。
