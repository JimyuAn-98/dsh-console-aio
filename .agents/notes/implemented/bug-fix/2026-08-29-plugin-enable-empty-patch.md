# 插件启用不生效：启用删空禁用行后写出空 patch 文件（BUG-001 真实根因）

- Status: implemented
- Date: 2026-08-29
- Related: docs/BUGS.md BUG-001；dshmarket lib/patch.js（dsh web 插件启停参照实现）

## 背景

BUG-001 原记录方向是「写入 patch 的是 bundle 名，与 cordis entry 真实 id 不匹配」。
实查发现 bundle名→entry id 映射已实现（load_view 经 dsh --dump-config 回 id_map，
页面 set_disabled 先映射再写），且用户实测停用已正常、仅启用不生效——原方向不是剩余根因。
用户最初怀疑「启用后缺少对 profile 的 build」。

## 排查过程（要点）

- 读 dsh 源码（D:\Applications\deepseek-harness）确认语义链：
  - apps/cli/src/plugin.ts：`dsh plugin` 是纯 pnpm 转发器 + bundles 对账，**无 enable/build 子命令**；
  - vendor/include applyEntryPatches：patch 行 `{id, disabled:true}` 仅在 id 命中 entry 时生效；
  - vendor/loader Entry.update：fiber 已销毁时再次 update 会重新 import+start——loader 侧
    disabled→enabled 热更新语义健全，无需 build（dshmarket 的 prepare 构建装包时已跑过，lib/ 存在）；
  - packages/boot/app-boot parsePatchList：patch 文件 `yaml.load` 后**必须是数组**，否则抛错——
    HMR 重载失败（旧树保留）且 loadProfile 阶段**启动即失败**。
- 本机实证：~/.dsh/profiles/web/cordis.patch.yml 在一次启用操作后仅剩 1 字节（0x0a），
  其 .bak 正是停用写入的 `- id: dsh-market / disabled: true`。
- dshmarket lib/patch.js 的 withPlaceholderRestored 注释原话证实该故障为已知形态：
  「Disable a plugin, enable it again, and the profile is bricked」——删到空必须恢复合法空数组。

## 根因机制

启用 = 从 cordis.patch.yml 删除禁用行；patch 只有一条禁用行时删空，`write_yaml([])` 经
`_dump_yaml`（空列表产零行）+ `"\n".join([])+"\n"` 写出**空文件**。空文档 YAML 解析为 null
而非 `[]`，dsh patch 层拒绝加载 → HMR 停在旧树（启用不生效）、重启即启动失败。
控制台侧 `_read_cordis_file` 对空文件容错返回 `[]`，页面显示「已启用」，故障被掩盖。

## 决策

- `core/data.py write_yaml`：序列化产出为空时 list 写 `[]`、dict 写 `{}`——根修，
  保护 settings.yaml / workspace.json 等全部 YAML 写路径的同类隐患。
- `core/plugins.py set_disabled`：启用未命中禁用行时追加 `{id, disabled: false}` 强启用行
  （对齐 dshmarket enableRow：禁用行丢失或来自更低层 bundle patch 时仍能启用），补齐与
  停用分支的对称性；弃用「静默空操作却报成功」的旧行为。
- 本机坏文件已修复：备份为 cordis.patch.yml.broken.bak 后写 `[]`（原 .bak 保留停用态不动）；
  运行中的 web 约 1 秒 HMR 感知，dsh-market 热启回来。

## 影响

- 纯单元 311 例全过（新增 4 例：空 list/dict 写出合法文档 + 启用删空回归 + 强启用行）。
- dsh 启停链路确认无需 build；P2 插件管理对齐（cordis 状态徽章）可直接复用本次对
  dshmarket patch.js / dsh 源码的语义结论。
