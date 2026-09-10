# 安装版一键更新：下载安装包并自动退出运行安装程序

- Status: implemented
- Date: 2026-09-10
- Related: `core/version.py`, `app/services.py`, `ui/pages_version.py`, `tests/test_core_version.py`

## 背景

打包(exe)版此前的「一键更新」只是用 `os.startfile` 打开 GitHub Releases 页面；用户还要手动找安装包、下载、双击、再回来关掉旧控制台，升级体验割裂，小白用户容易下错版本或找不到文件。

## 决策

一键更新在安装版下改为：确认后由后台线程下载最新安装包 → 校验 → 页面启动安装器 → 退出控制台。

- core 纯逻辑（零 Qt）：`installer_url` / `download_installer` / `launch_installer`，签名遵守 `_run_result_op`（events 为首个位置参数）；
- 下载流式读取并每 5% 经 events("status") 报进度；落盘后校验 MZ 魔数（防把 HTML 错误页当安装程序），并尽力比对同 Release 的 `SHA256SUMS.txt`（清单缺失/未命中只告警不阻断，命中不符则中止）；
- 安装器覆盖安装细节交给 Inno Setup（AppId 不变，识别为同一应用、支持升级安装）；控制台主动退出，避免占用将被替换的文件；启动安装器失败则保留进程并给出中文错误与手动路径。

## 拒绝的替代方案

- **仍打开浏览器下载页**：体验割裂，且小白用户容易下错版本/找不到文件。
- **安装版沿用源码模式的"下载 zip 替换文件 + 重启"**：onefile exe 运行中无法替换自身，PySide6 依赖也不适合逐文件替换。
- **不主动退出，靠安装器的 Restart Manager 关掉控制台**：依赖 Inno 检测与用户交互，不确定；主动退出更可靠。

## 影响

- 安装版升级变为"点一下 → 等下载 → 自动弹安装器"；源码模式行为不变。
- 新增 core 单测（URL/下载/校验/启动分支）与 service 测试覆盖新桥接方法。
