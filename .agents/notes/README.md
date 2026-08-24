# Agent Notes

本项目借鉴 dsh（deepseek-harness）的 Agent Note 工程实践：把影响代码库的**决策**（为什么、放弃了什么、代价是什么）记录为独立文档，代码和文档承载不了的部分由它承载。

## 布局与命名

路径两轴编码：{lifecycle}/{class}/yyyy-mm-dd-topic-title.md

- **Lifecycle**（顶层目录）是状态，随状态迁移：
  - proposed/ — 提案，尚未实现或只实现一部分。
  - implemented/ — 已落地的决策，记录"决定做了什么、拒绝了什么"，并随实际落地保持最新（代码移动、重命名、默认值变化时同一次改动更新 note 中的事实）。
  - rejected/ — 考虑过但拒绝的提案；仅在它的理由能阻止一个诱人的错误时保留，否则删除。
- **Class**（嵌套目录）是决策类型：
  - feature — 新的用户/模型可见能力
  - bug-fix — 修正缺陷
  - simplification — 删除代码/行为/表面面积
  - architecture — 关于已发布源码的结构性决策
  - process — 工具、策略、工作流（门禁、包管理器、历史处理等）
  - testing — 测试基础设施与策略

## 何时写

非平凡的改动**必须**在同一次提交里附 Agent Note；纯机械/局部编辑豁免。判断标准：这个决策的"为什么"和"放弃了什么"是否值得未来的人（或 agent）知道。

## 文件格式

markdown 文件，包含：
- Status: proposed | implemented | rejected
- Date: yyyy-mm-dd（首次提出日期，与文件名一致）
- 章节：背景 / 决策 / 拒绝的替代方案 / 影响

## 归档与删除

- 决策完成且理由不再指导未来工作时，把 note 移到 archived/{class}/；若其替代方案、所有权边界、负向保证、持久/线上语义、安全规则或回归条件仍有用，则保持活跃。
- 已归档 note 冻结：不编辑、不作为当前权威。
- 不建集中索引（INDEX.md），浏览 lifecycle/class 目录即可。
