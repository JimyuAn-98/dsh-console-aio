# 浅色主题 + 明/暗变体（主题页一键切换, config["theme_variant"], 深色默认）

- Status: implemented
- Date: 2026-08-31

## 背景

用户确认战略: P4 远程部署延后/独立(WSL 试验), 当前主线 = 小菜(浅色主题→弹窗收敛→技术债)
+ 大菜技术债清理。浅色主题是本批小菜第一件。此前主题引擎只有一套深色 DEFAULT_TOKENS,
ROADMAP 候选"浅色主题"。

## 决策

1. **明/暗入口选「主题页加切换」而非跟随系统/独立预设**: 不自动跟随 Windows 深浅色
   (用户未选), 不做独立预设文件(与现有具名主题文件机制叠加语义混乱)。主题页新增
   「明/暗变体」卡(深色/浅色两个按钮), 持久化 `config.json["theme_variant"]`(deep 仍为
   启动默认)。三者已确认: 入口=主题页切换, 默认=深色, 范围=先做这个不扩深。
2. **变体模型**: `VARIANTS = {"dark": DEFAULT_TOKENS, "light": LIGHT_TOKENS}`,
   `ACTIVE_VARIANT` 模块级(默认 dark)。`set_variant` 把 TOKENS 重置为该变体 base 并重算
   派生; `reset_default` 恢复当前变体的出厂; `current_overrides` 对当前变体 base 求差。
   **切变体=丢弃旧变体上的覆盖**(把另一套配色的覆盖叠到新底上会错乱), 不保留。
3. **新增 token `on_accent` / `on_selection`**: QSS 与画家层散落的选中/主按钮/导航 hover/
   spinner 硬编码 `#fff` 收编为这两个文字色 token(深=白、浅=深), 否则浅色下白字不可见。
   不入可编辑白名单(与 accent 同源配色, 不单独调)。
4. **画家层跟随**: ModernList hover 由 `_tint("#ffffff",12)` 改为读 `bg_hover` 固态色,
   spinner `_tint("#ffffff",200)` 改读 `text` token, 选中文字改读 `on_selection`。
5. **原生标题栏跟随变体**: `set_immersive_dark(hwnd, dark=(variant!="light"))`,
   浅色=亮标题栏(生产路径是保留原生标题栏的 set_accent_blur 亚克力, 致敬 VISION 定稿)。
6. **非 Mica 路径**: `_load_theme` 在浅色变体或自定义主题时走实时生成 QSS
   (外部 theme.qss 是深色出厂产物)。启动时先 `set_variant(config["theme_variant"])`
   再 `set_active(config["theme"])`。
7. **持久化合并**: `set_theme_variant` 写 config["theme_variant"], 同时清/设 config["theme"]
   覆盖(已回变体出厂则清), 经 core.save_config 自动 .bak。

## 拒绝的替代方案

- **跟随 Windows 系统深浅色**: 未选; 控制台是独立外观, 且切换窗口材质/标题栏有状态迁移
  成本, 先做手动切换。
- **独立"浅色预设"文件**: 与 themes/*.json 具名主题叠加语义混乱(浅色预设又是一个覆盖集,
  锚点不清); 直接做 base 变体更干净。
- **同一 TOKENS 原位覆盖成浅色**: 无法表达"两个出厂", 恢复默认/求覆盖集都会错。
- **切变体保留覆盖**: 把深色上的定制叠到浅色底上会错乱, 丢弃更符合直觉且实现最简。

## 影响

- `ui/theme.py`(LIGHT_TOKENS + VARIANTS/ACTIVE_VARIANT/set_variant/get_variant +
  reset_default/current_overrides 变体感知 + on_accent/on_selection + QSS 硬编码白 token 化)、
  `ui/widgets.py`(hover/spinner/选中文字读 token)、`ui/pages_theme.py`(明/暗变体卡 +
  _on_toggle_variant/_sync_variant_btns)、`dsh-console-aio.py`(启动切变体 + _load_theme
  分支 + set_theme_variant + 标题栏跟随)、`tests/test_theme.py`(+6 组变体用例)。
- 17 页构造冒烟 + 离屏切变体验证通过; theme 17 例全过(沙箱内 tmp 写测试例外为环境限制)。
- 打包需注意: 无新模块/add-data(浅色走实时生成), 现有 hidden-import 不受影响。
- 已知边界: 浅色下部分硬编码品牌红(winBtnClose #e81123)与新 accent 派生对比仍在可接受
  范围; 透明度滑杆"仅亚克力可见"提示在浅色下依旧。
