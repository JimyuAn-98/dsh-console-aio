# 三引号 docstring 禁令（补丁链路损坏）

- Status: implemented
- Date: 2026-08-25

## 背景

经 JSON 序列化 + 补丁脚本链路向 Python 源文件插入多行代码时，docstring 的三引号（"""）在传输中丢失一个引号变成双引号（""），导致 docstring 未闭合，后续整段代码被当作字符串，报错 "invalid character '。'"（SyntaxError at 中文标点）。

## 决策

新代码一律用 # 注释代替 docstring；若必须用三引号字符串，只写英文纯 ASCII 内容。已写入 AGENTS.md 约定。

## 拒绝的替代方案

- 修复传输链路：链路在多个环节（JSON 转义、shell、patch 脚本）都可能丢引号，修一处仍有隐患；从源头规避更稳。

## 影响

- InstallDialog / EnvDialog 等新增类均用 # 注释。
- 大段文本插入优先用文件读写 + 字符串替换（python 脚本 src.index + slice），避免内嵌转义。
