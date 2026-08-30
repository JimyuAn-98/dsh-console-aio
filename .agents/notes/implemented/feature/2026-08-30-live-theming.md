# 实时主题定制: TOKENS 活色板 + 主题页（颜色/透明度实时生效, 主题存载）

- Status: implemented
- Date: 2026-08-30

## 背景

主题色换版落地后用户提出: 颜色主题能否实时修改生效（含透明度）, 并希望软件有一个
"主题"标签页, 能改所有元素颜色、保存/加载不同主题。模糊（亚克力）开关明确不做。

## 决策

1. **激活模型**: `TOKENS` 即"当前生效色板"—— QSS 由它生成、画家层 `ui/widgets`
   逐帧读它; `DEFAULT_TOKENS` 为模块加载时冻结的出厂预设（恢复默认 = 拷回）。
   `set_active(overrides)` 原地更新 + 自动重算 accent 派生色（accent_soft/glow 不进
   覆盖集, 用户只管本色）。
2. **实时生效链**: 主题页改动 -> `MainWindow.apply_theme(overrides)` -> set_active ->
   重新 `build_qss` -> `setStyleSheet`。Qt 立即重抛光全部控件, 自绘 delegate 随全局
   重绘读到新值, 无需重启。
3. **外部 theme.qss 的优先级让位于自定义主题**: 启动时 config.json["theme"] 非空或
   运行中 apply_theme 过, 则样式一律由 TOKENS 生成（theme.qss 是出厂色产物, 会盖掉
   覆盖）; 无自定义时维持原优先级（外部 theme.qss -> 生成）。
4. **持久化两级**: config.json["theme"] = 启动默认（「保存为启动默认」, core
   save_config 自动 .bak）; themes/*.json = 具名主题文件（保存/加载/删除, 只做即时
   预览不改启动默认）。两者格式相同: PERSIST_KEYS 内合法颜色值的最小覆盖集。
5. **安全边界**: set_active 只接受 COLOR_GROUPS/ALPHA_KEYS 白名单内的合法颜色值
   （hex/rgba 正则）, 其余忽略不抛错 —— 脏 config/脏主题文件不致命; set_alpha 裁剪
   5%-100% 防全透明; 主题文件名拒绝路径分隔符; 删除/恢复默认走 QMessageBox 确认。
6. **滑杆节流**: 透明度 QSlider valueChanged 仅记录 pending + 更新标签, 停止 80ms
   后才重建 QSS（避免拖动时逐帧 repolish 整窗卡顿）。
7. **亚克力模式的主背景盲区修复（用户实测发现"改主背景无效果"）**: 原 mica 分支
   顶层背景是 `transparent`, bg token 完全不参与。现改为顶层 = `bg_rgba` 染色层
   （rgb 随 bg 联动、alpha 是独立自由度 = 「主背景」透明度滑杆, 默认 0.42）,
   面板 rgba 不变 —— bg 本色改动在两种模式下都可见。
8. **模糊开关刻意不做**: WA_TranslucentBackground/系统模糊须在窗口显示前设置,
   运行中切换需销毁重建整窗（挂着 service 桥/监控线程/全部页面）, 风险大于收益;
   透明度本身走 rgba token 即可满足诉求。

## 拒绝的替代方案

- **QSS 字符串整体替换 + 手工改 widgets 常量**: 仍是双源, 每次换肤要同步两处。
- **主题状态存独立 theme.json**: 多一个配置文件与 config.json 双写, 折腾; 跟随
  config.json 的 .bak/热重载机制更简。
- **模糊开关 + 重建窗口**: 收益仅一个开关状态, 代价是整窗重建与状态迁移风险。
- **每次 valueChanged 直接 repolish**: 整窗重抛光在拖动频率下可感卡顿, 80ms 节流
  足够顺滑。

## 影响

- `ui/theme.py`（管理段 + 滑杆/主题列表 QSS + `-m` 再生成）、`ui/pages_theme.py`
  （新页面）、`dsh-console-aio.py`（import/启动激活/_load_theme 分支/apply_theme/
  NAV 16 页）、`ui/widgets.py`（画家层读 TOKENS）、bat/两 spec 的
  `ui.pages_theme` hidden-import、`.gitignore`（themes/）。
- 348 例纯单元全过（新增 5 组主题管理用例）; dump_ui 16 页构造冒烟;
  apply_theme 实时换肤离屏验证（accent 换绿后导航条/主按钮像素级确认）。
- 已知边界: 页面若在导航离开期间被程序外_apply_theme（如未来其他入口）, 色板控件
  不自动回填（页面重建时从 TOKENS 取值, 正常路径无感）。
