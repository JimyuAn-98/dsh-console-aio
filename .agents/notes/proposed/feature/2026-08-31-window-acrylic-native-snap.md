# 窗口无边框/亚克力/原生贴靠 探索记录（重要，压缩后据此续做）

Status: proposed
Date: 2026-08-31
专题: feature（窗口机制改造）

> 本 note 是本轮长探索的**唯一落盘记录**。上下文可能被压缩删除，后续 agent 先读本文，再决定是否继续。
> 结论一句话：**「保留原生标题栏 + 非分层 + `set_accent_blur`(blurbehind)」已实现且几乎全部正常，只剩「原生标题栏自身透明/亚克力」未解决。**

---

## 1. 背景与目标

DSH 控制台（`dsh-console-aio.py`，PySide6 6.11.2，conda env `console`，Win11 多屏：主 4K 2560x1440@150%、右侧 U2790B 2560x1440@150%、左侧便携屏 NE140QDM 1707x1067@150%，便携屏在负坐标 [-2560,550] 逻辑）。

用户最初诉求：
- 当前是无边框（`Qt.FramelessWindowHint`）+ 分层亚克力方案，导致 **Win+方向键贴靠失效、拖到屏幕边缘不贴靠、多屏拖拽热区异常（便携屏触发区跑飞）**。
- 希望「保留 Windows 原生窗口机制（贴靠/多屏）+ 隐藏顶部标题栏」。
- 之后用户退一步：**保留原生标题栏也可，只求标题栏同步透明/亚克力**；若连这个也做不了，就不再纠结标题栏。

## 2. 全部已实证的关键事实（勿再重复试错）

环境：PySide6 6.11.2，Win11 22H2+（build 依赖 DWM API）。用 `C:/Users/1/.conda/envs/console/python.exe` 跑，GUI 需 `pythonw.exe` 见桌面，日志重定向到文件读。

### 2.1 跨屏热区 bug 的根因（已量化、已修复）
- 旧 `nativeEvent` 用 `geometry()+GetDpiForWindow/96` 手工换算命中，在便携屏（负坐标/异宽屏）**X 偏移约 853 逻辑px**（≈两屏宽度差 2560-1707），主屏原点对齐所以没事。
- 修复 = 用 **`ScreenToClient + GetClientRect`** 让 Windows 算多屏 DPI 坐标（成熟库 qframelesswindow 内部正是这么写的）。已实现于 `ui/win32_frame.py::hit_test/hit_test_at`。

### 2.2 DWM 亚克力两种来源，效果天差地别（关键！）
- **`DwmSetWindowAttribute(DWMWA_SYSTEMBACKDROP_TYPE, TRANSIENTWINDOW/MAINWINDOW)`（Mica/亚克力）**：在**非分层**窗口上**透不出来**。实测：非分层窗口 + `paintEvent CompositionMode_Clear` + 纯红背景在正后方，抓屏仍是纯黑 `(0,0,0)` → **Qt 非分层窗口无 alpha 通道，"clear=黑"**，DWM backdrop 被 Qt 不透明表面盖死。`ACRYLICBLURBEHIND` 同理。**这条路放弃。**
- **`SetWindowCompositionAttribute(WCA_ACCENT_POLICY, ACCENT_ENABLE_BLURBEHIND)`（即用户本科项目 areo.h 方案）**：在**非分层窗口上就能透出主区亚克力**！PySide6 6.11 实测 `BLUR=True` 且主区可见模糊。**这是唯一有效的亚克力来源。**（`ui/win32_frame.py::set_accent_blur`）

### 2.3 分层窗口（WS_EX_LAYERED）在 PySide6 6.11 的坑
- PySide6 6.11 里 **`setAttribute(Qt.WA_TranslucentBackground)` 不管设不设在 winId 之前，都不会让窗口变成 `WS_EX_LAYERED`**（实测一直 `LAY=False`）。不像用户 C++ Qt5.10 项目那样生效。
- **手动 `SetWindowLong(GWL_EXSTYLE)` 加 `WS_EX_LAYERED`（`ui/win32_frame.py::set_layered`）→ 窗口渲染坏掉**：标题栏消失、按钮消失/不可见（用户亲测“没看到标题栏和按钮”）。**不要用 set_layered。**
- 结论：**放弃分层（WS_EX_LAYERED）路线**。非分层 + blurbehind 即可。

### 2.4 当前唯一可行且几乎完美的配方（已验证到只剩标题栏透明）
```python
# 在 MainWindow.__init__ 里，不要 FramelessWindowHint，不要 WA_TranslucentBackground
# (keep native WS_CAPTION|WS_THICKFRAME)
hwnd = int(self.winId())
wframe.set_accent_blur(hwnd)          # blurbehind 亚克力: 主区透出模糊 ✓
wframe.set_immersive_dark(hwnd, True) # 暗色标题(但会让标题栏变实心深色!):
```
实测该配方下的表现（用户逐项确认）：
- ✓ 原生贴靠（拖到边缘、Win+方向键）正常
- ✓ 多屏拖拽正常、无热区异常
- ✓ 跨屏缩放/窗口间拖拽正常（不再有按钮热区变小、透明消失、贴靠后模糊闪退）
- ✓ 主区亚克力透出窗外模糊
- ✓ 按钮/下拉等全部正常
- ✗ **唯一遗漏：顶部原生标题栏不是透明的**（见下）

### 2.5 标题栏不透明的疑似原因（待验证）
- 现在 `set_immersive_dark(True)`（`DWMWA_USE_IMMERSIVE_DARK_MODE`）会把原生标题栏刷成**实心深色**，很可能正是它把 blurbehind 的透明/模糊盖住了。
- **下一步最优先试**：同一 minimal 窗口，**去掉 `set_immersive_dark`** 对比标题栏是否恢复透明/亚克力；若恢复则问题在暗色标题。
- 另可试：`DwmSetWindowAttribute(DWMWA_CAPTION_COLOR, 0)` 或给标题栏加 DWM backdrop，或在 `nativeEvent` 处理 `WM_NCACTIVATE`/注册 `WM_DWMNCRENDERINGCHANGED` 强制刷新非客户区。
- 若都无效 → 用户已说“实在做不到就算了”，即接受原生标题栏为实心深色，整体方案仍成立。

## 3. 当前源码改动状态（实现在 dsh 工作区，勿误删）

已在 `C:\Users\1\Desktop\dsh` 落地（但**尚未在真实应用里验证完整**，主窗口改造是半成品，见 §4）：

- **`ui/win32_frame.py`（新增，ctypes 封装，零外部依赖）**，含：
  - 常量：WS_CAPTION/WS_THICKFRAME/WS_EX_LAYERED、WM_NCCALCSIZE/WM_NCHITTEST/WM_ERASEBKGND/WM_SYSCOMMAND/SC_MOVE、DWM backdrop 常量。
  - `set_accent_blur(hwnd, gradient=0, state=3)` ← **亚克力关键，blurbehind**
  - `set_immersive_dark(hwnd, dark=True)` ← 暗色标题（疑点）
  - `set_system_backdrop(hwnd, kind)` ← DWM backdrop（非分层透不出，弃用但保留）
  - `extend_frame(hwnd, margins)`、`ensure_native_frame(hwnd)`、`set_layered(hwnd, on)`（勿用）
  - `hit_test / hit_test_at`（ScreenToClient 命中，跨屏修复核心）
  - `start_system_move(hwnd)`（SC_MOVE|HTCAPTION 原生移动循环，配合自绘标题栏拖拽/贴靠）
  - `query_backdrop / is_layered / has_caption / has_thickframe`（诊断）
- **`dsh-console-aio.py`（主窗口，已改，半成品）**：`MainWindow.__init__` 改为非分层 + DWM backdrop + dark；`nativeEvent` 已改成 `WM_NCCALCSIZE→0`（藏标题栏）+ `WM_NCHITTEST→hit_test`；`_TopBar` 已改为 `start_system_move` 拖拽；`_toggle_maximize` 改原生 `showMaximized/showNormal`。**这些是与「保留标题栏」方向冲突的藏标题栏实现，很可能要回退/调整。**

## 4. 关键分歧与下一步（最重要）

- **方向已由用户定为「保留原生标题栏」**，因此 `dsh-console-aio.py` 里那套「`WM_NCCALCSIZE→0` 藏标题栏 + `_TopBar` 自绘拖拽 + `nativeEvent` 手工命中」**应当回退/放弃**，改用 §2.4 保留标题栏的最简配方：
  - 去掉 `FramelessWindowHint`（已去掉）
  - 不设 `WA_TranslucentBackground`，不 `set_layered`
  - 保留原生 `WS_CAPTION|WS_THICKFRAME`（默认就在）
  - `set_accent_blur` 产生亚克力
  - 原生标题栏自行处理拖拽/贴靠/按钮（不再需要 `_TopBar` 拖拽逻辑、不再需要 `WM_NCCALCSIZE/hit_test`）
- **待办（按依赖顺序）**：
  1. 先验证「去掉 `set_immersive_dark` 后标题栏是否变透明/亚克力」（§2.5）。用一个最小脚本在桌面开窗，让用户看。
  2. 把验证通过的最简配方落进 `dsh-console-aio.py`：回退藏标题栏逻辑；主题 `_mica` 语义与 `set_accent_blur` 对齐；启动日志改准确。
  3. 若标题栏透明仍不可得，按用户意思就此打住（接受实心深色标题栏）。
  4. py_compile + offscreen 冒烟（`QT_QPA_PLATFORM=offscreen`）+ 主题页透明滑杆联动回归。
  5. 清理所有 `_*.py/_*.log` 临时测试脚本。
  6. 更新文档（docs/ROADMAP.md、RELEASE_NOTES.md、README）+ 本 note 移到 implemented 或 rejected。

## 5. 临时验证脚本（本次已删除，下次可重建）

- `_probe_patch.py`（DWM backdrop 5 模式抓屏）→ 全黑，证伪 DWM backdrop 非分层透出。
- `_probe_stack.py`（红窗在后 + 补丁窗在前）→ 抓屏 (0,0,0) 纯黑，铁证"非分层无 alpha，clear=黑"。
- `_verify_retain.py`（保留标题栏 + set_layered 强制分层）→ 窗口坏（无标题栏无按钮）。
- `_verify_minimal.py`（保留标题栏 + 不强制分层 + set_accent_blur）→ **几乎全正常，仅标题栏不透明**。← 这个就是当前方向原型。

## 6. 其他备忘

- Qt 项目约定（AGENTS.md）：禁三引号中文 docstring（用 # 注释）；每次 py_compile；GUI 用 offscreen 冒烟；文档要同步；安全值只存 config.json。
- `build_qss(mica=True)` 已在 Window/central/body 用 `rgba(27,32,46,0.42)` 半透明——配合 blurbehind 主区亚克力正好；**不要**再动它。
- 用户本科项目路径：`D:\HJY\OneDrive\本科\大三小学期\code\wireless\wireless\areo.h` + `wireless.cpp`（setAttribute 在 winId 前 + SetWindowLong 保留 WS_* + WCA_ACCENT_POLICY BLURBEHIND）。结论：blurbehind 是唯一确定有效的亚克力来源。
- 引库结论已否决：`qframelesswindow`（zhongyang219）仅 PyQt5 且 GPLv3；`pyqt-frameless-window`(yjg30737) 依赖 PyQt5。本项目 PySide6+MIT，不引入。

## 7. 最终落定（2026-08-31 收尾，方案已落地并验收）

**一句话结论**：采用「保留原生标题栏（实心不透明）+ 非分层窗口 + `set_accent_blur`(blurbehind) 亚克力 + 自绘业务工具栏」。
全部功能实测通过：原生贴靠、多屏拖拽、拉伸、标题栏按钮、主区亚克力、无边缘脏带。

### 7.1 标题栏透明确认（§2.5 待办1 的实测结果）
- 做了 W1(只 blurbehind) / W2(blur+immersive_dark) 双窗对比：**两者原生标题栏都实心不透明**。
- 去掉 `set_immersive_dark` **不能**让原生标题栏透明。Win11 原生标题栏真透明是死路（与百度结论一致：Qt 无法改原生标题栏样式）。
- 用户此前已同意：「保留标题栏」与「标题栏透明」不可兼得就放弃标题栏透明 → **接受实心深色原生标题栏**。immersion 问题到此终结，不再尝试。

### 7.2 边缘脏带根因（排查过程，重要备忘）
- 现象：窗口「内侧一圈深/浅色边」。
- 第一轮假设偏了：一度归因于 rgba 半透明主区或 blur。用 A/B/C 对照（全局 `QWidget{background:transparent}`）确实出带；但 D/E/F 对照（同 rgba 0.42、无全局 transparent）**完全无带**，正式 `build_qss(mica=True)` 跑出来也干净。
- **根因 = 全局 `QWidget{background:transparent}` 这条规则**把底层画脏（非分层窗口无 alpha，最底层一圈没正常覆盖）。正式主题 QSS 没有这条全局规则，所以正式 app 没有此问题；之前看到的带是某测试脚本自己引入的。**不动正式 QSS**。

### 7.3 落地改动（`dsh-console-aio.py`）
- `MainWindow.__init__`：删除 `_frameless`、`_normal_geo`、`_maxed`、`_btn_max`；窗口效果改为
  `self._mica = wframe.set_accent_blur(int(self.winId())) if sys.platform == "win32" else False`。
- `_TopBar`：改为普通业务工具栏容器（logo/标题/部署下拉/搜索/刷新），删除 `_is_drag_region`/`mousePressEvent`/`mouseMoveEvent`/`mouseDoubleClickEvent` 拖拽逻辑。
- `_build_topbar`：删除 `winBtn`（最小化/最大化/关闭自绘按钮）分支，改用原生标题栏按钮。
- `nativeEvent`：删除 `WM_NCCALCSIZE`/`WM_NCHITTEST` 手工命中，改为纯转发（原生框架管贴靠/拖拽/拉伸/多屏）。
- 删除 `_toggle_maximize`/`_sync_max_btn`（原生双击最大化已够）。
- `_log_window_facts` 保留（诊断 is_layered/query_backdrop/has_caption/has_thickframe 仍有意义）。

### 7.4 验证结果（用户桌面验收）
- 原生标题栏 + 关闭/最小化/最大化按钮、双击最大化：✓
- 主区亚克力模糊透出、无边缘脏带：✓
- 标题栏下方自绘工具栏（部署下拉/搜索/刷新）：✓
- 跨屏拖拽/边缘贴靠/热区：✓
- py_compile + offscreen `--smoke` + 主题滑杆（`set_alpha` → `build_qss(mica=self._mica)`）联动：✓

### 7.5 后续文档同步清单（已执行/待执行）
- [x] 清理所有 `_*.py/_*.log` 临时脚本
- [x] 本 note（§7 落定追加）
- [ ] docs/ROADMAP.md、RELEASE_NOTES.md、README 同步「保留原生标题栏 + blurbehind」表述
- [ ] 可选：把本 note 从 `proposed/feature` 移到 `implemented`/归档
