# 布局改造：三栏页横向可扩展 + 状态文字上移 + 设置页纵向滚动

- Status: implemented
- Date: 2026-08-30
- Related: 用户验收反馈（三栏页横向空间不足；设置页内容长需要纵向滚动）

## 需求（用户原话要点）

1. 会话与工作区/插件管理/部署管理三栏页 → 带**横向滚动条**的可横向扩展空间（方便未来加栏）；
   statusBar 文字挪到 cardTitle 右边，底部位置留给滚动条
2. 其他页面只去掉底部 statusBar
3. 设置页需要**纵向滚动条**

## 实现

- 三栏页：`mid.setMinimumWidth(1020)` + (mid, btns) 装进 QScrollArea（widgetResizable、
  无边框、透明）——视口 < 1020 出横向滚动条，宽窗口自动铺满（widgetResizable 尊重内容
  minimumSize）。设置页同构、只纵向。
- 全部 15 页：底部 `objectName="statusBar"` 标签取消，状态文字移到标题右侧
  （`objectName="monVal"`）；主窗口自己的底栏（`self.status`）不在此列，保留。

## 关键坑（离屏渲染验证抓出）

滚动区**外**的长提示 QLabel 未开 wordWrap 时，`minimumSizeHint` = 整行文字宽（约 700-900px），
经布局逐级上传把**页面**的 minimumSizeHint 撑到 1530px。顶层级 widget 无法缩到 minimum 以下
→ 视口永远 ≥ 内容宽 → 横向滚动条永远不触发（hbar max 恒 0）。修复：滚动区外的 hint 一律
`setWordWrap(True)`，页面 minimumSizeHint 降到 774px；900 宽窗口 hbar max=156（可滚）、
1400 宽 hbar max=0（自动铺满），行为正确。

## 追加（2026-08-30，用户验收反馈）：每栏固定最小宽度

用户发现插件页某栏元素过宽会挤压其他栏。根因与页级同款：详情卡徽章 chips QLabel
未开 wordWrap，整行 chips 宽成为详情栏最小宽度，QSplitter 缩不破它只能压别栏。修复：
- `three_split` 增加 `mins=(250, 320, 340)` 参数，对每栏 `setMinimumWidth`——栏有了
  固定最小宽度，拖拽/内容再宽都压不破其他栏；QSplitter 拖拽语义本身即"变宽向右吸收"。
- 插件页 `_d_name`/`_d_badges` 开 wordWrap（塌掉假最小宽度）。
- 部署页显式 `mins=(280, 340, 340)`；插件/会话用默认值。
- 离屏验证：塞入超长徽章文本压到最窄，三栏宽 [300, 372, 340] 全部 ≥ 各自最小值。

## 验证

- 离屏渲染 + 编程断言：滚动条出现/消失随窗口宽度正确切换；设置页 560px 高时纵向可滚
  （vbar max=191）。纯单元 341 例全绿。
- 真机观感由用户验收。
