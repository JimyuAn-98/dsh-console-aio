# P2 第一步：插件页 cordis 生效状态徽章（dump-config 双产出）

- Status: implemented
- Date: 2026-08-29
- Related: docs/ROADMAP.md P2；.agents/notes/implemented/bug-fix/2026-08-29-plugin-enable-empty-patch.md
  （同日查明的 dsh patch/entry 语义是本功能的直接地基）

## 背景与目标

P2「插件管理对齐 dsh web（配置状态 + cordis 状态徽章）」。此前插件页只有本地配置视图
（bundles + cordis.patch.yml 合成），看不到 cordis 合成层的生效状态；「配置停用但生效层
还在跑」「被更低层 bundle patch 压住」这类不一致无法呈现。

## 关键决策

- **一次子进程双产出**：`dsh --profile X --dump-config` 的输出就是 boot 挂载的同一合成
  （"a dump can never drift from what boots"，app-boot renderConfigDump），把原
  `load_entry_id_map` 升级为 `dump_entry_states`，同一次运行同时返回 id 映射与每条
  entry 的 disabled 状态，列表加载零新增开销。dump 即真相，无需查询运行中进程。
- **逐行缩进栈解析，不走完整 YAML**：dump 输出可含 `!!js` 表达式（离线不可求值），且
  自研 YAML 子集解析器覆盖不了该方言。js-yaml 输出缩进契约稳定（2），用缩进栈归属：
  `- id:` 行压栈开启 entry，字段行弹出比自身缩进深的栈顶后归属给「缩进-2」的 entry——
  config 里恰好叫 disabled 的配置键（更深缩进）、嵌套 group 子条目、group 尾部字段
  三类陷阱均有针对性测试钉住。
- **cordis 字段附在列表行上，UI 保持哑展示**：core 在 load_view 里完成 bundle名→entry id
  解析并附 `cordis` 字段（"enabled"/"disabled"/None），页面只渲染；None（远程/dump 失败/
  纯依赖库非 entry）显示"—"，不阻断、不报错。
- 页面原「状态」列更名「配置」（patch 层本地视图），新「cordis」列显示生效状态，
  两列并列让不一致一眼可辨。

## 放弃了什么

- 查询运行中 3080 进程的 loader 实时 fiber 状态：需进程内 API，且违背"dump 即挂载真相"
  的官方机制；entry 级 disabled 已覆盖启停对齐需求，fiber 级崩溃态留给日志查看器（P2 下一步）。
- dshmarket 的 state.json（client-only shim）状态：属于 dshmarket 私有账本，控制台不做，
  配置层 + cordis 层两列已覆盖用户可操作的真实状态。

## 验证

- 纯单元 316 例全绿（+5 例解析器：config 同名键噪音/嵌套子条目/group 尾部字段/!!js/空输出）。
- 真机 dump-config 实测：293 条 id 映射、147 条生效状态；dshmarket→dsh-market disabled=False
  （顺带独立确认同日 BUG-001 修复后 HMR 已把 dsh-market 热启回来）。
