# 主题色换版: accent #4f6ef7 → #5686fe + 中性色相 240°→224° 对齐

- Status: implemented
- Date: 2026-08-30

## 背景

配合新品牌 logo（蓝鲸, 纯蓝色系）与"更亮更纯的蓝"的诉求, 想把 accent 从偏紫的
`#4f6ef7`（色相 ~229°）换成 `#5686fe`（色相 ~223°, 更亮更饱和）。原中性色体系
（背景/边框/面板）统一压在 240° 蓝紫相上, 与纯蓝 accent 并置会有"accent 是蓝的、
底子是紫的"的割裂感。

## 决策

两步一起做（用户在预览图三方案中选定"第一步+第二步"）：

1. accent 换 `#5686fe`, hover `#7aa3ff`; 同步派生 rgba（表格选中 `accent_soft`、
   分栏手柄 hover `accent_glow`）与 accent 染色深底 `bg_active`。
2. 结构中性色（bg/border/面板/滚动条/按钮底等大面积色）色相 240° → ~224°,
   保持原明度只转色相。
3. 顺带把 build_qss 里散落的硬编码色值全部提升为 token（btn_bg/btn_hover/
   btn_pressed/btn_disabled_bg/input_disabled_bg/inset_border/table_alt/
   tooltip_border/accent_soft/accent_glow 等), 恢复"TOKENS 是主题唯一真源"的契约;
   `build_qss` 支持部分覆盖 dict（未给 key 落回默认）。画家侧调色板 `ui/widgets.py`
   的 ACCENT 同步换版; pages_plugins 徽章底、pages_version 详情框改为读 token。
4. 文字类灰（text/text_dim/nav_text/text_disabled）**不跟转**: 低饱和灰上 240°→224°
   不可感知, 改它们要连累十余处富文本字面量, 收益为零。
5. 新增 `tools/preview_theme.py`（离屏渲染新旧方案并排对比图, 配色全 token 驱动）
   与 `python -m ui.theme`（重新生成 theme.qss 产物）; 旧配色以完整覆盖表保留在
   预览工具里供对比/回滚参照。

## 拒绝的替代方案

- **只换 accent 不动中性色**（step1 方案）: 预览可见底子仍偏紫, 与新 logo 不贴。
- **文字灰一起转 224°**: 视觉零收益, 却把散落富文本色值全部卷进改动面。
- **保留字面量只换值**: 治标不治本, 下次换色仍要人肉同步 rgba/按钮底等暗坑。

## 影响

- `ui/theme.py`（token + 模板 + `-m` 生成入口）、`ui/theme.qss`（重新生成）、
  `ui/widgets.py`（ACCENT）、`ui/pages_plugins.py`/`ui/pages_version.py`（token 化）、
  `tests/test_theme.py`（主背景断言改 token 驱动 + 部分覆盖新用例）、
  `tools/preview_theme.py`（新旧对比）。
- 343 例纯单元全过; 全页面离屏渲染冒烟（预览工具）通过。
- 打包无需变更（theme.qss 照旧 add-data）。
