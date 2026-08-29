# P1 收官：表格页多栏展开（列表-详情-配置三栏现代列表）

- Status: implemented
- Date: 2026-08-29
- Related: docs/VISION_部署子工具组.md §7.4（三栏 QSplitter 方案）；ui/widgets.py

## 背景与目标

P1 遗留项。四页（插件/会话/用量/部署）此前是 QTableWidget 网格两栏/堆叠布局，
观感复古且信息密度差。用户要求「现代软件观感，表格形式有些复古」，先文字渲染设计稿
确认后实施。

## 关键决策

- **一套组件四页复用**：ui/widgets.py 提供 ModernList（自绘 delegate：标题/meta/状态点/
  徽章 chips）、three_split（三栏可拖拽）、card_wrap；业务层零改动，页面只换控件与装填。
- **徽章语义：例外才可见**：插件行配置态与 cordis 生效态一致时不显示第二徽章，分歧时才
  追加 `cordis 停用`(err)/`cordis 启用`(accent)——把双列并列的"常态冗余"换成"异常提示"。
- **插件第三栏 = dump-config 合成 entry 原文**：core/data._entry_yaml_blocks 按
  `- id:` 缩进切片抓原始 YAML 块（`# ==` 分组注释剔除），随 states 回包；行解析不碰
  config 内部结构，!!js 原样保留。
- **部署页操作日志就地化**：测试连接/刷新总览/保存结果带时间戳着色显示在第三栏
  （QPlainTextEdit maximumBlockCount 500 防涨），主日志区照常输出，两不误。
- **PySide6 QVariantMap 深拷贝坑**（测试抓出）：扁平 dict 经 setData(Qt.UserRole) 存取
  会丢失对象身份，`cur is row` 恒 False、部署详情不刷新。ModernList 改为 Python 侧
  自持 self._rows（浅拷贝保身份），Qt 侧副本仅供 delegate 绘制。

## 放弃了什么

- QSS/样式表实现徽章与选中高亮：自绘 delegate 才能精确控制圆角块/chip 排版与状态点。
- QTreeView 可展开行方案（愿景 §7.4 的备选）：三栏 splitter 更贴合"列表-详情-配置"
  心智，且四页布局统一。

## 验证

- 纯单元 338 例全绿（+1：entry yaml 块抓取，含嵌套子条目与分组注释剔除）。
- 离屏构造冒烟（FakeApp 注入假数据，不碰 MainWindow/3080）：四页列表/详情/配置/徽章
  更新/操作日志 14 项断言全过；过程抓出 QVariantMap 拷贝与 addWidget/addLayout 两处真错。
- 观感由用户重启控制台人工拍板（HANDOFF 约定：外观类改动不自行判定完成）。
