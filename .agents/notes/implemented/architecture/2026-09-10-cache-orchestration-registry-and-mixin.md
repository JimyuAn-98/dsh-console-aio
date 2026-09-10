# 缓存编排收口：种类注册表 + CacheableMixin

- Status: implemented
- Date: 2026-09-10
- Related: `core/cache.py`, `ui/cacheable.py`, `ui/pages_overview.py`/`pages_agents`/`pages_profiles`/`pages_taskboard`/`pages_usage`/`pages_sessions`, `tests/test_cacheable.py`

## 背景

缓存**存储层**早已集中（`core/cache.py` → 单个 `dsh_aio_cache.json`，4 个 API）；但**编排层**在每个数据页各复制了同一段约 20 行的样板（读缓存 → 比源 mtime → 后台拉取 → `data_changed/write_cache` → `RefreshIndicator` 指示灯 → busy 防重入），且 `kind` 字符串散落各页，没有一处能总览"有哪些缓存"。

## 决策

- **不做"全局变量存数据"**：存储已在磁盘、跨页面/进程复用；再放一份内存全局 dict 会带来内存占用、与磁盘不同步、以及与控件耦合的问题。
- **加注册表（元数据）**：`core/cache.py` 新增 `KINDS`/`PREFIX_KINDS` 与 `describe_kind`，以及管理 API `list_cached()`（每类大小/抓取时间）、`clear_cache(kind)`、`clear_all_cache()`；便于做缓存管理/诊断入口与统一失效，并杜绝 kind 拼写错误。
- **抽编排 mixin**：`ui/cacheable.py::CacheableMixin` 收口编排，页面只声明 4 个必需钩子（`_cache_kind/_cache_src_mtime/_cache_fetch/_cache_apply`）与若干可选钩子；mixin 不 import Qt，可用假页面做纯单测。
- **迁移范围**：总览/Agent/Profile/任务看板/用量/会话 6 页；插件页因"Profile 列表 + 插件列表"双 op 与动态 kind（`plugins_<profile>`）暂不迁移，保留现状。

## 拒绝的替代方案

- **内存全局缓存表**：重复存储、易 stale、与控件耦合，收益低。
- **一次性迁移全部 7 页（含插件页）**：插件页流程特殊，单独处理风险更可控；本次先收口 6 页。
- **只抽 helper 函数不改页面结构**：减重有限（每页仍需自己拼流程），mixin 才能真正把 busy/force/指示灯语义收成一处。

## 影响

- 6 个数据页各删去重复的缓存样板；"命中绿/变化黄/错误红"、`force` 语义、防重入只有一处实现。
- 新增 `tests/test_cacheable.py`（假页面纯单测）与注册表/管理 API 单测。
- 后续可基于注册表在「设置页 · 诊断」加"缓存管理"入口（列出种类/大小/时间，清空单类或全部）——本次仅备好 API。
