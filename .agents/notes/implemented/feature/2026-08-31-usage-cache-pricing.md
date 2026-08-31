# 用量页数据缓存 + 进页按需刷新 + 模型价格持久化

- Status: implemented
- Date: 2026-08-31
- Class: feature

## 背景

两个相连的后端/数据层痛点：
1. **所有 dsh 数据页"点击才看到 + 有时很慢"**：以用量页最典型——`usage_stats()`
   是同步解压扫描全部 `session.jsonl.zstd` 的阻塞函数，每次进页都全量重扫、长时间加载。
2. **模型价格每次都要用户改**：价格只存内存 `core.data.DEFAULT_PRICES`，注释明说
   "价格修改仅本次运行生效，不写入文件"。

## 决策

### A. 通用数据缓存/刷新框架（本期接入用量页验证）

- 新增 `core/cache.py`（零 Qt、纯 stdlib），数据持久化到软件路径 `dsh_aio_cache.json`
  （与 `config.json`/`model_prices.json` 同目录），结构 `{kind: {fetched_at, data}}`。
  API：`read_cache` / `write_cache` / `needs_refresh(kind, src_mtime)` /
  `data_changed(kind, new_data)` / `json_sig`。
- **进页流程**（用量页实现）：实测源时间戳 → 有缓存且源未变 → 直接用缓存呈现（绿，
  不转圈）；源变了或无缓存（或手动「刷新」强制）→ 后台重扫（标题右侧转圈），结束后
  用 `data_changed`（JSON 签名）对比：有变化写缓存 + 刷新界面 + 黄点；无变化写缓存
  + 绿点；错误红点。
- 新控件 `ui/widgets.py::RefreshIndicator`：loading 画旋转弧，结束显示状态点
  （绿=无变化 / 黄=有变化 / 红=错误，色值与主日志区语义色同源）。
- **范围**：本期只把通用层 + 用量页接通（验证机制）；会话/插件/任务板等其他数据页
  后续按同一机制迭代接入，不在本次铺开。

### B. 模型价格持久化 + 计费模式 + 弹窗重做

- 价格持久化到软件路径 `model_prices.json`，`core.data` 提供
  `load_prices` / `save_prices` / `effective_prices`（内置 `DEFAULT_PRICES` 被持久化
  覆盖合并，带模块级缓存，`save_prices` 后失效）。
- 每模型新增 **计费模式** `billing`：`token`（按量）/ `token-plan`（按月订阅）。
  `estimate_cost` 对 `token-plan` 直接返回 `None`（不走按量估算）。改动对既有调用
  无破坏：`estimate_cost` 不传 `prices` 时默认走 `effective_prices()`（含持久化覆盖），
  测试环境无价格文件时退化为内置默认。
- **价格弹窗重做**（`UsagePriceDialog`）：`QGridLayout` → `QTableWidget`，模型列
  `Stretch` 拉满不再压缩名字；新增「计费模式」下拉；保存走 `save_prices` 写持久化，
  并提示"下次启动自动带入"。
- **订阅（token-plan）模型存月/年费，不再填 token 单价**：按量模型存
  `{in_cached, in_miss, out, billing}`；订阅模型存 `{monthly, yearly, billing}`。
  `load_prices/save_prices` 按 `billing` 分支校验/写入。弹窗里选「订阅 token-plan」
  后该行动态切换成「月费/年费」两个输入框（隐藏三组 token 单价），切回按量即还原。
- **订阅费合计展示**：新增 `core.data.subscription_cost()` 汇总所有订阅模型的
  月/年费；用量页信息条加「订阅费: 月 ¥x · 年 ¥y」，进页/保存后刷新。

## 拒绝的替代方案

- **价格存进 `config.json` 主结构**：拒绝。避免污染部署清单主文件，独立
  `model_prices.json` 语义清晰、可单独备份/恢复。
- **每次估算都实时读文件合并价格**：拒绝。用量页每行 `estimate_cost` 高频调用，
  用模块级缓存（读一次 / save 后失效）避免每行一次磁盘 IO。
- **纯按数据源时间戳决定"是否变化"**：拒绝。mtime 变化不代表聚合内容变化
  （touch/无关写入），用 `data_changed` 对拉取结果做真实 diff，才决定绿/黄。
- **本次就铺开所有数据页**：拒绝。各页 schema/时间戳来源差异大，为控制范围与风险，
  本期只做通用层 + 用量页验证，其他页后续迭代。

## 影响

- `core/cache.py`（新）、`core/data.py`（价格层）、`ui/widgets.py`（RefreshIndicator）、
  `ui/pages_usage.py`（缓存接入 + 弹窗重做）改动；`dsh-console-aio.py` 概览页
  `estimate_cost` 无参调用自动吃到持久化价格。
- 新增测试：`tests/test_core_cache.py`（新）+ `tests/test_core_data.py::TestPricePersistence`。
- 遗留：`.pytest-tmp` 写入在 pwsh 沙盒下动态子目录可能被拒（环境限制，非代码问题）；
  GUI `test_gui_smoke.py` 存在既有的 fixture `ScopeMismatch`（module-scoped `main_win`
  请求 function-scoped `tmp_path`），与本改动无关。
